pub mod session;

pub mod commands {
    use base64::prelude::*;
    use image::codecs::jpeg::JpegEncoder;
    use image::ColorType;
    use serde::{Deserialize, Serialize};
    use std::collections::HashMap;
    use std::io::Cursor;
    use std::path::{Path, PathBuf};
    use std::sync::Mutex;
    use tauri::{AppHandle, State};
    use tauri_plugin_dialog::DialogExt;

    use crate::session::{BatchSummaryDto, CommitResultDto, Decision, SessionState};

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
        pub data_url: String,
        pub sharpness: f64,
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
                    tauri_plugin_dialog::FilePath::Url(u) => {
                        u.to_file_path().map(|p| p.to_string_lossy().to_string()).unwrap_or_else(|_| u.to_string())
                    }
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
        let dir = Path::new(&path);
        if !dir.is_dir() {
            return Err(format!("Path is not a directory: {path}"));
        }

        let extensions = keep_or_nah_core::scan::discover_extensions(dir);
        let groups = keep_or_nah_core::scan::build_photo_groups(dir, &extensions, &extensions);

        let dtos: Vec<PhotoGroupDto> = groups
            .into_iter()
            .enumerate()
            .map(|(index, group)| PhotoGroupDto {
                stem: group.stem,
                members: group.members.iter().map(|m| m.to_string_lossy().to_string()).collect(),
                representative: group.representative.to_string_lossy().to_string(),
                index,
            })
            .collect();

        if let Ok(mut state) = session_state.lock() {
            state.reset_with_dir(path.clone());
            state.register_groups(&dtos);
        }

        Ok(dtos)
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

        state.stage_decision(stem, parsed);
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

        Ok(state.undo_last_decision())
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
        let mut state = session_state
            .lock()
            .map_err(|_| "Failed to lock session state".to_string())?;

        let mode = action_mode.unwrap_or_else(|| "move".to_string());
        state.commit_staged_batch(keep_dir, nah_dir, &mode)
    }

    /// Generates an oriented, scaled thumbnail for a photo and computes its sharpness score.
    #[tauri::command]
    pub fn get_thumbnail(path: String, max_edge: Option<u32>) -> Result<ThumbnailDto, String> {
        let file_path = Path::new(&path);
        let loaded = keep_or_nah_core::image_loader::load_and_orient(file_path)
            .map_err(|e| format!("Failed to load image for thumbnail: {e}"))?;

        let edge = max_edge.unwrap_or(160);
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

        let sharpness = keep_or_nah_core::analysis::compute_sharpness(
            &thumbnail.rgba,
            thumbnail.width,
            thumbnail.height,
        );

        let mut jpeg_bytes = Vec::new();
        let mut cursor = Cursor::new(&mut jpeg_bytes);
        let mut encoder = JpegEncoder::new_with_quality(&mut cursor, 80);
        encoder
            .encode(
                &thumbnail.rgba,
                thumbnail.width,
                thumbnail.height,
                ColorType::Rgba8.into(),
            )
            .map_err(|e| format!("Failed to encode JPEG thumbnail: {e}"))?;

        let data_url = format!("data:image/jpeg;base64,{}", BASE64_STANDARD.encode(&jpeg_bytes));

        Ok(ThumbnailDto {
            path,
            data_url,
            sharpness: sharpness as f64,
            width: thumbnail.width,
            height: thumbnail.height,
        })
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
            dto.camera_model = Some(field.display_value().to_string().trim_matches('"').to_string());
        }
        if let Some(field) = exif.get_field(exif::Tag::LensModel, exif::In::PRIMARY) {
            dto.lens_model = Some(field.display_value().to_string().trim_matches('"').to_string());
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
            commands::stage_decision,
            commands::undo_decision,
            commands::get_staged_decisions,
            commands::get_batch_summary,
            commands::commit_batch,
            commands::get_thumbnail,
            commands::read_exif_metadata,
            commands::check_core_status
        ])
        .run(tauri::generate_context!())
        .expect("error while running Keep or Nah application");
}

#[cfg(test)]
mod tests {
    use super::commands::{check_core_status, read_exif_metadata};
    use tempfile::TempDir;

    #[test]
    fn test_core_linkage_succeeds() {
        let status = check_core_status();
        assert!(status.is_ok());
        assert_eq!(status.unwrap(), "keep_or_nah_core linked and operational");
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
}
