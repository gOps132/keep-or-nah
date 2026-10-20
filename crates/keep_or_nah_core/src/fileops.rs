//! Native, atomic-oriented file operation primitives for Keep or Nah.
//!
//! Copies stage a byte-complete file inside the destination folder as a hidden
//! temporary entry, preserve the source permissions and timestamps, fsync the
//! staged data, and return the staged identity so callers can publish it
//! exclusively (hard link / rename) with identity verification afterwards.
//! Removal primitives refuse to unlink entries whose on-disk identity no
//! longer matches the recorded one, which makes the undo journal transactional
//! against racers that replace published paths.
//!
//! The primitives themselves are plain Rust and carry no Python types, so the
//! rules above are unit tested without an interpreter. The `#[pyfunction]`
//! wrappers at the bottom of this module are the thin layer that turns a
//! [`FileOpError`] into the `OSError` the Python side expects.

use std::fmt;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

use pyo3::exceptions::PyOSError;
use pyo3::prelude::*;

/// The on-disk identity of a file entry.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FileIdentity {
    pub dev: u64,
    pub ino: u64,
}

/// A staged copy that is ready to be published.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StagedFile {
    pub path: String,
    pub dev: u64,
    pub ino: u64,
}

/// Which side of an operation a path belongs to. It only selects the wording
/// of the error message.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Role {
    /// A path the caller already owns and wants to keep owning.
    Owned,
    /// A path the caller wants to copy from.
    Source,
}

/// Why a file operation was refused.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FileOpError {
    /// The path could not be inspected at all.
    Io { path: String, message: String },
    /// The path is a symbolic link.
    Symlink { path: String, role: Role },
    /// The path exists but is not a regular file.
    NotARegularFile { path: String, role: Role },
    /// The path is no longer the regular file the caller owned.
    NoLongerARegularFile { path: String },
    /// The path does not exist.
    Missing { path: String },
    /// The path no longer carries the identity that was recorded for it.
    IdentityChanged { path: String, role: Role },
    /// The staging folder is not a directory.
    NotAStageDirectory { path: String },
    /// No unique staging name could be allocated.
    StageNameExhausted,
}

impl fmt::Display for FileOpError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            FileOpError::Io { message, .. } => write!(formatter, "{message}"),
            FileOpError::Symlink { path, role } => match role {
                Role::Owned => write!(formatter, "Owned path is a symbolic link: {path}"),
                Role::Source => write!(
                    formatter,
                    "Source path is a symbolic link and cannot be staged: {path}"
                ),
            },
            FileOpError::NotARegularFile { path, role } => match role {
                Role::Owned => write!(formatter, "Owned path is not a regular file: {path}"),
                Role::Source => write!(formatter, "Source path is not a regular file: {path}"),
            },
            FileOpError::NoLongerARegularFile { path } => {
                write!(formatter, "Owned path is no longer a regular file: {path}")
            }
            FileOpError::Missing { path } => write!(formatter, "Owned path is missing: {path}"),
            FileOpError::IdentityChanged { path, role } => match role {
                Role::Owned => write!(formatter, "Refusing to remove a replaced path: {path}"),
                Role::Source => write!(
                    formatter,
                    "Source path identity changed unexpectedly: {path}"
                ),
            },
            FileOpError::NotAStageDirectory { path } => {
                write!(formatter, "Stage folder is not a directory: {path}")
            }
            FileOpError::StageNameExhausted => {
                write!(formatter, "Could not allocate a unique staging file")
            }
        }
    }
}

impl std::error::Error for FileOpError {}

/// The identity of a regular, non-symlink file entry.
pub fn identity_of(path: &Path) -> Result<FileIdentity, FileOpError> {
    let metadata = fs::symlink_metadata(path).map_err(|error| FileOpError::Io {
        path: path.to_string_lossy().into_owned(),
        message: error.to_string(),
    })?;
    if metadata.file_type().is_symlink() {
        return Err(FileOpError::Symlink {
            path: path.to_string_lossy().into_owned(),
            role: Role::Owned,
        });
    }
    if !metadata.is_file() {
        return Err(FileOpError::NotARegularFile {
            path: path.to_string_lossy().into_owned(),
            role: Role::Owned,
        });
    }
    Ok(file_identity_of(path, &metadata))
}

/// Delete `path`, but only while it still owns `identity`.
pub fn remove_verified(path: &Path, identity: FileIdentity) -> Result<(), FileOpError> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            return Err(FileOpError::Missing {
                path: path.to_string_lossy().into_owned(),
            })
        }
        Err(error) => {
            return Err(FileOpError::Io {
                path: path.to_string_lossy().into_owned(),
                message: error.to_string(),
            })
        }
    };
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(FileOpError::NoLongerARegularFile {
            path: path.to_string_lossy().into_owned(),
        });
    }
    let actual = file_identity_of(path, &metadata);
    if actual != identity {
        return Err(FileOpError::IdentityChanged {
            path: path.to_string_lossy().into_owned(),
            role: Role::Owned,
        });
    }
    fs::remove_file(path).map_err(|error| FileOpError::Io {
        path: path.to_string_lossy().into_owned(),
        message: error.to_string(),
    })
}

/// Copy `source` into a fresh hidden temporary file inside `stage_dir`,
/// preserving permissions and timestamps, and fsync the staged bytes.
///
/// When an expected identity is supplied, the source must still own it.
pub fn stage_copy(
    source: &Path,
    stage_dir: &Path,
    expected: Option<FileIdentity>,
) -> Result<StagedFile, FileOpError> {
    let metadata = fs::symlink_metadata(source).map_err(|error| FileOpError::Io {
        path: source.to_string_lossy().into_owned(),
        message: error.to_string(),
    })?;
    if metadata.file_type().is_symlink() {
        return Err(FileOpError::Symlink {
            path: source.to_string_lossy().into_owned(),
            role: Role::Source,
        });
    }
    if !metadata.is_file() {
        return Err(FileOpError::NotARegularFile {
            path: source.to_string_lossy().into_owned(),
            role: Role::Source,
        });
    }
    if let Some(expected) = expected {
        if file_identity_of(source, &metadata) != expected {
            return Err(FileOpError::IdentityChanged {
                path: source.to_string_lossy().into_owned(),
                role: Role::Source,
            });
        }
    }

    let mode = source_mode(&metadata);
    let staged_path = create_stage_path(stage_dir)?;
    // A zero-byte source copies as a valid zero-byte staged file.
    if let Err(error) = fs::copy(source, &staged_path) {
        let _ = fs::remove_file(&staged_path);
        return Err(FileOpError::Io {
            path: source.to_string_lossy().into_owned(),
            message: error.to_string(),
        });
    }
    if let Err(error) = stage_finish(&staged_path, mode, &metadata) {
        let _ = fs::remove_file(&staged_path);
        return Err(error);
    }

    let staged_metadata = fs::symlink_metadata(&staged_path).map_err(|error| FileOpError::Io {
        path: staged_path.to_string_lossy().into_owned(),
        message: error.to_string(),
    })?;
    let identity = file_identity_of(&staged_path, &staged_metadata);
    Ok(StagedFile {
        path: staged_path.to_string_lossy().into_owned(),
        dev: identity.dev,
        ino: identity.ino,
    })
}

#[cfg(unix)]
fn source_mode(metadata: &fs::Metadata) -> Option<u32> {
    use std::os::unix::fs::PermissionsExt;
    Some(metadata.permissions().mode())
}

#[cfg(not(unix))]
fn source_mode(_metadata: &fs::Metadata) -> Option<u32> {
    None
}

#[cfg(unix)]
fn file_identity_of(path: &Path, metadata: &fs::Metadata) -> FileIdentity {
    use std::os::unix::fs::MetadataExt;
    let _ = path;
    FileIdentity {
        dev: metadata.dev(),
        ino: metadata.ino(),
    }
}

#[cfg(windows)]
fn file_identity_of(path: &Path, metadata: &fs::Metadata) -> FileIdentity {
    use std::os::windows::fs::MetadataExt;
    let file_index = metadata.file_index().map(|index| index as u64).unwrap_or(0);
    let _ = path;
    FileIdentity {
        dev: 0,
        ino: file_index,
    }
}

fn unique_stage_name() -> String {
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_nanos() as u64)
        .unwrap_or(0);
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let counter = COUNTER.fetch_add(1, Ordering::Relaxed);
    let mixed = nanos ^ (counter.wrapping_mul(0x9E37_79B9_7F4A_7C15));
    format!(".keep-or-nah-{mixed:012x}.tmp")
}

fn create_stage_path(stage_root: &Path) -> Result<PathBuf, FileOpError> {
    if !stage_root.is_dir() {
        return Err(FileOpError::NotAStageDirectory {
            path: stage_root.to_string_lossy().into_owned(),
        });
    }
    for _attempt in 0..100 {
        let candidate = stage_root.join(unique_stage_name());
        match fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&candidate)
        {
            Ok(_handle) => return Ok(candidate),
            Err(err) if err.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(err) => {
                return Err(FileOpError::Io {
                    path: stage_root.to_string_lossy().into_owned(),
                    message: err.to_string(),
                })
            }
        }
    }
    Err(FileOpError::StageNameExhausted)
}

fn stage_finish(
    staged: &Path,
    mode: Option<u32>,
    metadata: &fs::Metadata,
) -> Result<(), FileOpError> {
    if let Some(mode) = mode {
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let permissions = fs::Permissions::from_mode(mode & 0o7777);
            if let Err(permission_error) = fs::set_permissions(staged, permissions) {
                return Err(FileOpError::Io {
                    path: staged.to_string_lossy().into_owned(),
                    message: permission_error.to_string(),
                });
            }
        }
        #[cfg(not(unix))]
        {
            let _ = mode;
        }
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        filetime::set_file_times(
            staged,
            filetime::FileTime::from_unix_time(
                metadata.atime(),
                metadata.atime_nsec().try_into().unwrap_or(0),
            ),
            filetime::FileTime::from_unix_time(
                metadata.mtime(),
                metadata.mtime_nsec().try_into().unwrap_or(0),
            ),
        )
        .map_err(|error| FileOpError::Io {
            path: staged.to_string_lossy().into_owned(),
            message: error.to_string(),
        })?;
    }
    #[cfg(not(unix))]
    {
        let _ = metadata;
    }
    fs::File::open(staged)
        .and_then(|handle| handle.sync_all())
        .map_err(|error| FileOpError::Io {
            path: staged.to_string_lossy().into_owned(),
            message: error.to_string(),
        })
}

// ---------------------------------------------------------------------------
// Python bindings
// ---------------------------------------------------------------------------

#[pyclass(get_all)]
pub struct PyStagedFile {
    pub path: String,
    pub dev: u64,
    pub ino: u64,
}

impl From<StagedFile> for PyStagedFile {
    fn from(staged: StagedFile) -> Self {
        Self {
            path: staged.path,
            dev: staged.dev,
            ino: staged.ino,
        }
    }
}

fn to_py_error(error: FileOpError) -> PyErr {
    PyOSError::new_err(error.to_string())
}

/// Return the stable identity of a regular, non-symlink file entry.
#[pyfunction]
pub fn file_identity(path: &str) -> PyResult<(u64, u64)> {
    let identity = identity_of(Path::new(path)).map_err(to_py_error)?;
    Ok((identity.dev, identity.ino))
}

/// Verify an entry still owns `(dev, ino)` and delete it; refuse otherwise.
#[pyfunction]
#[pyo3(signature = (path, dev, ino))]
pub fn remove_verified_file(path: &str, dev: u64, ino: u64) -> PyResult<()> {
    remove_verified(Path::new(path), FileIdentity { dev, ino }).map_err(to_py_error)
}

/// Copy `source` into a fresh hidden temporary file inside `stage_dir`,
/// preserving permissions and timestamps, and fsync the staged bytes.
/// When an expected identity is supplied, the source must still own it.
#[pyfunction]
#[pyo3(signature = (source, stage_dir, expected_dev=None, expected_ino=None))]
pub fn stage_regular_file(
    source: &str,
    stage_dir: &str,
    expected_dev: Option<u64>,
    expected_ino: Option<u64>,
) -> PyResult<PyStagedFile> {
    let expected = match (expected_dev, expected_ino) {
        (Some(dev), Some(ino)) => Some(FileIdentity { dev, ino }),
        _ => None,
    };
    let staged =
        stage_copy(Path::new(source), Path::new(stage_dir), expected).map_err(to_py_error)?;
    Ok(PyStagedFile::from(staged))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::TempDir;

    fn write(dir: &Path, name: &str, contents: &[u8]) -> PathBuf {
        let path = dir.join(name);
        fs::write(&path, contents).expect("write fixture");
        path
    }

    fn file_name(path: &Path) -> String {
        path.file_name().unwrap().to_string_lossy().into_owned()
    }

    #[test]
    fn identity_of_a_regular_file_matches_the_file_system() {
        let dir = TempDir::new().unwrap();
        let path = write(dir.path(), "IMG.jpg", b"raw");

        let identity = identity_of(&path).expect("identity is readable");

        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            let metadata = fs::metadata(&path).unwrap();
            assert_eq!(identity.dev, metadata.dev());
            assert_eq!(identity.ino, metadata.ino());
        }
    }

    #[test]
    fn identity_of_a_missing_file_is_an_io_error() {
        let dir = TempDir::new().unwrap();
        let missing = dir.path().join("missing.jpg");

        let error = identity_of(&missing).expect_err("a missing file has no identity");

        assert!(matches!(error, FileOpError::Io { .. }));
    }

    #[test]
    fn identity_of_a_symlink_is_refused() {
        let dir = TempDir::new().unwrap();
        let target = write(dir.path(), "IMG.jpg", b"raw");
        let link = dir.path().join("LINK.jpg");
        #[cfg(unix)]
        std::os::unix::fs::symlink(&target, &link).unwrap();
        #[cfg(not(unix))]
        let _ = link;

        let error = identity_of(&link).expect_err("a symlink has no identity");

        assert_eq!(
            error,
            FileOpError::Symlink {
                path: link.to_string_lossy().into_owned(),
                role: Role::Owned,
            }
        );
    }

    #[test]
    fn identity_of_a_directory_is_refused() {
        let dir = TempDir::new().unwrap();

        let error = identity_of(dir.path()).expect_err("a directory has no identity");

        assert_eq!(
            error,
            FileOpError::NotARegularFile {
                path: dir.path().to_string_lossy().into_owned(),
                role: Role::Owned,
            }
        );
    }

    #[test]
    fn remove_verified_deletes_a_file_that_still_owns_its_identity() {
        let dir = TempDir::new().unwrap();
        let path = write(dir.path(), "IMG.jpg", b"raw");
        let identity = identity_of(&path).unwrap();

        remove_verified(&path, identity).expect("the file is removed");

        assert!(!path.exists());
    }

    #[test]
    fn remove_verified_refuses_a_replaced_path() {
        let dir = TempDir::new().unwrap();
        let path = write(dir.path(), "IMG.jpg", b"raw");
        let identity = identity_of(&path).unwrap();
        // A racer replaces the published path with a different file.
        fs::remove_file(&path).unwrap();
        write(dir.path(), "IMG.jpg", b"replacement");

        let error = remove_verified(&path, identity).expect_err("the replacement is kept");

        assert_eq!(
            error,
            FileOpError::IdentityChanged {
                path: path.to_string_lossy().into_owned(),
                role: Role::Owned,
            }
        );
        assert!(path.exists());
    }

    #[test]
    fn remove_verified_reports_a_missing_path() {
        let dir = TempDir::new().unwrap();
        let missing = dir.path().join("missing.jpg");

        let error = remove_verified(&missing, FileIdentity { dev: 0, ino: 0 })
            .expect_err("a missing file cannot be removed");

        assert_eq!(
            error,
            FileOpError::Missing {
                path: missing.to_string_lossy().into_owned(),
            }
        );
    }

    #[test]
    fn remove_verified_refuses_a_directory() {
        let dir = TempDir::new().unwrap();

        let error = remove_verified(dir.path(), FileIdentity { dev: 0, ino: 0 })
            .expect_err("a directory is not removed");

        assert_eq!(
            error,
            FileOpError::NoLongerARegularFile {
                path: dir.path().to_string_lossy().into_owned(),
            }
        );
        assert!(dir.path().exists());
    }

    #[test]
    fn stage_copies_the_content_into_a_hidden_temporary_entry() {
        let dir = TempDir::new().unwrap();
        let stage = dir.path().join("stage");
        fs::create_dir(&stage).unwrap();
        let source = write(dir.path(), "IMG.jpg", b"raw-content");

        let staged = stage_copy(&source, &stage, None).expect("the file is staged");

        let staged_name = file_name(Path::new(&staged.path));
        assert!(staged_name.starts_with(".keep-or-nah-"));
        assert!(staged_name.ends_with(".tmp"));
        assert_eq!(Path::new(&staged.path).parent().unwrap(), stage.as_path());
        assert_eq!(fs::read(&staged.path).unwrap(), b"raw-content");
    }

    #[test]
    fn stage_preserves_the_permissions_and_the_timestamps() {
        let dir = TempDir::new().unwrap();
        let stage = dir.path().join("stage");
        fs::create_dir(&stage).unwrap();
        let source = write(dir.path(), "IMG.jpg", b"raw");

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&source, fs::Permissions::from_mode(0o640)).unwrap();
        }
        let timestamp = filetime::FileTime::from_unix_time(1_700_000_000, 123_456_000);
        filetime::set_file_times(&source, timestamp, timestamp).unwrap();

        let staged = stage_copy(&source, &stage, None).expect("the file is staged");
        let staged_metadata = fs::metadata(&staged.path).unwrap();
        let source_metadata = fs::metadata(&source).unwrap();

        assert_eq!(
            staged_metadata.len(),
            source_metadata.len(),
            "the staged copy has a different size"
        );
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                staged_metadata.permissions().mode() & 0o7777,
                source_metadata.permissions().mode() & 0o7777
            );
        }
        assert_eq!(
            staged_metadata
                .modified()
                .unwrap()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos(),
            source_metadata
                .modified()
                .unwrap()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        );
    }

    #[test]
    fn stage_reports_the_identity_of_the_staged_entry() {
        let dir = TempDir::new().unwrap();
        let stage = dir.path().join("stage");
        fs::create_dir(&stage).unwrap();
        let source = write(dir.path(), "IMG.jpg", b"raw");

        let staged = stage_copy(&source, &stage, None).expect("the file is staged");
        let identity = identity_of(Path::new(&staged.path)).expect("the staged file is readable");

        assert_eq!((staged.dev, staged.ino), (identity.dev, identity.ino));
    }

    #[test]
    fn stage_refuses_a_symlink_source() {
        let dir = TempDir::new().unwrap();
        let stage = dir.path().join("stage");
        fs::create_dir(&stage).unwrap();
        let target = write(dir.path(), "IMG.jpg", b"raw");
        let link = dir.path().join("LINK.jpg");
        #[cfg(unix)]
        std::os::unix::fs::symlink(&target, &link).unwrap();
        #[cfg(not(unix))]
        let _ = link;

        let error = stage_copy(&link, &stage, None).expect_err("a symlink is not staged");

        assert_eq!(
            error,
            FileOpError::Symlink {
                path: link.to_string_lossy().into_owned(),
                role: Role::Source,
            }
        );
        assert_eq!(fs::read_dir(&stage).unwrap().count(), 0);
    }

    #[test]
    fn stage_refuses_a_directory_source() {
        let dir = TempDir::new().unwrap();
        let stage = dir.path().join("stage");
        fs::create_dir(&stage).unwrap();

        let error = stage_copy(dir.path(), &stage, None).expect_err("a directory is not staged");

        assert_eq!(
            error,
            FileOpError::NotARegularFile {
                path: dir.path().to_string_lossy().into_owned(),
                role: Role::Source,
            }
        );
        assert_eq!(fs::read_dir(&stage).unwrap().count(), 0);
    }

    #[test]
    fn stage_refuses_a_source_that_lost_its_identity() {
        let dir = TempDir::new().unwrap();
        let stage = dir.path().join("stage");
        fs::create_dir(&stage).unwrap();
        let source = write(dir.path(), "IMG.jpg", b"raw");
        let identity = identity_of(&source).unwrap();
        // A racer replaces the source with a different file.
        fs::remove_file(&source).unwrap();
        write(dir.path(), "IMG.jpg", b"replacement");

        let error = stage_copy(&source, &stage, Some(identity))
            .expect_err("the replaced source is not staged");

        assert_eq!(
            error,
            FileOpError::IdentityChanged {
                path: source.to_string_lossy().into_owned(),
                role: Role::Source,
            }
        );
        assert_eq!(fs::read_dir(&stage).unwrap().count(), 0);
    }

    #[test]
    fn stage_refuses_a_folder_that_is_not_a_directory() {
        let dir = TempDir::new().unwrap();
        let source = write(dir.path(), "IMG.jpg", b"raw");
        let not_a_folder = dir.path().join("not-a-folder");

        let error = stage_copy(&source, &not_a_folder, None)
            .expect_err("a missing stage folder is refused");

        assert_eq!(
            error,
            FileOpError::NotAStageDirectory {
                path: not_a_folder.to_string_lossy().into_owned(),
            }
        );
    }

    #[test]
    fn stage_leaves_the_source_untouched() {
        let dir = TempDir::new().unwrap();
        let stage = dir.path().join("stage");
        fs::create_dir(&stage).unwrap();
        let source = write(dir.path(), "IMG.jpg", b"raw");

        stage_copy(&source, &stage, None).expect("the file is staged");

        assert_eq!(fs::read(&source).unwrap(), b"raw");
    }

    #[test]
    fn staging_twice_produces_two_distinct_entries() {
        let dir = TempDir::new().unwrap();
        let stage = dir.path().join("stage");
        fs::create_dir(&stage).unwrap();
        let source = write(dir.path(), "IMG.jpg", b"raw");

        let first = stage_copy(&source, &stage, None).unwrap();
        let second = stage_copy(&source, &stage, None).unwrap();

        assert_ne!(first.path, second.path);
        assert_eq!(fs::read_dir(&stage).unwrap().count(), 2);
    }
}
