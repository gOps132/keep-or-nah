use keep_or_nah_core::fileops::{
    identity_matches, identity_of, remove_verified, stage_copy, FileOpError, Role,
};
use std::fs::{self, File};
use std::io::Write;
use tempfile::tempdir;

#[test]
fn test_read_identity_and_verify_match() {
    let dir = tempdir().expect("create temp dir");
    let file_path = dir.path().join("photo.jpg");

    {
        let mut f = File::create(&file_path).unwrap();
        f.write_all(b"sample photo data").unwrap();
    }

    let identity = identity_of(&file_path).expect("read identity");
    assert_eq!(identity.size, 17);

    let components = identity.components();
    assert!(identity_matches(&identity, &components));

    // Legacy 2-component match (dev, ino)
    let legacy = &components[..2];
    assert!(identity_matches(&identity, legacy));

    // Invalid length
    assert!(!identity_matches(&identity, &components[..1]));
}

#[test]
fn test_stage_copy_preserves_content_and_reports_identity() {
    let source_dir = tempdir().expect("source dir");
    let target_dir = tempdir().expect("target dir");

    let src_file = source_dir.path().join("DSC_0001.JPG");
    {
        let mut f = File::create(&src_file).unwrap();
        f.write_all(b"high-res raw image content").unwrap();
    }

    let staged = stage_copy(&src_file, target_dir.path(), None).expect("stage copy");
    let staged_path = std::path::Path::new(&staged.path);

    assert!(staged_path.exists());
    assert_eq!(fs::read(&src_file).unwrap(), fs::read(staged_path).unwrap());
    assert_eq!(staged.size, 26);
}

#[test]
fn test_remove_verified_succeeds_for_matching_identity() {
    let dir = tempdir().expect("temp dir");
    let file_path = dir.path().join("to_delete.jpg");
    File::create(&file_path).unwrap();

    let identity = identity_of(&file_path).unwrap();
    let components = identity.components();

    // Verification and removal succeeds
    let result = remove_verified(&file_path, &components);
    assert!(result.is_ok());
    assert!(!file_path.exists());

    // Subsequent removal fails with Missing
    let second_attempt = remove_verified(&file_path, &components);
    assert!(matches!(second_attempt, Err(FileOpError::Missing { .. })));
}

#[test]
fn test_remove_verified_refuses_when_file_tampered() {
    let dir = tempdir().expect("temp dir");
    let file_path = dir.path().join("tampered.jpg");
    {
        let mut f = File::create(&file_path).unwrap();
        f.write_all(b"original").unwrap();
    }

    let identity = identity_of(&file_path).unwrap();
    let components = identity.components();

    // File content modified (size changed)
    {
        let mut f = File::create(&file_path).unwrap();
        f.write_all(b"modified with different size").unwrap();
    }

    let result = remove_verified(&file_path, &components);
    assert!(matches!(
        result,
        Err(FileOpError::IdentityChanged {
            role: Role::Owned,
            ..
        })
    ));
    assert!(file_path.exists(), "Tampered file should not be deleted");
}
