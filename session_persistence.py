from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Callable

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
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        return data if isinstance(data, dict) else None

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
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


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
            if session.remaining_count == 0:
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
