//! Fast embedded-JPEG preview extraction for camera RAW files (Sony ARW, Canon CR2/CR3,
//! Nikon NEF, DNG, etc.).
//!
//! Camera RAW files contain one or more pre-rendered embedded JPEG previews (from thumbnail
//! to full camera resolution). Extracting these embedded JPEGs allows instant (<15ms)
//! previews and thumbnails without performing heavy Bayer demosaicing.

use std::fs::{self, File};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

/// Common camera RAW file extensions.
pub const RAW_EXTENSIONS: &[&str] = &[
    ".arw", ".cr2", ".cr3", ".nef", ".nrw", ".dng", ".orf", ".rw2", ".pef", ".raf", ".srw",
];

/// Returns true if the file extension corresponds to a recognized camera RAW format.
pub fn is_raw_file(path: &Path) -> bool {
    path.extension()
        .and_then(|ext| ext.to_str())
        .map(|ext| {
            let dotted = format!(".{}", ext.to_lowercase());
            RAW_EXTENSIONS.contains(&dotted.as_str())
        })
        .unwrap_or(false)
}

/// Finds the largest embedded JPEG in a raw byte slice.
///
/// Searches for JPEG SOI markers (0xFF 0xD8 0xFF) followed by valid application or frame
/// markers, locates the corresponding EOI marker (0xFF 0xD9), and returns the candidate
/// with the largest byte size.
pub fn find_largest_embedded_jpeg(data: &[u8]) -> Option<&[u8]> {
    if data.len() < 4 {
        return None;
    }

    // First attempt: check TIFF structure for JPEGInterchangeFormat / Length tags
    if let Some(tiff_jpeg) = extract_tiff_jpeg(data) {
        if tiff_jpeg.len() > 100_000 {
            // Large enough to be a full preview (>100KB)
            return Some(tiff_jpeg);
        }
    }

    // Fallback or secondary: scan for all valid embedded JPEG streams
    let mut best_candidate: Option<&[u8]> = None;
    let mut max_len: usize = 0;

    let mut i = 0;
    while i + 3 < data.len() {
        if data[i] == 0xFF && data[i + 1] == 0xD8 && data[i + 2] == 0xFF {
            let next_byte = data[i + 3];
            // Valid JPEG marker right after SOI
            if matches!(next_byte, 0xE0..=0xEF | 0xDB | 0xC0 | 0xC2) {
                let start = i;
                let mut search = start + 4;
                let mut found_eoi = None;

                while search + 1 < data.len() {
                    if data[search] == 0xFF && data[search + 1] == 0xD9 {
                        found_eoi = Some(search + 2);
                        break;
                    }
                    search += 1;
                }

                if let Some(end) = found_eoi {
                    let len = end - start;
                    if len > max_len && len >= 256 {
                        max_len = len;
                        best_candidate = Some(&data[start..end]);
                    }
                    i = end;
                    continue;
                }
            }
        }
        i += 1;
    }

    best_candidate
}

/// Helper to parse standard TIFF headers and search for JPEGInterchangeFormat (0x0201)
/// and JPEGInterchangeFormatLength (0x0202).
fn extract_tiff_jpeg(data: &[u8]) -> Option<&[u8]> {
    if data.len() < 8 {
        return None;
    }

    let is_le = match &data[0..4] {
        [0x49, 0x49, 0x2A, 0x00] => true,
        [0x4D, 0x4D, 0x00, 0x2A] => false,
        _ => return None,
    };

    let read_u16 = |buf: &[u8], offset: usize| -> Option<u16> {
        if offset + 2 > buf.len() {
            return None;
        }
        if is_le {
            Some(u16::from_le_bytes([buf[offset], buf[offset + 1]]))
        } else {
            Some(u16::from_be_bytes([buf[offset], buf[offset + 1]]))
        }
    };

    let read_u32 = |buf: &[u8], offset: usize| -> Option<u32> {
        if offset + 4 > buf.len() {
            return None;
        }
        if is_le {
            Some(u32::from_le_bytes([
                buf[offset],
                buf[offset + 1],
                buf[offset + 2],
                buf[offset + 3],
            ]))
        } else {
            Some(u32::from_be_bytes([
                buf[offset],
                buf[offset + 1],
                buf[offset + 2],
                buf[offset + 3],
            ]))
        }
    };

    let ifd0_offset = read_u32(data, 4)? as usize;
    let mut current_ifd = ifd0_offset;

    let mut best_jpeg: Option<&[u8]> = None;
    let mut best_len: usize = 0;

    // Traverse up to 8 IFDs
    for _ in 0..8 {
        if current_ifd == 0 || current_ifd + 2 > data.len() {
            break;
        }
        let entry_count = read_u16(data, current_ifd)? as usize;
        let entries_start = current_ifd + 2;
        let entries_size = entry_count * 12;

        if entries_start + entries_size > data.len() {
            break;
        }

        let mut jpeg_offset: Option<usize> = None;
        let mut jpeg_len: Option<usize> = None;

        for e in 0..entry_count {
            let entry_offset = entries_start + e * 12;
            let tag = read_u16(data, entry_offset)?;
            let val = read_u32(data, entry_offset + 8)? as usize;

            if tag == 0x0201 {
                jpeg_offset = Some(val);
            } else if tag == 0x0202 {
                jpeg_len = Some(val);
            }
        }

        if let (Some(off), Some(len)) = (jpeg_offset, jpeg_len) {
            if off + len <= data.len()
                && len > best_len
                && data[off] == 0xFF
                && data[off + 1] == 0xD8
            {
                best_len = len;
                best_jpeg = Some(&data[off..off + len]);
            }
        }

        let next_ifd_pos = entries_start + entries_size;
        current_ifd = read_u32(data, next_ifd_pos).unwrap_or(0) as usize;
    }

    best_jpeg
}

/// Computes a deterministic cache filename for a given file based on stem, mtime, and file size.
fn make_cache_filename(raw_path: &Path) -> String {
    let stem = raw_path
        .file_stem()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_else(|| "photo".to_string());

    let (mtime, size) = fs::metadata(raw_path)
        .map(|meta| {
            let mtime_secs = meta
                .modified()
                .ok()
                .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                .map(|d| d.as_secs())
                .unwrap_or(0);
            (mtime_secs, meta.len())
        })
        .unwrap_or((0, 0));

    format!("{stem}_{mtime}_{size}.preview.jpg")
}

/// Extracts the embedded JPEG from a RAW image file and writes it into `cache_dir`.
///
/// If a cached preview already exists for this exact file version, returns the existing
/// path immediately.
pub fn extract_and_cache_preview(raw_path: &Path, cache_dir: &Path) -> Result<PathBuf, String> {
    if !raw_path.exists() {
        return Err(format!("File does not exist: {}", raw_path.display()));
    }

    fs::create_dir_all(cache_dir).map_err(|e| format!("Failed to create cache directory: {e}"))?;

    let filename = make_cache_filename(raw_path);
    let target_path = cache_dir.join(&filename);

    if target_path.exists() && fs::metadata(&target_path).map(|m| m.len()).unwrap_or(0) > 0 {
        return Ok(target_path);
    }

    let mut file = File::open(raw_path)
        .map_err(|e| format!("Failed to open RAW file {}: {e}", raw_path.display()))?;
    let mut buffer = Vec::new();
    file.read_to_end(&mut buffer)
        .map_err(|e| format!("Failed to read RAW file {}: {e}", raw_path.display()))?;

    let jpeg_bytes = find_largest_embedded_jpeg(&buffer)
        .ok_or_else(|| format!("No embedded JPEG preview found in {}", raw_path.display()))?;

    // Atomic write via temporary file
    let temp_path = cache_dir.join(format!(".tmp_{}", filename));
    let mut out_file = File::create(&temp_path)
        .map_err(|e| format!("Failed to create temporary cache file: {e}"))?;
    out_file
        .write_all(jpeg_bytes)
        .map_err(|e| format!("Failed to write embedded preview: {e}"))?;
    out_file
        .flush()
        .map_err(|e| format!("Failed to flush temporary cache file: {e}"))?;
    drop(out_file);

    fs::rename(&temp_path, &target_path)
        .map_err(|e| format!("Failed to rename temporary cache preview to destination: {e}"))?;

    Ok(target_path)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn make_dummy_jpeg(payload_size: usize) -> Vec<u8> {
        let mut jpeg = Vec::with_capacity(payload_size + 4);
        jpeg.extend_from_slice(&[0xFF, 0xD8, 0xFF, 0xE1]); // SOI + APP1
        jpeg.resize(payload_size + 2, 0xAA);
        jpeg.extend_from_slice(&[0xFF, 0xD9]); // EOI
        jpeg
    }

    #[test]
    fn test_is_raw_file() {
        assert!(is_raw_file(Path::new("photo.arw")));
        assert!(is_raw_file(Path::new("photo.ARW")));
        assert!(is_raw_file(Path::new("photo.cr2")));
        assert!(is_raw_file(Path::new("photo.dng")));
        assert!(!is_raw_file(Path::new("photo.jpg")));
        assert!(!is_raw_file(Path::new("photo.png")));
        assert!(!is_raw_file(Path::new("photo.xmp")));
    }

    #[test]
    fn test_find_largest_embedded_jpeg() {
        let small_jpeg = make_dummy_jpeg(5000);
        let large_jpeg = make_dummy_jpeg(20000);

        let mut container = Vec::new();
        container.extend_from_slice(b"RAW_HEADER_PREFIX");
        container.extend_from_slice(&small_jpeg);
        container.extend_from_slice(b"INTERMEDIATE_SENSOR_DATA");
        container.extend_from_slice(&large_jpeg);
        container.extend_from_slice(b"TRAILING_METADATA");

        let extracted = find_largest_embedded_jpeg(&container);
        assert!(extracted.is_some());
        let found = extracted.unwrap();
        assert_eq!(found.len(), large_jpeg.len());
        assert_eq!(found, &large_jpeg[..]);
    }

    #[test]
    fn test_extract_and_cache_preview_roundtrip() {
        let dir = tempdir().unwrap();
        let cache_dir = dir.path().join("cache");
        let raw_file = dir.path().join("DSC0001.ARW");

        let embedded_jpeg = make_dummy_jpeg(8192);
        let mut raw_data = vec![0u8; 1024];
        raw_data.extend_from_slice(&embedded_jpeg);
        raw_data.extend_from_slice(&vec![0u8; 1024]);
        fs::write(&raw_file, &raw_data).unwrap();

        let cached = extract_and_cache_preview(&raw_file, &cache_dir).unwrap();
        assert!(cached.exists());
        let read_back = fs::read(&cached).unwrap();
        assert_eq!(read_back, embedded_jpeg);

        // Second call hits cache
        let cached_again = extract_and_cache_preview(&raw_file, &cache_dir).unwrap();
        assert_eq!(cached, cached_again);
    }

    #[test]
    fn test_extract_from_empty_raw_fails_gracefully() {
        let dir = tempdir().unwrap();
        let cache_dir = dir.path().join("cache");
        let raw_file = dir.path().join("EMPTY.ARW");
        fs::write(&raw_file, b"NOT_A_VALID_CONTAINER").unwrap();

        let res = extract_and_cache_preview(&raw_file, &cache_dir);
        assert!(res.is_err());
        assert!(res.unwrap_err().contains("No embedded JPEG preview found"));
    }
}
