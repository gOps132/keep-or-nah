use keep_or_nah_lib::commands::PhotoGroupDto;
use keep_or_nah_lib::session::{ActionMode, Decision, SessionState};
use std::fs::File;
use std::io::Write;
use tempfile::tempdir;

#[test]
fn test_session_lifecycle_staging_undo_and_counts() {
    let mut state = SessionState::new();
    let dir = tempdir().unwrap();
    state.reset_with_dir(dir.path().to_string_lossy().to_string());

    // Register 3 photo groups
    let groups = vec![
        PhotoGroupDto {
            stem: "IMG_0001".to_string(),
            members: vec![dir
                .path()
                .join("IMG_0001.jpg")
                .to_string_lossy()
                .to_string()],
            representative: dir
                .path()
                .join("IMG_0001.jpg")
                .to_string_lossy()
                .to_string(),
            index: 0,
        },
        PhotoGroupDto {
            stem: "IMG_0002".to_string(),
            members: vec![dir
                .path()
                .join("IMG_0002.jpg")
                .to_string_lossy()
                .to_string()],
            representative: dir
                .path()
                .join("IMG_0002.jpg")
                .to_string_lossy()
                .to_string(),
            index: 1,
        },
        PhotoGroupDto {
            stem: "IMG_0003".to_string(),
            members: vec![dir
                .path()
                .join("IMG_0003.jpg")
                .to_string_lossy()
                .to_string()],
            representative: dir
                .path()
                .join("IMG_0003.jpg")
                .to_string_lossy()
                .to_string(),
            index: 2,
        },
    ];
    state.register_groups(&groups);

    // Initial counts
    let counts = state.get_staged_counts();
    assert_eq!(counts.keep, 0);
    assert_eq!(counts.nah, 0);
    assert_eq!(counts.flag, 0);

    // Stage Keep on 1, Nah on 2, Flag on 3
    state.stage_decision("IMG_0001".to_string(), Decision::Keep);
    state.stage_decision("IMG_0002".to_string(), Decision::Nah);
    state.stage_decision("IMG_0003".to_string(), Decision::Flag);

    let counts = state.get_staged_counts();
    assert_eq!(counts.keep, 1);
    assert_eq!(counts.nah, 1);
    assert_eq!(counts.flag, 1);

    // Change decision on 1 from Keep to Nah
    state.stage_decision("IMG_0001".to_string(), Decision::Nah);
    let counts = state.get_staged_counts();
    assert_eq!(counts.keep, 0);
    assert_eq!(counts.nah, 2);

    // Undo reverts 1 back to Keep
    let undone = state.undo_last_decision();
    assert_eq!(undone, Some("IMG_0001".to_string()));
    assert_eq!(state.decisions.get("IMG_0001"), Some(&Decision::Keep));

    // Undo reverts 3 back to un-staged
    let undone = state.undo_last_decision();
    assert_eq!(undone, Some("IMG_0003".to_string()));
    assert_eq!(state.decisions.get("IMG_0003"), None);
}

#[test]
fn test_session_commit_batch_move_flow() {
    let source_dir = tempdir().unwrap();
    let keep_dest = tempdir().unwrap();
    let nah_dest = tempdir().unwrap();

    let f1_jpg = source_dir.path().join("PHOTO_1.jpg");
    let f1_cr2 = source_dir.path().join("PHOTO_1.cr2");
    let f2_jpg = source_dir.path().join("PHOTO_2.jpg");

    File::create(&f1_jpg).unwrap().write_all(b"jpg1").unwrap();
    File::create(&f1_cr2).unwrap().write_all(b"cr2_1").unwrap();
    File::create(&f2_jpg).unwrap().write_all(b"jpg2").unwrap();

    let mut state = SessionState::new();
    state.reset_with_dir(source_dir.path().to_string_lossy().to_string());

    let groups = vec![
        PhotoGroupDto {
            stem: "PHOTO_1".to_string(),
            members: vec![
                f1_jpg.to_string_lossy().to_string(),
                f1_cr2.to_string_lossy().to_string(),
            ],
            representative: f1_jpg.to_string_lossy().to_string(),
            index: 0,
        },
        PhotoGroupDto {
            stem: "PHOTO_2".to_string(),
            members: vec![f2_jpg.to_string_lossy().to_string()],
            representative: f2_jpg.to_string_lossy().to_string(),
            index: 1,
        },
    ];
    state.register_groups(&groups);

    // Stage PHOTO_1 as Keep, PHOTO_2 as Nah
    state.stage_decision("PHOTO_1".to_string(), Decision::Keep);
    state.stage_decision("PHOTO_2".to_string(), Decision::Nah);

    // Summary calculation
    let summary = state.calculate_batch_summary();
    assert_eq!(summary.total_groups, 2);
    assert_eq!(summary.keep_count, 1);
    assert_eq!(summary.nah_count, 1);
    assert_eq!(summary.total_reclaimed_bytes, 4); // PHOTO_2 len = 4

    // Execute Move batch commit
    let result = state
        .commit_staged_batch(
            Some(keep_dest.path().to_string_lossy().to_string()),
            Some(nah_dest.path().to_string_lossy().to_string()),
            ActionMode::Move,
        )
        .expect("commit batch succeeds");

    assert_eq!(result.successful_groups, 2);
    assert_eq!(result.successful_files, 3);
    assert!(result.errors.is_empty());

    // Verify files moved to correct destinations
    assert!(keep_dest.path().join("PHOTO_1.jpg").exists());
    assert!(keep_dest.path().join("PHOTO_1.cr2").exists());
    assert!(nah_dest.path().join("PHOTO_2.jpg").exists());

    // Verify source files are no longer in source dir
    assert!(!f1_jpg.exists());
    assert!(!f1_cr2.exists());
    assert!(!f2_jpg.exists());

    // Verify state is clean
    assert!(state.decisions.is_empty());
}

#[test]
fn test_session_commit_batch_copy_flow() {
    let source_dir = tempdir().unwrap();
    let keep_dest = tempdir().unwrap();

    let f1_jpg = source_dir.path().join("PHOTO_COPY.jpg");
    File::create(&f1_jpg)
        .unwrap()
        .write_all(b"copy-me")
        .unwrap();

    let mut state = SessionState::new();
    state.reset_with_dir(source_dir.path().to_string_lossy().to_string());

    let groups = vec![PhotoGroupDto {
        stem: "PHOTO_COPY".to_string(),
        members: vec![f1_jpg.to_string_lossy().to_string()],
        representative: f1_jpg.to_string_lossy().to_string(),
        index: 0,
    }];
    state.register_groups(&groups);

    state.stage_decision("PHOTO_COPY".to_string(), Decision::Keep);

    let result = state
        .commit_staged_batch(
            Some(keep_dest.path().to_string_lossy().to_string()),
            None,
            ActionMode::Copy,
        )
        .expect("commit copy succeeds");

    assert_eq!(result.successful_groups, 1);
    assert_eq!(result.successful_files, 1);

    // Destination has the copy
    assert!(keep_dest.path().join("PHOTO_COPY.jpg").exists());
    // Source file remains intact
    assert!(f1_jpg.exists());
}
