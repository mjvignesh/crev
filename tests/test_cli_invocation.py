"""Tests for the claude CLI invocation in Reviewer."""
from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from crev.config import Config
from crev.reviewer import (
    ClaudeCliError,
    Reviewer,
    find_claude_cli,
)


def test_find_claude_cli_uses_env_override(monkeypatch, tmp_path):
    fake_bin = tmp_path / "fake-claude"
    fake_bin.write_text("#!/bin/sh\necho hi\n")
    fake_bin.chmod(0o755)
    monkeypatch.setenv("CREV_CLAUDE_BIN", str(fake_bin))
    assert find_claude_cli() == str(fake_bin)


def test_find_claude_cli_rejects_non_executable_path(monkeypatch, tmp_path):
    """A path that exists but is not executable must be rejected.

    Without this, setting CREV_CLAUDE_BIN=/etc/passwd would let crev try to
    'execute' a non-executable file.
    """
    not_exec = tmp_path / "data.txt"
    not_exec.write_text("not a binary")
    not_exec.chmod(0o644)  # readable but not executable
    monkeypatch.setenv("CREV_CLAUDE_BIN", str(not_exec))
    with pytest.raises(ClaudeCliError, match="not found or is not executable"):
        find_claude_cli()


def test_find_claude_cli_raises_when_missing(monkeypatch):
    monkeypatch.setenv("CREV_CLAUDE_BIN", "/nonexistent/path/to/claude-bin-xyz")
    with pytest.raises(ClaudeCliError, match="not found"):
        find_claude_cli()


def test_reviewer_invokes_claude_with_correct_flags(monkeypatch, tmp_path):
    fake_bin = tmp_path / "fake-claude"
    fake_bin.write_text("#!/bin/sh\nexit 0\n")
    fake_bin.chmod(0o755)
    monkeypatch.setenv("CREV_CLAUDE_BIN", str(fake_bin))

    cfg = Config(model="opus", bare_mode=True)
    reviewer = Reviewer(cfg)

    fake_envelope = json.dumps({
        "type": "result",
        "subtype": "success",
        "result": '{"findings": [{"severity": "high", "category": "bug", "file": "x.py", "title": "t", "description": "d"}]}',
    })

    captured_cmd = {}
    def fake_run(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=fake_envelope, stderr="")

    with patch("crev.reviewer.subprocess.run", side_effect=fake_run):
        findings = reviewer.review(diff="--- a\n+++ b\n@@\n+ x\n", file_context={}, checks=["bugs"])

    cmd = captured_cmd["cmd"]
    assert cmd[0] == str(fake_bin)
    assert "--bare" in cmd
    assert "-p" in cmd
    assert "--output-format" in cmd and "json" in cmd
    assert "--max-turns" in cmd
    assert "--append-system-prompt" in cmd
    assert "--model" in cmd and "opus" in cmd
    assert len(findings) == 1
    assert findings[0].severity == "high"


def test_reviewer_omits_bare_when_disabled(monkeypatch, tmp_path):
    fake_bin = tmp_path / "fake-claude"
    fake_bin.write_text("#!/bin/sh\nexit 0\n")
    fake_bin.chmod(0o755)
    monkeypatch.setenv("CREV_CLAUDE_BIN", str(fake_bin))

    cfg = Config(bare_mode=False)
    reviewer = Reviewer(cfg)

    captured = {}
    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout='{"result": "{\\"findings\\": []}"}', stderr="")

    with patch("crev.reviewer.subprocess.run", side_effect=fake_run):
        reviewer.review(diff="diff", file_context={}, checks=["bugs"])

    assert "--bare" not in captured["cmd"]


def test_reviewer_handles_cli_failure_gracefully(monkeypatch, tmp_path, capsys):
    fake_bin = tmp_path / "fake-claude"
    fake_bin.write_text("#!/bin/sh\nexit 1\n")
    fake_bin.chmod(0o755)
    monkeypatch.setenv("CREV_CLAUDE_BIN", str(fake_bin))

    cfg = Config()
    reviewer = Reviewer(cfg)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="not authenticated")

    with patch("crev.reviewer.subprocess.run", side_effect=fake_run):
        findings = reviewer.review(diff="diff", file_context={}, checks=["bugs"])

    assert findings == []
    err = capsys.readouterr().err
    assert "claude CLI exited" in err
    assert "not authenticated" in err


def test_reviewer_handles_timeout(monkeypatch, tmp_path, capsys):
    fake_bin = tmp_path / "fake-claude"
    fake_bin.write_text("#!/bin/sh\nexit 0\n")
    fake_bin.chmod(0o755)
    monkeypatch.setenv("CREV_CLAUDE_BIN", str(fake_bin))

    cfg = Config(timeout_seconds=5)
    reviewer = Reviewer(cfg)

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=5)

    with patch("crev.reviewer.subprocess.run", side_effect=fake_run):
        findings = reviewer.review(diff="diff", file_context={}, checks=["bugs"])

    assert findings == []
    err = capsys.readouterr().err
    assert "timed out" in err


def test_reviewer_parses_envelope_with_error_subtype(monkeypatch, tmp_path, capsys):
    fake_bin = tmp_path / "fake-claude"
    fake_bin.write_text("#!/bin/sh\nexit 0\n")
    fake_bin.chmod(0o755)
    monkeypatch.setenv("CREV_CLAUDE_BIN", str(fake_bin))

    cfg = Config()
    reviewer = Reviewer(cfg)

    err_envelope = json.dumps({"type": "result", "subtype": "error", "result": "rate limited"})

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=err_envelope, stderr="")

    with patch("crev.reviewer.subprocess.run", side_effect=fake_run):
        findings = reviewer.review(diff="diff", file_context={}, checks=["bugs"])

    assert findings == []
    err = capsys.readouterr().err
    assert "rate limited" in err


def test_reviewer_detects_is_error_with_success_subtype(monkeypatch, tmp_path, capsys):
    """claude can return subtype=success but is_error=true (e.g. 'Not logged in')."""
    fake_bin = tmp_path / "fake-claude"
    fake_bin.write_text("#!/bin/sh\nexit 0\n")
    fake_bin.chmod(0o755)
    monkeypatch.setenv("CREV_CLAUDE_BIN", str(fake_bin))

    cfg = Config()
    reviewer = Reviewer(cfg)

    err_envelope = json.dumps({
        "type": "result",
        "subtype": "success",
        "is_error": True,
        "result": "Not logged in · Please run /login",
    })

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=err_envelope, stderr="")

    with patch("crev.reviewer.subprocess.run", side_effect=fake_run):
        findings = reviewer.review(diff="diff", file_context={}, checks=["bugs"])

    assert findings == []
    err = capsys.readouterr().err
    assert "Not logged in" in err
    assert "/login" in err  # hint should be included


def test_reviewer_skips_empty_diff(monkeypatch, tmp_path):
    fake_bin = tmp_path / "fake-claude"
    fake_bin.write_text("#!/bin/sh\nexit 0\n")
    fake_bin.chmod(0o755)
    monkeypatch.setenv("CREV_CLAUDE_BIN", str(fake_bin))

    cfg = Config()
    reviewer = Reviewer(cfg)

    # Should not invoke subprocess at all
    with patch("crev.reviewer.subprocess.run") as mock_run:
        findings = reviewer.review(diff="   \n  ", file_context={}, checks=["bugs"])
    assert findings == []
    mock_run.assert_not_called()
