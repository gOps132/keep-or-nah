//! Native, GIL-free directory scan.
//!
//! Direct-child file enumeration and same-stem photo grouping, with
//! deterministic parity against the historical `photo_groups.py`
//! implementation: exact stem matching, case-insensitive ordering,
//! and preview-preferred representative selection.

use std::collections::{BTreeSet, HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};

/// One deterministic queue item: every direct-child file sharing one
/// exact filename stem, plus the preview-preferred representative.
#[derive(Clone)]
pub struct ScannedGroup {
    pub stem: String,
    pub members: Vec<PathBuf>,
    pub representative: PathBuf,
}

struct Member {
    name: String,
    lower_name: String,
    suffix_lower: String,
    path: PathBuf,
}

impl Member {
    fn is_enabled(&self, enabled: &HashSet<String>) -> bool {
        enabled.contains(&self.suffix_lower)
    }
}

/// Python `pathlib.is_file()` + `is_symlink()` exclusion semantics.
fn is_direct_regular_file(path: &Path) -> bool {
    match fs::symlink_metadata(path) {
        Ok(md) => md.is_file() && !md.is_symlink(),
        Err(_) => false,
    }
}

/// Split a bare filename into `(stem, suffix)` using Python `pathlib`
/// semantics: the suffix is empty when the only dot is a leading one or
/// the final character (``.hidden``,
/// ``weird.``), otherwise everything from the last dot is the suffix.
fn pathlib_stem_suffix(file_name: &str) -> (&str, &str) {
    match file_name.rfind('.') {
        Some(index) if index > 0 && index < file_name.len() - 1 => {
            (&file_name[..index], &file_name[index..])
        }
        _ => (file_name, ""),
    }
}

fn member_of(path: &Path) -> Member {
    let name = path
        .file_name()
        .map(|raw| raw.to_string_lossy().into_owned())
        .unwrap_or_default();
    let (_, suffix) = pathlib_stem_suffix(&name);
    Member {
        name: name.clone(),
        lower_name: name.to_lowercase(),
        suffix_lower: suffix.to_lowercase(),
        path: path.to_path_buf(),
    }
}

fn read_direct_children(source_dir: &Path) -> Vec<Member> {
    let Ok(entries) = fs::read_dir(source_dir) else {
        return Vec::new();
    };
    entries
        .filter_map(|entry| entry.ok())
        .map(|entry| entry.path())
        .filter(|path| is_direct_regular_file(path))
        .map(|path| member_of(&path))
        .collect()
}

/// Default raster formats that can be displayed directly in preview viewports.
pub const DEFAULT_PREVIEWABLE_EXTENSIONS: &[&str] = &[
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".tif", ".heic", ".heif", ".hif",
    ".avif", ".jxl", ".psd", ".exr", ".hdr", ".qoi", ".tga", ".ico",
];

/// Returns the default list of previewable extensions.
pub fn default_previewable_extensions() -> Vec<String> {
    DEFAULT_PREVIEWABLE_EXTENSIONS
        .iter()
        .map(|s| s.to_string())
        .collect()
}

/// Normalized extensions found among direct-child regular files,
/// ascending — Python `discover_extensions`.
pub fn discover_extensions(source_dir: &Path) -> Vec<String> {
    let mut extensions = BTreeSet::new();
    for member in read_direct_children(source_dir) {
        if !member.suffix_lower.is_empty() {
            extensions.insert(member.suffix_lower);
        }
    }
    extensions.into_iter().collect()
}

/// Build one deterministic queue item for every eligible exact stem —
/// Python `build_photo_groups`.
pub fn build_photo_groups(
    source_dir: &Path,
    enabled: &[String],
    previewable: &[String],
) -> Vec<ScannedGroup> {
    let enabled_set: HashSet<String> = enabled.iter().map(|raw| raw.to_lowercase()).collect();
    let mut previewable_order: HashMap<String, usize> = HashMap::new();
    for (idx, raw) in previewable.iter().enumerate() {
        previewable_order.entry(raw.to_lowercase()).or_insert(idx);
    }

    // Bucket by exact stem (case-sensitive), like Python's `setdefault` loop.
    let mut buckets: HashMap<String, Vec<Member>> = HashMap::new();
    for member in read_direct_children(source_dir) {
        let (stem, _) = pathlib_stem_suffix(&member.name);
        buckets.entry(stem.to_string()).or_default().push(member);
    }

    // Order buckets by (stem.lower(), stem).
    let mut stems: Vec<(String, String, Vec<Member>)> = buckets
        .into_iter()
        .map(|(stem, members)| (stem.to_lowercase(), stem, members))
        .collect();
    stems.sort_by(|a, b| match a.0.cmp(&b.0) {
        std::cmp::Ordering::Equal => a.1.cmp(&b.1),
        other => other,
    });

    let mut groups = Vec::with_capacity(stems.len());
    for (_, stem, members) in stems {
        // Members ordered by (name.lower(), name).
        let mut members = members;
        members.sort_by(|a, b| match a.lower_name.cmp(&b.lower_name) {
            std::cmp::Ordering::Equal => a.name.cmp(&b.name),
            other => other,
        });

        let eligible: Vec<&Member> = members
            .iter()
            .filter(|member| member.is_enabled(&enabled_set))
            .collect();
        if eligible.is_empty() {
            continue;
        }

        // Representative: previewable first (by order), then extension, then filename.
        let representative = eligible
            .iter()
            .min_by(|a, b| {
                rank_member(a, &previewable_order).cmp(&rank_member(b, &previewable_order))
            })
            .expect("eligible is non-empty")
            .path
            .clone();

        groups.push(ScannedGroup {
            stem,
            members: members.into_iter().map(|member| member.path).collect(),
            representative,
        });
    }
    groups
}

fn rank_member(
    member: &Member,
    previewable_order: &HashMap<String, usize>,
) -> (usize, String, String, String) {
    (
        previewable_order
            .get(&member.suffix_lower)
            .copied()
            .unwrap_or(usize::MAX),
        member.suffix_lower.clone(),
        member.lower_name.clone(),
        member.name.clone(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn write(dir: &Path, name: &str) -> PathBuf {
        let path = dir.join(name);
        fs::write(&path, b"fixture").expect("write fixture");
        path
    }

    fn names(paths: &[PathBuf]) -> Vec<String> {
        paths
            .iter()
            .map(|path| path.file_name().unwrap().to_string_lossy().into_owned())
            .collect()
    }

    fn extensions(values: &[&str]) -> Vec<String> {
        values.iter().map(|value| value.to_string()).collect()
    }

    /// True when the file system keeps two entries whose names differ only in
    /// case. macOS and Windows fold case, Linux does not.
    fn case_sensitive_file_system(dir: &Path) -> bool {
        let upper = dir.join("CaseProbe");
        let lower = dir.join("caseprobe");
        fs::write(&upper, b"upper").unwrap();
        fs::write(&lower, b"lower").unwrap();
        let distinct = upper.exists()
            && lower.exists()
            && fs::read(&upper).unwrap() != fs::read(&lower).unwrap();
        let _ = fs::remove_file(&upper);
        let _ = fs::remove_file(&lower);
        distinct
    }

    #[test]
    fn discover_extensions_normalizes_case_and_sorts_ascending() {
        let dir = TempDir::new().unwrap();
        write(dir.path(), "b.JPG");
        write(dir.path(), "a.jpeg");
        write(dir.path(), "c.XMP");

        assert_eq!(
            discover_extensions(dir.path()),
            vec![".jpeg".to_string(), ".jpg".to_string(), ".xmp".to_string()]
        );
    }

    #[test]
    fn discover_extensions_ignores_files_without_a_suffix() {
        let dir = TempDir::new().unwrap();
        write(dir.path(), "README");
        write(dir.path(), ".hidden");
        write(dir.path(), "photo.jpg");

        assert_eq!(discover_extensions(dir.path()), vec![".jpg".to_string()]);
    }

    #[test]
    fn discover_extensions_only_looks_at_direct_children() {
        let dir = TempDir::new().unwrap();
        write(dir.path(), "photo.jpg");
        let nested = dir.path().join("nested");
        fs::create_dir(&nested).unwrap();
        fs::write(nested.join("inside.png"), b"fixture").unwrap();

        assert_eq!(discover_extensions(dir.path()), vec![".jpg".to_string()]);
    }

    #[test]
    fn discover_extensions_of_a_missing_directory_is_empty() {
        let dir = TempDir::new().unwrap();
        let missing = dir.path().join("does-not-exist");

        assert!(discover_extensions(&missing).is_empty());
    }

    #[test]
    fn build_photo_groups_groups_files_that_share_a_stem() {
        let dir = TempDir::new().unwrap();
        write(dir.path(), "IMG.jpg");
        write(dir.path(), "IMG.xmp");
        write(dir.path(), "OTHER.jpg");

        let groups = build_photo_groups(
            dir.path(),
            &extensions(&[".jpg", ".xmp"]),
            &extensions(&[".jpg"]),
        );

        assert_eq!(groups.len(), 2);
        let group = &groups[0];
        assert_eq!(group.stem, "IMG");
        assert_eq!(names(&group.members), vec!["IMG.jpg", "IMG.xmp"]);
        assert_eq!(group.representative.file_name().unwrap(), "IMG.jpg");
        assert_eq!(groups[1].stem, "OTHER");
    }

    #[test]
    fn build_photo_groups_picks_the_previewable_member_as_representative() {
        let dir = TempDir::new().unwrap();
        write(dir.path(), "IMG.cr2");
        write(dir.path(), "IMG.xmp");
        write(dir.path(), "IMG.jpg");

        let groups = build_photo_groups(
            dir.path(),
            &extensions(&[".cr2", ".jpg", ".xmp"]),
            &extensions(&[".jpg"]),
        );

        assert_eq!(groups.len(), 1);
        assert_eq!(groups[0].representative.file_name().unwrap(), "IMG.jpg");
    }

    #[test]
    fn build_photo_groups_falls_back_to_the_lowest_extension() {
        let dir = TempDir::new().unwrap();
        write(dir.path(), "IMG.xmp");
        write(dir.path(), "IMG.cr2");

        let groups =
            build_photo_groups(dir.path(), &extensions(&[".cr2", ".xmp"]), &extensions(&[]));

        assert_eq!(groups.len(), 1);
        assert_eq!(groups[0].representative.file_name().unwrap(), "IMG.cr2");
    }

    #[test]
    fn build_photo_groups_skips_stems_without_an_enabled_member() {
        let dir = TempDir::new().unwrap();
        write(dir.path(), "IMG.jpg");
        write(dir.path(), "NOTES.txt");

        let groups = build_photo_groups(dir.path(), &extensions(&[".jpg"]), &extensions(&[".jpg"]));

        assert_eq!(groups.len(), 1);
        assert_eq!(groups[0].stem, "IMG");
    }

    #[test]
    fn build_photo_groups_keeps_disabled_members_in_the_group() {
        let dir = TempDir::new().unwrap();
        write(dir.path(), "IMG.jpg");
        write(dir.path(), "IMG.txt");

        let groups = build_photo_groups(dir.path(), &extensions(&[".jpg"]), &extensions(&[".jpg"]));

        assert_eq!(groups.len(), 1);
        assert_eq!(names(&groups[0].members), vec!["IMG.jpg", "IMG.txt"]);
        assert_eq!(groups[0].representative.file_name().unwrap(), "IMG.jpg");
    }

    #[test]
    fn build_photo_groups_treats_stems_case_sensitively() {
        let dir = TempDir::new().unwrap();
        if !case_sensitive_file_system(dir.path()) {
            // The file system folds case, so two stems that differ only in
            // case cannot live in the same directory.
            return;
        }
        write(dir.path(), "IMG.jpg");
        write(dir.path(), "img.jpg");

        let groups = build_photo_groups(dir.path(), &extensions(&[".jpg"]), &extensions(&[".jpg"]));

        assert_eq!(groups.len(), 2);
        let stems: Vec<&str> = groups.iter().map(|group| group.stem.as_str()).collect();
        assert_eq!(stems, vec!["IMG", "img"]);
    }

    #[test]
    fn build_photo_groups_orders_groups_case_insensitively() {
        let dir = TempDir::new().unwrap();
        write(dir.path(), "beta.jpg");
        write(dir.path(), "Alpha.jpg");
        write(dir.path(), "gamma.jpg");

        let groups = build_photo_groups(dir.path(), &extensions(&[".jpg"]), &extensions(&[".jpg"]));

        let stems: Vec<&str> = groups.iter().map(|group| group.stem.as_str()).collect();
        assert_eq!(stems, vec!["Alpha", "beta", "gamma"]);
    }

    #[test]
    fn build_photo_groups_uses_pathlib_suffix_semantics() {
        let dir = TempDir::new().unwrap();
        write(dir.path(), "IMG.tar.gz");
        write(dir.path(), "sidecar.xmp");

        let groups = build_photo_groups(
            dir.path(),
            &extensions(&[".gz", ".xmp"]),
            &extensions(&[".gz"]),
        );

        assert_eq!(groups.len(), 2);
        let stems: Vec<&str> = groups.iter().map(|group| group.stem.as_str()).collect();
        assert_eq!(stems, vec!["IMG.tar", "sidecar"]);
    }

    #[test]
    fn build_photo_groups_ignores_symlinks_and_directories() {
        let dir = TempDir::new().unwrap();
        let target = write(dir.path(), "IMG.jpg");
        let link = dir.path().join("LINK.jpg");
        #[cfg(unix)]
        std::os::unix::fs::symlink(&target, &link).unwrap();
        #[cfg(windows)]
        // Creating a symbolic link on Windows needs a privilege that a
        // build agent does not have. The scan still has to leave the
        // directory alone when the link cannot be created.
        let _ = std::os::windows::fs::symlink_file(&target, &link);
        fs::create_dir(dir.path().join("FOLDER.jpg")).unwrap();

        let groups = build_photo_groups(dir.path(), &extensions(&[".jpg"]), &extensions(&[".jpg"]));

        assert_eq!(groups.len(), 1);
        assert_eq!(groups[0].stem, "IMG");
        assert_eq!(names(&groups[0].members), vec!["IMG.jpg"]);
    }

    #[test]
    fn build_photo_groups_of_a_missing_directory_is_empty() {
        let dir = TempDir::new().unwrap();
        let missing = dir.path().join("does-not-exist");

        let groups = build_photo_groups(&missing, &extensions(&[".jpg"]), &extensions(&[".jpg"]));

        assert!(groups.is_empty());
    }

    #[test]
    fn build_photo_groups_prioritizes_jpeg_over_arw_in_same_stem_group() {
        let dir = TempDir::new().unwrap();
        write(dir.path(), "DSC0001.ARW");
        write(dir.path(), "DSC0001.JPG");
        write(dir.path(), "DSC0001.xmp");

        let groups = build_photo_groups(
            dir.path(),
            &discover_extensions(dir.path()),
            &default_previewable_extensions(),
        );

        assert_eq!(groups.len(), 1);
        assert_eq!(groups[0].stem, "DSC0001");
        assert_eq!(
            names(&groups[0].members),
            vec!["DSC0001.ARW", "DSC0001.JPG", "DSC0001.xmp"]
        );
        assert_eq!(groups[0].representative.file_name().unwrap(), "DSC0001.JPG");
    }

    #[test]
    fn build_photo_groups_respects_previewable_order_priority() {
        let dir = TempDir::new().unwrap();
        write(dir.path(), "DSC0001.png");
        write(dir.path(), "DSC0001.jpg");

        let groups_png_first = build_photo_groups(
            dir.path(),
            &extensions(&[".png", ".jpg"]),
            &extensions(&[".png", ".jpg"]),
        );
        assert_eq!(
            groups_png_first[0].representative.file_name().unwrap(),
            "DSC0001.png"
        );

        let groups_jpg_first = build_photo_groups(
            dir.path(),
            &extensions(&[".png", ".jpg"]),
            &extensions(&[".jpg", ".png"]),
        );
        assert_eq!(
            groups_jpg_first[0].representative.file_name().unwrap(),
            "DSC0001.jpg"
        );
    }
}
