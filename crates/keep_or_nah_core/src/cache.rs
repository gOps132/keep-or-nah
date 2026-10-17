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
        self.render_limit_bytes = (total_budget_bytes.saturating_sub(self.source_limit_bytes)).max(8 * 1024 * 1024);
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
        self.unavailable_keys.retain(|k| allowed_paths.contains(&k.path));
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
