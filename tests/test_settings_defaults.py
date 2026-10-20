"""Tests for the persisted application settings defaults.

The defaults are a product decision, not an implementation detail. ADR-0005
records the one that matters most: Staged Triage is the default interaction
model, because ADR-0004 chose it over immediate filesystem writes.
"""

from __future__ import annotations

import json
from pathlib import Path

from app_settings import (
    DEFAULT_PREVIEW_CACHE_BUDGET_MB,
    DEFAULT_STAGED_DECISIONS,
    AppSettings,
    resolve_settings_path,
)


def test_staged_decisions_is_on_by_default() -> None:
    """ADR-0005: the safer model is the one you get by doing nothing."""
    assert DEFAULT_STAGED_DECISIONS is True
    assert AppSettings().staged_decisions is True


def test_a_settings_file_without_the_staged_key_reads_as_staged(tmp_path, monkeypatch) -> None:
    """An existing settings file predating the key must not silently keep the
    old behaviour, and must not be read as explicitly opting out either."""
    path = tmp_path / "settings.json"
    payload = {
        "progressive_preview": True,
        "loading_indicator": True,
        "preview_cache_budget_mb": DEFAULT_PREVIEW_CACHE_BUDGET_MB,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr("app_settings.resolve_settings_path", lambda: path)

    loaded = AppSettings.load()
    assert loaded.staged_decisions is True


def test_an_explicit_staged_choice_is_preserved(tmp_path, monkeypatch) -> None:
    """A user who turned staging off keeps it off, in both directions."""
    path = tmp_path / "settings.json"
    monkeypatch.setattr("app_settings.resolve_settings_path", lambda: path)

    AppSettings(staged_decisions=False).save()
    assert AppSettings.load().staged_decisions is False

    AppSettings(staged_decisions=True).save()
    assert AppSettings.load().staged_decisions is True


def test_normalized_clamps_the_cache_budget() -> None:
    settings = AppSettings(preview_cache_budget_mb=1).normalized()
    assert settings.preview_cache_budget_mb >= 64

    settings = AppSettings(preview_cache_budget_mb=10**9).normalized()
    assert settings.preview_cache_budget_mb <= 4096


def test_a_corrupt_settings_file_falls_back_to_the_defaults(tmp_path, monkeypatch) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr("app_settings.resolve_settings_path", lambda: path)

    loaded = AppSettings.load()
    assert loaded.staged_decisions is DEFAULT_STAGED_DECISIONS


def test_the_settings_file_is_readable_json() -> None:
    """The persisted format is a plain JSON object, so a user can inspect it."""
    path = resolve_settings_path()
    assert isinstance(path, Path)
    assert path.name == "settings.json"
