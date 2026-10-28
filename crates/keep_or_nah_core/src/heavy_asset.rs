//! Extensible 2-stage progressive heavy asset decoder framework.
//!
//! Provides a format-agnostic trait and registry for heavy media types
//! (camera RAW photos, HEIC/HIF containers, high-resolution TIFF scans, video posters, etc.)
//! where an instant fast representation (<15ms) is needed during rapid navigation,
//! followed by background full-fidelity hardware-accelerated decode/render on settle.

use std::path::{Path, PathBuf};

/// Stage of representation for progressive asset loading.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AssetStage {
    Fast,
    Full,
}

/// Trait implemented by decoders for specific heavy file formats.
pub trait HeavyAssetDecoder: Send + Sync {
    /// Identifier name for this decoder (e.g. "raw_demosaic", "heic", "tiff").
    fn name(&self) -> &'static str;

    /// Returns true if this decoder can handle the given file extension (case-insensitive, without dot).
    fn can_handle(&self, ext: &str) -> bool;

    /// Returns list of extensions handled by this decoder (without leading dot).
    fn handled_extensions(&self) -> &[&'static str];

    /// Extracts or returns an instant fast preview (e.g. embedded JPEG or cached thumbnail).
    fn extract_fast_preview(&self, path: &Path, cache_dir: &Path) -> Result<PathBuf, String>;

    /// Resolves full-fidelity render (e.g. 14-bit Bayer demosaic or full HDR decode) directly to a cached image path.
    fn resolve_full_render(&self, path: &Path, cache_dir: &Path) -> Result<PathBuf, String>;
}

/// Camera RAW decoder implementing hardware-accelerated demosaicing and embedded preview extraction.
pub struct RawDemosaicDecoder;

impl HeavyAssetDecoder for RawDemosaicDecoder {
    fn name(&self) -> &'static str {
        "raw_demosaic"
    }

    fn can_handle(&self, ext: &str) -> bool {
        let dummy = format!("file.{}", ext);
        crate::raw_extractor::is_raw_file(Path::new(&dummy))
    }

    fn handled_extensions(&self) -> &[&'static str] {
        &[
            "arw", "cr2", "cr3", "nef", "nrw", "dng", "orf", "rw2", "pef", "raf", "srw",
        ]
    }

    fn extract_fast_preview(&self, path: &Path, cache_dir: &Path) -> Result<PathBuf, String> {
        crate::raw_extractor::extract_and_cache_preview(path, cache_dir)
    }

    fn resolve_full_render(&self, path: &Path, cache_dir: &Path) -> Result<PathBuf, String> {
        crate::raw_demosaic::render_raw_to_cache(path, cache_dir)
    }
}

/// Hardware-accelerated decoder for modern container and photo formats (HEIC, HEIF, HIF, AVIF, JXL, PSD).
pub struct HeicDecoder;

impl HeavyAssetDecoder for HeicDecoder {
    fn name(&self) -> &'static str {
        "heic"
    }

    fn can_handle(&self, ext: &str) -> bool {
        matches!(
            ext.to_ascii_lowercase().as_str(),
            "heic" | "heif" | "hif" | "avif" | "jxl" | "psd"
        )
    }

    fn handled_extensions(&self) -> &[&'static str] {
        &["heic", "heif", "hif", "avif", "jxl", "psd"]
    }

    fn extract_fast_preview(&self, path: &Path, cache_dir: &Path) -> Result<PathBuf, String> {
        crate::raw_demosaic::render_raw_to_cache(path, cache_dir)
    }

    fn resolve_full_render(&self, path: &Path, cache_dir: &Path) -> Result<PathBuf, String> {
        crate::raw_demosaic::render_raw_to_cache(path, cache_dir)
    }
}

/// Backwards compatibility alias for template references.
pub type HeicDecoderTemplate = HeicDecoder;

/// Central registry managing all registered heavy asset decoders.
pub struct HeavyAssetRegistry {
    decoders: Vec<Box<dyn HeavyAssetDecoder>>,
}

impl Default for HeavyAssetRegistry {
    fn default() -> Self {
        let mut registry = Self::new();
        registry.register(Box::new(RawDemosaicDecoder));
        registry.register(Box::new(HeicDecoder));
        registry
    }
}

impl HeavyAssetRegistry {
    pub fn new() -> Self {
        Self {
            decoders: Vec::new(),
        }
    }

    pub fn register(&mut self, decoder: Box<dyn HeavyAssetDecoder>) {
        self.decoders.push(decoder);
    }

    pub fn supported_extensions(&self) -> Vec<String> {
        let mut set = std::collections::BTreeSet::new();
        for decoder in &self.decoders {
            for ext in decoder.handled_extensions() {
                set.insert(format!(".{}", ext.to_ascii_lowercase()));
            }
        }
        set.into_iter().collect()
    }

    pub fn find_decoder(&self, path: &Path) -> Option<&dyn HeavyAssetDecoder> {
        let ext = path.extension()?.to_str()?;
        self.decoders
            .iter()
            .find(|d| d.can_handle(ext))
            .map(|d| d.as_ref())
    }

    pub fn is_heavy_asset(&self, path: &Path) -> bool {
        self.find_decoder(path).is_some()
    }

    pub fn resolve_fast_preview(&self, path: &Path, cache_dir: &Path) -> Result<PathBuf, String> {
        if let Some(decoder) = self.find_decoder(path) {
            decoder.extract_fast_preview(path, cache_dir)
        } else {
            Ok(path.to_path_buf())
        }
    }

    pub fn resolve_full_render(&self, path: &Path, cache_dir: &Path) -> Result<PathBuf, String> {
        if let Some(decoder) = self.find_decoder(path) {
            decoder.resolve_full_render(path, cache_dir)
        } else {
            Ok(path.to_path_buf())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_heavy_asset_registry_detection() {
        let registry = HeavyAssetRegistry::default();
        assert!(registry.is_heavy_asset(Path::new("photo.ARW")));
        assert!(registry.is_heavy_asset(Path::new("photo.cr2")));
        assert!(registry.is_heavy_asset(Path::new("photo.heic")));
        assert!(registry.is_heavy_asset(Path::new("photo.HEIF")));
        assert!(registry.is_heavy_asset(Path::new("photo.hif")));
        assert!(registry.is_heavy_asset(Path::new("photo.avif")));
        assert!(registry.is_heavy_asset(Path::new("photo.jxl")));
        assert!(registry.is_heavy_asset(Path::new("photo.psd")));
        assert!(!registry.is_heavy_asset(Path::new("photo.jpg")));
        assert!(!registry.is_heavy_asset(Path::new("photo.png")));
    }

    #[test]
    fn test_supported_extensions_contains_all_registered() {
        let registry = HeavyAssetRegistry::default();
        let exts = registry.supported_extensions();
        assert!(exts.contains(&".heic".to_string()));
        assert!(exts.contains(&".heif".to_string()));
        assert!(exts.contains(&".hif".to_string()));
        assert!(exts.contains(&".avif".to_string()));
        assert!(exts.contains(&".jxl".to_string()));
        assert!(exts.contains(&".psd".to_string()));
        assert!(exts.contains(&".arw".to_string()));
        assert!(exts.contains(&".dng".to_string()));
    }

    #[test]
    fn test_non_heavy_asset_passthrough() {
        let registry = HeavyAssetRegistry::default();
        let jpg_path = Path::new("/dummy/photo.jpg");
        let cache_dir = Path::new("/dummy/cache");

        let fast = registry.resolve_fast_preview(jpg_path, cache_dir).unwrap();
        assert_eq!(fast, jpg_path);

        let full = registry.resolve_full_render(jpg_path, cache_dir).unwrap();
        assert_eq!(full, jpg_path);
    }

    #[test]
    fn test_custom_decoder_registration() {
        struct MockTiffDecoder;
        impl HeavyAssetDecoder for MockTiffDecoder {
            fn name(&self) -> &'static str {
                "mock_tiff"
            }
            fn can_handle(&self, ext: &str) -> bool {
                matches!(ext.to_ascii_lowercase().as_str(), "tif" | "tiff")
            }
            fn handled_extensions(&self) -> &[&'static str] {
                &["tif", "tiff"]
            }
            fn extract_fast_preview(
                &self,
                path: &Path,
                _cache_dir: &Path,
            ) -> Result<PathBuf, String> {
                Ok(path.with_extension("fast.jpg"))
            }
            fn resolve_full_render(
                &self,
                path: &Path,
                _cache_dir: &Path,
            ) -> Result<PathBuf, String> {
                Ok(path.with_extension("full.jpg"))
            }
        }

        let mut registry = HeavyAssetRegistry::new();
        registry.register(Box::new(MockTiffDecoder));

        let tiff_path = Path::new("/dummy/scan.tiff");
        assert!(registry.is_heavy_asset(tiff_path));
        let fast = registry
            .resolve_fast_preview(tiff_path, Path::new("/cache"))
            .unwrap();
        assert_eq!(fast, Path::new("/dummy/scan.fast.jpg"));
        let full = registry
            .resolve_full_render(tiff_path, Path::new("/cache"))
            .unwrap();
        assert_eq!(full, Path::new("/dummy/scan.full.jpg"));
    }
}
