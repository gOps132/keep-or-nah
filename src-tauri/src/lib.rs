pub mod burst;
pub mod debug_log;
pub mod session;

pub mod commands {
    use image::codecs::jpeg::JpegEncoder;
    use image::ColorType;
    use serde::{Deserialize, Serialize};
    use std::collections::HashMap;
    use std::path::{Path, PathBuf};
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::sync::{Mutex, OnceLock};
    use tauri::async_runtime::Mutex as AsyncMutex;
    use tauri::{AppHandle, Emitter, Manager, State};
    use tauri_plugin_dialog::DialogExt;

    static HEAVY_RENDER_GENERATION: AtomicU64 = AtomicU64::new(0);

    fn get_heavy_render_lock() -> &'static AsyncMutex<()> {
        static LOCK: OnceLock<AsyncMutex<()>> = OnceLock::new();
        LOCK.get_or_init(|| AsyncMutex::new(()))
    }

    use crate::burst::{BurstCluster, BurstClusterer, PhotoBurstInfo};
    use crate::debug_log;
    use crate::session::{BatchSummaryDto, CommitResultDto, Decision, SessionState};
    use serde_json::json;
    use std::time::Instant;

    #[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
    pub struct PhotoGroupDto {
        pub stem: String,
        pub members: Vec<String>,
        pub representative: String,
        pub index: usize,
    }

    #[derive(Debug, Clone, Serialize, Deserialize)]
    pub struct ThumbnailDto {
        pub path: String,
        pub cache_path: String,
        pub src_url: String,
        pub data_url: Option<String>,
        pub sharpness: f64,
        pub image_hash: u64,
        pub timestamp: f64,
        pub width: u32,
        pub height: u32,
    }

    #[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq, Eq)]
    pub struct ExifMetadataDto {
        pub shutter_speed: Option<String>,
        pub aperture: Option<String>,
        pub iso: Option<String>,
        pub focal_length: Option<String>,
        pub camera_model: Option<String>,
        pub lens_model: Option<String>,
    }

    /// Prompts the user to pick a photo directory using the native OS dialog.
    #[tauri::command]
    pub async fn open_directory_dialog(app: AppHandle) -> Result<Option<String>, String> {
        let folder_path = app
            .dialog()
            .file()
            .set_title("Select Photo Session Folder")
            .blocking_pick_folder();

        match folder_path {
            Some(path) => {
                let path_str = match path {
                    tauri_plugin_dialog::FilePath::Path(p) => p.to_string_lossy().to_string(),
                    tauri_plugin_dialog::FilePath::Url(u) => u
                        .to_file_path()
                        .map(|p| p.to_string_lossy().to_string())
                        .unwrap_or_else(|_| u.to_string()),
                };
                Ok(Some(path_str))
            }
            None => Ok(None),
        }
    }

    /// Scans a directory and returns atomically grouped photo items.
    #[tauri::command]
    pub fn scan_directory(
        path: String,
        session_state: State<'_, Mutex<SessionState>>,
    ) -> Result<Vec<PhotoGroupDto>, String> {
        let start = Instant::now();
        let dir = Path::new(&path);
        if !dir.is_dir() {
            let err = format!("Path is not a directory: {path}");
            debug_log::log_action(
                "error",
                None,
                json!({ "source": "scan_directory", "error": err }),
            );
            return Err(err);
        }

        let extensions = keep_or_nah_core::scan::discover_extensions(dir);
        let previewable = keep_or_nah_core::scan::default_previewable_extensions();
        let groups = keep_or_nah_core::scan::build_photo_groups(dir, &extensions, &previewable);

        let dtos: Vec<PhotoGroupDto> = groups
            .into_iter()
            .enumerate()
            .map(|(index, group)| PhotoGroupDto {
                stem: group.stem,
                members: group
                    .members
                    .iter()
                    .map(|m| m.to_string_lossy().to_string())
                    .collect(),
                representative: group.representative.to_string_lossy().to_string(),
                index,
            })
            .collect();

        if let Ok(mut state) = session_state.lock() {
            state.reset_with_dir(path.clone());
            state.register_groups(&dtos);
        }

        debug_log::log_action(
            "folder_selection",
            Some(start.elapsed().as_secs_f64() * 1000.0),
            json!({ "path": path, "group_count": dtos.len() }),
        );

        Ok(dtos)
    }

    /// Updates the Keep, Nah, and Flag destination folders for the active session.
    #[tauri::command]
    pub fn set_session_destinations(
        keep_dir: Option<String>,
        nah_dir: Option<String>,
        flag_dir: Option<String>,
        session_state: State<'_, Mutex<SessionState>>,
    ) -> Result<(), String> {
        let mut state = session_state
            .lock()
            .map_err(|_| "Failed to lock session state".to_string())?;
        state.set_destinations(keep_dir.clone(), nah_dir.clone(), flag_dir.clone());
        debug_log::log_action(
            "settings_change",
            None,
            json!({ "keep_dir": keep_dir, "nah_dir": nah_dir, "flag_dir": flag_dir }),
        );
        Ok(())
    }

    /// Executes an immediate triage decision on a Photo Group.
    #[tauri::command]
    pub fn decide_immediate(
        stem: String,
        decision: String,
        action_mode: Option<String>,
        session_state: State<'_, Mutex<SessionState>>,
    ) -> Result<CommitResultDto, String> {
        let start = Instant::now();
        let parsed = Decision::from_str_opt(&decision)
            .ok_or_else(|| format!("Invalid triage decision: {decision}"))?;
        let mode = action_mode
            .as_deref()
            .and_then(crate::session::ActionMode::from_str_opt)
            .unwrap_or(crate::session::ActionMode::Move);

        let mut state = session_state
            .lock()
            .map_err(|_| "Failed to lock session state".to_string())?;

        match state.decide_immediate(stem.clone(), parsed, mode) {
            Ok(res) => {
                debug_log::log_action(
                    "decision",
                    Some(start.elapsed().as_secs_f64() * 1000.0),
                    json!({ "stem": stem, "decision": decision, "mode": "immediate" }),
                );
                Ok(res)
            }
            Err(err) => {
                debug_log::log_action(
                    "error",
                    Some(start.elapsed().as_secs_f64() * 1000.0),
                    json!({ "source": "decide_immediate", "stem": stem, "decision": decision, "error": err }),
                );
                Err(err)
            }
        }
    }

    /// Records an in-memory staged triage decision for a photo stem.
    #[tauri::command]
    pub fn stage_decision(
        stem: String,
        decision: String,
        session_state: State<'_, Mutex<SessionState>>,
    ) -> Result<HashMap<String, String>, String> {
        let parsed = Decision::from_str_opt(&decision)
            .ok_or_else(|| format!("Invalid triage decision: {decision}"))?;

        let mut state = session_state
            .lock()
            .map_err(|_| "Failed to lock session state".to_string())?;

        state.stage_decision(stem.clone(), parsed);
        debug_log::log_action(
            "decision",
            None,
            json!({ "stem": stem, "decision": decision, "mode": "staged" }),
        );
        Ok(state.get_decisions_map())
    }

    /// Undoes the last staged decision and returns the affected stem.
    #[tauri::command]
    pub fn undo_decision(
        session_state: State<'_, Mutex<SessionState>>,
    ) -> Result<Option<String>, String> {
        let mut state = session_state
            .lock()
            .map_err(|_| "Failed to lock session state".to_string())?;

        let undone = state.undo_last_decision();
        debug_log::log_action("undo", None, json!({ "undone_stem": undone }));
        Ok(undone)
    }

    /// Retrieves the current map of staged decisions.
    #[tauri::command]
    pub fn get_staged_decisions(
        session_state: State<'_, Mutex<SessionState>>,
    ) -> Result<HashMap<String, String>, String> {
        let state = session_state
            .lock()
            .map_err(|_| "Failed to lock session state".to_string())?;

        Ok(state.get_decisions_map())
    }

    /// Calculates summary information for all staged decisions before commit.
    #[tauri::command]
    pub fn get_batch_summary(
        session_state: State<'_, Mutex<SessionState>>,
    ) -> Result<BatchSummaryDto, String> {
        let state = session_state
            .lock()
            .map_err(|_| "Failed to lock session state".to_string())?;

        Ok(state.calculate_batch_summary())
    }

    /// Executes atomic batch moves or copies of all staged files with rollback on error.
    #[tauri::command]
    pub fn commit_batch(
        keep_dir: Option<String>,
        nah_dir: Option<String>,
        action_mode: Option<String>,
        session_state: State<'_, Mutex<SessionState>>,
    ) -> Result<CommitResultDto, String> {
        let start = Instant::now();
        let mut state = session_state
            .lock()
            .map_err(|_| "Failed to lock session state".to_string())?;

        let mode = action_mode
            .as_deref()
            .and_then(crate::session::ActionMode::from_str_opt)
            .unwrap_or(crate::session::ActionMode::Move);
        match state.commit_staged_batch(keep_dir, nah_dir, mode) {
            Ok(res) => {
                debug_log::log_action(
                    "batch_commit",
                    Some(start.elapsed().as_secs_f64() * 1000.0),
                    json!({
                        "successful_groups": res.successful_groups,
                        "successful_files": res.successful_files,
                        "action_mode": action_mode.unwrap_or_else(|| "move".to_string())
                    }),
                );
                Ok(res)
            }
            Err(err) => {
                debug_log::log_action(
                    "error",
                    Some(start.elapsed().as_secs_f64() * 1000.0),
                    json!({ "source": "commit_batch", "error": err }),
                );
                Err(err)
            }
        }
    }

    /// Generates an oriented, scaled thumbnail for a photo and computes its sharpness score.
    pub fn generate_thumbnail_dto(
        path: &str,
        edge: u32,
        cache_dir: &Path,
    ) -> Result<ThumbnailDto, String> {
        let start = Instant::now();
        let file_path = Path::new(path);
        let registry = keep_or_nah_core::heavy_asset::HeavyAssetRegistry::default();
        let preview_path = if registry.is_heavy_asset(file_path) {
            let heavy_cache = cache_dir.join("heavy_previews");
            registry
                .resolve_fast_preview(file_path, &heavy_cache)
                .map_err(|e| format!("Failed to extract heavy asset preview: {e}"))?
        } else {
            file_path.to_path_buf()
        };
        let loaded = keep_or_nah_core::image_loader::load_and_orient(&preview_path)
            .map_err(|e| format!("Failed to load image for thumbnail: {e}"))?;

        let (target_w, target_h) = if loaded.width >= loaded.height {
            let h = ((loaded.height as f64 / loaded.width as f64) * edge as f64).round() as u32;
            (edge, h.max(1))
        } else {
            let w = ((loaded.width as f64 / loaded.height as f64) * edge as f64).round() as u32;
            (w.max(1), edge)
        };

        let thumbnail = keep_or_nah_core::image_loader::render_fit(
            &loaded,
            target_w,
            target_h,
            keep_or_nah_core::image_loader::PreviewStage::Fast,
        )?;

        let sharpness = keep_or_nah_core::analysis::sharpness_score_f64(
            &thumbnail.rgba,
            thumbnail.width,
            thumbnail.height,
        );

        let image_hash = keep_or_nah_core::analysis::difference_hash_64(
            &thumbnail.rgba,
            thumbnail.width,
            thumbnail.height,
        );

        let timestamp = extract_timestamp(file_path);

        // Derive unique cache file path from path + mtime
        let mtime = std::fs::metadata(file_path)
            .and_then(|m| m.modified())
            .ok()
            .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
            .map(|d| d.as_secs())
            .unwrap_or(0);
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        std::hash::Hash::hash(&(path, mtime, edge), &mut hasher);
        let cache_key = format!("{:016x}", std::hash::Hasher::finish(&hasher));
        let cache_file = cache_dir.join(format!("{cache_key}.jpg"));

        if !cache_file.exists() {
            let file = std::fs::File::create(&cache_file)
                .map_err(|e| format!("Failed to create thumbnail cache file: {e}"))?;
            let mut writer = std::io::BufWriter::new(file);
            let mut encoder = JpegEncoder::new_with_quality(&mut writer, 80);
            let rgb: Vec<u8> = thumbnail
                .rgba
                .as_chunks::<4>()
                .0
                .iter()
                .flat_map(|c| [c[0], c[1], c[2]])
                .collect();
            encoder
                .encode(
                    &rgb,
                    thumbnail.width,
                    thumbnail.height,
                    ColorType::Rgb8.into(),
                )
                .map_err(|e| format!("Failed to encode JPEG thumbnail: {e}"))?;
        }

        let cache_path_str = cache_file.to_string_lossy().to_string();
        let src_url = format!("asset://localhost/{}", cache_path_str);

        debug_log::log_render(
            "render.thumbnail_decode",
            start.elapsed().as_secs_f64() * 1000.0,
            json!({
                "path": path,
                "width": thumbnail.width,
                "height": thumbnail.height,
                "sharpness": sharpness
            }),
        );

        Ok(ThumbnailDto {
            path: path.to_string(),
            cache_path: cache_path_str,
            src_url,
            data_url: None,
            sharpness,
            image_hash,
            timestamp,
            width: thumbnail.width,
            height: thumbnail.height,
        })
    }

    /// Generates an oriented, scaled thumbnail for a photo and caches it to disk without Base64 IPC overhead.
    #[tauri::command]
    pub fn get_thumbnail(path: String, max_edge: Option<u32>) -> Result<ThumbnailDto, String> {
        let edge = max_edge.unwrap_or(160);
        let cache_dir = std::env::temp_dir().join("keep_or_nah_cache");
        let _ = std::fs::create_dir_all(&cache_dir);
        generate_thumbnail_dto(&path, edge, &cache_dir)
    }

    /// Resolves a photo file path for display.
    /// If the path is a RAW format (e.g. .arw), extracts the embedded preview JPEG to cache
    /// and returns the path to the cached JPEG; otherwise returns the original path.
    #[tauri::command]
    pub fn resolve_photo_preview(app: AppHandle, path: String) -> Result<String, String> {
        let start = Instant::now();
        let file_path = Path::new(&path);
        if !file_path.exists() {
            let err = format!("File does not exist: {path}");
            debug_log::log_action(
                "error",
                None,
                json!({ "source": "resolve_photo_preview", "error": err }),
            );
            return Err(err);
        }

        let registry = keep_or_nah_core::heavy_asset::HeavyAssetRegistry::default();
        let resolved = if registry.is_heavy_asset(file_path) {
            let cache_dir = app
                .path()
                .app_cache_dir()
                .unwrap_or_else(|_| std::env::temp_dir().join("keep_or_nah_cache"))
                .join("heavy_previews");
            let cached = registry.resolve_fast_preview(file_path, &cache_dir)?;
            cached.to_string_lossy().to_string()
        } else {
            path.clone()
        };

        debug_log::log_render(
            "render.preview.fast",
            start.elapsed().as_secs_f64() * 1000.0,
            json!({ "path": path, "resolved": resolved, "stage": "fast" }),
        );

        Ok(resolved)
    }

    /// Resolves a full-resolution demosaiced RAW render for display.
    ///
    /// If the path is a RAW format (e.g. .arw), demosaics the true sensor data
    /// (via native hardware demosaicing in keep_or_nah_core) and caches it to disk
    /// in `app_cache_dir/raw_full_renders/<key>.jpg`.
    /// If the path is not a RAW format, returns the original path.
    ///
    /// Applies single-worker concurrency gating and monotonic cancellation
    /// so fast navigation abandons obsolete in-flight jobs without memory spikes.
    #[tauri::command]
    pub async fn resolve_full_raw_render(app: AppHandle, path: String) -> Result<String, String> {
        let file_path = PathBuf::from(&path);
        if !file_path.exists() {
            return Err(format!("File does not exist: {path}"));
        }

        let registry = keep_or_nah_core::heavy_asset::HeavyAssetRegistry::default();
        if !registry.is_heavy_asset(&file_path) {
            return Ok(path);
        }

        let cache_dir = app
            .path()
            .app_cache_dir()
            .unwrap_or_else(|_| std::env::temp_dir().join("keep_or_nah_cache"))
            .join("raw_full_renders");

        let _ = std::fs::create_dir_all(&cache_dir);

        // Monotonic generation counter for superseding / cancellation
        let my_gen = HEAVY_RENDER_GENERATION.fetch_add(1, Ordering::SeqCst) + 1;

        // Bounded concurrency = 1 (single-worker queue to guarantee bounded RAM)
        let _guard = get_heavy_render_lock().lock().await;

        // Abandon if superseded while waiting in queue
        if HEAVY_RENDER_GENERATION.load(Ordering::SeqCst) != my_gen {
            return Err("Heavy render cancelled by newer request".to_string());
        }

        // Offload demosaicing and hardware export to a blocking background thread
        let result = tauri::async_runtime::spawn_blocking(move || {
            resolve_full_raw_render_sync(&file_path, &cache_dir)
        })
        .await
        .map_err(|e| format!("Failed to spawn blocking demosaic task: {e}"))??;

        // Abandon if superseded during decode
        if HEAVY_RENDER_GENERATION.load(Ordering::SeqCst) != my_gen {
            return Err("Heavy render cancelled by newer request".to_string());
        }

        Ok(result)
    }

    /// Resolves any heavy asset (RAW, HEIC, TIFF, etc.) via the extensible HeavyAssetDecoder registry.
    #[tauri::command]
    pub async fn resolve_heavy_render(app: AppHandle, path: String) -> Result<String, String> {
        resolve_full_raw_render(app, path).await
    }

    /// Returns the list of file extensions handled by HeavyAssetRegistry.
    #[tauri::command]
    pub fn get_supported_heavy_extensions() -> Vec<String> {
        let registry = keep_or_nah_core::heavy_asset::HeavyAssetRegistry::default();
        registry.supported_extensions()
    }

    /// Synchronous helper for resolving and caching full RAW demosaic.
    pub fn resolve_full_raw_render_sync(
        file_path: &Path,
        cache_dir: &Path,
    ) -> Result<String, String> {
        let start = Instant::now();
        let registry = keep_or_nah_core::heavy_asset::HeavyAssetRegistry::default();
        let cached = registry.resolve_full_render(file_path, cache_dir)?;
        let out = cached.to_string_lossy().to_string();
        debug_log::log_render(
            "render.preview.full",
            start.elapsed().as_secs_f64() * 1000.0,
            json!({
                "path": file_path.to_string_lossy(),
                "resolved": out,
                "stage": "full"
            }),
        );
        Ok(out)
    }

    /// Asynchronously streams progressive thumbnail generation via Tauri IPC events.
    #[tauri::command]
    pub fn start_thumbnail_stream(
        app: AppHandle,
        paths: Vec<String>,
        max_edge: Option<u32>,
    ) -> Result<(), String> {
        let edge = max_edge.unwrap_or(160);
        std::thread::spawn(move || {
            let cache_dir = std::env::temp_dir().join("keep_or_nah_cache");
            let _ = std::fs::create_dir_all(&cache_dir);

            for path in paths {
                if let Ok(dto) = generate_thumbnail_dto(&path, edge, &cache_dir) {
                    let _ = app.emit("thumbnail-ready", dto);
                }
            }
        });
        Ok(())
    }

    fn extract_timestamp(path: &Path) -> f64 {
        if let Ok(file) = std::fs::File::open(path) {
            let mut reader = std::io::BufReader::new(file);
            if let Ok(exif) = exif::Reader::new().read_from_container(&mut reader) {
                if let Some(field) = exif.get_field(exif::Tag::DateTimeOriginal, exif::In::PRIMARY)
                {
                    let val = field.display_value().to_string();
                    let parts: Vec<&str> = val.split([' ', ':', '-']).collect();
                    if parts.len() >= 6 {
                        if let (Ok(y), Ok(m), Ok(d), Ok(h), Ok(min), Ok(s)) = (
                            parts[0].parse::<i32>(),
                            parts[1].parse::<u32>(),
                            parts[2].parse::<u32>(),
                            parts[3].parse::<u32>(),
                            parts[4].parse::<u32>(),
                            parts[5].parse::<u32>(),
                        ) {
                            let days =
                                (y - 1970) as f64 * 365.25 + (m as f64 - 1.0) * 30.4375 + d as f64;
                            return days * 86400.0
                                + h as f64 * 3600.0
                                + min as f64 * 60.0
                                + s as f64;
                        }
                    }
                }
            }
        }

        if let Ok(meta) = std::fs::metadata(path) {
            if let Ok(modified) = meta.modified() {
                if let Ok(dur) = modified.duration_since(std::time::UNIX_EPOCH) {
                    return dur.as_secs_f64();
                }
            }
        }
        0.0
    }

    /// Computes burst clusters and identifies the relative Best Shot in each cluster.
    #[tauri::command]
    pub fn compute_burst_clusters(
        photos: Vec<PhotoBurstInfo>,
    ) -> Result<Vec<BurstCluster>, String> {
        let clusterer = BurstClusterer::default();
        Ok(clusterer.cluster(photos))
    }

    /// Extracts camera telemetry from image EXIF metadata.
    #[tauri::command]
    pub fn read_exif_metadata(path: String) -> Result<ExifMetadataDto, String> {
        let file = match std::fs::File::open(&path) {
            Ok(f) => f,
            Err(_) => return Ok(ExifMetadataDto::default()),
        };
        let mut reader = std::io::BufReader::new(file);
        let exif = match exif::Reader::new().read_from_container(&mut reader) {
            Ok(e) => e,
            Err(_) => return Ok(ExifMetadataDto::default()),
        };

        let mut dto = ExifMetadataDto::default();
        if let Some(field) = exif.get_field(exif::Tag::ExposureTime, exif::In::PRIMARY) {
            dto.shutter_speed = Some(field.display_value().to_string());
        }
        if let Some(field) = exif.get_field(exif::Tag::FNumber, exif::In::PRIMARY) {
            dto.aperture = Some(format!("f/{}", field.display_value()));
        }
        if let Some(field) = exif.get_field(exif::Tag::PhotographicSensitivity, exif::In::PRIMARY) {
            dto.iso = Some(format!("ISO {}", field.display_value()));
        }
        if let Some(field) = exif.get_field(exif::Tag::FocalLength, exif::In::PRIMARY) {
            dto.focal_length = Some(field.display_value().to_string());
        }
        if let Some(field) = exif.get_field(exif::Tag::Model, exif::In::PRIMARY) {
            dto.camera_model = Some(
                field
                    .display_value()
                    .to_string()
                    .trim_matches('"')
                    .to_string(),
            );
        }
        if let Some(field) = exif.get_field(exif::Tag::LensModel, exif::In::PRIMARY) {
            dto.lens_model = Some(
                field
                    .display_value()
                    .to_string()
                    .trim_matches('"')
                    .to_string(),
            );
        }

        Ok(dto)
    }

    /// Helper to verify native core integration at runtime.
    #[tauri::command]
    pub fn check_core_status() -> Result<String, String> {
        let dummy_path = PathBuf::from("dummy");
        let _ = keep_or_nah_core::scan::discover_extensions(&dummy_path);
        Ok("keep_or_nah_core linked and operational".to_string())
    }

    /// Returns true when debug timing mode (`KEEP_OR_NAH_DEBUG=1`) is enabled.
    #[tauri::command]
    pub fn get_debug_status() -> bool {
        debug_log::is_debug_enabled()
    }

    /// Appends a frontend render or interaction event to the thread-safe JSON Lines debug log.
    #[tauri::command]
    pub fn record_debug_event(
        event: String,
        category: String,
        duration_ms: Option<f64>,
        details: Option<serde_json::Value>,
    ) -> Result<(), String> {
        let payload = details.unwrap_or_else(|| json!({}));
        if category == "render" {
            debug_log::log_render(&event, duration_ms.unwrap_or(0.0), payload);
        } else {
            debug_log::log_action(&event, duration_ms, payload);
        }
        Ok(())
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(std::sync::Mutex::new(session::SessionState::new()))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .invoke_handler(tauri::generate_handler![
            commands::open_directory_dialog,
            commands::scan_directory,
            commands::set_session_destinations,
            commands::decide_immediate,
            commands::stage_decision,
            commands::undo_decision,
            commands::get_staged_decisions,
            commands::get_batch_summary,
            commands::commit_batch,
            commands::get_thumbnail,
            commands::start_thumbnail_stream,
            commands::compute_burst_clusters,
            commands::read_exif_metadata,
            commands::resolve_photo_preview,
            commands::resolve_full_raw_render,
            commands::resolve_heavy_render,
            commands::get_supported_heavy_extensions,
            commands::check_core_status,
            commands::get_debug_status,
            commands::record_debug_event
        ])
        .run(tauri::generate_context!())
        .expect("error while running Keep or Nah application");
}

#[cfg(test)]
mod tests {
    use super::burst::PhotoBurstInfo;
    use super::commands::{check_core_status, compute_burst_clusters, read_exif_metadata};
    use tempfile::TempDir;

    #[test]
    fn test_core_linkage_succeeds() {
        let status = check_core_status();
        assert!(status.is_ok());
        assert_eq!(status.unwrap(), "keep_or_nah_core linked and operational");
    }

    #[test]
    fn test_compute_burst_clusters_command() {
        let p1 = PhotoBurstInfo {
            path: "shot1.jpg".to_string(),
            timestamp: 10.0,
            image_hash: 0xAAAA,
            sharpness: 50.0,
        };
        let p2 = PhotoBurstInfo {
            path: "shot2.jpg".to_string(),
            timestamp: 10.5,
            image_hash: 0xAAAA,
            sharpness: 90.0,
        };

        let clusters = compute_burst_clusters(vec![p1, p2]).unwrap();
        assert_eq!(clusters.len(), 1);
        assert!(clusters[0].is_burst);
        assert_eq!(clusters[0].best_shot, "shot2.jpg");
    }

    #[test]
    fn test_read_exif_on_empty_file_returns_default() {
        let temp = TempDir::new().unwrap();
        let file_path = temp.path().join("empty.jpg");
        std::fs::write(&file_path, b"").unwrap();

        let metadata = read_exif_metadata(file_path.to_string_lossy().to_string()).unwrap();
        assert!(metadata.shutter_speed.is_none());
        assert!(metadata.aperture.is_none());
    }

    #[test]
    fn test_generate_thumbnail_dto_caches_to_disk_without_base64() {
        use image::{ImageBuffer, Rgba};
        let temp = TempDir::new().unwrap();
        let cache_dir = temp.path().join("cache");
        std::fs::create_dir_all(&cache_dir).unwrap();

        let img_path = temp.path().join("test.png");
        let img: ImageBuffer<Rgba<u8>, Vec<u8>> =
            ImageBuffer::from_pixel(64, 48, Rgba([255, 0, 0, 255]));
        img.save(&img_path).unwrap();

        let dto =
            super::commands::generate_thumbnail_dto(&img_path.to_string_lossy(), 40, &cache_dir)
                .unwrap();

        assert!(
            dto.data_url.is_none(),
            "Base64 data_url must be eliminated for binary IPC streaming"
        );
        assert!(dto.src_url.starts_with("asset://localhost/"));
        assert!(
            std::path::Path::new(&dto.cache_path).exists(),
            "Cached thumbnail must exist on disk"
        );
        assert_eq!(dto.width, 40);
        assert_eq!(dto.height, 30);
    }

    #[test]
    fn test_scan_directory_prioritizes_jpeg_over_arw_representative() {
        let temp = TempDir::new().unwrap();
        let arw_path = temp.path().join("DSC_0001.ARW");
        let jpg_path = temp.path().join("DSC_0001.JPG");
        let xmp_path = temp.path().join("DSC_0001.xmp");
        std::fs::write(&arw_path, b"fake-arw").unwrap();
        std::fs::write(&jpg_path, b"fake-jpg").unwrap();
        std::fs::write(&xmp_path, b"fake-xmp").unwrap();

        let extensions = keep_or_nah_core::scan::discover_extensions(temp.path());
        let previewable = keep_or_nah_core::scan::default_previewable_extensions();
        let groups =
            keep_or_nah_core::scan::build_photo_groups(temp.path(), &extensions, &previewable);

        assert_eq!(groups.len(), 1);
        assert_eq!(groups[0].stem, "DSC_0001");
        assert_eq!(
            groups[0].representative.file_name().unwrap(),
            "DSC_0001.JPG"
        );
        assert_eq!(groups[0].members.len(), 3);
    }

    #[test]
    fn test_generate_thumbnail_dto_extracts_from_raw_file() {
        use image::{ImageBuffer, Rgb};
        let temp = TempDir::new().unwrap();
        let cache_dir = temp.path().join("cache");
        std::fs::create_dir_all(&cache_dir).unwrap();

        // Create a real JPEG buffer to embed into raw
        let img: ImageBuffer<Rgb<u8>, Vec<u8>> =
            ImageBuffer::from_pixel(64, 48, Rgb([0, 200, 100]));
        let mut jpeg_bytes = Vec::new();
        let mut cursor = std::io::Cursor::new(&mut jpeg_bytes);
        img.write_to(&mut cursor, image::ImageFormat::Jpeg).unwrap();

        let raw_path = temp.path().join("DSC_9999.ARW");
        let mut raw_container = vec![0x49, 0x49, 0x2A, 0x00]; // TIFF header
        raw_container.extend_from_slice(&[0u8; 100]);
        raw_container.extend_from_slice(&jpeg_bytes);
        raw_container.extend_from_slice(&[0u8; 100]);
        std::fs::write(&raw_path, &raw_container).unwrap();

        let dto =
            super::commands::generate_thumbnail_dto(&raw_path.to_string_lossy(), 40, &cache_dir)
                .unwrap();

        assert_eq!(dto.width, 40);
        assert_eq!(dto.height, 30);
        assert!(std::path::Path::new(&dto.cache_path).exists());
    }

    #[test]
    fn test_resolve_full_raw_render_sync_caching() {
        use image::{ImageBuffer, Rgb};
        let temp = TempDir::new().unwrap();
        let cache_dir = temp.path().join("full_cache");
        std::fs::create_dir_all(&cache_dir).unwrap();

        // Create a real JPEG buffer to embed into raw
        let img: ImageBuffer<Rgb<u8>, Vec<u8>> =
            ImageBuffer::from_pixel(64, 48, Rgb([200, 100, 50]));
        let mut jpeg_bytes = Vec::new();
        let mut cursor = std::io::Cursor::new(&mut jpeg_bytes);
        img.write_to(&mut cursor, image::ImageFormat::Jpeg).unwrap();

        let raw_path = temp.path().join("DSC_7777.ARW");
        let mut raw_container = vec![0x49, 0x49, 0x2A, 0x00];
        raw_container.extend_from_slice(&[0u8; 100]);
        raw_container.extend_from_slice(&jpeg_bytes);
        raw_container.extend_from_slice(&[0u8; 100]);
        std::fs::write(&raw_path, &raw_container).unwrap();

        let cached_path =
            super::commands::resolve_full_raw_render_sync(&raw_path, &cache_dir).unwrap();
        assert!(std::path::Path::new(&cached_path).exists());

        // Calling again should return the exact same cached path without error
        let cached_again =
            super::commands::resolve_full_raw_render_sync(&raw_path, &cache_dir).unwrap();
        assert_eq!(cached_path, cached_again);
    }

    #[test]
    fn test_get_supported_heavy_extensions_includes_all_formats() {
        let exts = super::commands::get_supported_heavy_extensions();
        assert!(exts.contains(&".heic".to_string()));
        assert!(exts.contains(&".heif".to_string()));
        assert!(exts.contains(&".hif".to_string()));
        assert!(exts.contains(&".avif".to_string()));
        assert!(exts.contains(&".jxl".to_string()));
        assert!(exts.contains(&".psd".to_string()));
        assert!(exts.contains(&".arw".to_string()));
        assert!(exts.contains(&".cr2".to_string()));
        assert!(exts.contains(&".dng".to_string()));
    }
}
