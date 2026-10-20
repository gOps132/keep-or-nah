"""Repository hygiene checks.

The build produces a lot of artifacts: a PyInstaller cache, a `dist/` tree, a
`build/` tree, and the native crate's `target/` directory. None of them belong
in version control, and a rule that quietly stops matching is how a 900 KB
agent session transcript ends up committed.

`scripts/agent/check-artifacts.sh` does the real work. This test runs it, so
a plain `uv run pytest` catches a hygiene regression without needing the
pre-commit hook or the CI job.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK_SCRIPT = REPO_ROOT / "scripts" / "agent" / "check-artifacts.sh"

# Resolved to an absolute path so the subprocess call does not depend on the
# caller's PATH.
GIT = shutil.which("git") or "git"


def test_the_artifact_check_script_exists() -> None:
    assert CHECK_SCRIPT.is_file(), f"Expected {CHECK_SCRIPT} to exist"
    assert CHECK_SCRIPT.stat().st_mode & 0o111, "The artifact check must be executable"


def test_no_tracked_file_lives_in_a_build_or_cache_directory() -> None:
    tracked = subprocess.run(  # noqa: S603
        [GIT, "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()

    offenders = [
        path
        for path in tracked
        if any(
            segment
            in {
                "__pycache__",
                ".pytest_cache",
                ".ruff_cache",
                ".mypy_cache",
                ".pyinstaller",
                "node_modules",
                "target",
                "build",
                "dist",
            }
            for segment in Path(path).parts
        )
        or path.endswith((".pyc", ".so", ".dylib", ".pyd"))
        or Path(path).name == ".DS_Store"
    ]

    assert not offenders, f"Tracked build artifacts: {offenders}"


def test_the_ignore_rules_cover_every_known_artifact() -> None:
    result = subprocess.run(  # noqa: S603, PLW1510
        [str(CHECK_SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"The artifact check failed:\n{result.stdout}\n{result.stderr}"


def test_the_working_tree_has_no_stray_session_transcript() -> None:
    leftovers = list(REPO_ROOT.glob("freebuff-chat-*.md"))
    assert not leftovers, f"Stray agent session transcript(s): {leftovers}"


def test_the_ignore_rules_cover_the_native_crate_target_directory() -> None:
    """The crate's build output is the largest artifact the project produces."""
    ignored = subprocess.run(  # noqa: S603, PLW1510
        [GIT, "check-ignore", "-q", "crates/keep_or_nah_core/target/probe"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    assert ignored.returncode == 0, "crates/keep_or_nah_core/target is not ignored by .gitignore"


if __name__ == "__main__":  # pragma: no cover
    sys.exit(subprocess.call([str(CHECK_SCRIPT)], cwd=REPO_ROOT))  # noqa: S603
