use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Decision {
    Keep,
    Nah,
    Flag,
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

#[derive(Debug, Default)]
pub struct SessionState {
    pub source_dir: Option<String>,
    pub decisions: HashMap<String, Decision>,
    pub undo_stack: Vec<StagedDecisionRecord>,
}

impl SessionState {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn reset_with_dir(&mut self, dir: String) {
        self.source_dir = Some(dir);
        self.decisions.clear();
        self.undo_stack.clear();
    }

    pub fn stage_decision(&mut self, stem: String, decision: Decision) {
        self.decisions.insert(stem.clone(), decision);
        self.undo_stack.push(StagedDecisionRecord { stem, decision });
    }

    pub fn undo_last_decision(&mut self) -> Option<String> {
        if let Some(record) = self.undo_stack.pop() {
            let previous = self.undo_stack.iter().rev().find(|r| r.stem == record.stem);
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

    pub fn get_staged_counts(&self) -> (usize, usize, usize) {
        let mut keep = 0;
        let mut nah = 0;
        let mut flag = 0;
        for d in self.decisions.values() {
            match d {
                Decision::Keep => keep += 1,
                Decision::Nah => nah += 1,
                Decision::Flag => flag += 1,
            }
        }
        (keep, nah, flag)
    }

    pub fn get_decisions_map(&self) -> HashMap<String, String> {
        self.decisions
            .iter()
            .map(|(k, v)| (k.clone(), v.as_str().to_string()))
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_stage_and_undo_decisions() {
        let mut session = SessionState::new();
        assert_eq!(session.decisions.len(), 0);

        // Stage Keep
        session.stage_decision("DSC_001".to_string(), Decision::Keep);
        assert_eq!(session.decisions.get("DSC_001"), Some(&Decision::Keep));
        assert_eq!(session.get_staged_counts(), (1, 0, 0));

        // Stage Nah for second photo
        session.stage_decision("DSC_002".to_string(), Decision::Nah);
        assert_eq!(session.get_staged_counts(), (1, 1, 0));

        // Change mind on DSC_001: Flag it
        session.stage_decision("DSC_001".to_string(), Decision::Flag);
        assert_eq!(session.decisions.get("DSC_001"), Some(&Decision::Flag));
        assert_eq!(session.get_staged_counts(), (0, 1, 1));

        // Undo once: DSC_001 reverts to Keep
        let undone = session.undo_last_decision();
        assert_eq!(undone, Some("DSC_001".to_string()));
        assert_eq!(session.decisions.get("DSC_001"), Some(&Decision::Keep));
        assert_eq!(session.get_staged_counts(), (1, 1, 0));

        // Undo again: DSC_002 is un-staged
        let undone2 = session.undo_last_decision();
        assert_eq!(undone2, Some("DSC_002".to_string()));
        assert_eq!(session.decisions.get("DSC_002"), None);
        assert_eq!(session.get_staged_counts(), (1, 0, 0));
    }
}
