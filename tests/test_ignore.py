"""Tests for ignore rule matching."""
from __future__ import annotations

from crev.ignore import IgnoreRules


def test_directory_pattern():
    rules = IgnoreRules(["dist/", "node_modules/"])
    assert rules.is_ignored("dist/main.js")
    assert rules.is_ignored("node_modules/foo/bar.js")
    assert not rules.is_ignored("src/main.js")


def test_glob_pattern():
    rules = IgnoreRules(["*.min.js"])
    assert rules.is_ignored("foo.min.js")
    assert rules.is_ignored("dist/bundle.min.js")
    assert not rules.is_ignored("foo.js")


def test_double_star():
    rules = IgnoreRules(["**/fixtures/**"])
    assert rules.is_ignored("tests/fixtures/sample.json")
    assert rules.is_ignored("a/b/fixtures/c/d.json")


def test_comments_and_blanks_ignored_at_load_time():
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".ignore", delete=False) as tmp:
        tmp.write("# a comment\n\ndist/\n# another\n*.log\n")
        tmp_path = tmp.name

    rules = IgnoreRules.load(tmp_path)
    assert rules.is_ignored("dist/x.js")
    assert rules.is_ignored("foo.log")
    assert not rules.is_ignored("src/main.py")


def test_empty_file_returns_no_rules():
    rules = IgnoreRules.load("/nonexistent/path/to/file")
    assert rules.patterns == []
    assert not rules.is_ignored("anything.py")
