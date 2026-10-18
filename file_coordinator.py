from __future__ import annotations

import errno
import os
from pathlib import Path
import sys
from typing import Callable

from keep_or_nah_core import stage_regular_file
from photo_groups import PhotoGroup
from photo_triage import (
    ActionMode,
    ActionRecord,
    FileOperation,
    PhotoSessionError,
)
import file_identity


def _get_stage_fn() -> Callable[..., object]:
    mod = sys.modules.get("photo_session")
    if mod and hasattr(mod, "stage_regular_file"):
        return getattr(mod, "stage_regular_file")
    return stage_regular_file


def _get_os() -> object:
    mod = sys.modules.get("photo_session")
    if mod and hasattr(mod, "os"):
        return getattr(mod, "os")
    return os


class FileCoordinator:
    """Coordinates atomic and verified disk file operations for photo groups."""

    @staticmethod
    def _path_occupied(path: Path) -> bool:
        return file_identity.path_occupied(path)

    @staticmethod
    def _validate_basename(name: str) -> None:
        file_identity.validate_basename(name)

    @staticmethod
    def _path_identity(path: Path) -> tuple[int, int]:
        return file_identity.path_identity(path)

    @staticmethod
    def _directory_identity(path: Path) -> tuple[int, int]:
        return file_identity.directory_identity(path)

    @classmethod
    def _require_directory_identity(cls, path: Path, expected_identity: tuple[int, int]) -> None:
        file_identity.require_directory_identity(path, expected_identity)

    @classmethod
    def _require_owned_path(cls, path: Path, expected_identity: tuple[int, int]) -> None:
        file_identity.require_owned_path(path, expected_identity)

    @classmethod
    def _remove_owned_path(cls, path: Path, expected_identity: tuple[int, int]) -> None:
        file_identity.remove_owned_path(path, expected_identity)

    @staticmethod
    def _validate_destination_parent(path: Path, destination_root: Path) -> None:
        file_identity.validate_destination_parent(path, destination_root)

    @classmethod
    def _validate_destination(cls, path: Path, destination_root: Path) -> None:
        file_identity.validate_destination(path, destination_root)

    @staticmethod
    def _is_direct_child(path: Path, root: Path) -> bool:
        return file_identity.is_direct_child(path, root)

    @staticmethod
    def _publish_hard_link(source: Path, destination: Path) -> None:
        os_mod = _get_os()
        if os_mod.link in os_mod.supports_follow_symlinks:
            os_mod.link(source, destination, follow_symlinks=False)
        else:
            os_mod.link(source, destination)

    @staticmethod
    def _is_windows_fallback() -> bool:
        return os.name == "nt"

    def _publish_staged(self, source: Path, destination: Path) -> bool:
        try:
            self._publish_hard_link(source, destination)
            return False
        except OSError as error:
            unsupported_errors = {
                errno.ENOSYS,
                errno.ENOTSUP,
                errno.EOPNOTSUPP,
                errno.EPERM,
                errno.EXDEV,
                errno.EINVAL,
            }
            if (
                not self._is_windows_fallback()
                or error.errno not in unsupported_errors
            ):
                raise
        if self._path_occupied(destination):
            raise FileExistsError(f"Destination became occupied: {destination}")
        os_mod = _get_os()
        os_mod.rename(source, destination)
        return True

    def _copy_path_exclusive(
        self,
        source: Path,
        destination: Path,
        destination_root: Path,
        *,
        expected_source_identity: tuple[int, int] | None = None,
        expected_destination_root_identity: tuple[int, int] | None = None,
    ) -> tuple[int, int]:
        if expected_destination_root_identity is None:
            expected_destination_root_identity = self._directory_identity(destination_root)
        self._require_directory_identity(destination_root, expected_destination_root_identity)
        self._validate_destination(destination, destination_root)
        if expected_source_identity is not None:
            self._require_owned_path(source, expected_source_identity)

        stage_fn = _get_stage_fn()
        staged = stage_fn(
            str(source),
            str(destination_root),
            expected_dev=expected_source_identity[0] if expected_source_identity is not None else None,
            expected_ino=expected_source_identity[1] if expected_source_identity is not None else None,
        )
        temporary_path = Path(staged.path)
        temporary_identity = (staged.dev, staged.ino)
        published_identity: tuple[int, int] | None = None
        temporary_consumed = False
        try:
            self._require_owned_path(temporary_path, temporary_identity)
            self._require_directory_identity(destination_root, expected_destination_root_identity)
            self._validate_destination(destination, destination_root)
            temporary_consumed = self._publish_staged(temporary_path, destination)
            published_identity = temporary_identity
            self._require_owned_path(destination, published_identity)
            self._require_directory_identity(destination_root, expected_destination_root_identity)
            self._validate_destination_parent(destination, destination_root)
        except Exception as primary_error:
            cleanup_errors: list[BaseException] = []
            if published_identity is not None:
                try:
                    self._remove_owned_path(destination, published_identity)
                except Exception as cleanup_error:
                    cleanup_errors.append(cleanup_error)
            if not temporary_consumed:
                try:
                    self._remove_owned_path(temporary_path, temporary_identity)
                except Exception as cleanup_error:
                    cleanup_errors.append(cleanup_error)
            if cleanup_errors:
                details = "; ".join(str(error) for error in cleanup_errors)
                raise OSError(
                    f"{primary_error}; staged destination cleanup failed: {details}"
                ) from primary_error
            raise
        else:
            if not temporary_consumed:
                self._remove_owned_path(temporary_path, temporary_identity)
            return published_identity

    def _move_path_exclusive(
        self,
        source: Path,
        destination: Path,
        destination_root: Path,
        *,
        expected_source_identity: tuple[int, int] | None = None,
        expected_destination_root_identity: tuple[int, int] | None = None,
    ) -> tuple[int, int]:
        if expected_source_identity is None:
            expected_source_identity = self._path_identity(source)
        self._require_owned_path(source, expected_source_identity)
        published_identity = self._copy_path_exclusive(
            source,
            destination,
            destination_root,
            expected_source_identity=expected_source_identity,
            expected_destination_root_identity=expected_destination_root_identity,
        )
        try:
            self._remove_owned_path(source, expected_source_identity)
        except Exception as primary_error:
            try:
                self._remove_owned_path(destination, published_identity)
            except Exception as cleanup_error:
                raise OSError(
                    f"{primary_error}; published destination cleanup failed: {cleanup_error}"
                ) from primary_error
            raise
        return published_identity

    def _group_destinations(self, group: PhotoGroup, destination_dir: Path) -> tuple[FileOperation, ...]:
        collision_number = 0
        while True:
            operations = tuple(
                FileOperation(
                    member,
                    destination_dir
                    / (
                        member.name
                        if collision_number == 0
                        else f"{member.stem} ({collision_number}){member.suffix}"
                    ),
                )
                for member in group.members
            )
            if not any(self._path_occupied(item.destination) for item in operations):
                return operations
            collision_number += 1

    def execute_group_operations(
        self,
        group: PhotoGroup,
        source_root: Path,
        destination_root: Path,
        action_mode: ActionMode,
    ) -> tuple[FileOperation, ...]:
        resolved_source_root = source_root.resolve(strict=True)
        resolved_destination_root = destination_root.resolve(strict=True)
        destination_root_identity = self._directory_identity(resolved_destination_root)
        source_root_identity = self._directory_identity(resolved_source_root)
        operations = self._group_destinations(group, resolved_destination_root)
        completed: list[FileOperation] = []
        try:
            for operation in operations:
                if action_mode == "move":
                    identity = self._move_path_exclusive(
                        operation.source,
                        operation.destination,
                        resolved_destination_root,
                        expected_destination_root_identity=destination_root_identity,
                    )
                else:
                    identity = self._copy_path_exclusive(
                        operation.source,
                        operation.destination,
                        resolved_destination_root,
                        expected_destination_root_identity=destination_root_identity,
                    )
                completed.append(FileOperation(operation.source, operation.destination, identity))
        except Exception as primary_error:
            rollback_errors: list[BaseException] = []
            for operation in reversed(completed):
                try:
                    if action_mode == "move":
                        self._move_path_exclusive(
                            operation.destination,
                            operation.source,
                            resolved_source_root,
                            expected_source_identity=operation.destination_identity,
                            expected_destination_root_identity=source_root_identity,
                        )
                    else:
                        self._remove_owned_path(operation.destination, operation.destination_identity)
                except Exception as rollback_error:
                    rollback_errors.append(rollback_error)
            message = f"Could not {action_mode} the photo group: {primary_error}"
            if rollback_errors:
                details = "; ".join(str(error) for error in rollback_errors)
                message += f". Rollback also failed: {details}"
            raise PhotoSessionError(
                message,
                primary_error=primary_error,
                rollback_errors=tuple(rollback_errors),
                completed_operations=tuple(completed),
            ) from primary_error
        return tuple(completed)

    @classmethod
    def recorded_destination_root(cls, record: ActionRecord) -> Path:
        if not record.files:
            raise PhotoSessionError(
                "The recorded action has no destination files, so it cannot be undone."
            )
        recorded_parent = record.files[0].destination.parent
        for operation in record.files:
            if operation.destination_identity is None:
                raise PhotoSessionError(
                    "A recorded action is missing its destination identity, so it cannot be undone."
                )
            if operation.destination.parent != recorded_parent:
                raise PhotoSessionError(
                    "All files in an action must share the same recorded destination folder."
                )
            try:
                cls._validate_basename(operation.destination.name)
            except OSError as error:
                raise PhotoSessionError(
                    f"A recorded undo destination is unsafe: {error}",
                    primary_error=error,
                ) from error
        try:
            destination_root = recorded_parent.resolve(strict=True)
            cls._directory_identity(destination_root)
            for operation in record.files:
                cls._validate_destination_parent(operation.destination, destination_root)
                recorded_destination = destination_root / operation.destination.name
                if (
                    cls._path_occupied(recorded_destination)
                    and cls._path_identity(recorded_destination) != operation.destination_identity
                ):
                    raise PhotoSessionError(
                        "A recorded destination identity no longer matches the action-owned file."
                    )
        except PhotoSessionError:
            raise
        except OSError as error:
            raise PhotoSessionError(
                f"Could not validate the recorded undo destination folder: {error}",
                primary_error=error,
            ) from error
        return destination_root

    def undo_move_record(
        self,
        record: ActionRecord,
        destination_root: Path,
        source_dir: Path | None,
        on_refresh: Callable[[ActionRecord, dict[FileOperation, tuple[int, int]]], None],
    ) -> None:
        if source_dir is None:
            raise PhotoSessionError(
                "The source folder is unavailable, so undo cannot restore files."
            )
        source_root = source_dir.resolve(strict=True)
        source_root_identity = self._directory_identity(source_root)
        destination_root_identity = self._directory_identity(destination_root)
        pending: list[tuple[FileOperation, tuple[int, int]]] = []
        for operation in reversed(record.files):
            recorded_destination = destination_root / operation.destination.name
            source_occupied = self._path_occupied(operation.source)
            destination_occupied = self._path_occupied(recorded_destination)
            if destination_occupied:
                self._require_owned_path(recorded_destination, operation.destination_identity)
            if destination_occupied and not source_occupied:
                pending.append((operation, self._path_identity(recorded_destination)))
            elif source_occupied and not destination_occupied:
                continue
            elif source_occupied:
                raise PhotoSessionError(
                    "An original group file path is already occupied, so undo cannot restore it."
                )
            else:
                raise PhotoSessionError(
                    "A moved group file is missing, so the last action cannot be undone."
                )

        completed: list[tuple[FileOperation, tuple[int, int]]] = []
        try:
            for operation, destination_identity in pending:
                restored_identity = self._move_path_exclusive(
                    destination_root / operation.destination.name,
                    operation.source,
                    source_root,
                    expected_source_identity=destination_identity,
                    expected_destination_root_identity=source_root_identity,
                )
                completed.append((operation, restored_identity))
        except Exception as primary_error:
            rollback_errors: list[BaseException] = []
            identity_updates: dict[FileOperation, tuple[int, int]] = {}
            for operation, restored_identity in reversed(completed):
                try:
                    identity_updates[operation] = self._move_path_exclusive(
                        operation.source,
                        destination_root / operation.destination.name,
                        destination_root,
                        expected_source_identity=restored_identity,
                        expected_destination_root_identity=destination_root_identity,
                    )
                except Exception as rollback_error:
                    rollback_errors.append(rollback_error)
            on_refresh(record, identity_updates)
            self._raise_undo_failure(
                "moved",
                primary_error,
                tuple(rollback_errors),
                [operation for operation, _identity in completed],
            )

    def undo_copy_record(
        self,
        record: ActionRecord,
        destination_root: Path,
        partial_copy_undo: set[FileOperation],
        on_refresh: Callable[[ActionRecord, dict[FileOperation, tuple[int, int]]], None],
    ) -> None:
        destination_root_identity = self._directory_identity(destination_root)
        pending: list[tuple[FileOperation, tuple[int, int]]] = []
        for operation in reversed(record.files):
            recorded_destination = destination_root / operation.destination.name
            if self._path_occupied(recorded_destination):
                self._require_owned_path(recorded_destination, operation.destination_identity)
                pending.append((operation, self._path_identity(recorded_destination)))
            elif operation not in partial_copy_undo:
                raise PhotoSessionError(
                    "A copied group file is missing, so the last action cannot be undone."
                )

        completed: list[FileOperation] = []
        try:
            for operation, destination_identity in pending:
                self._remove_owned_path(destination_root / operation.destination.name, destination_identity)
                completed.append(operation)
                partial_copy_undo.add(operation)
        except Exception as primary_error:
            rollback_errors: list[BaseException] = []
            identity_updates: dict[FileOperation, tuple[int, int]] = {}
            for operation in reversed(completed):
                try:
                    identity_updates[operation] = self._copy_path_exclusive(
                        operation.source,
                        destination_root / operation.destination.name,
                        destination_root,
                        expected_destination_root_identity=destination_root_identity,
                    )
                    partial_copy_undo.discard(operation)
                except Exception as rollback_error:
                    rollback_errors.append(rollback_error)
            on_refresh(record, identity_updates)
            self._raise_undo_failure("copied", primary_error, tuple(rollback_errors), completed)

    @staticmethod
    def _raise_undo_failure(
        operation_label: str,
        primary_error: BaseException,
        rollback_errors: tuple[BaseException, ...],
        completed: list[FileOperation],
    ) -> None:
        message = f"Could not undo the {operation_label} photo group: {primary_error}"
        if rollback_errors:
            details = "; ".join(str(error) for error in rollback_errors)
            message += f". Undo rollback also failed: {details}"
        raise PhotoSessionError(
            message,
            primary_error=primary_error,
            rollback_errors=rollback_errors,
            completed_operations=tuple(completed),
        ) from primary_error

    def unique_destination(self, destination_dir: Path, filename: str) -> Path:
        candidate = destination_dir / filename
        if not self._path_occupied(candidate):
            return candidate

        stem = Path(filename).stem
        suffix = Path(filename).suffix
        counter = 1
        while True:
            candidate = destination_dir / f"{stem} ({counter}){suffix}"
            if not self._path_occupied(candidate):
                return candidate
            counter += 1
