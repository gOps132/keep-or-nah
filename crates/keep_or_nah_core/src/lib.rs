pub mod cache;
pub mod image_loader;
pub mod pipeline;

use std::path::{Path, PathBuf};
use std::sync::Arc;

use pyo3::prelude::*;
use pyo3::types::PyBytes;

use crate::image_loader::{load_and_orient, render_fit, LoadedImage, PreviewStage};
use crate::pipeline::{CompletedPreview, Pipeline, PreviewLookup};

#[pyclass(get_all)]
pub struct PyPreviewLookup {
    pub stage: Option<String>,
    pub width: u32,
    pub height: u32,
    pub data: Option<Py<PyBytes>>,
    pub failed: bool,
    pub unavailable: bool,
}

#[pyclass(get_all)]
pub struct PyRawImage {
    pub width: u32,
    pub height: u32,
    pub data: Py<PyBytes>,
}

#[pyclass(get_all)]
#[derive(Clone)]
pub struct PyCompletedPreview {
    pub path: String,
    pub request_id: u64,
    pub stage: String,
}

impl From<CompletedPreview> for PyCompletedPreview {
    fn from(c: CompletedPreview) -> Self {
        Self {
            path: c.path.to_string_lossy().to_string(),
            request_id: c.request_id,
            stage: c.stage,
        }
    }
}

#[pyclass]
pub struct RustPreviewPipeline {
    inner: Arc<Pipeline>,
}

#[pymethods]
impl RustPreviewPipeline {
    #[new]
    #[pyo3(signature = (window_radius=2, cache_budget_mb=256, max_workers=1))]
    fn new(window_radius: usize, cache_budget_mb: usize, max_workers: usize) -> Self {
        Self {
            inner: Pipeline::new(window_radius, cache_budget_mb, max_workers),
        }
    }

    fn reset(&self, paths: Vec<String>) {
        let path_bufs: Vec<PathBuf> = paths.into_iter().map(PathBuf::from).collect();
        self.inner.reset(path_bufs);
    }

    fn set_viewport(&self, width: u32, height: u32) {
        self.inner.set_viewport(width, height);
    }

    fn configure_cache_budget(&self, cache_budget_mb: usize) {
        self.inner.configure_cache_budget(cache_budget_mb);
    }

    #[pyo3(signature = (path, active_index, progressive=true))]
    fn start_preview_request(&self, path: String, active_index: usize, progressive: bool) -> u64 {
        self.inner
            .start_preview_request(Path::new(&path), active_index, progressive)
    }

    fn get_best_preview(&self, py: Python<'_>, path: String) -> PyPreviewLookup {
        let lookup: PreviewLookup = self.inner.get_best_preview(Path::new(&path));
        match lookup.image {
            Some(img) => {
                let py_bytes = PyBytes::new(py, &img.rgba).unbind();
                PyPreviewLookup {
                    stage: lookup.stage.map(|s| match s {
                        PreviewStage::Fast => "fast".to_string(),
                        PreviewStage::Full => "full".to_string(),
                    }),
                    width: img.width,
                    height: img.height,
                    data: Some(py_bytes),
                    failed: false,
                    unavailable: false,
                }
            }
            None => PyPreviewLookup {
                stage: None,
                width: 0,
                height: 0,
                data: None,
                failed: lookup.failed,
                unavailable: lookup.unavailable,
            },
        }
    }

    fn get_cached_source(&self, py: Python<'_>, path: String) -> Option<PyRawImage> {
        let img = self.inner.get_cached_source(Path::new(&path))?;
        let py_bytes = PyBytes::new(py, &img.rgba).unbind();
        Some(PyRawImage {
            width: img.width,
            height: img.height,
            data: py_bytes,
        })
    }

    fn has_source(&self, path: String) -> bool {
        self.inner.has_source(Path::new(&path))
    }

    fn drain_completed(&self) -> Vec<PyCompletedPreview> {
        self.inner
            .drain_completed()
            .into_iter()
            .map(PyCompletedPreview::from)
            .collect()
    }

    fn shutdown(&self) {
        self.inner.shutdown();
    }
}

#[pyfunction]
fn load_image_rgba(py: Python<'_>, path: String) -> PyResult<PyRawImage> {
    match load_and_orient(Path::new(&path)) {
        Ok(loaded) => {
            let py_bytes = PyBytes::new(py, &loaded.rgba).unbind();
            Ok(PyRawImage {
                width: loaded.width,
                height: loaded.height,
                data: py_bytes,
            })
        }
        Err(e) => Err(pyo3::exceptions::PyIOError::new_err(format!(
            "Failed to load image '{path}': {e}"
        ))),
    }
}

#[pyfunction]
fn resize_image_rgba(
    py: Python<'_>,
    rgba: &[u8],
    width: u32,
    height: u32,
    viewport_width: u32,
    viewport_height: u32,
    stage: &str,
) -> PyResult<PyRawImage> {
    let p_stage = if stage == "fast" {
        PreviewStage::Fast
    } else {
        PreviewStage::Full
    };

    let source = LoadedImage {
        width,
        height,
        rgba: rgba.to_vec(),
    };

    match render_fit(&source, viewport_width, viewport_height, p_stage) {
        Ok(rendered) => {
            let py_bytes = PyBytes::new(py, &rendered.rgba).unbind();
            Ok(PyRawImage {
                width: rendered.width,
                height: rendered.height,
                data: py_bytes,
            })
        }
        Err(e) => Err(pyo3::exceptions::PyValueError::new_err(e)),
    }
}

#[pyfunction]
fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

#[pymodule]
fn keep_or_nah_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<RustPreviewPipeline>()?;
    m.add_class::<PyPreviewLookup>()?;
    m.add_class::<PyRawImage>()?;
    m.add_class::<PyCompletedPreview>()?;
    m.add_function(wrap_pyfunction!(load_image_rgba, m)?)?;
    m.add_function(wrap_pyfunction!(resize_image_rgba, m)?)?;
    m.add_function(wrap_pyfunction!(version, m)?)?;
    Ok(())
}
