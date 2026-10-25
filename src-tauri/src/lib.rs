pub mod commands {
    use base64::prelude::*;
    use image::codecs::jpeg::JpegEncoder;
    use image::ColorType;
    use serde::{Deserialize, Serialize};
    use std::io::Cursor;
    use std::path::{Path, PathBuf};
    use tauri::AppHandle;
    use tauri_plugin_dialog::DialogExt;

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
    pub fn scan_directory(path: String) -> Result<Vec<PhotoGroupDto>, String> {
        let dir = Path::new(&path);
        if !dir.is_dir() {
            return Err(format!("Path is not a directory: {path}"));
        }

        let extensions = keep_or_nah_core::scan::discover_extensions(dir);
        let groups = keep_or_nah_core::scan::build_photo_groups(dir, &extensions, &extensions);

        let dtos = groups
            .into_iter()
            .enumerate()
            .map(|(index, group)| PhotoGroupDto {
                stem: group.stem,
                members: group.members.iter().map(|m| m.to_string_lossy().to_string()).collect(),
                representative: group.representative.to_string_lossy().to_string(),
                index,
            })
            .collect();

        Ok(dtos)
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
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .invoke_handler(tauri::generate_handler![
            commands::open_directory_dialog,
            commands::scan_directory,
            commands::get_thumbnail,
            commands::check_core_status
        ])
        .run(tauri::generate_context!())
        .expect("error while running Keep or Nah application");
}

#[cfg(test)]
mod tests {
    use super::commands::{check_core_status, scan_directory};
    use tempfile::TempDir;

    #[test]
    fn test_core_linkage_succeeds() {
        let status = check_core_status();
        assert!(status.is_ok());
        assert_eq!(status.unwrap(), "keep_or_nah_core linked and operational");
    }

    #[test]
    fn test_scan_directory_groups_same_stem_files() {
        let temp = TempDir::new().unwrap();
        let path = temp.path();

        std::fs::write(path.join("DSC_0001.JPG"), b"dummy").unwrap();
        std::fs::write(path.join("DSC_0001.RAW"), b"dummy").unwrap();
        std::fs::write(path.join("DSC_0002.JPG"), b"dummy").unwrap();

        let groups = scan_directory(path.to_string_lossy().to_string()).unwrap();
        assert_eq!(groups.len(), 2);
        assert_eq!(groups[0].stem, "DSC_0001");
        assert_eq!(groups[0].members.len(), 2);
        assert_eq!(groups[1].stem, "DSC_0002");
    }
}
