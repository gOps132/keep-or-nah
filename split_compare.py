from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from burst_clustering import PhotoBurstInfo
from photo_groups import PhotoGroup
from photo_session import PhotoSession


@dataclass(frozen=True)
class CompareCandidate:
    group: PhotoGroup
    preview_path: Path
    is_best_shot: bool = False
    sharpness: float | None = None

    @property
    def stem(self) -> str:
        return self.group.stem


class ComparePairSelector:
    """Selects and resolves pairs of candidate photos for side-by-side comparison and instant triage."""

    def resolve_pair(
        self,
        session: PhotoSession,
        burst_info_map: Mapping[Path, PhotoBurstInfo] | None = None,
        best_shots: set[Path] | None = None,
        candidate_offset: int = 1,
    ) -> tuple[CompareCandidate, CompareCandidate] | None:
        queue = session.queue
        if len(queue) < 2 or session.active_group is None:
            return None

        active_idx = session.active_index
        if active_idx < 0 or active_idx >= len(queue):
            active_idx = 0

        active_group = queue[active_idx]
        active_preview = active_group.representative
        active_info = burst_info_map.get(active_preview) if burst_info_map else None

        target_idx: int | None = None
        if active_info and burst_info_map:
            for idx, group in enumerate(queue):
                if idx == active_idx:
                    continue
                info = burst_info_map.get(group.representative)
                if info:
                    time_diff = abs(info.timestamp - active_info.timestamp)
                    hash_dist = (info.image_hash ^ active_info.image_hash).bit_count()
                    if time_diff <= 2.5 and hash_dist <= 10:
                        if best_shots and group.representative in best_shots:
                            target_idx = idx
                            break
                        if target_idx is None:
                            target_idx = idx

        if target_idx is None:
            target_idx = active_idx + candidate_offset
            if target_idx >= len(queue):
                target_idx = active_idx - 1 if active_idx > 0 else 1
            elif target_idx < 0:
                target_idx = active_idx + 1 if active_idx < len(queue) - 1 else 0

        if target_idx == active_idx:
            target_idx = (active_idx + 1) % len(queue)

        g1 = queue[active_idx]
        g2 = queue[target_idx]

        def _make_candidate(group: PhotoGroup) -> CompareCandidate:
            preview = group.representative
            is_best = False
            sharpness = None
            if best_shots is not None and preview in best_shots:
                is_best = True
            if burst_info_map is not None and preview in burst_info_map:
                sharpness = burst_info_map[preview].sharpness
            return CompareCandidate(
                group=group,
                preview_path=preview,
                is_best_shot=is_best,
                sharpness=sharpness,
            )

        return _make_candidate(g1), _make_candidate(g2)

    def pick(
        self,
        pair: tuple[CompareCandidate, CompareCandidate],
        choice: int,
        session: PhotoSession,
    ) -> tuple[PhotoGroup, PhotoGroup]:
        """Triage the selected keeper as Keep and the alternate as Nah."""
        c1, c2 = pair
        if choice == 1:
            keeper_candidate = c1
            rejected_candidate = c2
        else:
            keeper_candidate = c2
            rejected_candidate = c1

        # Locate and triage the keeper first
        keeper_idx = next(
            (i for i, g in enumerate(session.queue) if g.stem == keeper_candidate.stem),
            None,
        )
        if keeper_idx is not None:
            session.set_active_index(keeper_idx)
            session.decide("keep")

        # Then locate and triage the rejected photo
        rejected_idx = next(
            (i for i, g in enumerate(session.queue) if g.stem == rejected_candidate.stem),
            None,
        )
        if rejected_idx is not None:
            session.set_active_index(rejected_idx)
            session.decide("nah")

        return keeper_candidate.group, rejected_candidate.group


class SynchronizedViewTracker:
    """Maintains synchronized pan and zoom viewport parameters for dual 2-up canvases."""

    def __init__(self, zoom_factor: float = 1.0) -> None:
        self.zoom_factor = zoom_factor
        self.pan_x = 0.0
        self.pan_y = 0.0

    def set_zoom(self, factor: float) -> None:
        self.zoom_factor = factor

    def update_pan(self, x: float, y: float) -> None:
        self.pan_x = x
        self.pan_y = y
