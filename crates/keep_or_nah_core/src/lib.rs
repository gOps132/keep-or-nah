pub mod analysis;
pub mod cache;
pub mod fileops;
pub mod heavy_asset;
pub mod image_loader;
pub mod pipeline;
pub mod raw_demosaic;
pub mod raw_extractor;
pub mod scan;

pub fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    #[test]
    fn the_core_modules_are_reachable() {
        let rgba = vec![0u8; 4 * 4 * 4];
        assert!(analysis::compute_sharpness(&rgba, 4, 4) >= 0.0);
        assert_eq!(analysis::compute_image_hash(&rgba, 4, 4), 0);
        assert!(scan::discover_extensions(Path::new("/definitely/not/here")).is_empty());
        assert!(scan::build_photo_groups(Path::new("/definitely/not/here"), &[], &[]).is_empty());
        assert_eq!(cache::PreviewCache::new(1024).source_limit_bytes, 634);
        assert_eq!(
            image_loader::PreviewStage::Fast,
            image_loader::PreviewStage::Fast
        );
        assert!(pipeline::Pipeline::new(1, 64, 1)
            .get_best_preview(Path::new("/nope"))
            .image
            .is_none());
        assert!(fileops::identity_of(Path::new("/definitely/not/here")).is_err());
    }

    #[test]
    fn the_reported_version_is_the_package_version() {
        assert_eq!(version(), env!("CARGO_PKG_VERSION"));
    }
}
