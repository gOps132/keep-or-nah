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
    let previewable_set: HashSet<String> = previewable
        .iter()
        .map(|raw| raw.to_lowercase())
        .collect();

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

        // Representative: previewable first, then extension, then filename.
        let representative = eligible
            .iter()
            .min_by(|a, b| {
                rank_member(a, &previewable_set)
                    .cmp(&rank_member(b, &previewable_set))
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

fn rank_member(member: &Member, previewable_set: &HashSet<String>) -> (bool, String, String, String) {
    (
        !previewable_set.contains(&member.suffix_lower),
        member.suffix_lower.clone(),
        member.lower_name.clone(),
        member.name.clone(),
    )
}
