//! Native, atomic-oriented file operation primitives for Keep or Nah.
//!
//! Copies stage a byte-complete file inside the destination folder as a hidden
//! temporary entry, preserve the source permissions and timestamps, fsync the
//! staged data, and return the staged identity so callers can publish it
//! exclusively (hard link / rename) with identity verification afterwards.
//! Removal primitives refuse to unlink entries whose on-disk identity no
//! longer matches the recorded one, which makes the undo journal transactional
//! against racers that replace published paths.

use std::fs;
use std::io;
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};

use pyo3::exceptions::PyOSError;
use pyo3::prelude::*;

#[pyclass(get_all)]
pub struct PyStagedFile {
    pub path: String,
    pub dev: u64,
    pub ino: u64,
}

fn io_error(error: io::Error) -> PyErr {
    PyOSError::new_err(error.to_string())
}

fn error(message: impl Into<String>) -> PyErr {
    PyOSError::new_err(message.into())
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
fn file_identity_of(path: &Path, metadata: &fs::Metadata) -> PyResult<(u64, u64)> {
    use std::os::unix::fs::MetadataExt;
    let _ = path;
    Ok((metadata.dev(), metadata.ino()))
}

#[cfg(windows)]
fn file_identity_of(_path: &Path, metadata: &fs::Metadata) -> PyResult<(u64, u64)> {
    use std::os::windows::fs::MetadataExt;
    let file_index = metadata
        .file_index()
        .map(|index| index as u64)
        .unwrap_or(0);
    Ok((0_u64, file_index))
}

/// Return the stable identity of a regular, non-symlink file entry.
#[pyfunction]
pub fn file_identity(path: &str) -> PyResult<(u64, u64)> {
    let entry = Path::new(path);
    let metadata = fs::symlink_metadata(entry).map_err(io_error)?;
    if metadata.file_type().is_symlink() {
        return Err(error(format!("Owned path is a symbolic link: {path}")));
    }
    if !metadata.is_file() {
        return Err(error(format!("Owned path is not a regular file: {path}")));
    }
    file_identity_of(entry, &metadata)
}

/// Verify an entry still owns `(dev, ino)` and delete it; refuse otherwise.
#[pyfunction]
#[pyo3(signature = (path, dev, ino))]
pub fn remove_verified_file(path: &str, dev: u64, ino: u64) -> PyResult<()> {
    let entry = Path::new(path);
    let metadata = match fs::symlink_metadata(entry) {
        Ok(metadata) => metadata,
        Err(error_ref) if error_ref.kind() == io::ErrorKind::NotFound => {
            return Err(error(format!("Owned path is missing: {path}")));
        }
        Err(error_ref) => return Err(io_error(error_ref)),
    };
    if metadata.file_type().is_symlink() {
        return Err(error(format!(
            "Owned path is no longer a regular file: {path}"
        )));
    }
    if !metadata.is_file() {
        return Err(error(format!(
            "Owned path is no longer a regular file: {path}"
        )));
    }
    let (actual_dev, actual_ino) = file_identity_of(entry, &metadata)?;
    if (actual_dev, actual_ino) != (dev, ino) {
        return Err(error(format!("Refusing to remove a replaced path: {path}")));
    }
    fs::remove_file(entry).map_err(io_error)?;
    Ok(())
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
    let source_path = Path::new(source);
    let stage_root = Path::new(stage_dir);

    let metadata = fs::symlink_metadata(source_path).map_err(io_error)?;
    if metadata.file_type().is_symlink() {
        return Err(error(format!(
            "Source path is a symbolic link and cannot be staged: {source}"
        )));
    }
    if !metadata.is_file() {
        return Err(error(format!(
            "Source path is not a regular file: {source}"
        )));
    }
    if let (Some(expected_dev), Some(expected_ino)) = (expected_dev, expected_ino) {
        let (actual_dev, actual_ino) = file_identity_of(source_path, &metadata)?;
        if (actual_dev, actual_ino) != (expected_dev, expected_ino) {
            return Err(error(format!(
                "Source path identity changed unexpectedly: {source}"
            )));
        }
    }
    let mode = source_mode(&metadata);
    let staged_path = create_stage_path(stage_root)?;
    // A zero-byte source copies as a valid zero-byte staged file.
    fs::copy(source_path, &staged_path).map_err(|copy_error| {
        let _staged = fs::remove_file(&staged_path);
        copy_error
    })?;
    let result = stage_finish(&staged_path, mode, &metadata);
    if let Err(stage_error) = result {
        let _ = fs::remove_file(&staged_path);
        return Err(stage_error);
    }

    let staged_metadata = fs::symlink_metadata(&staged_path).map_err(io_error)?;
    let (staged_dev, staged_ino) = file_identity_of(&staged_path, &staged_metadata)?;
    Ok(PyStagedFile {
        path: staged_path.to_string_lossy().into_owned(),
        dev: staged_dev,
        ino: staged_ino,
    })
}

fn create_stage_path(stage_root: &Path) -> PyResult<std::path::PathBuf> {
    if !stage_root.is_dir() {
        return Err(error(format!(
            "Stage folder is not a directory: {}",
            stage_root.display()
        )));
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
            Err(err) => return Err(io_error(err)),
        }
    }
    Err(error("Could not allocate a unique staging file"))
}

fn stage_finish(
    staged: &Path,
    mode: Option<u32>,
    metadata: &fs::Metadata,
) -> PyResult<()> {
    if let Some(mode) = mode {
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let permissions = fs::Permissions::from_mode(mode & 0o7777);
            if let Err(permission_error) = fs::set_permissions(staged, permissions) {
                return Err(io_error(permission_error));
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
        .map_err(io_error)?;
    }
    #[cfg(not(unix))]
    {
        let _ = metadata;
    }
    fs::File::open(staged)
        .and_then(|handle| handle.sync_all())
        .map_err(io_error)?;
    Ok(())
}
