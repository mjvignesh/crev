"""Interactively apply auto-fix diffs proposed by Claude.

Security notes:
- Patches come from the model and could in principle include path traversal
  (e.g. `--- a/../../etc/passwd`). We guard against this in two ways:
    1. We scan the patch text for paths and reject any with `..` segments
       or absolute paths before invoking git apply.
    2. We always run `git apply` from the repo root, so even if a path slips
       through, git will refuse to write outside the working tree by default.
- Each fix is shown to the user and requires explicit confirmation. No fix
  is ever applied silently.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import click

from crev.git_utils import get_repo_root

if TYPE_CHECKING:
    from crev.reviewer import Finding


# Hard limit on patch size to defend against runaway model output.
MAX_PATCH_BYTES = 1_000_000  # 1 MB

# Timeout for `git apply` so a malformed patch can't hang the CLI forever.
GIT_APPLY_TIMEOUT_SECONDS = 30


class UnsafePatchError(Exception):
    """Raised when a patch attempts path traversal or is otherwise unsafe."""


def apply_fixes_interactive(findings: list["Finding"]) -> None:
    """Walk through findings with fix_diffs and offer to apply each one."""
    fixable = [f for f in findings if f.fix_diff]
    if not fixable:
        click.echo()
        click.echo("No auto-fix suggestions available.")
        return

    click.echo()
    click.echo(click.style(f"\nFound {len(fixable)} auto-fix suggestion(s).", bold=True))

    for finding in fixable:
        click.echo()
        click.echo(click.style(f"→ {finding.file}:{finding.line or '?'}", bold=True))
        click.echo(f"  {finding.title}")
        click.echo()
        for line in (finding.fix_diff or "").splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                click.echo(click.style(f"  {line}", fg="green"))
            elif line.startswith("-") and not line.startswith("---"):
                click.echo(click.style(f"  {line}", fg="red"))
            else:
                click.echo(f"  {line}")

        if not click.confirm("\nApply this fix?", default=False):
            continue

        try:
            ok = _apply_patch(finding.fix_diff or "")
        except UnsafePatchError as e:
            click.echo(click.style(f"  ✗ Refused: {e}", fg="red"))
            continue

        if ok:
            click.echo(click.style("  ✓ Applied", fg="green"))
        else:
            click.echo(click.style("  ✗ Failed to apply (patch may be stale)", fg="red"))


_PATH_LINE = re.compile(r"^(?:---|\+\+\+)\s+(\S+)", re.MULTILINE)


def _validate_patch_paths(diff_text: str) -> None:
    """Reject patches with absolute paths, parent-dir traversal, or no paths.

    Raises UnsafePatchError on violation.
    """
    if not diff_text.strip():
        raise UnsafePatchError("patch is empty")

    if len(diff_text.encode("utf-8", errors="replace")) > MAX_PATCH_BYTES:
        raise UnsafePatchError(f"patch exceeds {MAX_PATCH_BYTES} bytes")

    found_any = False
    for match in _PATH_LINE.finditer(diff_text):
        raw = match.group(1)
        found_any = True

        if raw == "/dev/null":
            continue

        # Strip git's a/ b/ prefixes if present
        path = raw
        if path.startswith(("a/", "b/")):
            path = path[2:]

        # Reject absolute paths (Unix and Windows-style)
        if path.startswith("/") or (len(path) >= 2 and path[1] == ":"):
            raise UnsafePatchError(f"absolute path in patch: {raw!r}")

        # Reject parent-dir traversal in any path component.
        # Normalize separators first so `..\\foo` is caught on any platform.
        normalized = path.replace("\\", "/")
        parts = normalized.split("/")
        if any(part == ".." for part in parts):
            raise UnsafePatchError(f"path traversal in patch: {raw!r}")

    if not found_any:
        raise UnsafePatchError("patch contains no file paths")


def _apply_patch(diff_text: str) -> bool:
    """Apply a unified diff via `git apply`. Returns True on success.

    Raises UnsafePatchError if the patch fails security validation.
    """
    _validate_patch_paths(diff_text)

    repo_root = get_repo_root()

    # Write the patch to a tempfile. We use delete=False + manual cleanup so
    # the file is closed before subprocess reads it (required on Windows where
    # an open handle blocks read access).
    fd, tmp_path = tempfile.mkstemp(suffix=".patch", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(diff_text)
            if not diff_text.endswith("\n"):
                f.write("\n")

        result = subprocess.run(
            [
                "git", "apply",
                "--whitespace=nowarn",
                # Run from repo root explicitly so paths can't escape.
                "--directory", str(repo_root),
                tmp_path,
            ],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            timeout=GIT_APPLY_TIMEOUT_SECONDS,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass
