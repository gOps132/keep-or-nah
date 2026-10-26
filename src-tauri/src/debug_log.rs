use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DebugEvent {
    pub timestamp_ms: u64,
    pub event: String,
    pub category: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub duration_ms: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub details: Option<Value>,
}

pub struct DebugLogger {
    enabled: bool,
    log_path: PathBuf,
    write_lock: Mutex<()>,
}

impl DebugLogger {
    pub fn new(enabled: bool, log_path: PathBuf) -> Self {
        Self {
            enabled,
            log_path,
            write_lock: Mutex::new(()),
        }
    }

    pub fn from_env() -> Self {
        Self::new(is_debug_enabled(), resolve_debug_log_path())
    }

    pub fn is_enabled(&self) -> bool {
        self.enabled
    }

    pub fn log_path(&self) -> &Path {
        &self.log_path
    }

    pub fn log_render(&self, event: &str, duration_ms: f64, details: Option<Value>) {
        if !self.enabled {
            return;
        }
        self.write_record(DebugEvent {
            timestamp_ms: now_epoch_ms(),
            event: event.to_string(),
            category: "render".to_string(),
            duration_ms: Some(duration_ms),
            details,
        });
    }

    pub fn log_event(&self, event: &str, duration_ms: Option<f64>, details: Option<Value>) {
        if !self.enabled {
            return;
        }
        self.write_record(DebugEvent {
            timestamp_ms: now_epoch_ms(),
            event: event.to_string(),
            category: "event".to_string(),
            duration_ms,
            details,
        });
    }

    fn write_record(&self, record: DebugEvent) {
        let _guard = match self.write_lock.lock() {
            Ok(g) => g,
            Err(poisoned) => poisoned.into_inner(),
        };

        if let Some(parent) = self.log_path.parent() {
            if !parent.as_os_str().is_empty() {
                let _ = fs::create_dir_all(parent);
            }
        }

        if let Ok(mut line) = serde_json::to_string(&record) {
            line.push('\n');
            if let Ok(mut file) = OpenOptions::new()
                .create(true)
                .append(true)
                .open(&self.log_path)
            {
                let _ = file.write_all(line.as_bytes());
                let _ = file.flush();
            }
        }
    }
}

fn now_epoch_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

static GLOBAL_WRITE_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn global_lock() -> &'static Mutex<()> {
    GLOBAL_WRITE_LOCK.get_or_init(|| Mutex::new(()))
}

/// Checks whether debug timing mode is enabled via `KEEP_OR_NAH_DEBUG=1`.
pub fn is_debug_enabled() -> bool {
    std::env::var("KEEP_OR_NAH_DEBUG")
        .map(|v| {
            let trimmed = v.trim();
            trimmed == "1" || trimmed.eq_ignore_ascii_case("true")
        })
        .unwrap_or(false)
}

/// Returns the default OS settings directory for Keep or Nah.
pub fn default_settings_dir() -> PathBuf {
    #[cfg(target_os = "macos")]
    {
        if let Ok(home) = std::env::var("HOME") {
            return PathBuf::from(home)
                .join("Library")
                .join("Application Support")
                .join("keep-or-nah");
        }
    }
    #[cfg(target_os = "windows")]
    {
        if let Ok(appdata) = std::env::var("APPDATA") {
            return PathBuf::from(appdata).join("keep-or-nah");
        }
    }
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    {
        if let Ok(xdg) = std::env::var("XDG_CONFIG_HOME") {
            if !xdg.trim().is_empty() {
                return PathBuf::from(xdg).join("keep-or-nah");
            }
        }
        if let Ok(home) = std::env::var("HOME") {
            return PathBuf::from(home).join(".config").join("keep-or-nah");
        }
    }
    std::env::temp_dir().join("keep-or-nah")
}

/// Resolves the debug log file path from `KEEP_OR_NAH_DEBUG_LOG`, defaulting to
/// `<settings_dir>/render-log.jsonl`.
pub fn resolve_debug_log_path() -> PathBuf {
    if let Ok(custom) = std::env::var("KEEP_OR_NAH_DEBUG_LOG") {
        let trimmed = custom.trim();
        if !trimmed.is_empty() {
            return PathBuf::from(trimmed);
        }
    }
    default_settings_dir().join("render-log.jsonl")
}

fn with_env_logger<F: FnOnce(&DebugLogger)>(f: F) {
    if !is_debug_enabled() {
        return;
    }
    let _guard = match global_lock().lock() {
        Ok(g) => g,
        Err(poisoned) => poisoned.into_inner(),
    };
    let logger = DebugLogger::from_env();
    f(&logger);
}

pub fn log_render(event: &str, duration_ms: f64, details: Value) {
    with_env_logger(|logger| logger.log_render(event, duration_ms, Some(details)));
}

pub fn log_action(event: &str, duration_ms: Option<f64>, details: Value) {
    with_env_logger(|logger| logger.log_event(event, duration_ms, Some(details)));
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::sync::Arc;
    use tempfile::TempDir;

    #[test]
    fn test_normal_run_writes_nothing_and_creates_no_file() {
        let temp = TempDir::new().unwrap();
        let log_file = temp.path().join("nested").join("render-log.jsonl");
        let logger = DebugLogger::new(false, log_file.clone());

        logger.log_render(
            "render.preview.fast",
            14.2,
            Some(json!({ "stem": "DSC_0001" })),
        );
        logger.log_event(
            "decision",
            None,
            Some(json!({ "stem": "DSC_0001", "decision": "keep" })),
        );

        assert!(
            !log_file.exists(),
            "Disabled logger must not create any file"
        );
    }

    #[test]
    fn test_debug_run_writes_valid_json_lines_with_duration_ms() {
        let temp = TempDir::new().unwrap();
        let log_file = temp.path().join("render-log.jsonl");
        let logger = DebugLogger::new(true, log_file.clone());

        logger.log_render(
            "render.preview.fast",
            12.5,
            Some(json!({ "path": "/photos/DSC_0001.JPG", "stage": "fast" })),
        );
        logger.log_render("render.thumbnail_strip", 4.75, Some(json!({ "count": 24 })));
        logger.log_render(
            "render.split_comparison",
            18.0,
            Some(json!({ "primary": "DSC_0001", "comparison": "DSC_0002" })),
        );
        logger.log_render("render.loading_overlay", 32.1, None);
        logger.log_event(
            "decision",
            None,
            Some(json!({ "stem": "DSC_0001", "decision": "keep" })),
        );

        assert!(log_file.exists(), "Enabled logger must write the log file");
        let content = std::fs::read_to_string(&log_file).unwrap();
        let lines: Vec<&str> = content.lines().collect();
        assert_eq!(lines.len(), 5, "Must write one JSON line per event");

        for (i, line) in lines.iter().enumerate() {
            let parsed: DebugEvent = serde_json::from_str(line)
                .unwrap_or_else(|e| panic!("Line {i} failed to parse as JSON: {e}"));
            assert!(parsed.timestamp_ms > 0);
            if parsed.category == "render" {
                assert!(
                    parsed.duration_ms.is_some(),
                    "Every render boundary must report duration_ms"
                );
            }
        }
    }

    #[test]
    fn test_thread_safe_concurrent_writes_produce_valid_jsonl() {
        let temp = TempDir::new().unwrap();
        let log_file = temp.path().join("concurrent-log.jsonl");
        let logger = Arc::new(DebugLogger::new(true, log_file.clone()));

        let mut handles = Vec::new();
        for thread_id in 0..8 {
            let logger_clone = Arc::clone(&logger);
            handles.push(std::thread::spawn(move || {
                for seq in 0..15 {
                    logger_clone.log_render(
                        "render.thumbnail_decode",
                        (seq as f64) * 1.25,
                        Some(json!({ "worker": thread_id, "seq": seq })),
                    );
                }
            }));
        }

        for h in handles {
            h.join().unwrap();
        }

        let content = std::fs::read_to_string(&log_file).unwrap();
        let lines: Vec<&str> = content.lines().collect();
        assert_eq!(lines.len(), 8 * 15);
        for line in lines {
            let parsed: DebugEvent = serde_json::from_str(line).unwrap();
            assert_eq!(parsed.event, "render.thumbnail_decode");
            assert!(parsed.duration_ms.is_some());
        }
    }
}
