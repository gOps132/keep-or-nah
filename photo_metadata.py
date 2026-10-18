from __future__ import annotations

import os
from pathlib import Path
from PIL import Image

SUPPORTED_IMAGE_EXTENSIONS: set[str] = {
    ".bmp",
    ".gif",
    ".heic",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}


def pillow_previewable_extensions() -> frozenset[str]:
    """Return desired image suffixes backed by a loaded Pillow decoder."""
    Image.init()
    open_formats = set(Image.OPEN)
    return frozenset(
        extension.lower()
        for extension, format_name in Image.registered_extensions().items()
        if extension.lower() in SUPPORTED_IMAGE_EXTENSIONS
        and format_name in open_formats
    )


def extract_photo_metadata(path: Path) -> dict[str, object]:
    """Extract basic dimensions, format, and timestamp from photo path."""
    stat = path.stat()
    metadata: dict[str, object] = {
        "size_bytes": stat.st_size,
        "mtime": stat.st_mtime,
    }
    try:
        with Image.open(path) as img:
            metadata["width"] = img.width
            metadata["height"] = img.height
            metadata["format"] = img.format
    except Exception:
        pass
    return metadata
