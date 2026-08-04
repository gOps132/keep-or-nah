# Photo Groups and View Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Group every same-stem source file into one sortable item, add an extension view filter, and show a safe placeholder for formats without a preview strategy.

**Architecture:** Introduce focused `PhotoGroup`/group-operation domain types and a registry-backed preview strategy layer. `PhotoSession` owns filtered groups, compound decisions, rollback, undo, and versioned snapshots; shared helpers keep both Tk frontends behaviorally identical.

**Tech Stack:** Python 3.12, pathlib/shutil, Pillow, tkinter/CustomTkinter, unittest, PyInstaller.

---

### Task 1: Photo grouping and representative selection

**Files:**
- Create: `photo_groups.py`
- Test: `tests/test_photo_groups.py`

- [ ] **Step 1: Write failing grouping tests**

```python
def test_build_groups_uses_one_item_per_exact_stem(tmp_path):
    jpg = (tmp_path / "IMG_1.jpg"); jpg.write_bytes(b"jpg")
    raw = (tmp_path / "IMG_1.cr3"); raw.write_bytes(b"raw")
    other = (tmp_path / "IMG_10.jpg"); other.write_bytes(b"other")
    groups = build_photo_groups(tmp_path, {".jpg", ".cr3"}, {".jpg"})
    assert [(g.stem, g.members, g.representative) for g in groups] == [
        ("IMG_1", (raw, jpg), jpg),
        ("IMG_10", (other,), other),
    ]

def test_group_requires_enabled_extension_and_falls_back_alphabetically(tmp_path):
    cr3 = (tmp_path / "A.cr3"); cr3.write_bytes(b"raw")
    xmp = (tmp_path / "A.xmp"); xmp.write_bytes(b"meta")
    assert build_photo_groups(tmp_path, {".cr3"}, set())[0].representative == cr3
    assert build_photo_groups(tmp_path, {".xmp"}, set())[0].representative == xmp
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run python -m unittest tests.test_photo_groups -v`

Expected: `ModuleNotFoundError: No module named 'photo_groups'`.

- [ ] **Step 3: Implement immutable group model and builder**

```python
@dataclass(frozen=True)
class PhotoGroup:
    stem: str
    members: tuple[Path, ...]
    representative: Path

def discover_extensions(source_dir: Path) -> tuple[str, ...]:
    return tuple(sorted({p.suffix.lower() for p in source_dir.iterdir() if p.is_file() and p.suffix}))

def build_photo_groups(source_dir: Path, enabled: set[str], previewable: set[str]) -> list[PhotoGroup]:
    buckets: dict[str, list[Path]] = {}
    for path in source_dir.iterdir():
        if path.is_file():
            buckets.setdefault(path.stem, []).append(path)
    groups = []
    for stem, members in sorted(buckets.items(), key=lambda item: item[0].lower()):
        eligible = [p for p in members if p.suffix.lower() in enabled]
        if not eligible:
            continue
        representative = min(eligible, key=lambda p: (p.suffix.lower() not in previewable, p.suffix.lower(), p.name))
        groups.append(PhotoGroup(stem, tuple(sorted(members, key=lambda p: p.name.lower())), representative))
    return groups
```

- [ ] **Step 4: Run tests and commit**

Run: `uv run python -m unittest tests.test_photo_groups -v`

Expected: all grouping tests pass.

```bash
git add photo_groups.py tests/test_photo_groups.py
git commit -m "Add same-stem photo grouping"
```

### Task 2: Preview strategy registry and unavailable state

**Files:**
- Create: `preview_strategies.py`
- Modify: `preview_pipeline.py`
- Test: `tests/test_preview_strategies.py`

- [ ] **Step 1: Write failing strategy tests**

```python
def test_registry_selects_pillow_or_unavailable(tmp_path):
    registry = PreviewStrategyRegistry([PillowPreviewStrategy()])
    assert registry.supports_extension(".JPG")
    assert not registry.supports_extension(".cr3")
    assert isinstance(registry.for_path(tmp_path / "A.cr3"), UnavailablePreviewStrategy)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run python -m unittest tests.test_preview_strategies -v`

Expected: import failure for `preview_strategies`.

- [ ] **Step 3: Implement strategies and registry**

```python
class PreviewStrategy(Protocol):
    extensions: frozenset[str]
    def load(self, path: Path) -> Image.Image | None: ...

class PillowPreviewStrategy:
    extensions = frozenset(SUPPORTED_IMAGE_EXTENSIONS)
    def load(self, path: Path) -> Image.Image:
        with Image.open(path) as image:
            return ImageOps.exif_transpose(image).convert("RGB")

class UnavailablePreviewStrategy:
    extensions = frozenset()
    def load(self, path: Path) -> None:
        return None
```

`PreviewStrategyRegistry.for_path()` returns the first matching registered strategy, then one shared unavailable strategy. Route `PreviewPipeline._load_source()` through the registry and emit a distinct unavailable completion state instead of `error` when strategy returns `None`.

- [ ] **Step 4: Run focused and existing preview tests, then commit**

Run: `uv run python -m unittest tests.test_preview_strategies tests.test_session_persistence -v`

Expected: all tests pass.

```bash
git add preview_strategies.py preview_pipeline.py tests/test_preview_strategies.py
git commit -m "Add pluggable preview strategies"
```

### Task 3: Compound group decisions, collision naming, rollback, and undo

**Files:**
- Modify: `photo_session.py`
- Test: `tests/test_photo_session_groups.py`

- [ ] **Step 1: Write failing compound-operation tests**

```python
def test_move_group_uses_one_collision_suffix_and_undoes_every_member(session, tmp_path):
    (session.keep_dir / "IMG.jpg").write_bytes(b"occupied")
    result = session.decide("keep")
    assert [p.destination.name for p in result.files] == ["IMG (1).cr3", "IMG (1).jpg"]
    assert not any(p.exists() for p in result.group.members)
    session.undo()
    assert all(p.exists() for p in result.group.members)

def test_failed_group_copy_rolls_back_completed_members(self):
    session = self.make_group_session(action_mode="copy")
    real_copy = shutil.copy2
    calls = 0
    def fail_second(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk full")
        return real_copy(source, destination)
    with patch("photo_session.shutil.copy2", side_effect=fail_second):
        with self.assertRaises(PhotoSessionError):
            session.decide("keep")
    assert list(session.keep_dir.iterdir()) == []
    assert session.remaining_count == 1
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run python -m unittest tests.test_photo_session_groups -v`

Expected: failures because queue entries and action records are single paths.

- [ ] **Step 3: Replace path queue with groups and compound records**

```python
@dataclass(frozen=True)
class FileOperation:
    source: Path
    destination: Path

@dataclass(frozen=True)
class ActionRecord:
    decision: Decision
    action_mode: ActionMode
    group: PhotoGroup
    files: tuple[FileOperation, ...]
    index: int
```

Add `enabled_extensions`, `available_extensions`, `active_group`, and compatibility `active_photo` returning the representative. `load_queue()` discovers all extensions, enables all for a new source, and builds groups. `apply_extension_filter()` rebuilds groups while retaining the active stem.

Preflight destinations by testing suffix candidates against every member. Execute members in deterministic order. On failure, reverse completed moves or delete completed copies; raise `PhotoSessionError` containing operation and rollback errors. Pop/count once per group. Undo reverses every `FileOperation` in reverse order and reinserts the group once.

- [ ] **Step 4: Run focused tests and commit**

Run: `uv run python -m unittest tests.test_photo_session_groups tests.test_photo_groups -v`

Expected: all tests pass.

```bash
git add photo_session.py tests/test_photo_session_groups.py
git commit -m "Process same-stem files as one decision"
```

### Task 4: Versioned grouped persistence and legacy migration

**Files:**
- Modify: `photo_session.py`
- Modify: `session_persistence.py`
- Test: `tests/test_session_persistence.py`

- [ ] **Step 1: Write failing snapshot tests**

```python
def test_grouped_snapshot_round_trip_preserves_filter_groups_and_history(group_session):
    restored = PhotoSession.from_snapshot(group_session.to_snapshot())
    assert restored.enabled_extensions == group_session.enabled_extensions
    assert restored.active_group.stem == group_session.active_group.stem
    assert restored.history == group_session.history

def test_legacy_snapshot_rebuilds_groups_from_source(legacy_payload):
    restored = PhotoSession.from_snapshot(legacy_payload)
    assert restored is not None
    assert restored.snapshot_version == 2
    assert {g.stem for g in restored.queue} == {"IMG_1", "IMG_2"}
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run python -m unittest tests.test_session_persistence -v`

Expected: grouped fields absent and compound history cannot round-trip.

- [ ] **Step 3: Implement snapshot version 2**

Persist `snapshot_version: 2`, source/destination roots, enabled/available extensions, group member paths, representative, active stem, counts, mode, and compound file operations. Validate every restored member as a direct child of source and every history destination as a direct child of its decision-matched destination root. Reject symlink escapes. Drop unsafe history records.

For version 1, derive enabled extensions from saved queue suffixes, rebuild groups from the source directory, preserve the active legacy path's stem, and translate each safe single-file history record into a one-file compound record. Invalid legacy payloads continue to clear through `SessionLifecycle.restore()`.

- [ ] **Step 4: Run persistence/security tests and commit**

Run: `uv run python -m unittest tests.test_session_persistence -v`

Expected: round-trip, migration, malformed numeric, out-of-root, and symlink tests pass.

```bash
git add photo_session.py session_persistence.py tests/test_session_persistence.py
git commit -m "Persist grouped photo sessions"
```

### Task 5: Shared extension-filter UI and unsupported preview rendering

**Files:**
- Create: `view_filter.py`
- Modify: `gui_app.py`
- Modify: `classic_gui.py`
- Modify: `session_startup.py`
- Test: `tests/test_view_filter.py`
- Test: `tests/test_session_persistence.py`

- [ ] **Step 1: Write failing display-free integration tests**

```python
def test_apply_view_filter_updates_both_frontends_and_persists():
    for app_class in (App, ClassicApp):
        fake = make_frontend_fake({".jpg", ".cr3"})
        app_class.apply_view_filter(fake, {".cr3"})
        assert fake.session.enabled_extensions == {".cr3"}
        assert fake.persist_calls == 1
        assert fake.preview_messages[-1] == "Preview not available\nIMG_1.cr3"

def test_settings_lists_discovered_extensions_for_shared_model():
    model = ExtensionFilterModel.from_session(session)
    assert model.options == (".cr3", ".jpg", ".xmp")
    assert model.selected == frozenset({".cr3", ".jpg", ".xmp"})
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run python -m unittest tests.test_view_filter -v`

Expected: missing `view_filter` and frontend methods.

- [ ] **Step 3: Implement shared model and frontend hooks**

```python
@dataclass(frozen=True)
class ExtensionFilterModel:
    options: tuple[str, ...]
    selected: frozenset[str]

    @classmethod
    def from_session(cls, session: PhotoSession) -> "ExtensionFilterModel":
        return cls(tuple(sorted(session.available_extensions)), frozenset(session.enabled_extensions))
```

Add an `Extension View Filter` checkbox section to both existing preview settings dialogs. Disable Save when no extension is selected and show `Choose at least one file extension.` if invoked anyway. On Save, call shared `apply_extension_filter()`, reset pipeline/caches/thumbnails, persist, retain active stem when possible, and refresh UI/preview.

When `PreviewPipeline` reports unavailable, render centered `Preview not available`, representative filename, and extension; keep Keep/Nah enabled. Update startup restoration to reset the pipeline using representative paths while group state stays in `PhotoSession`.

- [ ] **Step 4: Run frontend tests and commit**

Run: `uv run python -m unittest tests.test_view_filter tests.test_session_persistence tests.test_main -v`

Expected: both frontend paths, picker/autoload, restore, filter persistence, and unsupported placeholder tests pass.

```bash
git add view_filter.py gui_app.py classic_gui.py session_startup.py tests/test_view_filter.py tests/test_session_persistence.py
git commit -m "Add extension view filter"
```

### Task 6: Full regression and macOS package verification

**Files:**
- Modify only files required by failures found below.

- [ ] **Step 1: Run complete automated verification**

```bash
uv run python -m unittest discover -v
uv run python -m compileall -q .
git diff --check
```

Expected: zero failures and zero diff errors.

- [ ] **Step 2: Build and inspect macOS bundle**

```bash
uv run --extra build python scripts/build.py macos
test -x "dist/macos/Keep or Nah.app/Contents/MacOS/Keep or Nah"
plutil -lint "dist/macos/Keep or Nah.app/Contents/Info.plist"
codesign --verify --deep --strict --verbose=2 "dist/macos/Keep or Nah.app"
```

Expected: build exit 0, executable exists, plist reports `OK`, and codesign reports valid on disk.

- [ ] **Step 3: Review scope and commit verification fixes**

Confirm no logo/icon changes, RAW decoder dependency, unrelated UI redesign, or path-safety regression entered the diff. If verification required fixes, stage each exact modified source/test path shown by `git status --short`, then commit:

```bash
git status --short
git add photo_groups.py preview_strategies.py preview_pipeline.py photo_session.py session_persistence.py view_filter.py gui_app.py classic_gui.py session_startup.py tests
git commit -m "Fix photo group integration regressions"
```
