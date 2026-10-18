from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import keep_or_nah_core


@dataclass(frozen=True)
class PhotoBurstInfo:
    path: Path
    timestamp: float
    image_hash: int
    sharpness: float


@dataclass(frozen=True)
class BurstCluster:
    photos: tuple[PhotoBurstInfo, ...]
    best_shot: Path
    is_burst: bool


class BurstClusterer:
    """Clusters photos taken in bursts and identifies the sharpest 'Best Shot' in each cluster."""

    def __init__(
        self,
        time_threshold_seconds: float = 2.5,
        hash_distance_threshold: int = 10,
    ) -> None:
        self.time_threshold_seconds = time_threshold_seconds
        self.hash_distance_threshold = hash_distance_threshold

    @staticmethod
    def hamming_distance(h1: int, h2: int) -> int:
        return (h1 ^ h2).bit_count()

    def analyze_photo(
        self,
        path: Path,
        timestamp: float,
        rgba: bytes,
        width: int,
        height: int,
    ) -> PhotoBurstInfo:
        sharpness = keep_or_nah_core.compute_sharpness(rgba, width, height)
        image_hash = keep_or_nah_core.compute_image_hash(rgba, width, height)
        return PhotoBurstInfo(
            path=path,
            timestamp=timestamp,
            image_hash=image_hash,
            sharpness=sharpness,
        )

    def cluster(self, photos: list[PhotoBurstInfo] | tuple[PhotoBurstInfo, ...]) -> list[BurstCluster]:
        if not photos:
            return []

        sorted_photos = sorted(photos, key=lambda p: p.timestamp)
        clusters: list[list[PhotoBurstInfo]] = []
        current_cluster: list[PhotoBurstInfo] = [sorted_photos[0]]

        for photo in sorted_photos[1:]:
            prev_photo = current_cluster[-1]
            time_diff = abs(photo.timestamp - prev_photo.timestamp)
            hash_dist = self.hamming_distance(photo.image_hash, prev_photo.image_hash)

            if time_diff <= self.time_threshold_seconds and hash_dist <= self.hash_distance_threshold:
                current_cluster.append(photo)
            else:
                clusters.append(current_cluster)
                current_cluster = [photo]

        if current_cluster:
            clusters.append(current_cluster)

        result: list[BurstCluster] = []
        for group in clusters:
            best_photo = max(group, key=lambda p: p.sharpness)
            result.append(
                BurstCluster(
                    photos=tuple(group),
                    best_shot=best_photo.path,
                    is_burst=len(group) >= 2,
                )
            )

        return result
