from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sys


APP_SETTINGS_DIR_NAME = "keep-or-nah"
APP_SETTINGS_FILE_NAME = "settings.json"
DEFAULT_PREVIEW_CACHE_BUDGET_MB = 256
MIN_PREVIEW_CACHE_BUDGET_MB = 64
MAX_PREVIEW_CACHE_BUDGET_MB = 4096


def resolve_settings_path() -> Path:
    if sys.platform == "darwin":
        base_dir = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base_dir / APP_SETTINGS_DIR_NAME / APP_SETTINGS_FILE_NAME


@dataclass(frozen=True)
class AppSettings:
    progressive_preview: bool = True
    loading_indicator: bool = True
    preview_cache_budget_mb: int = DEFAULT_PREVIEW_CACHE_BUDGET_MB
    staged_decisions: bool = False

    def normalized(self) -> "AppSettings":
        budget = min(max(int(self.preview_cache_budget_mb), MIN_PREVIEW_CACHE_BUDGET_MB), MAX_PREVIEW_CACHE_BUDGET_MB)
        return AppSettings(
            progressive_preview=bool(self.progressive_preview),
            loading_indicator=bool(self.loading_indicator),
            preview_cache_budget_mb=budget,
            staged_decisions=bool(self.staged_decisions),
        )

    def save(self) -> None:
        payload = asdict(self.normalized())
        path = resolve_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    @classmethod
    def load(cls) -> "AppSettings":
        path = resolve_settings_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return cls()

        try:
            settings = cls(
                progressive_preview=bool(data.get("progressive_preview", True)),
                loading_indicator=bool(data.get("loading_indicator", True)),
                preview_cache_budget_mb=int(data.get("preview_cache_budget_mb", DEFAULT_PREVIEW_CACHE_BUDGET_MB)),
                staged_decisions=bool(data.get("staged_decisions", False)),
            )
        except (TypeError, ValueError):
            return cls()
        return settings.normalized()
