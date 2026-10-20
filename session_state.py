from __future__ import annotations

from pathlib import Path

from photo_groups import PhotoGroup, build_photo_groups, discover_extensions
from photo_metadata import pillow_previewable_extensions
from photo_triage import (
    EMPTY_EXTENSION_SELECTION_MESSAGE,
    ActionMode,
    PhotoSessionError,
)


class SessionState:
    """Manages the in-memory photo queue, active index, and extension filters."""

    def __init__(
        self,
        source_dir: str | Path | None = None,
        keep_dir: str | Path | None = None,
        nah_dir: str | Path | None = None,
        action_mode: ActionMode = "move",
        *,
        previewable_extensions: frozenset[str] | None = None,
        pending_groups: list[PhotoGroup] | None = None,
        available_extensions: tuple[str, ...] = (),
        enabled_extensions: set[str] | None = None,
        active_index: int = 0,
        completed_stems: set[str] | None = None,
        total_loaded: int = 0,
    ) -> None:
        self.source_dir = Path(source_dir).expanduser() if source_dir else None
        self.keep_dir = Path(keep_dir).expanduser() if keep_dir else None
        self.nah_dir = Path(nah_dir).expanduser() if nah_dir else None
        self.action_mode: ActionMode = action_mode
        self.previewable_extensions = (
            previewable_extensions
            if previewable_extensions is not None
            else pillow_previewable_extensions()
        )
        self.pending_groups: list[PhotoGroup] = (
            list(pending_groups) if pending_groups is not None else []
        )
        self.completed_stems: set[str] = (
            set(completed_stems) if completed_stems is not None else set()
        )
        self.available_extensions: tuple[str, ...] = tuple(available_extensions)
        self.enabled_extensions: set[str] = (
            set(enabled_extensions) if enabled_extensions is not None else set(available_extensions)
        )
        self.queue: list[PhotoGroup] = self._project_pending_groups()
        self.active_index: int = active_index
        self.total_loaded: int = total_loaded
        self._extensions_source: Path | None = None

    @staticmethod
    def _as_group(item: PhotoGroup | Path) -> PhotoGroup:
        if isinstance(item, PhotoGroup):
            return item
        return PhotoGroup(item.stem, (item,), item)

    @property
    def active_group(self) -> PhotoGroup | None:
        if not self.queue:
            return None
        return self._as_group(self.queue[self.active_index])

    @property
    def active_photo(self) -> Path | None:
        group = self.active_group
        return group.representative if group is not None else None

    @property
    def preview_paths(self) -> tuple[Path, ...]:
        """Representatives suitable for preview and thumbnail infrastructure."""
        return tuple(self._as_group(item).representative for item in self.queue)

    @property
    def remaining_count(self) -> int:
        return len(self.pending_groups)

    @property
    def pending_count(self) -> int:
        return len(self.pending_groups)

    @property
    def visible_count(self) -> int:
        return len(self.queue)

    @property
    def current_position(self) -> int:
        if not self.queue:
            return 0
        return self.active_index + 1

    def set_source_dir(self, path: str | Path | None) -> None:
        self.source_dir = Path(path).expanduser() if path else None

    def set_keep_dir(self, path: str | Path | None) -> None:
        self.keep_dir = Path(path).expanduser() if path else None

    def set_nah_dir(self, path: str | Path | None) -> None:
        self.nah_dir = Path(path).expanduser() if path else None

    def set_action_mode(self, mode: str) -> None:
        if mode not in {"move", "copy"}:
            raise PhotoSessionError(f"Unsupported action mode: {mode}")
        self.action_mode = mode

    def reset_queue(self) -> None:
        self.queue = []
        self.pending_groups = []
        self.completed_stems = set()
        self.active_index = 0
        self.total_loaded = 0

    def load_queue(self) -> int:
        source_dir = self._validated_source_dir()
        source_identity = source_dir.resolve()
        available = discover_extensions(source_dir)
        if self._extensions_source != source_identity:
            self.enabled_extensions = set(available)
        else:
            self.enabled_extensions.intersection_update(available)

        self.available_extensions = available
        self._extensions_source = source_identity
        self.pending_groups = build_photo_groups(
            source_dir,
            set(available),
            self.previewable_extensions,
        )
        self.completed_stems = set()
        self.queue = self._project_pending_groups()
        self.active_index = 0
        self.total_loaded = len(self.pending_groups)
        return len(self.queue)

    def apply_extension_filter(self, enabled: set[str], processed_count: int = 0) -> int:
        source_dir = self._validated_source_dir()
        available = discover_extensions(source_dir)
        reconciled_groups = build_photo_groups(
            source_dir,
            set(available),
            self.previewable_extensions,
        )
        return self.apply_prepared_extension_filter(
            available,
            enabled,
            reconciled_groups,
            processed_count=processed_count,
        )

    def apply_prepared_extension_filter(
        self,
        available: tuple[str, ...],
        enabled: set[str],
        reconciled_groups: list[PhotoGroup] | tuple[PhotoGroup, ...] | None = None,
        processed_count: int = 0,
    ) -> int:
        previous_group = self.active_group
        previous_stem = previous_group.stem if previous_group is not None else None
        previous_position = next(
            (
                index
                for index, group in enumerate(self.pending_groups)
                if group.stem == previous_stem
            ),
            self.active_index,
        )
        effective_enabled = {
            extension.lower() for extension in enabled if extension.lower() in set(available)
        }
        if not effective_enabled:
            raise PhotoSessionError(EMPTY_EXTENSION_SELECTION_MESSAGE)
        if reconciled_groups is not None:
            self.pending_groups = [
                group for group in reconciled_groups if group.stem not in self.completed_stems
            ]
        self.available_extensions = available
        self.enabled_extensions = effective_enabled

        rebuilt = self._project_pending_groups()
        self.queue = rebuilt

        if not rebuilt:
            self.active_index = 0
        else:
            retained_index = next(
                (index for index, group in enumerate(rebuilt) if group.stem == previous_stem),
                None,
            )
            if retained_index is not None:
                self.active_index = retained_index
            else:
                all_positions = {
                    group.stem: index for index, group in enumerate(self.pending_groups)
                }
                self.active_index = min(
                    range(len(rebuilt)),
                    key=lambda index: (
                        abs(all_positions.get(rebuilt[index].stem, index) - previous_position),
                        all_positions.get(rebuilt[index].stem, index),
                    ),
                )

        self.total_loaded = processed_count + len(self.pending_groups)
        return len(self.queue)

    def _project_pending_groups(self) -> list[PhotoGroup]:
        projected: list[PhotoGroup] = []
        for group in self.pending_groups:
            eligible = tuple(
                member
                for member in group.members
                if member.suffix.lower() in self.enabled_extensions
            )
            if not eligible:
                continue
            projected.append(
                PhotoGroup(group.stem, group.members, self._representative_for(eligible))
            )
        return projected

    def _validated_source_dir(self) -> Path:
        if self.source_dir is None:
            raise PhotoSessionError("Choose a source folder before loading photos.")
        if not self.source_dir.is_dir():
            raise PhotoSessionError(f"Source folder does not exist: {self.source_dir}")
        return self.source_dir

    def set_active_index(self, index: int) -> Path | None:
        if not self.queue:
            self.active_index = 0
            return None

        self.active_index = min(max(index, 0), len(self.queue) - 1)
        return self.active_photo

    def move_active(self, offset: int) -> Path | None:
        return self.set_active_index(self.active_index + offset)

    def remove_queue_item(self, index: int) -> PhotoGroup:
        removed = self._as_group(self.queue.pop(index))
        self.pending_groups = [group for group in self.pending_groups if group.stem != removed.stem]
        if self.queue:
            self.active_index = min(index, len(self.queue) - 1)
        else:
            self.active_index = 0
        return removed

    def restore_queue_item(self, group: PhotoGroup) -> None:
        self.completed_stems.discard(group.stem)
        self.pending_groups.append(group)
        self.pending_groups.sort(key=lambda item: (item.stem.lower(), item.stem))
        self.queue = self._project_pending_groups()
        self.active_index = next(
            (index for index, item in enumerate(self.queue) if item.stem == group.stem),
            0,
        )

    def _representative_for(self, members: tuple[Path, ...]) -> Path:
        return min(
            members,
            key=lambda path: (
                path.suffix.lower() not in self.previewable_extensions,
                path.suffix.lower(),
                path.name.lower(),
                path.name,
            ),
        )
