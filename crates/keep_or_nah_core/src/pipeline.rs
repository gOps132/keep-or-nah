use std::cmp::Ordering;
use std::collections::{BinaryHeap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering as AtomicOrdering};
use std::sync::Arc;
use std::thread::{self, JoinHandle};

use crossbeam_channel::{unbounded, Receiver, Sender};
use parking_lot::{Condvar, Mutex, RwLock};

use crate::cache::{PreviewCache, RenderKey, ViewportKey};
use crate::image_loader::{load_and_orient, render_fit, LoadedImage, PreviewStage};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TaskKind {
    ActiveFast,
    ActiveFull,
    PrefetchFull,
    Shutdown,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PreviewTask {
    pub priority: (u8, u32, u64), // (category, distance, sequence) - smaller is higher priority
    pub sequence: u64,
    pub kind: TaskKind,
    pub path: PathBuf,
    pub viewport: (u32, u32),
    pub request_id: u64,
    pub generation: u64,
}

impl Ord for PreviewTask {
    fn cmp(&self, other: &Self) -> Ordering {
        // Reverse ordering so BinaryHeap acts as a min-heap
        other.priority.cmp(&self.priority)
    }
}

impl PartialOrd for PreviewTask {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

#[derive(Debug, Clone)]
pub struct CompletedPreview {
    pub path: PathBuf,
    pub request_id: u64,
    pub stage: String, // "source", "fast", "full", "unavailable", "error"
}

pub struct PreviewLookup {
    pub image: Option<Arc<LoadedImage>>,
    pub stage: Option<PreviewStage>,
    pub failed: bool,
    pub unavailable: bool,
}

struct PipelineState {
    paths: Vec<PathBuf>,
    paths_set: HashSet<PathBuf>,
    viewport: (u32, u32),
    generation: u64,
    cache: PreviewCache,
    window_radius: usize,
    base_window_radius: usize,
    pending_tasks: HashSet<(u64, u8, PathBuf, (u32, u32))>,
}

pub struct Pipeline {
    state: Arc<RwLock<PipelineState>>,
    task_queue: Arc<Mutex<BinaryHeap<PreviewTask>>>,
    task_notifier: Arc<Condvar>,
    #[allow(dead_code)]
    completed_tx: Sender<CompletedPreview>,
    completed_rx: Receiver<CompletedPreview>,
    sequence: AtomicU64,
    closed: AtomicBool,
    workers: Mutex<Vec<JoinHandle<()>>>,
}

impl Pipeline {
    pub fn new(window_radius: usize, cache_budget_mb: usize, max_workers: usize) -> Arc<Self> {
        let budget_bytes = cache_budget_mb.max(64) * 1024 * 1024;
        let base_radius = window_radius;
        let calculated_radius = (base_radius.max(cache_budget_mb / 96)).min(12);

        let state = Arc::new(RwLock::new(PipelineState {
            paths: Vec::new(),
            paths_set: HashSet::new(),
            viewport: (0, 0),
            generation: 0,
            cache: PreviewCache::new(budget_bytes),
            window_radius: calculated_radius,
            base_window_radius: base_radius,
            pending_tasks: HashSet::new(),
        }));

        let task_queue = Arc::new(Mutex::new(BinaryHeap::new()));
        let task_notifier = Arc::new(Condvar::new());
        let (completed_tx, completed_rx) = unbounded();

        let num_workers = max_workers.max(1).min(4);
        let mut workers = Vec::with_capacity(num_workers);

        for index in 0..num_workers {
            let state_clone = Arc::clone(&state);
            let queue_clone = Arc::clone(&task_queue);
            let notifier_clone = Arc::clone(&task_notifier);
            let completed_tx_clone = completed_tx.clone();

            let handle = thread::Builder::new()
                .name(format!("preview-worker-{index}"))
                .spawn(move || {
                    Self::worker_loop(state_clone, queue_clone, notifier_clone, completed_tx_clone);
                })
                .expect("Failed to spawn preview worker thread");

            workers.push(handle);
        }

        Arc::new(Self {
            state,
            task_queue,
            task_notifier,
            completed_tx,
            completed_rx,
            sequence: AtomicU64::new(1),
            closed: AtomicBool::new(false),
            workers: Mutex::new(workers),
        })
    }

    pub fn shutdown(&self) {
        if self.closed.swap(true, AtomicOrdering::SeqCst) {
            return;
        }

        let num_workers = { self.workers.lock().len() };
        {
            let mut queue = self.task_queue.lock();
            for i in 0..num_workers {
                queue.push(PreviewTask {
                    priority: (99, i as u32, 0),
                    sequence: 0,
                    kind: TaskKind::Shutdown,
                    path: PathBuf::new(),
                    viewport: (0, 0),
                    request_id: 0,
                    generation: 0,
                });
            }
            self.task_notifier.notify_all();
        }

        let mut workers = self.workers.lock();
        for worker in workers.drain(..) {
            let _ = worker.join();
        }
    }

    pub fn reset(&self, paths: Vec<PathBuf>) {
        let paths_set: HashSet<PathBuf> = paths.iter().cloned().collect();
        let mut state = self.state.write();
        state.generation += 1;
        state.cache.prune(&paths_set);
        state.paths_set = paths_set;
        state.paths = paths;
        state.pending_tasks.clear();

        // Clear existing tasks for previous generations from queue
        let mut queue = self.task_queue.lock();
        queue.clear();
    }

    pub fn set_viewport(&self, width: u32, height: u32) {
        let mut state = self.state.write();
        state.viewport = (width, height);
    }

    pub fn configure_cache_budget(&self, cache_budget_mb: usize) {
        let budget_bytes = cache_budget_mb.max(64) * 1024 * 1024;
        let mut state = self.state.write();
        state.cache.set_limits(budget_bytes);
        state.window_radius = (state.base_window_radius.max(cache_budget_mb / 96)).min(12);
    }

    pub fn start_preview_request(&self, path: &Path, active_index: usize, progressive: bool) -> u64 {
        let request_id = self.sequence.fetch_add(1, AtomicOrdering::Relaxed);
        let (viewport, generation, window_radius, paths_len) = {
            let state = self.state.read();
            (state.viewport, state.generation, state.window_radius, state.paths.len())
        };

        if viewport.0 < 8 || viewport.1 < 8 {
            return request_id;
        }

        let has_fast = {
            let state = self.state.read();
            state.cache.has_render(&RenderKey {
                path: path.to_path_buf(),
                width: viewport.0,
                height: viewport.1,
                stage: PreviewStage::Fast,
            })
        };

        let has_full = {
            let state = self.state.read();
            state.cache.has_render(&RenderKey {
                path: path.to_path_buf(),
                width: viewport.0,
                height: viewport.1,
                stage: PreviewStage::Full,
            })
        };

        if progressive && !has_fast {
            self.enqueue_task(
                TaskKind::ActiveFast,
                path.to_path_buf(),
                viewport,
                request_id,
                generation,
                (0, 0, request_id),
            );
        }

        if !has_full {
            self.enqueue_task(
                TaskKind::ActiveFull,
                path.to_path_buf(),
                viewport,
                request_id,
                generation,
                (1, 0, request_id),
            );
        }

        // Prefetch surrounding photos
        if paths_len > 0 {
            let paths_snapshot = { self.state.read().paths.clone() };
            for distance in 1..=window_radius {
                let left_idx = active_index.checked_sub(distance);
                let right_idx = active_index + distance;

                for &idx_opt in &[left_idx, Some(right_idx)] {
                    if let Some(idx) = idx_opt {
                        if idx < paths_snapshot.len() {
                            let p = &paths_snapshot[idx];
                            let already_rendered = {
                                let state = self.state.read();
                                state.cache.has_render(&RenderKey {
                                    path: p.clone(),
                                    width: viewport.0,
                                    height: viewport.1,
                                    stage: PreviewStage::Full,
                                })
                            };
                            if !already_rendered {
                                self.enqueue_task(
                                    TaskKind::PrefetchFull,
                                    p.clone(),
                                    viewport,
                                    request_id,
                                    generation,
                                    (2, distance as u32, request_id),
                                );
                            }
                        }
                    }
                }
            }
        }

        request_id
    }

    pub fn get_best_preview(&self, path: &Path) -> PreviewLookup {
        let (viewport, has_path) = {
            let state = self.state.read();
            (state.viewport, state.paths_set.contains(path))
        };

        if !has_path || viewport.0 < 8 || viewport.1 < 8 {
            return PreviewLookup {
                image: None,
                stage: None,
                failed: false,
                unavailable: false,
            };
        }

        let mut state = self.state.write();
        let full_key = RenderKey {
            path: path.to_path_buf(),
            width: viewport.0,
            height: viewport.1,
            stage: PreviewStage::Full,
        };

        if let Some(img) = state.cache.get_render(&full_key) {
            return PreviewLookup {
                image: Some(img),
                stage: Some(PreviewStage::Full),
                failed: false,
                unavailable: false,
            };
        }

        let fast_key = RenderKey {
            path: path.to_path_buf(),
            width: viewport.0,
            height: viewport.1,
            stage: PreviewStage::Fast,
        };

        if let Some(img) = state.cache.get_render(&fast_key) {
            return PreviewLookup {
                image: Some(img),
                stage: Some(PreviewStage::Fast),
                failed: false,
                unavailable: false,
            };
        }

        let vp_key = ViewportKey {
            path: path.to_path_buf(),
            width: viewport.0,
            height: viewport.1,
        };

        PreviewLookup {
            image: None,
            stage: None,
            failed: state.cache.is_failed(&vp_key),
            unavailable: state.cache.is_unavailable(&vp_key),
        }
    }

    pub fn get_cached_source(&self, path: &Path) -> Option<Arc<LoadedImage>> {
        let mut state = self.state.write();
        state.cache.get_source(path)
    }

    pub fn has_source(&self, path: &Path) -> bool {
        let state = self.state.read();
        state.cache.has_source(path)
    }

    pub fn drain_completed(&self) -> Vec<CompletedPreview> {
        let mut out = Vec::new();
        while let Ok(item) = self.completed_rx.try_recv() {
            out.push(item);
        }
        out
    }

    fn enqueue_task(
        &self,
        kind: TaskKind,
        path: PathBuf,
        viewport: (u32, u32),
        request_id: u64,
        generation: u64,
        priority: (u8, u32, u64),
    ) {
        if self.closed.load(AtomicOrdering::Relaxed) {
            return;
        }

        let kind_id = match kind {
            TaskKind::ActiveFast => 0,
            TaskKind::ActiveFull => 1,
            TaskKind::PrefetchFull => 2,
            TaskKind::Shutdown => 99,
        };

        {
            let mut state = self.state.write();
            if state.generation != generation || !state.paths_set.contains(&path) {
                return;
            }
            let key = (generation, kind_id, path.clone(), viewport);
            if state.pending_tasks.contains(&key) {
                return;
            }
            state.pending_tasks.insert(key);
        }

        let seq = self.sequence.fetch_add(1, AtomicOrdering::Relaxed);
        let task = PreviewTask {
            priority,
            sequence: seq,
            kind,
            path,
            viewport,
            request_id,
            generation,
        };

        {
            let mut queue = self.task_queue.lock();
            queue.push(task);
            self.task_notifier.notify_one();
        }
    }

    fn worker_loop(
        state: Arc<RwLock<PipelineState>>,
        task_queue: Arc<Mutex<BinaryHeap<PreviewTask>>>,
        task_notifier: Arc<Condvar>,
        completed_tx: Sender<CompletedPreview>,
    ) {
        loop {
            let task = {
                let mut queue = task_queue.lock();
                loop {
                    if let Some(t) = queue.pop() {
                        break t;
                    }
                    task_notifier.wait(&mut queue);
                }
            };

            if task.kind == TaskKind::Shutdown {
                return;
            }

            // Remove from pending_tasks
            let kind_id = match task.kind {
                TaskKind::ActiveFast => 0,
                TaskKind::ActiveFull => 1,
                TaskKind::PrefetchFull => 2,
                TaskKind::Shutdown => 99,
            };

            // Check if still current
            let is_current = {
                let mut s = state.write();
                s.pending_tasks
                    .remove(&(task.generation, kind_id, task.path.clone(), task.viewport));
                s.generation == task.generation && s.paths_set.contains(&task.path)
            };

            if !is_current {
                continue;
            }

            // Skip if already rendered
            let stage = match task.kind {
                TaskKind::ActiveFast => PreviewStage::Fast,
                TaskKind::ActiveFull | TaskKind::PrefetchFull => PreviewStage::Full,
                TaskKind::Shutdown => continue,
            };

            let render_key = RenderKey {
                path: task.path.clone(),
                width: task.viewport.0,
                height: task.viewport.1,
                stage,
            };

            let already_have_render = {
                let s = state.read();
                s.cache.has_render(&render_key)
            };

            if already_have_render {
                continue;
            }

            // Get or load source image
            let source_opt = {
                let mut s = state.write();
                s.cache.get_source(&task.path)
            };

            let source = match source_opt {
                Some(src) => src,
                None => {
                    let vp_key = ViewportKey {
                        path: task.path.clone(),
                        width: task.viewport.0,
                        height: task.viewport.1,
                    };
                    let already_failed_or_unavailable = {
                        let s = state.read();
                        s.cache.is_unavailable(&vp_key) || s.cache.is_failed(&vp_key)
                    };
                    if already_failed_or_unavailable {
                        continue;
                    }

                    let ext = task.path.extension().and_then(|s| s.to_str()).map(|s| s.to_lowercase());
                    let is_known_extension = match ext.as_deref() {
                        Some("bmp" | "gif" | "jpeg" | "jpg" | "png" | "tif" | "tiff" | "webp") => true,
                        _ => false,
                    };

                    if !is_known_extension {
                        {
                            let mut s = state.write();
                            s.cache.mark_unavailable(vp_key);
                        }
                        let _ = completed_tx.send(CompletedPreview {
                            path: task.path.clone(),
                            request_id: task.request_id,
                            stage: "unavailable".to_string(),
                        });
                        continue;
                    }

                    match load_and_orient(&task.path) {
                        Ok(loaded) => {
                            let arc = Arc::new(loaded);
                            {
                                let mut s = state.write();
                                s.cache.put_source(task.path.clone(), Arc::clone(&arc));
                            }
                            let _ = completed_tx.send(CompletedPreview {
                                path: task.path.clone(),
                                request_id: task.request_id,
                                stage: "source".to_string(),
                            });
                            arc
                        }
                        Err(err) => {
                            let is_unsupported = match &err {
                                image::ImageError::Unsupported(_) => true,
                                _ => false,
                            };
                            {
                                let mut s = state.write();
                                if is_unsupported {
                                    s.cache.mark_unavailable(vp_key);
                                } else {
                                    s.cache.mark_failed(vp_key);
                                }
                            }
                            let _ = completed_tx.send(CompletedPreview {
                                path: task.path.clone(),
                                request_id: task.request_id,
                                stage: if is_unsupported {
                                    "unavailable".to_string()
                                } else {
                                    "error".to_string()
                                },
                            });
                            continue;
                        }
                    }
                }
            };

            // Render fit preview
            match render_fit(&source, task.viewport.0, task.viewport.1, stage) {
                Ok(rendered) => {
                    let arc_render = Arc::new(rendered);
                    {
                        let mut s = state.write();
                        s.cache.put_render(render_key, arc_render);
                    }
                    let _ = completed_tx.send(CompletedPreview {
                        path: task.path,
                        request_id: task.request_id,
                        stage: match stage {
                            PreviewStage::Fast => "fast".to_string(),
                            PreviewStage::Full => "full".to_string(),
                        },
                    });
                }
                Err(_) => {
                    let vp_key = ViewportKey {
                        path: task.path.clone(),
                        width: task.viewport.0,
                        height: task.viewport.1,
                    };
                    {
                        let mut s = state.write();
                        s.cache.mark_failed(vp_key);
                    }
                    let _ = completed_tx.send(CompletedPreview {
                        path: task.path,
                        request_id: task.request_id,
                        stage: "error".to_string(),
                    });
                }
            }
        }
    }
}
