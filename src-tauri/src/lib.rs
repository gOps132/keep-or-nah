pub mod commands {
    use std::path::PathBuf;
    use tauri::AppHandle;
    use tauri_plugin_dialog::DialogExt;

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

    /// Helper to verify native core integration at runtime.
    #[tauri::command]
    pub fn check_core_status() -> Result<String, String> {
        // Calling into keep_or_nah_core to verify direct static/rlib linkage
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
            commands::check_core_status
        ])
        .run(tauri::generate_context!())
        .expect("error while running Keep or Nah application");
}

#[cfg(test)]
mod tests {
    use super::commands::check_core_status;

    #[test]
    fn test_core_linkage_succeeds() {
        let status = check_core_status();
        assert!(status.is_ok());
        assert_eq!(status.unwrap(), "keep_or_nah_core linked and operational");
    }
}
