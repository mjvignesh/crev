"""Tests for patch validation security guards in fixer."""
from __future__ import annotations

import pytest

from crev.fixer import (
    MAX_PATCH_BYTES,
    UnsafePatchError,
    _validate_patch_paths,
)


def test_validates_a_normal_patch():
    diff = (
        "--- a/src/foo.py\n"
        "+++ b/src/foo.py\n"
        "@@ -1 +1 @@\n"
        "- old\n"
        "+ new\n"
    )
    _validate_patch_paths(diff)  # should not raise


def test_rejects_absolute_unix_path():
    diff = (
        "--- a/src/foo.py\n"
        "+++ /etc/passwd\n"
        "@@ -1 +1 @@\n"
        "- old\n"
        "+ new\n"
    )
    with pytest.raises(UnsafePatchError, match="absolute path"):
        _validate_patch_paths(diff)


def test_rejects_parent_dir_traversal():
    diff = (
        "--- a/src/foo.py\n"
        "+++ b/../../etc/passwd\n"
        "@@ -1 +1 @@\n"
        "- old\n"
        "+ new\n"
    )
    with pytest.raises(UnsafePatchError, match="path traversal"):
        _validate_patch_paths(diff)


def test_rejects_windows_absolute_path():
    diff = (
        "--- a/src/foo.py\n"
        "+++ C:/Windows/System32/foo.dll\n"
        "@@ -1 +1 @@\n"
    )
    with pytest.raises(UnsafePatchError, match="absolute path"):
        _validate_patch_paths(diff)


def test_rejects_backslash_traversal():
    """Path traversal using Windows-style separators should also be caught."""
    diff = (
        "--- a/src/foo.py\n"
        "+++ b/..\\..\\etc\\passwd\n"
        "@@ -1 +1 @@\n"
    )
    with pytest.raises(UnsafePatchError, match="path traversal"):
        _validate_patch_paths(diff)


def test_allows_dev_null():
    """Patches that delete files use /dev/null as the destination — that's fine."""
    diff = (
        "--- a/src/old.py\n"
        "+++ /dev/null\n"
        "@@ -1 +0,0 @@\n"
        "- removed\n"
    )
    _validate_patch_paths(diff)  # should not raise


def test_rejects_empty_patch():
    with pytest.raises(UnsafePatchError, match="empty"):
        _validate_patch_paths("")
    with pytest.raises(UnsafePatchError, match="empty"):
        _validate_patch_paths("   \n  ")


def test_rejects_oversized_patch():
    huge = "--- a/x\n+++ b/x\n" + ("+ line\n" * (MAX_PATCH_BYTES // 6))
    with pytest.raises(UnsafePatchError, match="exceeds"):
        _validate_patch_paths(huge)


def test_rejects_patch_without_paths():
    diff = "@@ -1 +1 @@\n- old\n+ new\n"
    with pytest.raises(UnsafePatchError, match="no file paths"):
        _validate_patch_paths(diff)
