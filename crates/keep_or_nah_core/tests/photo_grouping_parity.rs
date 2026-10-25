use keep_or_nah_core::scan::{build_photo_groups, discover_extensions};
use std::fs::{self, File};
use tempfile::tempdir;

#[test]
fn test_photo_grouping_same_stem_multiple_extensions() {
    let dir = tempdir().expect("create temp dir");
    let path = dir.path();

    File::create(path.join("DSC_0001.JPG")).unwrap();
    File::create(path.join("DSC_0001.CR2")).unwrap();
    File::create(path.join("DSC_0001.XMP")).unwrap();
    File::create(path.join("DSC_0002.jpg")).unwrap();

    let enabled = vec![".jpg".to_string(), ".cr2".to_string(), ".xmp".to_string()];
    // Only JPG is in previewable set; CR2 is not previewable
    let previewable = vec![".jpg".to_string()];

    let groups = build_photo_groups(path, &enabled, &previewable);
    assert_eq!(groups.len(), 2);

    let g1 = &groups[0];
    assert_eq!(g1.stem, "DSC_0001");
    assert_eq!(g1.members.len(), 3);
    assert_eq!(g1.representative.file_name().unwrap(), "DSC_0001.JPG");

    let g2 = &groups[1];
    assert_eq!(g2.stem, "DSC_0002");
    assert_eq!(g2.members.len(), 1);
    assert_eq!(g2.representative.file_name().unwrap(), "DSC_0002.jpg");
}

#[test]
fn test_photo_grouping_case_insensitive_ordering() {
    let dir = tempdir().expect("create temp dir");
    let path = dir.path();

    File::create(path.join("banana.jpg")).unwrap();
    File::create(path.join("cherry.jpg")).unwrap();
    File::create(path.join("Apple.jpg")).unwrap();

    let enabled = vec![".jpg".to_string()];
    let previewable = vec![".jpg".to_string()];

    let groups = build_photo_groups(path, &enabled, &previewable);
    assert_eq!(groups.len(), 3);

    // Sorted by (stem.lower(), stem): Apple, banana, cherry
    assert_eq!(groups[0].stem, "Apple");
    assert_eq!(groups[1].stem, "banana");
    assert_eq!(groups[2].stem, "cherry");
}

#[test]
fn test_photo_grouping_ignores_subdirectories_and_files_without_extensions() {
    let dir = tempdir().expect("create temp dir");
    let path = dir.path();

    let subdir = path.join("subfolder");
    fs::create_dir(&subdir).unwrap();
    File::create(subdir.join("IMG_9999.jpg")).unwrap();

    File::create(path.join("README")).unwrap();
    File::create(path.join("valid.jpg")).unwrap();

    let enabled = vec![".jpg".to_string()];
    let previewable = vec![".jpg".to_string()];

    let groups = build_photo_groups(path, &enabled, &previewable);
    assert_eq!(groups.len(), 1);
    assert_eq!(groups[0].stem, "valid");
}

#[test]
fn test_discover_extensions_normalized_and_sorted() {
    let dir = tempdir().expect("create temp dir");
    let path = dir.path();

    File::create(path.join("a.JPG")).unwrap();
    File::create(path.join("b.cr2")).unwrap();
    File::create(path.join("c.xmp")).unwrap();
    File::create(path.join("d.Jpg")).unwrap();
    File::create(path.join("no_extension")).unwrap();

    let exts = discover_extensions(path);
    assert_eq!(exts, vec![".cr2", ".jpg", ".xmp"]);
}

#[test]
fn test_photo_grouping_empty_and_nonexistent_directory() {
    let dir = tempdir().expect("create temp dir");
    let enabled = vec![".jpg".to_string()];
    let previewable = vec![".jpg".to_string()];

    let empty_groups = build_photo_groups(dir.path(), &enabled, &previewable);
    assert!(empty_groups.is_empty());

    let nonexistent = dir.path().join("does_not_exist");
    let non_groups = build_photo_groups(&nonexistent, &enabled, &previewable);
    assert!(non_groups.is_empty());

    let empty_exts = discover_extensions(&nonexistent);
    assert!(empty_exts.is_empty());
}
