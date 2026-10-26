use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Decision {
    Keep,
    Nah,
    Flag,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ActionMode {
    Move,
    Copy,
}

impl ActionMode {
    pub fn is_move(&self) -> bool {
        matches!(self, ActionMode::Move)
    }

    pub fn from_str_opt(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "move" => Some(ActionMode::Move),
            "copy" => Some(ActionMode::Copy),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct StagedCounts {
    pub keep: usize,
    pub nah: usize,
    pub flag: usize,
}

impl Decision {
    pub fn as_str(&self) -> &'static str {
        match self {
            Decision::Keep => "keep",
            Decision::Nah => "nah",
            Decision::Flag => "flag",
        }
    }

    pub fn from_str_opt(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "keep" => Some(Decision::Keep),
            "nah" => Some(Decision::Nah),
            "flag" => Some(Decision::Flag),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct StagedDecisionRecord {
    pub stem: String,
    pub decision: Decision,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BatchItemSummary {
    pub stem: String,
    pub decision: String,
    pub file_count: usize,
    pub total_bytes: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct BatchSummaryDto {
    pub total_groups: usize,
    pub keep_count: usize,
    pub nah_count: usize,
    pub flag_count: usize,
    pub total_files: usize,
    pub total_reclaimed_bytes: u64,
    pub items: Vec<BatchItemSummary>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CommitResultDto {
    pub successful_groups: usize,
    pub successful_files: usize,
    pub errors: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum ExecutedOp {
    Moved {
        source: PathBuf,
        destination: PathBuf,
    },
    Copied {
        destination: PathBuf,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RecoveryJournal {
    pub timestamp_epoch_sec: u64,
    pub session_dir: String,
    pub unreversed_ops: Vec<ExecutedOp>,
    pub rollback_errors: Vec<String>,
}

fn rollback_ops(ops: Vec<ExecutedOp>, session_dir: &Path) -> Result<(), String> {
    let mut rollback_errors = Vec::new();
    let mut unreversed_ops = Vec::new();

    for op in ops.into_iter().rev() {
        match &op {
            ExecutedOp::Moved {
                source,
                destination,
            } => {
                if destination.exists() {
                    if let Err(e) = fs::rename(destination, source) {
                        rollback_errors.push(format!(
                            "Failed to restore {} to {}: {}",
                            destination.display(),
                            source.display(),
                            e
                        ));
                        unreversed_ops.push(op);
                    }
                }
            }
            ExecutedOp::Copied { destination } => {
                if destination.exists() {
                    if let Err(e) = fs::remove_file(destination) {
                        rollback_errors.push(format!(
                            "Failed to clean up copied file {}: {}",
                            destination.display(),
                            e
                        ));
                        unreversed_ops.push(op);
                    }
                }
            }
        }
    }

    if !rollback_errors.is_empty() {
        let journal = RecoveryJournal {
            timestamp_epoch_sec: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs(),
            session_dir: session_dir.to_string_lossy().to_string(),
            unreversed_ops,
            rollback_errors: rollback_errors.clone(),
        };
        let journal_path = session_dir.join(format!(
            "_emergency_recovery_{}.json",
            journal.timestamp_epoch_sec
        ));
        if let Ok(json) = serde_json::to_string_pretty(&journal) {
            let _ = fs::write(&journal_path, json);
        }
        return Err(format!(
            "Rollback errors encountered (recovery journal saved to {}):\n{}",
            journal_path.display(),
            rollback_errors.join("\n")
        ));
    }

    Ok(())
}

fn execute_group_file_ops(
    members: &[PathBuf],
    dest_folder: &Path,
    action_mode: ActionMode,
) -> (Vec<ExecutedOp>, Option<String>) {
    let mut group_ops = Vec::new();
    let is_move = action_mode.is_move();

    for member in members {
        let file_name = match member.file_name() {
            Some(name) => name,
            None => continue,
        };
        let target_file = dest_folder.join(file_name);

        if is_move {
            match fs::rename(member, &target_file) {
                Ok(_) => {
                    group_ops.push(ExecutedOp::Moved {
                        source: member.clone(),
                        destination: target_file,
                    });
                }
                Err(rename_err) => {
                    let source_ident = match keep_or_nah_core::fileops::identity_of(member) {
                        Ok(id) => id,
                        Err(e) => {
                            return (
                                group_ops,
                                Some(format!(
                                    "Failed to read source identity for {} ({rename_err}): {e}",
                                    member.display()
                                )),
                            );
                        }
                    };
                    match keep_or_nah_core::fileops::stage_copy(
                        member,
                        dest_folder,
                        Some(&source_ident.components()),
                    ) {
                        Ok(staged) => {
                            let staged_p = Path::new(&staged.path);
                            if let Err(e) = fs::rename(staged_p, &target_file) {
                                let _ = fs::remove_file(staged_p);
                                return (
                                    group_ops,
                                    Some(format!(
                                        "Failed to publish staged file for {}: {e}",
                                        member.display()
                                    )),
                                );
                            }
                            if let Err(e) = keep_or_nah_core::fileops::remove_verified(
                                member,
                                &source_ident.components(),
                            ) {
                                let _ = fs::remove_file(&target_file);
                                return (
                                    group_ops,
                                    Some(format!(
                                        "Failed to verified-remove source {}: {e}",
                                        member.display()
                                    )),
                                );
                            }
                            group_ops.push(ExecutedOp::Moved {
                                source: member.clone(),
                                destination: target_file,
                            });
                        }
                        Err(e) => {
                            return (
                                group_ops,
                                Some(format!(
                                    "Failed to move {} ({rename_err}): {e}",
                                    member.display()
                                )),
                            );
                        }
                    }
                }
            }
        } else {
            match keep_or_nah_core::fileops::stage_copy(member, dest_folder, None) {
                Ok(staged) => {
                    let staged_p = Path::new(&staged.path);
                    if let Err(e) = fs::rename(staged_p, &target_file) {
                        let _ = fs::remove_file(staged_p);
                        return (
                            group_ops,
                            Some(format!(
                                "Failed to publish staged copy for {}: {e}",
                                member.display()
                            )),
                        );
                    }
                    group_ops.push(ExecutedOp::Copied {
                        destination: target_file,
                    });
                }
                Err(e) => {
                    return (
                        group_ops,
                        Some(format!(
                            "Failed to stage copy for {}: {e}",
                            member.display()
                        )),
                    );
                }
            }
        }
    }

    (group_ops, None)
}

fn clean_dir_opt(dir: Option<String>) -> Option<String> {
    dir.and_then(|d| {
        let trimmed = d.trim().to_string();
        if trimmed.is_empty() {
            None
        } else {
            Some(trimmed)
        }
    })
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ImmediateDecisionRecord {
    pub stem: String,
    pub decision: Decision,
    pub ops: Vec<ExecutedOp>,
    pub members: Vec<PathBuf>,
}

#[derive(Debug, Default)]
pub struct SessionState {
    pub source_dir: Option<String>,
    pub keep_dir: Option<String>,
    pub nah_dir: Option<String>,
    pub flag_dir: Option<String>,
    pub decisions: HashMap<String, Decision>,
    pub group_members: HashMap<String, Vec<PathBuf>>,
    pub undo_journal: Vec<StagedDecisionRecord>,
    pub immediate_undo_journal: Vec<ImmediateDecisionRecord>,
}

impl SessionState {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn set_destinations(
        &mut self,
        keep_dir: Option<String>,
        nah_dir: Option<String>,
        flag_dir: Option<String>,
    ) {
        self.keep_dir = clean_dir_opt(keep_dir);
        self.nah_dir = clean_dir_opt(nah_dir);
        self.flag_dir = clean_dir_opt(flag_dir);
    }

    pub fn decide_immediate(
        &mut self,
        stem: String,
        decision: Decision,
        action_mode: ActionMode,
    ) -> Result<CommitResultDto, String> {
        let source_root = self
            .source_dir
            .as_ref()
            .ok_or_else(|| "No active session source directory".to_string())?;
        let session_path = Path::new(source_root);

        let dest_folder = match decision {
            Decision::Keep => self
                .keep_dir
                .as_ref()
                .map(PathBuf::from)
                .unwrap_or_else(|| session_path.join("keep")),
            Decision::Nah => self
                .nah_dir
                .as_ref()
                .map(PathBuf::from)
                .unwrap_or_else(|| session_path.join("trash")),
            Decision::Flag => match self.flag_dir.as_ref() {
                Some(dir) => PathBuf::from(dir),
                None => return Err("Choose a Flag folder before sorting.".to_string()),
            },
        };

        fs::create_dir_all(&dest_folder).map_err(|e| {
            format!(
                "Failed to create destination folder {}: {e}",
                dest_folder.display()
            )
        })?;

        let members = self
            .group_members
            .get(&stem)
            .cloned()
            .ok_or_else(|| format!("Photo group not found: {stem}"))?;

        let (group_ops, err_opt) = execute_group_file_ops(&members, &dest_folder, action_mode);
        if let Some(err) = err_opt {
            let _ = rollback_ops(group_ops, session_path);
            return Err(err);
        }

        let file_count = group_ops.len();
        self.decisions.remove(&stem);
        self.group_members.remove(&stem);
        self.immediate_undo_journal.push(ImmediateDecisionRecord {
            stem,
            decision,
            ops: group_ops,
            members,
        });

        Ok(CommitResultDto {
            successful_groups: 1,
            successful_files: file_count,
            errors: Vec::new(),
        })
    }

    pub fn reset_with_dir(&mut self, dir: String) {
        self.source_dir = Some(dir);
        self.decisions.clear();
        self.group_members.clear();
        self.undo_journal.clear();
        self.immediate_undo_journal.clear();
    }

    pub fn register_groups(&mut self, groups: &[crate::commands::PhotoGroupDto]) {
        self.group_members.clear();
        for g in groups {
            let members: Vec<PathBuf> = g.members.iter().map(PathBuf::from).collect();
            self.group_members.insert(g.stem.clone(), members);
        }
    }

    pub fn stage_decision(&mut self, stem: String, decision: Decision) {
        self.decisions.insert(stem.clone(), decision);
        self.undo_journal
            .push(StagedDecisionRecord { stem, decision });
    }

    pub fn undo_last_decision(&mut self) -> Option<String> {
        if let Some(imm_record) = self.immediate_undo_journal.pop() {
            let session_path = self
                .source_dir
                .as_deref()
                .map(Path::new)
                .unwrap_or_else(|| Path::new("."));
            if rollback_ops(imm_record.ops, session_path).is_ok() {
                self.group_members
                    .insert(imm_record.stem.clone(), imm_record.members);
                return Some(imm_record.stem);
            }
            return None;
        }

        if let Some(record) = self.undo_journal.pop() {
            let previous = self
                .undo_journal
                .iter()
                .rev()
                .find(|r| r.stem == record.stem);
            match previous {
                Some(prev) => {
                    self.decisions.insert(record.stem.clone(), prev.decision);
                }
                None => {
                    self.decisions.remove(&record.stem);
                }
            }
            Some(record.stem)
        } else {
            None
        }
    }

    pub fn get_staged_counts(&self) -> StagedCounts {
        let mut counts = StagedCounts::default();
        for d in self.decisions.values() {
            match d {
                Decision::Keep => counts.keep += 1,
                Decision::Nah => counts.nah += 1,
                Decision::Flag => counts.flag += 1,
            }
        }
        counts
    }

    pub fn get_decisions_map(&self) -> HashMap<String, String> {
        self.decisions
            .iter()
            .map(|(k, v)| (k.clone(), v.as_str().to_string()))
            .collect()
    }

    pub fn calculate_batch_summary(&self) -> BatchSummaryDto {
        let mut summary = BatchSummaryDto::default();
        let counts = self.get_staged_counts();
        summary.keep_count = counts.keep;
        summary.nah_count = counts.nah;
        summary.flag_count = counts.flag;
        summary.total_groups = self.decisions.len();

        for (stem, decision) in &self.decisions {
            let members = self.group_members.get(stem).cloned().unwrap_or_default();
            let mut total_bytes = 0u64;
            for m in &members {
                if let Ok(md) = fs::metadata(m) {
                    total_bytes += md.len();
                }
            }

            summary.total_files += members.len();
            if *decision == Decision::Nah {
                summary.total_reclaimed_bytes += total_bytes;
            }

            summary.items.push(BatchItemSummary {
                stem: stem.clone(),
                decision: decision.as_str().to_string(),
                file_count: members.len(),
                total_bytes,
            });
        }

        summary
    }

    pub fn commit_staged_batch(
        &mut self,
        keep_dir_override: Option<String>,
        nah_dir_override: Option<String>,
        action_mode: ActionMode,
    ) -> Result<CommitResultDto, String> {
        let source_root = self
            .source_dir
            .as_ref()
            .ok_or_else(|| "No active session source directory".to_string())?;

        let session_path = Path::new(source_root);
        let keep_destination = clean_dir_opt(keep_dir_override)
            .or_else(|| self.keep_dir.clone())
            .map(PathBuf::from)
            .unwrap_or_else(|| session_path.join("keep"));
        let nah_destination = clean_dir_opt(nah_dir_override)
            .or_else(|| self.nah_dir.clone())
            .map(PathBuf::from)
            .unwrap_or_else(|| session_path.join("trash"));

        let mut executed_ops: Vec<ExecutedOp> = Vec::new();
        let mut committed_stems = Vec::new();
        let mut errors = Vec::new();

        for (stem, decision) in &self.decisions {
            let target_dir = match decision {
                Decision::Keep => Some(&keep_destination),
                Decision::Nah => Some(&nah_destination),
                Decision::Flag => None,
            };

            let dest_folder = match target_dir {
                Some(d) => d,
                None => {
                    // Flag stays in source directory in staged mode
                    committed_stems.push(stem.clone());
                    continue;
                }
            };

            if let Err(e) = fs::create_dir_all(dest_folder) {
                errors.push(format!(
                    "Failed to create destination folder {}: {e}",
                    dest_folder.display()
                ));
                break;
            }

            let members = match self.group_members.get(stem) {
                Some(m) => m,
                None => continue,
            };

            let (group_ops, err_opt) = execute_group_file_ops(members, dest_folder, action_mode);
            executed_ops.extend(group_ops);
            if let Some(err) = err_opt {
                errors.push(err);
                break;
            } else {
                committed_stems.push(stem.clone());
            }
        }

        if !errors.is_empty() {
            // Deduplicated rollback execution with emergency recovery journal
            let rollback_res = rollback_ops(executed_ops, session_path);
            if let Err(rollback_err) = rollback_res {
                errors.push(rollback_err);
            }
            return Err(errors.join("\n"));
        }

        // Clean committed decisions from in-memory state
        for stem in &committed_stems {
            self.decisions.remove(stem);
            self.group_members.remove(stem);
        }
        self.undo_journal
            .retain(|r| !committed_stems.contains(&r.stem));

        let file_count = executed_ops.len();
        Ok(CommitResultDto {
            successful_groups: committed_stems.len(),
            successful_files: file_count,
            errors,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn test_stage_and_undo_decisions() {
        let mut session = SessionState::new();
        assert_eq!(session.decisions.len(), 0);

        session.stage_decision("DSC_001".to_string(), Decision::Keep);
        assert_eq!(session.decisions.get("DSC_001"), Some(&Decision::Keep));
        assert_eq!(
            session.get_staged_counts(),
            StagedCounts {
                keep: 1,
                nah: 0,
                flag: 0
            }
        );

        session.stage_decision("DSC_002".to_string(), Decision::Nah);
        assert_eq!(
            session.get_staged_counts(),
            StagedCounts {
                keep: 1,
                nah: 1,
                flag: 0
            }
        );

        session.stage_decision("DSC_001".to_string(), Decision::Flag);
        assert_eq!(session.decisions.get("DSC_001"), Some(&Decision::Flag));
        assert_eq!(
            session.get_staged_counts(),
            StagedCounts {
                keep: 0,
                nah: 1,
                flag: 1
            }
        );

        let undone = session.undo_last_decision();
        assert_eq!(undone, Some("DSC_001".to_string()));
        assert_eq!(session.decisions.get("DSC_001"), Some(&Decision::Keep));
        assert_eq!(
            session.get_staged_counts(),
            StagedCounts {
                keep: 1,
                nah: 1,
                flag: 0
            }
        );

        let undone2 = session.undo_last_decision();
        assert_eq!(undone2, Some("DSC_002".to_string()));
        assert_eq!(session.decisions.get("DSC_002"), None);
        assert_eq!(
            session.get_staged_counts(),
            StagedCounts {
                keep: 1,
                nah: 0,
                flag: 0
            }
        );
    }

    #[test]
    fn test_commit_batch_moves_files_and_cleans_staged() {
        let temp = TempDir::new().unwrap();
        let src = temp.path().join("source");
        fs::create_dir(&src).unwrap();

        let file1 = src.join("A01.JPG");
        let file2 = src.join("A02.JPG");
        fs::write(&file1, b"hello").unwrap();
        fs::write(&file2, b"world").unwrap();

        let mut session = SessionState::new();
        session.reset_with_dir(src.to_string_lossy().to_string());
        session
            .group_members
            .insert("A01".to_string(), vec![file1.clone()]);
        session
            .group_members
            .insert("A02".to_string(), vec![file2.clone()]);

        session.stage_decision("A01".to_string(), Decision::Keep);
        session.stage_decision("A02".to_string(), Decision::Nah);

        let result = session
            .commit_staged_batch(None, None, ActionMode::Move)
            .unwrap();
        assert_eq!(result.successful_groups, 2);
        assert_eq!(result.successful_files, 2);

        // Files moved
        assert!(!file1.exists());
        assert!(!file2.exists());
        assert!(src.join("keep").join("A01.JPG").exists());
        assert!(src.join("trash").join("A02.JPG").exists());

        // Staged state is now clean
        assert_eq!(session.decisions.len(), 0);
    }

    #[test]
    fn test_commit_batch_copies_files_and_preserves_source() {
        let temp = TempDir::new().unwrap();
        let src = temp.path().join("source");
        fs::create_dir(&src).unwrap();

        let file1 = src.join("A01.JPG");
        fs::write(&file1, b"hello copy").unwrap();

        let mut session = SessionState::new();
        session.reset_with_dir(src.to_string_lossy().to_string());
        session
            .group_members
            .insert("A01".to_string(), vec![file1.clone()]);
        session.stage_decision("A01".to_string(), Decision::Keep);

        let result = session
            .commit_staged_batch(None, None, ActionMode::Copy)
            .unwrap();
        assert_eq!(result.successful_groups, 1);
        assert_eq!(result.successful_files, 1);

        // Source file preserved, target file created
        assert!(file1.exists());
        assert!(src.join("keep").join("A01.JPG").exists());
        assert_eq!(session.decisions.len(), 0);
    }

    #[test]
    fn test_commit_batch_rolls_back_on_failure() {
        let temp = TempDir::new().unwrap();
        let src = temp.path().join("source");
        fs::create_dir(&src).unwrap();

        let file1 = src.join("A01.JPG");
        let file2 = src.join("A02.JPG");
        fs::write(&file1, b"first").unwrap();
        // file2 is intentionally NOT written to disk, so moving file2 will fail!

        let mut session = SessionState::new();
        session.reset_with_dir(src.to_string_lossy().to_string());
        session
            .group_members
            .insert("A01".to_string(), vec![file1.clone()]);
        session
            .group_members
            .insert("A02".to_string(), vec![file2.clone()]);

        session.stage_decision("A01".to_string(), Decision::Keep);
        session.stage_decision("A02".to_string(), Decision::Keep);

        let result = session.commit_staged_batch(None, None, ActionMode::Move);
        assert!(result.is_err());

        // Because batch failed on A02, A01 must have been rolled back to source!
        assert!(
            file1.exists(),
            "A01 should be restored to its source path after rollback"
        );
        assert!(
            !src.join("keep").join("A01.JPG").exists(),
            "Keep destination should not have A01"
        );

        // Staged decisions should still be retained because commit failed
        assert_eq!(session.decisions.len(), 2);
    }

    #[test]
    fn test_rollback_creates_emergency_recovery_journal_on_unresolvable_error() {
        let temp = TempDir::new().unwrap();
        let session_dir = temp.path().join("session");
        fs::create_dir(&session_dir).unwrap();

        let src_path = session_dir.join("original.jpg");
        let dest_path = session_dir.join("moved.jpg");
        fs::write(&dest_path, b"data").unwrap();

        // Simulate that moving back to source will fail because src_path is a directory
        fs::create_dir(&src_path).unwrap();

        let op = ExecutedOp::Moved {
            source: src_path.clone(),
            destination: dest_path.clone(),
        };

        let result = rollback_ops(vec![op], &session_dir);
        assert!(result.is_err());

        // Check that an emergency recovery file was written
        let mut found_journal = false;
        for entry in fs::read_dir(&session_dir).unwrap() {
            let entry = entry.unwrap();
            let name = entry.file_name().to_string_lossy().to_string();
            if name.starts_with("_emergency_recovery_") && name.ends_with(".json") {
                found_journal = true;
                let content = fs::read_to_string(entry.path()).unwrap();
                let journal: RecoveryJournal = serde_json::from_str(&content).unwrap();
                assert_eq!(journal.unreversed_ops.len(), 1);
                assert_eq!(journal.rollback_errors.len(), 1);
                break;
            }
        }
        assert!(
            found_journal,
            "Emergency recovery journal file should be created"
        );
    }

    #[test]
    fn test_flagging_with_and_without_destination_and_undo() {
        let temp = TempDir::new().unwrap();
        let src = temp.path().join("source");
        let flag_dest = temp.path().join("flagged");
        fs::create_dir(&src).unwrap();

        let file1 = src.join("F01.JPG");
        let file2 = src.join("F02.JPG");
        fs::write(&file1, b"flag-data-1").unwrap();
        fs::write(&file2, b"flag-data-2").unwrap();

        let mut session = SessionState::new();
        session.reset_with_dir(src.to_string_lossy().to_string());
        session
            .group_members
            .insert("F01".to_string(), vec![file1.clone()]);
        session
            .group_members
            .insert("F02".to_string(), vec![file2.clone()]);

        // 1. Immediate mode without Flag destination returns exact error
        let err = session
            .decide_immediate("F01".to_string(), Decision::Flag, ActionMode::Move)
            .unwrap_err();
        assert_eq!(err, "Choose a Flag folder before sorting.");
        assert!(
            file1.exists(),
            "File must remain untouched when Flag folder is unset"
        );

        // 2. Staged batch commit without Flag destination leaves flagged group in place
        session.stage_decision("F02".to_string(), Decision::Flag);
        let staged_res = session
            .commit_staged_batch(None, None, ActionMode::Move)
            .unwrap();
        assert_eq!(staged_res.successful_groups, 1);
        assert!(
            file2.exists(),
            "Staged Flag without destination stays in source folder"
        );

        // 3. Configure Flag destination and execute immediate Flag (Move)
        session.set_destinations(None, None, Some(flag_dest.to_string_lossy().to_string()));
        let imm_res = session
            .decide_immediate("F01".to_string(), Decision::Flag, ActionMode::Move)
            .unwrap();
        assert_eq!(imm_res.successful_groups, 1);
        assert_eq!(imm_res.successful_files, 1);
        assert!(!file1.exists(), "F01 should be moved out of source");
        assert!(
            flag_dest.join("F01.JPG").exists(),
            "F01 should exist in Flag destination"
        );

        // 4. Undoing immediate Flag through Undo Journal restores F01 to source
        let undone_stem = session.undo_last_decision();
        assert_eq!(undone_stem, Some("F01".to_string()));
        assert!(
            file1.exists(),
            "Undo must restore F01 back to source folder"
        );
        assert!(
            !flag_dest.join("F01.JPG").exists(),
            "Undo must remove F01 from Flag destination"
        );

        // 5. Execute immediate Flag (Copy) and verify source + destination both exist, then undo
        let copy_res = session
            .decide_immediate("F01".to_string(), Decision::Flag, ActionMode::Copy)
            .unwrap();
        assert_eq!(copy_res.successful_groups, 1);
        assert!(file1.exists(), "F01 should remain in source on Copy");
        assert!(
            flag_dest.join("F01.JPG").exists(),
            "F01 should be copied to Flag destination"
        );
        let undone_copy_stem = session.undo_last_decision();
        assert_eq!(undone_copy_stem, Some("F01".to_string()));
        assert!(file1.exists(), "Source F01 remains after undoing Copy");
        assert!(
            !flag_dest.join("F01.JPG").exists(),
            "Copied F01 in Flag destination is cleaned up on undo"
        );
    }
}
