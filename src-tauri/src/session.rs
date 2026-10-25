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

#[derive(Debug, Default)]
pub struct SessionState {
    pub source_dir: Option<String>,
    pub decisions: HashMap<String, Decision>,
    pub group_members: HashMap<String, Vec<PathBuf>>,
    pub undo_journal: Vec<StagedDecisionRecord>,
}

impl SessionState {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn reset_with_dir(&mut self, dir: String) {
        self.source_dir = Some(dir);
        self.decisions.clear();
        self.group_members.clear();
        self.undo_journal.clear();
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
        self.undo_journal.push(StagedDecisionRecord { stem, decision });
    }

    pub fn undo_last_decision(&mut self) -> Option<String> {
        if let Some(record) = self.undo_journal.pop() {
            let previous = self.undo_journal.iter().rev().find(|r| r.stem == record.stem);
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

        let keep_destination = keep_dir_override
            .map(PathBuf::from)
            .unwrap_or_else(|| Path::new(source_root).join("keep"));
        let nah_destination = nah_dir_override
            .map(PathBuf::from)
            .unwrap_or_else(|| Path::new(source_root).join("trash"));

        let mut executed_ops: Vec<(PathBuf, PathBuf, bool)> = Vec::new(); // (source, dest, is_move)
        let mut committed_stems = Vec::new();
        let mut errors = Vec::new();

        let is_move = action_mode.is_move();

        for (stem, decision) in &self.decisions {
            let target_dir = match decision {
                Decision::Keep => Some(&keep_destination),
                Decision::Nah => Some(&nah_destination),
                Decision::Flag => None,
            };

            let dest_folder = match target_dir {
                Some(d) => d,
                None => {
                    // Flag stays in source directory, nothing to move
                    committed_stems.push(stem.clone());
                    continue;
                }
            };

            if let Err(e) = fs::create_dir_all(dest_folder) {
                errors.push(format!("Failed to create destination folder {}: {e}", dest_folder.display()));
                break;
            }

            let members = match self.group_members.get(stem) {
                Some(m) => m,
                None => continue,
            };

            let mut group_ops = Vec::new();
            let mut group_failed = false;

            for member in members {
                let file_name = match member.file_name() {
                    Some(name) => name,
                    None => continue,
                };
                let target_file = dest_folder.join(file_name);

                let op_result = if is_move {
                    fs::rename(member, &target_file)
                } else {
                    fs::copy(member, &target_file).map(|_| ())
                };

                match op_result {
                    Ok(_) => {
                        group_ops.push((member.clone(), target_file, is_move));
                    }
                    Err(e) => {
                        errors.push(format!("Failed to transfer {}: {e}", member.display()));
                        group_failed = true;
                        break;
                    }
                }
            }

            if group_failed {
                // Roll back current group operations
                for (src, dest, was_move) in group_ops.into_iter().rev() {
                    if was_move {
                        let _ = fs::rename(&dest, &src);
                    } else {
                        let _ = fs::remove_file(&dest);
                    }
                }
                break;
            } else {
                executed_ops.extend(group_ops);
                committed_stems.push(stem.clone());
            }
        }

        if !errors.is_empty() {
            // Roll back all executed operations on batch failure
            for (src, dest, was_move) in executed_ops.into_iter().rev() {
                if was_move {
                    let _ = fs::rename(&dest, &src);
                } else {
                    let _ = fs::remove_file(&dest);
                }
            }
            return Err(errors.join("\n"));
        }

        // Clean committed decisions from in-memory state
        for stem in &committed_stems {
            self.decisions.remove(stem);
            self.group_members.remove(stem);
        }
        self.undo_journal.retain(|r| !committed_stems.contains(&r.stem));

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
        assert_eq!(session.get_staged_counts(), StagedCounts { keep: 1, nah: 0, flag: 0 });

        session.stage_decision("DSC_002".to_string(), Decision::Nah);
        assert_eq!(session.get_staged_counts(), StagedCounts { keep: 1, nah: 1, flag: 0 });

        session.stage_decision("DSC_001".to_string(), Decision::Flag);
        assert_eq!(session.decisions.get("DSC_001"), Some(&Decision::Flag));
        assert_eq!(session.get_staged_counts(), StagedCounts { keep: 0, nah: 1, flag: 1 });

        let undone = session.undo_last_decision();
        assert_eq!(undone, Some("DSC_001".to_string()));
        assert_eq!(session.decisions.get("DSC_001"), Some(&Decision::Keep));
        assert_eq!(session.get_staged_counts(), StagedCounts { keep: 1, nah: 1, flag: 0 });

        let undone2 = session.undo_last_decision();
        assert_eq!(undone2, Some("DSC_002".to_string()));
        assert_eq!(session.decisions.get("DSC_002"), None);
        assert_eq!(session.get_staged_counts(), StagedCounts { keep: 1, nah: 0, flag: 0 });
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
        session.group_members.insert("A01".to_string(), vec![file1.clone()]);
        session.group_members.insert("A02".to_string(), vec![file2.clone()]);

        session.stage_decision("A01".to_string(), Decision::Keep);
        session.stage_decision("A02".to_string(), Decision::Nah);

        let result = session.commit_staged_batch(None, None, ActionMode::Move).unwrap();
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
}
