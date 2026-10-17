from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import logging
from pathlib import Path
from queue import Empty, PriorityQueue, Queue
import threading
from typing import Literal, Sequence

from PIL import Image

try:
    import keep_or_nah_core
except ImportError as err:
    raise RuntimeError(
        "keep_or_nah_core native Rust extension is required but not installed or compiled. "
        "Please compile it by running: uv run maturin develop"
    ) from err

from preview_strategies import DEFAULT_PREVIEW_STRATEGY_REGISTRY, PreviewStrategyRegistry, UnavailablePreviewStrategy


logger = logging.getLogger(__name__)

PreviewStage = Literal["fast", "full"]
TaskKind = Literal["active_fast", "active_full", "prefetch_full", "shutdown"]
PreviewKey = tuple[Path, int, int]
RenderKey = tuple[Path, int, int, PreviewStage]


@dataclass(frozen=True)
class PreviewLookup:
    image: Image.Image | None
    stage: PreviewStage | None
    failed: bool = False
    unavailable: bool = False


@dataclass(frozen=True)
class CompletedPreview:
    path: Path
    request_id: int
    stage: Literal["source", "fast", "full", "unavailable", "error"]


@dataclass(order=True)
class PreviewTask:
    priority: tuple[int, int, int]
    sequence: int
    kind: TaskKind = field(compare=False)
    path: Path = field(compare=False)
    viewport: tuple[int, int] = field(compare=False)
    request_id: int = field(compare=False)
    generation: int = field(compare=False)


class PreviewPipeline:
    def __init__(
        self,
        window_radius: int = 2,
        cache_budget_mb: int = 256,
        max_workers: int = 1,
        preview_registry: PreviewStrategyRegistry | None = None,
    ) -> None:
        self.base_window_radius = max(window_radius, 0)
        self.window_radius = self.base_window_radius
        self.paths: tuple[Path, ...] = ()
        self.viewport = (0, 0)
        self.cache_budget_mb = max(int(cache_budget_mb), 64)
        self.preview_registry = preview_registry or DEFAULT_PREVIEW_STRATEGY_REGISTRY
        self._custom_registry = (
            preview_registry is not None
            and preview_registry is not DEFAULT_PREVIEW_STRATEGY_REGISTRY
        )

        self._closed = False
        self._path_map: dict[str, Path] = {}

        if not self._custom_registry:
            self._rust: keep_or_nah_core.RustPreviewPipeline | None = (
                keep_or_nah_core.RustPreviewPipeline(
                    window_radius=self.base_window_radius,
                    cache_budget_mb=self.cache_budget_mb,
                    max_workers=max_workers,
                )
            )
            self._python_pipeline: _PythonPreviewEngine | None = None
        else:
            self._rust = None
            self._python_pipeline = _PythonPreviewEngine(
                window_radius=self.base_window_radius,
                cache_budget_mb=self.cache_budget_mb,
                max_workers=max_workers,
                preview_registry=self.preview_registry,
            )

    @property
    def source_cache(self):
        if self._python_pipeline is not None:
            return self._python_pipeline.source_cache
        return {}

    @property
    def render_cache(self):
        if self._python_pipeline is not None:
            return self._python_pipeline.render_cache
        return {}

    @property
    def _pending_keys(self):
        if self._python_pipeline is not None:
            return self._python_pipeline._pending_keys
        return set()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._rust is not None:
            self._rust.shutdown()
        if self._python_pipeline is not None:
            self._python_pipeline.shutdown()

    def reset(self, paths: Sequence[Path]) -> None:
        self.paths = tuple(paths)
        self._path_map = {str(p): p for p in self.paths}
        if self._rust is not None:
            self._rust.reset([str(p) for p in self.paths])
        if self._python_pipeline is not None:
            self._python_pipeline.reset(paths)

    def set_viewport(self, width: int, height: int) -> None:
        self.viewport = (max(int(width), 0), max(int(height), 0))
        if self._rust is not None:
            self._rust.set_viewport(self.viewport[0], self.viewport[1])
        if self._python_pipeline is not None:
            self._python_pipeline.set_viewport(width, height)

    def configure_cache_budget(self, cache_budget_mb: int) -> None:
        budget_mb = max(int(cache_budget_mb), 64)
        self.cache_budget_mb = budget_mb
        self.window_radius = min(max(self.base_window_radius, budget_mb // 96), 12)
        if self._rust is not None:
            self._rust.configure_cache_budget(budget_mb)
        if self._python_pipeline is not None:
            self._python_pipeline.configure_cache_budget(budget_mb)

    def start_preview_request(
        self, path: Path, active_index: int, progressive_enabled: bool = True
    ) -> int:
        if self._rust is not None:
            return self._rust.start_preview_request(
                str(path), active_index, progressive_enabled
            )
        assert self._python_pipeline is not None
        return self._python_pipeline.start_preview_request(
            path, active_index, progressive_enabled
        )

    def get_best_preview(self, path: Path) -> PreviewLookup:
        if self._rust is not None:
            res = self._rust.get_best_preview(str(path))
            if res.data is not None:
                img = Image.frombytes("RGBA", (res.width, res.height), res.data)
                return PreviewLookup(
                    image=img, stage=res.stage, failed=False, unavailable=False
                )
            if res.unavailable:
                strategy = self.preview_registry.for_path(path)
                if not isinstance(strategy, UnavailablePreviewStrategy):
                    try:
                        source = strategy.load(path)
                        if source is not None:
                            img = self._render_fit_preview(
                                source, self.viewport, stage="full"
                            )
                            return PreviewLookup(
                                image=img,
                                stage="full",
                                failed=False,
                                unavailable=False,
                            )
                    except Exception:
                        pass
            return PreviewLookup(
                image=None,
                stage=None,
                failed=res.failed,
                unavailable=res.unavailable,
            )
        assert self._python_pipeline is not None
        return self._python_pipeline.get_best_preview(path)

    def get_cached_source_copy(self, path: Path) -> Image.Image | None:
        if self._rust is not None:
            raw = self._rust.get_cached_source(str(path))
            if raw is not None:
                return Image.frombytes("RGBA", (raw.width, raw.height), raw.data)
            return None
        assert self._python_pipeline is not None
        return self._python_pipeline.get_cached_source_copy(path)

    def has_source(self, path: Path) -> bool:
        if self._rust is not None:
            return self._rust.has_source(str(path))
        assert self._python_pipeline is not None
        return self._python_pipeline.has_source(path)

    def drain_completed(self) -> list[CompletedPreview]:
        if self._rust is not None:
            raw_events = self._rust.drain_completed()
            return [
                CompletedPreview(
                    path=self._path_map.get(event.path, Path(event.path)),
                    request_id=event.request_id,
                    stage=event.stage,
                )
                for event in raw_events
            ]
        assert self._python_pipeline is not None
        return self._python_pipeline.drain_completed()

    @staticmethod
    def _render_fit_preview(
        source: Image.Image, viewport: tuple[int, int], stage: PreviewStage
    ) -> Image.Image:
        viewport_width, viewport_height = viewport
        if viewport_width < 8 or viewport_height < 8:
            return source.copy()

        fit_scale = min(viewport_width / source.width, viewport_height / source.height)
        display_width = max(int(round(source.width * fit_scale)), 1)
        display_height = max(int(round(source.height * fit_scale)), 1)
        resampling = (
            Image.Resampling.BILINEAR if stage == "fast" else Image.Resampling.LANCZOS
        )
        return source.resize((display_width, display_height), resampling)


class _PythonPreviewEngine:
    def __init__(
        self,
        window_radius: int = 2,
        cache_budget_mb: int = 256,
        max_workers: int = 1,
        preview_registry: PreviewStrategyRegistry | None = None,
    ) -> None:
        self.base_window_radius = max(window_radius, 0)
        self.window_radius = self.base_window_radius
        self.paths: tuple[Path, ...] = ()
        self.viewport = (0, 0)

        self.source_cache: OrderedDict[Path, Image.Image] = OrderedDict()
        self.source_cache_bytes = 0
        self.render_cache: OrderedDict[RenderKey, Image.Image] = OrderedDict()
        self.render_cache_bytes = 0
        self.failed_preview_keys: set[PreviewKey] = set()
        self.unavailable_preview_keys: set[PreviewKey] = set()
        self.preview_registry = preview_registry or DEFAULT_PREVIEW_STRATEGY_REGISTRY

        self.cache_budget_mb = 0
        self.source_cache_limit_bytes = 0
        self.render_cache_limit_bytes = 0

        self._sequence = 0
        self._generation = 0
        self._pending_keys: set[tuple[int, TaskKind, Path, tuple[int, int]]] = set()
        self._tasks: PriorityQueue[PreviewTask] = PriorityQueue()
        self._completed: Queue[CompletedPreview] = Queue()
        self._lock = threading.Lock()
        self._closed = False
        self._workers = [
            threading.Thread(
                target=self._worker_loop,
                name=f"python-preview-pipeline-{index}",
                daemon=True,
            )
            for index in range(max(max_workers, 1))
        ]
        self.configure_cache_budget(cache_budget_mb)
        for worker in self._workers:
            worker.start()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        for index in range(len(self._workers)):
            self._tasks.put(
                PreviewTask(
                    priority=(99, index, 0),
                    sequence=self._next_sequence(),
                    kind="shutdown",
                    path=Path("."),
                    viewport=(0, 0),
                    request_id=0,
                    generation=self._generation,
                )
            )
        for worker in self._workers:
            worker.join(timeout=0.2)

    def reset(self, paths: Sequence[Path]) -> None:
        with self._lock:
            self._generation += 1
            self.paths = tuple(paths)
            allowed = set(self.paths)
            self._prune_source_cache_locked(allowed)
            self._prune_render_cache_locked(allowed)
            self.failed_preview_keys = {
                key for key in self.failed_preview_keys if key[0] in allowed
            }
            self.unavailable_preview_keys = {
                key for key in self.unavailable_preview_keys if key[0] in allowed
            }

    def set_viewport(self, width: int, height: int) -> None:
        self.viewport = (max(int(width), 0), max(int(height), 0))

    def configure_cache_budget(self, cache_budget_mb: int) -> None:
        budget_mb = max(int(cache_budget_mb), 64)
        self.cache_budget_mb = budget_mb
        total_bytes = budget_mb * 1024 * 1024
        self.source_cache_limit_bytes = int(total_bytes * 0.62)
        self.render_cache_limit_bytes = max(
            total_bytes - self.source_cache_limit_bytes, 8 * 1024 * 1024
        )
        self.window_radius = min(max(self.base_window_radius, budget_mb // 96), 12)
        with self._lock:
            self._trim_source_cache_locked()
            self._trim_render_cache_locked()

    def start_preview_request(
        self, path: Path, active_index: int, progressive_enabled: bool = True
    ) -> int:
        viewport = self.viewport
        request_id = self._next_sequence()
        with self._lock:
            generation = self._generation
        if viewport[0] < 8 or viewport[1] < 8:
            return request_id

        if progressive_enabled and not self._has_render(path, viewport, "fast"):
            self._enqueue_task(
                "active_fast",
                path,
                viewport,
                request_id,
                generation,
                priority=(0, 0, request_id),
            )
        if not self._has_render(path, viewport, "full"):
            self._enqueue_task(
                "active_full",
                path,
                viewport,
                request_id,
                generation,
                priority=(1, 0, request_id),
            )
        self._enqueue_prefetch(active_index, viewport, request_id, generation)
        return request_id

    def get_best_preview(self, path: Path) -> PreviewLookup:
        key = self._preview_key(path, self.viewport)
        if key is None:
            return PreviewLookup(image=None, stage=None)

        with self._lock:
            full_key = (*key, "full")
            full_image = self.render_cache.get(full_key)
            if full_image is not None:
                self.render_cache.move_to_end(full_key)
                return PreviewLookup(image=full_image, stage="full")

            fast_key = (*key, "fast")
            fast_image = self.render_cache.get(fast_key)
            if fast_image is not None:
                self.render_cache.move_to_end(fast_key)
                return PreviewLookup(image=fast_image, stage="fast")

            return PreviewLookup(
                image=None,
                stage=None,
                failed=key in self.failed_preview_keys,
                unavailable=key in self.unavailable_preview_keys,
            )

    def get_cached_source_copy(self, path: Path) -> Image.Image | None:
        with self._lock:
            source = self.source_cache.get(path)
            if source is None:
                return None
            self.source_cache.move_to_end(path)
            return source.copy()

    def has_source(self, path: Path) -> bool:
        with self._lock:
            return path in self.source_cache

    def drain_completed(self) -> list[CompletedPreview]:
        completed: list[CompletedPreview] = []
        while True:
            try:
                completed.append(self._completed.get_nowait())
            except Empty:
                return completed

    def _enqueue_prefetch(
        self,
        active_index: int,
        viewport: tuple[int, int],
        request_id: int,
        generation: int,
    ) -> None:
        if not self.paths:
            return

        for distance in range(1, self.window_radius + 1):
            for index in (active_index - distance, active_index + distance):
                if index < 0 or index >= len(self.paths):
                    continue
                path = self.paths[index]
                if self._has_render(path, viewport, "full"):
                    continue
                self._enqueue_task(
                    "prefetch_full",
                    path,
                    viewport,
                    request_id,
                    generation,
                    priority=(2, distance, request_id),
                )

    def _enqueue_task(
        self,
        kind: TaskKind,
        path: Path,
        viewport: tuple[int, int],
        request_id: int,
        generation: int,
        priority: tuple[int, int, int],
    ) -> None:
        key = (generation, kind, path, viewport)
        with self._lock:
            if (
                key in self._pending_keys
                or self._closed
                or generation != self._generation
                or path not in self.paths
            ):
                return
            self._pending_keys.add(key)
        self._tasks.put(
            PreviewTask(
                priority=priority,
                sequence=self._next_sequence(),
                kind=kind,
                path=path,
                viewport=viewport,
                request_id=request_id,
                generation=generation,
            )
        )

    def _worker_loop(self) -> None:
        while True:
            task = self._tasks.get()
            if task.kind == "shutdown":
                return

            pending_key = (task.generation, task.kind, task.path, task.viewport)
            try:
                if self._task_is_current(task):
                    self._process_task(task)
            except Exception:
                logger.exception("Preview task failed for %s", task.path)
                self._mark_failed(task)
            finally:
                with self._lock:
                    self._pending_keys.discard(pending_key)

    def _process_task(self, task: PreviewTask) -> None:
        if task.kind == "prefetch_full" and self._has_render(
            task.path, task.viewport, "full"
        ):
            return
        if task.kind == "active_fast" and self._has_render(
            task.path, task.viewport, "fast"
        ):
            return
        if task.kind == "active_full" and self._has_render(
            task.path, task.viewport, "full"
        ):
            return

        source = self._get_or_load_source(task)
        if source is None:
            return

        if task.kind == "active_fast":
            preview = PreviewPipeline._render_fit_preview(
                source, task.viewport, stage="fast"
            )
            if self._store_render(task, "fast", preview):
                self._publish_completion(task, "fast")
            return

        preview = PreviewPipeline._render_fit_preview(
            source, task.viewport, stage="full"
        )
        if self._store_render(task, "full", preview):
            self._publish_completion(task, "full")

    def _get_or_load_source(
        self,
        task: PreviewTask,
    ) -> Image.Image | None:
        with self._lock:
            if not self._task_is_current_locked(task):
                return None
            cached = self.source_cache.get(task.path)
            if cached is not None:
                self.source_cache.move_to_end(task.path)
                return cached
            if (
                self._preview_key(task.path, task.viewport)
                in self.unavailable_preview_keys
            ):
                return None

        try:
            source = self._load_source(task.path)
        except OSError:
            self._mark_failed(task)
            return None
        if source is None:
            self._mark_unavailable(task)
            return None

        if not self._store_source(task, source):
            return None
        self._publish_completion(task, "source")
        return source

    def _store_source(self, task: PreviewTask, source: Image.Image) -> bool:
        source_bytes = self._estimate_bytes(source)
        with self._lock:
            if not self._task_is_current_locked(task):
                return False
            previous = self.source_cache.pop(task.path, None)
            if previous is not None:
                self.source_cache_bytes -= self._estimate_bytes(previous)
            self.source_cache[task.path] = source
            self.source_cache_bytes += source_bytes
            self._trim_source_cache_locked()
            return True

    def _store_render(
        self,
        task: PreviewTask,
        stage: PreviewStage,
        preview: Image.Image,
    ) -> bool:
        key = (task.path, task.viewport[0], task.viewport[1], stage)
        preview_bytes = self._estimate_bytes(preview)
        with self._lock:
            if not self._task_is_current_locked(task):
                return False
            previous = self.render_cache.pop(key, None)
            if previous is not None:
                self.render_cache_bytes -= self._estimate_bytes(previous)
            self.render_cache[key] = preview
            self.render_cache_bytes += preview_bytes
            self.failed_preview_keys.discard(
                (task.path, task.viewport[0], task.viewport[1])
            )
            self.unavailable_preview_keys.discard(
                (task.path, task.viewport[0], task.viewport[1])
            )
            self._trim_render_cache_locked()
            return True

    def _mark_failed(self, task: PreviewTask) -> None:
        key = self._preview_key(task.path, task.viewport)
        with self._lock:
            if not self._task_is_current_locked(task):
                return
            if key is not None:
                self.failed_preview_keys.add(key)
                self.unavailable_preview_keys.discard(key)
            self._completed.put(
                CompletedPreview(
                    path=task.path, request_id=task.request_id, stage="error"
                )
            )

    def _mark_unavailable(self, task: PreviewTask) -> None:
        key = self._preview_key(task.path, task.viewport)
        with self._lock:
            if not self._task_is_current_locked(task):
                return
            if key is not None:
                self.unavailable_preview_keys.add(key)
                self.failed_preview_keys.discard(key)
            self._completed.put(
                CompletedPreview(
                    path=task.path, request_id=task.request_id, stage="unavailable"
                )
            )

    def _publish_completion(self, task: PreviewTask, stage) -> None:
        with self._lock:
            if not self._task_is_current_locked(task):
                return
            self._completed.put(
                CompletedPreview(
                    path=task.path, request_id=task.request_id, stage=stage
                )
            )

    def _task_is_current(self, task: PreviewTask) -> bool:
        with self._lock:
            return self._task_is_current_locked(task)

    def _task_is_current_locked(self, task: PreviewTask) -> bool:
        return task.generation == self._generation and task.path in self.paths

    def _has_render(
        self, path: Path, viewport: tuple[int, int], stage: PreviewStage
    ) -> bool:
        key = self._preview_key(path, viewport)
        if key is None:
            return False
        with self._lock:
            return (*key, stage) in self.render_cache

    def _prune_source_cache_locked(self, allowed: set[Path]) -> None:
        for path in list(self.source_cache.keys()):
            if path in allowed:
                continue
            image = self.source_cache.pop(path)
            self.source_cache_bytes -= self._estimate_bytes(image)
        self._trim_source_cache_locked()

    def _prune_render_cache_locked(self, allowed: set[Path]) -> None:
        for key in list(self.render_cache.keys()):
            if key[0] in allowed:
                continue
            image = self.render_cache.pop(key)
            self.render_cache_bytes -= self._estimate_bytes(image)
        self._trim_render_cache_locked()

    def _trim_source_cache_locked(self) -> None:
        while (
            self.source_cache
            and self.source_cache_bytes > self.source_cache_limit_bytes
        ):
            _path, image = self.source_cache.popitem(last=False)
            self.source_cache_bytes -= self._estimate_bytes(image)

    def _trim_render_cache_locked(self) -> None:
        while (
            self.render_cache
            and self.render_cache_bytes > self.render_cache_limit_bytes
        ):
            _key, image = self.render_cache.popitem(last=False)
            self.render_cache_bytes -= self._estimate_bytes(image)

    def _preview_key(
        self, path: Path, viewport: tuple[int, int]
    ) -> PreviewKey | None:
        viewport_width, viewport_height = viewport
        if viewport_width < 8 or viewport_height < 8:
            return None
        return (path, viewport_width, viewport_height)

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    @staticmethod
    def _estimate_bytes(image: Image.Image) -> int:
        channels = len(image.getbands()) or 4
        return image.width * image.height * channels

    def _load_source(self, path: Path) -> Image.Image | None:
        return self.preview_registry.for_path(path).load(path)
