use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use lru::LruCache;

use crate::image_loader::{LoadedImage, PreviewStage};

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct RenderKey {
    pub path: PathBuf,
    pub width: u32,
    pub height: u32,
    pub stage: PreviewStage,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct ViewportKey {
    pub path: PathBuf,
    pub width: u32,
    pub height: u32,
}

pub struct PreviewCache {
    pub source_cache: LruCache<PathBuf, Arc<LoadedImage>>,
    pub source_bytes: usize,
    pub source_limit_bytes: usize,

    pub render_cache: LruCache<RenderKey, Arc<LoadedImage>>,
    pub render_bytes: usize,
    pub render_limit_bytes: usize,

    pub failed_keys: HashSet<ViewportKey>,
    pub unavailable_keys: HashSet<ViewportKey>,
}

impl PreviewCache {
    pub fn new(total_budget_bytes: usize) -> Self {
        let source_limit = (total_budget_bytes as f64 * 0.62) as usize;
        let render_limit = (total_budget_bytes.saturating_sub(source_limit)).max(8 * 1024 * 1024);

        Self {
            source_cache: LruCache::unbounded(),
            source_bytes: 0,
            source_limit_bytes: source_limit,

            render_cache: LruCache::unbounded(),
            render_bytes: 0,
            render_limit_bytes: render_limit,

            failed_keys: HashSet::new(),
            unavailable_keys: HashSet::new(),
        }
    }

    pub fn set_limits(&mut self, total_budget_bytes: usize) {
        self.source_limit_bytes = (total_budget_bytes as f64 * 0.62) as usize;
        self.render_limit_bytes =
            (total_budget_bytes.saturating_sub(self.source_limit_bytes)).max(8 * 1024 * 1024);
        self.trim();
    }

    pub fn get_source(&mut self, path: &Path) -> Option<Arc<LoadedImage>> {
        self.source_cache.get(path).cloned()
    }

    pub fn has_source(&self, path: &Path) -> bool {
        self.source_cache.peek(path).is_some()
    }

    pub fn put_source(&mut self, path: PathBuf, image: Arc<LoadedImage>) {
        let bytes = image.byte_size();
        if let Some(old) = self.source_cache.put(path, image) {
            self.source_bytes = self.source_bytes.saturating_sub(old.byte_size());
        }
        self.source_bytes += bytes;
        self.trim_sources();
    }

    pub fn get_render(&mut self, key: &RenderKey) -> Option<Arc<LoadedImage>> {
        self.render_cache.get(key).cloned()
    }

    pub fn has_render(&self, key: &RenderKey) -> bool {
        self.render_cache.peek(key).is_some()
    }

    pub fn put_render(&mut self, key: RenderKey, image: Arc<LoadedImage>) {
        let bytes = image.byte_size();
        let viewport_key = ViewportKey {
            path: key.path.clone(),
            width: key.width,
            height: key.height,
        };
        self.failed_keys.remove(&viewport_key);
        self.unavailable_keys.remove(&viewport_key);

        if let Some(old) = self.render_cache.put(key, image) {
            self.render_bytes = self.render_bytes.saturating_sub(old.byte_size());
        }
        self.render_bytes += bytes;
        self.trim_renders();
    }

    pub fn mark_failed(&mut self, key: ViewportKey) {
        self.unavailable_keys.remove(&key);
        self.failed_keys.insert(key);
    }

    pub fn mark_unavailable(&mut self, key: ViewportKey) {
        self.failed_keys.remove(&key);
        self.unavailable_keys.insert(key);
    }

    pub fn is_failed(&self, key: &ViewportKey) -> bool {
        self.failed_keys.contains(key)
    }

    pub fn is_unavailable(&self, key: &ViewportKey) -> bool {
        self.unavailable_keys.contains(key)
    }

    pub fn prune(&mut self, allowed_paths: &HashSet<PathBuf>) {
        // Prune sources
        let mut keys_to_remove = Vec::new();
        for (k, _) in self.source_cache.iter() {
            if !allowed_paths.contains(k) {
                keys_to_remove.push(k.clone());
            }
        }
        for k in keys_to_remove {
            if let Some(img) = self.source_cache.pop(&k) {
                self.source_bytes = self.source_bytes.saturating_sub(img.byte_size());
            }
        }

        // Prune renders
        let mut render_keys_to_remove = Vec::new();
        for (k, _) in self.render_cache.iter() {
            if !allowed_paths.contains(&k.path) {
                render_keys_to_remove.push(k.clone());
            }
        }
        for k in render_keys_to_remove {
            if let Some(img) = self.render_cache.pop(&k) {
                self.render_bytes = self.render_bytes.saturating_sub(img.byte_size());
            }
        }

        self.failed_keys.retain(|k| allowed_paths.contains(&k.path));
        self.unavailable_keys
            .retain(|k| allowed_paths.contains(&k.path));
    }

    pub fn trim(&mut self) {
        self.trim_sources();
        self.trim_renders();
    }

    fn trim_sources(&mut self) {
        while self.source_bytes > self.source_limit_bytes {
            if let Some((_, img)) = self.source_cache.pop_lru() {
                self.source_bytes = self.source_bytes.saturating_sub(img.byte_size());
            } else {
                break;
            }
        }
    }

    fn trim_renders(&mut self) {
        while self.render_bytes > self.render_limit_bytes {
            if let Some((_, img)) = self.render_cache.pop_lru() {
                self.render_bytes = self.render_bytes.saturating_sub(img.byte_size());
            } else {
                break;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const MIB: usize = 1024 * 1024;

    /// A fully opaque image of `pixels` square pixels.
    fn image(pixels: u32) -> Arc<LoadedImage> {
        Arc::new(LoadedImage {
            width: pixels,
            height: pixels,
            rgba: vec![7u8; (pixels * pixels * 4) as usize],
        })
    }

    fn viewport_key(path: &str) -> ViewportKey {
        ViewportKey {
            path: PathBuf::from(path),
            width: 100,
            height: 100,
        }
    }

    fn render_key(path: &str, stage: PreviewStage) -> RenderKey {
        RenderKey {
            path: PathBuf::from(path),
            width: 100,
            height: 100,
            stage,
        }
    }

    #[test]
    fn new_splits_the_budget_between_sources_and_renders() {
        let cache = PreviewCache::new(100 * MIB);

        assert_eq!(cache.source_limit_bytes, 65_011_712);
        assert_eq!(cache.render_limit_bytes, 39_845_888);
    }

    #[test]
    fn new_keeps_a_render_floor_of_eight_mebibytes() {
        let cache = PreviewCache::new(4 * MIB);

        assert_eq!(cache.source_limit_bytes, 2_600_468);
        assert_eq!(cache.render_limit_bytes, 8 * MIB);
    }

    #[test]
    fn sources_round_trip_through_the_cache() {
        let mut cache = PreviewCache::new(100 * MIB);
        let path = PathBuf::from("/photos/IMG.jpg");
        let picture = image(64);

        assert!(!cache.has_source(&path));
        assert!(cache.get_source(&path).is_none());

        cache.put_source(path.clone(), Arc::clone(&picture));

        assert!(cache.has_source(&path));
        assert_eq!(cache.get_source(&path).map(|entry| entry.width), Some(64));
        assert_eq!(cache.source_bytes, picture.byte_size());
    }

    #[test]
    fn putting_the_same_source_twice_does_not_double_count() {
        let mut cache = PreviewCache::new(100 * MIB);
        let path = PathBuf::from("/photos/IMG.jpg");
        let picture = image(64);

        cache.put_source(path.clone(), Arc::clone(&picture));
        cache.put_source(path.clone(), Arc::clone(&picture));

        assert_eq!(cache.source_bytes, picture.byte_size());
    }

    #[test]
    fn the_least_recently_used_source_is_evicted_first() {
        let mut cache = PreviewCache::new(16 * MIB);
        // 9 sources of 1 MiB fit into the 10 MiB source budget, the tenth
        // pushes the cache over the limit.
        let pictures: Vec<Arc<LoadedImage>> = (0..10).map(|_| image(512)).collect();
        let paths: Vec<PathBuf> = (0..10)
            .map(|index| PathBuf::from(format!("/photos/{index}.jpg")))
            .collect();

        for (path, picture) in paths.iter().zip(pictures.iter()) {
            cache.put_source(path.clone(), Arc::clone(picture));
        }

        assert!(
            !cache.has_source(&paths[0]),
            "the oldest source must be gone"
        );
        assert!(cache.has_source(&paths[9]), "the newest source must stay");
        assert_eq!(cache.source_cache.len(), 9);
        assert!(cache.source_bytes <= cache.source_limit_bytes);
    }

    #[test]
    fn reading_a_source_makes_it_the_most_recently_used_one() {
        // A 4 MiB budget leaves 2 MiB for the sources, so two 1 MiB images fit
        // and the third one evicts the least recently used entry.
        let mut cache = PreviewCache::new(4 * MIB);
        let pictures: Vec<Arc<LoadedImage>> = (0..2).map(|_| image(512)).collect();
        let paths: Vec<PathBuf> = (0..2)
            .map(|index| PathBuf::from(format!("/photos/{index}.jpg")))
            .collect();

        cache.put_source(paths[0].clone(), Arc::clone(&pictures[0]));
        cache.put_source(paths[1].clone(), Arc::clone(&pictures[1]));
        // Touch the first entry so the second one becomes the eviction
        // candidate.
        assert!(cache.get_source(&paths[0]).is_some());
        cache.put_source(PathBuf::from("/photos/2.jpg"), Arc::clone(&pictures[0]));

        assert!(cache.has_source(&paths[0]));
        assert!(!cache.has_source(&paths[1]));
    }

    #[test]
    fn renders_round_trip_through_the_cache() {
        let mut cache = PreviewCache::new(100 * MIB);
        let key = render_key("/photos/IMG.jpg", PreviewStage::Full);
        let picture = image(32);

        assert!(!cache.has_render(&key));
        cache.put_render(key.clone(), Arc::clone(&picture));

        assert!(cache.has_render(&key));
        assert_eq!(cache.get_render(&key).map(|entry| entry.height), Some(32));
        assert_eq!(cache.render_bytes, picture.byte_size());
    }

    #[test]
    fn storing_a_render_clears_its_failure_markers() {
        let mut cache = PreviewCache::new(100 * MIB);
        let key = render_key("/photos/IMG.jpg", PreviewStage::Full);
        let viewport = viewport_key("/photos/IMG.jpg");

        cache.mark_failed(viewport.clone());
        assert!(cache.is_failed(&viewport));
        assert!(!cache.is_unavailable(&viewport));

        cache.put_render(key, Arc::clone(&image(32)));

        assert!(!cache.is_failed(&viewport));
        assert!(!cache.is_unavailable(&viewport));
    }

    #[test]
    fn failure_and_unavailable_are_mutually_exclusive() {
        let mut cache = PreviewCache::new(100 * MIB);
        let viewport = viewport_key("/photos/IMG.jpg");

        cache.mark_failed(viewport.clone());
        assert!(cache.is_failed(&viewport));
        assert!(!cache.is_unavailable(&viewport));

        cache.mark_unavailable(viewport.clone());
        assert!(!cache.is_failed(&viewport));
        assert!(cache.is_unavailable(&viewport));
    }

    #[test]
    fn prune_drops_everything_outside_the_allowed_paths() {
        let mut cache = PreviewCache::new(100 * MIB);
        let kept = PathBuf::from("/photos/kept.jpg");
        let dropped = PathBuf::from("/photos/dropped.jpg");

        cache.put_source(kept.clone(), image(64));
        cache.put_source(dropped.clone(), image(64));
        cache.put_render(
            render_key("/photos/kept.jpg", PreviewStage::Full),
            image(32),
        );
        cache.put_render(
            render_key("/photos/dropped.jpg", PreviewStage::Full),
            image(32),
        );
        cache.mark_failed(viewport_key("/photos/dropped.jpg"));

        let allowed: HashSet<PathBuf> = HashSet::from([kept.clone()]);
        cache.prune(&allowed);

        assert!(cache.has_source(&kept));
        assert!(!cache.has_source(&dropped));
        assert!(cache.has_render(&render_key("/photos/kept.jpg", PreviewStage::Full)));
        assert!(!cache.has_render(&render_key("/photos/dropped.jpg", PreviewStage::Full)));
        assert!(!cache.is_failed(&viewport_key("/photos/dropped.jpg")));
        assert_eq!(cache.source_bytes, 64 * 64 * 4);
        assert_eq!(cache.render_bytes, 32 * 32 * 4);
    }

    #[test]
    fn set_limits_trims_the_cache_down_to_the_new_budget() {
        let mut cache = PreviewCache::new(100 * MIB);
        let paths: Vec<PathBuf> = (0..4)
            .map(|index| PathBuf::from(format!("/photos/{index}.jpg")))
            .collect();
        for path in &paths {
            cache.put_source(path.clone(), image(512));
        }
        assert_eq!(cache.source_cache.len(), 4);

        cache.set_limits(2 * MIB);

        assert!(cache.source_bytes <= cache.source_limit_bytes);
        assert!(cache.source_cache.len() < 4);
    }
}
