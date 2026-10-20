from __future__ import annotations

import contextlib
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

from app_settings import resolve_settings_path
from photo_session import PhotoSession

SESSION_FILE_NAME = "session.json"


def resolve_session_path() -> Path:
    return resolve_settings_path().with_name(SESSION_FILE_NAME)


class SessionPersistence:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or resolve_session_path()

    def load(self) -> dict[str, object] | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            self.clear()
            return None
        except OSError:
            return None
        if not isinstance(data, dict):
            self.clear()
            return None
        return data

    def save(self, payload: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as file:
                json.dump(payload, file, indent=2, sort_keys=True)
                file.flush()
                os.fsync(file.fileno())
            temporary.replace(self.path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()

    def clear(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()


class SessionLifecycle:
    """Shared persistence policy used by both desktop frontends."""

    def __init__(
        self,
        persistence: SessionPersistence | None = None,
        error_handler: Callable[[str], None] | None = None,
    ) -> None:
        self.persistence = persistence or SessionPersistence()
        self.error_handler = error_handler or (lambda message: print(message, file=sys.stderr))
        self._persistence_error_reported = False

    def restore(self) -> PhotoSession | None:
        try:
            payload = self.persistence.load()
        except OSError as error:
            self._report_error(error)
            return None
        if payload is None:
            return None
        session = PhotoSession.from_snapshot(payload)
        if session is None:
            self.clear()
        return session

    def persist(self, session: PhotoSession) -> bool:
        try:
            pending_count = getattr(session, "pending_count", None)
            if pending_count is None:
                pending_count = session.remaining_count
            if pending_count == 0:
                self.persistence.clear()
            else:
                self.persistence.save(session.to_snapshot())
        except OSError as error:
            self._report_error(error)
            return False
        return True

    def clear(self) -> bool:
        try:
            self.persistence.clear()
        except OSError as error:
            self._report_error(error)
            return False
        return True

    def _report_error(self, error: OSError) -> None:
        if self._persistence_error_reported:
            return
        self._persistence_error_reported = True
        self.error_handler(f"Keep or Nah could not update session recovery data: {error}")
