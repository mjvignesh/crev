"""Git utilities for crev.

Wraps `git` CLI commands. We shell out rather than use a library
to keep dependencies minimal.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _run(args: list[str], check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def is_git_repo() -> bool:
    """Return True if the current directory is inside a git work tree."""
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def get_repo_root() -> Path:
    """Return the absolute path to the repo root."""
    out = _run(["rev-parse", "--show-toplevel"]).strip()
    return Path(out)


def get_staged_diff() -> str:
    """Return the unified diff for staged changes."""
    return _run(["diff", "--cached", "--no-color", "-U10"])


def get_unstaged_diff() -> str:
    """Return the unified diff for unstaged (working tree) changes."""
    return _run(["diff", "--no-color", "-U10"])


def get_diff_for_files(paths: list[str]) -> str:
    """Return a diff for explicit file paths (HEAD vs working tree).

    Returns empty string if any of the paths are unknown to git or git fails.
    """
    if not paths:
        return ""
    result = subprocess.run(
        ["git", "diff", "HEAD", "--no-color", "-U10", "--", *paths],
        capture_output=True,
        text=True,
        check=False,
    )
    # If git failed (e.g. file not tracked), return what we have rather than
    # leaking stderr into the review payload.
    return result.stdout if result.returncode == 0 else ""


def get_changed_files_staged() -> list[str]:
    """Return list of files with staged changes. Handles spaces & unicode safely."""
    out = _run(["diff", "--cached", "--name-only", "-z"])
    return [p for p in out.split("\x00") if p]


def get_changed_files_all() -> list[str]:
    """Return list of files with any uncommitted changes (staged or unstaged)."""
    staged = _run(["diff", "--cached", "--name-only", "-z"]).split("\x00")
    unstaged = _run(["diff", "--name-only", "-z"]).split("\x00")
    seen: set[str] = set()
    result: list[str] = []
    for path in (*staged, *unstaged):
        if path and path not in seen:
            seen.add(path)
            result.append(path)
    return result


def get_file_contents_at_head(paths: list[str]) -> dict[str, str]:
    """For each path, return the current working-tree contents (after changes).

    These are sent to Claude as additional context so it can reason
    about the surrounding code, not just the patch hunks.
    """
    contents: dict[str, str] = {}
    for path in paths:
        p = Path(path)
        if p.exists() and p.is_file():
            try:
                contents[path] = p.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                # Skip binary or unreadable files
                continue
    return contents
