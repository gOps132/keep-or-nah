"""Documentation consistency checks.

The documentation for this project shipped describing an application that no
longer existed: it told readers that the app "falls back to the standard
`tkinter` interface", a path that was deleted when the second frontend was
retired. Nothing stopped that claim from coming back, or from the docs
drifting away from the code again.

These checks make the documentation a build artifact rather than prose. They
assert three things:

1. The retired GUI path is not described anywhere.
2. The README documents the capabilities that actually ship.
3. The keyboard shortcuts the README advertises are the ones the app binds.

They are deliberately narrow. A check that fails on legitimate wording is a
check that gets deleted, so each assertion targets something concrete.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

README = Path("README.md")
PLATFORM = Path("docs/PLATFORM.md")
BUILD = Path("docs/BUILD.md")
DOCS = (README, PLATFORM, BUILD)

# The retired second frontend. `classic_gui.py` was deleted in issue #6
# (ADR-0002, "Consolidate Desktop GUI on CustomTkinter"). No document may
# describe it, and no document may promise a fallback to it.
RETIRED_GUI_PATTERNS = (
    r"classic_gui",
    r"classic\s+(?:tk|tcl|tkinter)",
    r"classic\s+`?tkinter`?",
    r"falls?\s+back\s+to\s+the\s+standard",
    r"fallback\s+to\s+the\s+standard",
    r"standard\s+`?tkinter`?\s+interface",
    r"second\s+frontend",
)

# Capabilities that ship today. Each one is a real feature backed by code, and
# the README is the place a user looks to learn what the app does.
REQUIRED_README_FEATURES = (
    "Photo Group",
    "Representative",
    "Photo Session",
    "Triage",
    "Keep",
    "Nah",
    "Flag",
    "Staged Decision",
    "Batch Commit",
    "Undo Journal",
    "Action Mode",
    "Burst Cluster",
    "Best Shot",
    "Split Comparison",
    "Thumbnail Strip",
)

# Terms `CONTEXT.md` explicitly forbids. Using one means the glossary and the
# prose have drifted apart.
FORBIDDEN_GLOSSARY_TERMS = (
    "stem group",
    "photo cluster",
    "primary file",
    "display image",
    "hero file",
    "culling",
    "approve",
    "favorite",
    "reject",
    "draft decision",
    "pending action",
    "uncommitted change",
    "save changes",
    "apply actions",
    "flush decisions",
    "file transfer",
    "history log",
    "audit trail",
    "undo stack",
    "transfer type",
    "execution mode",
    "photo series",
    "burst group",
    "hero shot",
    "top photo",
    "compare mode",
    "dual view",
    "side-by-side mode",
    "filmstrip",
    "bottom gallery",
    "preview bar",
)


def test_documentation_files_exist() -> None:
    for path in DOCS:
        assert path.exists(), f"Expected {path} to exist"


def test_no_document_describes_a_retired_gui_path() -> None:
    for path in DOCS:
        text = path.read_text(encoding="utf-8")
        for pattern in RETIRED_GUI_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            assert match is None, (
                f"{path} describes a GUI path that was retired: {match.group(0)!r}"
            )


def test_readme_documents_the_features_that_ship() -> None:
    text = README.read_text(encoding="utf-8")
    for feature in REQUIRED_README_FEATURES:
        assert feature in text, f"{README} does not mention {feature!r}"


def test_documentation_avoids_forbidden_glossary_terms() -> None:
    for path in DOCS:
        text = path.read_text(encoding="utf-8")
        for term in FORBIDDEN_GLOSSARY_TERMS:
            pattern = r"\b" + re.escape(term) + r"\b"
            match = re.search(pattern, text, re.IGNORECASE)
            assert match is None, (
                f"{path} uses the term {match.group(0)!r}, which CONTEXT.md forbids"
            )


def _gui_binding_sources() -> str:
    """The text of every module that can hold the keyboard bindings.

    The bindings may live in `gui_app.py` or in the `ui` package the GUI was
    decomposed into, so the search covers both.
    """
    sources = [Path("gui_app.py")]
    ui_package = Path("ui")
    if ui_package.is_dir():
        sources.extend(sorted(ui_package.rglob("*.py")))
    return "\n".join(path.read_text(encoding="utf-8") for path in sources)


def test_readme_shortcuts_are_bound_by_the_app() -> None:
    """Every shortcut the README advertises must be a real key binding.

    The README's shortcut table is the part of the documentation most likely
    to rot, because the bindings live in the GUI and nothing else connects
    the two.
    """
    readme = README.read_text(encoding="utf-8")
    gui_source = _gui_binding_sources()

    # Keys the README advertises, mapped to the Tk sequence that must exist.
    advertised = {
        "Left": "<Left>",
        "Right": "<Right>",
        "A": "<KeyPress-a>",
        "D": "<KeyPress-d>",
        "F": "<KeyPress-f>",
        "Space": "<space>",
        "Del": "<Delete>",
        "C": "<KeyPress-c>",
        "1": "<KeyPress-1>",
        "2": "<KeyPress-2>",
    }

    table = readme.split("## Keyboard Shortcuts", 1)
    assert len(table) == 2, "The README must have a '## Keyboard Shortcuts' section"
    shortcut_section = table[1].split("##", 1)[0]

    for key, sequence in advertised.items():
        assert f"`{key}`" in shortcut_section, f"The README does not document the {key} key"
        assert sequence in gui_source, (
            f"The README documents {key}, but no GUI module binds {sequence}"
        )


def test_readme_documents_the_verification_entrypoint() -> None:
    """The README must point at the canonical gate, not at raw commands."""
    text = README.read_text(encoding="utf-8")
    assert "scripts/verify.sh" in text, "The README must document scripts/verify.sh"
    assert Path("scripts/verify.sh").exists()
    if os.name == "posix":
        assert Path("scripts/verify.sh").stat().st_mode & 0o111, (
            "scripts/verify.sh must be executable"
        )


def test_platform_notes_omit_the_retired_fallback() -> None:
    text = PLATFORM.read_text(encoding="utf-8")
    assert "tkinter" in text.lower(), "The platform notes should still mention Tk"
    assert "classic" not in text.lower()
