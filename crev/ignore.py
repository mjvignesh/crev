"""Ignore rules for crev.

Reads a `.crevignore` file (gitignore-style glob patterns) and
filters out paths that should not be reviewed.
"""
from __future__ import annotations

import fnmatch
from pathlib import Path


DEFAULT_IGNORE = """\
# crev ignore patterns (gitignore-style globs)
# One pattern per line. Lines starting with # are comments.

# Build artifacts
dist/
build/
*.min.js
*.min.css

# Dependencies
node_modules/
vendor/
.venv/
venv/

# Generated files
*.generated.*
*_pb2.py
*.pb.go

# Test fixtures
**/fixtures/**
**/__snapshots__/**

# Lockfiles (usually not worth reviewing)
package-lock.json
yarn.lock
poetry.lock
Cargo.lock
"""


class IgnoreRules:
    def __init__(self, patterns: list[str]) -> None:
        self.patterns = patterns

    @classmethod
    def load(cls, path: str | Path) -> "IgnoreRules":
        p = Path(path)
        if not p.exists():
            return cls([])
        lines = p.read_text(encoding="utf-8").splitlines()
        # Normalize backslashes to forward slashes so Windows-authored patterns
        # work the same on Linux/Mac (and vice versa).
        patterns = [
            line.strip().replace("\\", "/")
            for line in lines
            if line.strip() and not line.strip().startswith("#")
        ]
        return cls(patterns)

    def is_ignored(self, file_path: str) -> bool:
        path = file_path.replace("\\", "/")
        for pattern in self.patterns:
            if _matches(pattern, path):
                return True
        return False


def _matches(pattern: str, path: str) -> bool:
    """Match gitignore-style patterns against a path.

    Limited subset: supports `*`, `**`, `?`, trailing `/` for directories,
    and leading `/` for repo-root-anchored patterns.
    """
    if not pattern:
        return False

    # Trailing slash means "match this dir and everything inside it"
    if pattern.endswith("/"):
        prefix = pattern.rstrip("/")
        return path == prefix or path.startswith(prefix + "/") or fnmatch.fnmatch(path, prefix + "/*")

    # Leading slash anchors to repo root
    if pattern.startswith("/"):
        return fnmatch.fnmatch(path, pattern[1:])

    # ** glob
    if "**" in pattern:
        return fnmatch.fnmatch(path, pattern)

    # Default: match basename or path
    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(Path(path).name, pattern)


def write_default_ignore(path: Path = Path(".crevignore")) -> Path:
    if path.exists():
        return path
    path.write_text(DEFAULT_IGNORE, encoding="utf-8")
    return path
