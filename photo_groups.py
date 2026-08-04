"""Group same-stem source files into a single photo queue item."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PhotoGroup:
    """All direct-child files sharing one exact filename stem."""

    stem: str
    members: tuple[Path, ...]
    representative: Path


def discover_extensions(source_dir: Path) -> tuple[str, ...]:
    """Return normalized extensions found among direct-child regular files."""
    return tuple(
        sorted(
            {
                path.suffix.lower()
                for path in source_dir.iterdir()
                if _is_direct_regular_file(path) and path.suffix
            }
        )
    )


def build_photo_groups(
    source_dir: Path, enabled: set[str], previewable: set[str]
) -> list[PhotoGroup]:
    """Build one deterministic queue item for every eligible exact stem."""
    normalized_enabled = {extension.lower() for extension in enabled}
    normalized_previewable = {extension.lower() for extension in previewable}
    buckets: dict[str, list[Path]] = {}

    for path in source_dir.iterdir():
        if _is_direct_regular_file(path):
            buckets.setdefault(path.stem, []).append(path)

    groups: list[PhotoGroup] = []
    for stem, paths in sorted(buckets.items(), key=lambda item: (item[0].lower(), item[0])):
        members = tuple(sorted(paths, key=_filename_key))
        eligible = [path for path in members if path.suffix.lower() in normalized_enabled]
        if not eligible:
            continue
        representative = min(
            eligible,
            key=lambda path: (
                path.suffix.lower() not in normalized_previewable,
                path.suffix.lower(),
                *_filename_key(path),
            ),
        )
        groups.append(PhotoGroup(stem, members, representative))
    return groups


def _filename_key(path: Path) -> tuple[str, str]:
    return path.name.lower(), path.name


def _is_direct_regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()
