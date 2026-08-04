from __future__ import annotations

from pathlib import Path
from typing import Protocol

from PIL import Image, ImageOps

from photo_session import SUPPORTED_IMAGE_EXTENSIONS


class PreviewStrategy(Protocol):
    extensions: frozenset[str]

    def load(self, path: Path) -> Image.Image | None: ...


class PillowPreviewStrategy:
    extensions = frozenset(SUPPORTED_IMAGE_EXTENSIONS)

    def load(self, path: Path) -> Image.Image:
        with Image.open(path) as image:
            return ImageOps.exif_transpose(image).convert("RGBA")


class UnavailablePreviewStrategy:
    extensions = frozenset()

    def load(self, path: Path) -> None:
        return None


class PreviewStrategyRegistry:
    def __init__(self, strategies: list[PreviewStrategy]) -> None:
        self.strategies = tuple(strategies)
        self.unavailable_strategy = UnavailablePreviewStrategy()

    def supports_extension(self, extension: str) -> bool:
        normalized_extension = extension.lower()
        return any(normalized_extension in strategy.extensions for strategy in self.strategies)

    def for_path(self, path: Path) -> PreviewStrategy:
        extension = path.suffix.lower()
        return next(
            (strategy for strategy in self.strategies if extension in strategy.extensions),
            self.unavailable_strategy,
        )


DEFAULT_PREVIEW_STRATEGY_REGISTRY = PreviewStrategyRegistry([PillowPreviewStrategy()])
