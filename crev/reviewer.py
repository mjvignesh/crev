"""Core review engine - sends diffs to the `claude` CLI and parses findings."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from typing import Optional

from crev.config import Config


VALID_SEVERITIES = {"info", "low", "medium", "high", "critical"}
VALID_CATEGORIES = {"bug", "security", "style", "performance"}


@dataclass
class Finding:
    """A single issue identified by Claude."""
    severity: str  # info | low | medium | high | critical
    category: str  # bug | security | style | performance
    file: str
    line: Optional[int]
    title: str
    description: str
    suggestion: Optional[str] = None
    fix_diff: Optional[str] = None
    rule_id: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


SYSTEM_PROMPT = """You are an expert code reviewer invoked by the `crev` tool. You analyze code diffs and identify real, actionable issues.

Your job:
1. Read the diff and the surrounding file context.
2. Identify concrete issues — bugs, security problems, style violations, performance traps.
3. Be precise: cite the exact file and line number from the diff.
4. Be conservative: do NOT flag stylistic preferences as bugs. Do NOT invent issues. If the code is fine, return an empty list.
5. When possible, propose a minimal fix as a unified diff.

Severity guide:
- critical: data loss, security vulnerability, crashes in production paths
- high: likely bugs, auth/authz issues, race conditions, broken contracts
- medium: error handling gaps, edge cases, accessibility, maintainability hot spots
- low: minor style / readability / naming
- info: tips and FYIs

Category guide:
- bug: logic errors, null derefs, off-by-one, type mismatches
- security: injection, secrets, unsafe deserialization, missing validation
- style: naming, formatting, idiom violations, dead code
- performance: O(n^2) where O(n) works, allocations in hot loops, unbounded growth

CRITICAL OUTPUT FORMAT: respond with ONLY a JSON object matching this schema. No prose, no markdown fences, no explanation. Just the JSON object:
{
  "findings": [
    {
      "severity": "high",
      "category": "bug",
      "file": "src/foo.py",
      "line": 42,
      "title": "Short one-line summary",
      "description": "Why this is a problem and what could go wrong.",
      "suggestion": "What to do instead (1-3 sentences).",
      "fix_diff": "--- a/src/foo.py\\n+++ b/src/foo.py\\n@@ ... @@\\n- bad\\n+ good\\n",
      "rule_id": "bug/null-deref"
    }
  ]
}

If there are no issues, return {"findings": []}.
"""


def build_user_message(diff: str, file_context: dict[str, str], checks: list[str]) -> str:
    """Build the user-turn message for Claude."""
    parts: list[str] = []
    parts.append(f"Please review the following code changes. Run these checks: {', '.join(checks)}.\n")

    if file_context:
        parts.append("## Full file contents (for context)\n")
        for path, content in file_context.items():
            if len(content) > 40_000:
                content = content[:40_000] + "\n\n[... truncated for length ...]"
            parts.append(f"### `{path}`\n```\n{content}\n```\n")

    parts.append("## Diff to review\n")
    parts.append("```diff\n")
    parts.append(diff)
    parts.append("\n```\n")
    parts.append(
        "\nReturn JSON only. Focus on the changed lines but use the file context "
        "to understand whether each change is actually correct. "
        "If you are not confident an issue is real, do not report it."
    )
    return "".join(parts)


class ClaudeCliError(Exception):
    """Raised when the claude CLI fails or is missing."""


def find_claude_cli() -> str:
    """Locate the claude CLI binary, return its path. Raises ClaudeCliError if missing."""
    # Allow override for testing / non-standard installs
    override = os.environ.get("CREV_CLAUDE_BIN")
    if override:
        # Resolve relative paths and expand ~/. shutil.which honors PATHEXT on Windows.
        resolved = shutil.which(override)
        if resolved:
            return resolved
        # Direct path: must exist AND be executable. We don't accept e.g. /etc/passwd.
        if os.path.isfile(override) and os.access(override, os.X_OK):
            return override
        raise ClaudeCliError(
            f"CREV_CLAUDE_BIN points to '{override}' but it was not found or is not executable."
        )

    found = shutil.which("claude")
    if found:
        return found

    raise ClaudeCliError(
        "The 'claude' CLI was not found on PATH.\n"
        "  crev uses Claude Code to review your changes — install it first:\n"
        "    npm install -g @anthropic-ai/claude-code\n"
        "  Then sign in by running:  claude  (and following the auth prompt)\n"
        "  Or set CREV_CLAUDE_BIN to a custom path."
    )


class Reviewer:
    """Wraps the `claude` CLI and parses responses into Findings."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._claude_bin = find_claude_cli()

    def review(self, diff: str, file_context: dict[str, str], checks: list[str]) -> list[Finding]:
        if not diff.strip():
            return []

        user_message = build_user_message(diff, file_context, checks)

        try:
            text = self._invoke_claude(user_message)
        except ClaudeCliError as e:
            print(f"error: {e}", file=sys.stderr)
            return []

        return parse_findings(text)

    def _invoke_claude(self, user_message: str) -> str:
        """Run `claude -p ... --output-format json` and return the result text."""
        cmd: list[str] = [self._claude_bin]

        # --bare skips loading project CLAUDE.md, hooks, MCP servers, plugins, etc.
        # Recommended for scripted use so reviews are reproducible across machines.
        if self.config.bare_mode:
            cmd.append("--bare")

        cmd.extend([
            "-p", user_message,
            "--output-format", "json",
            "--max-turns", "1",
            "--append-system-prompt", SYSTEM_PROMPT,
            "--allowedTools", "",   # no tools needed; pure text in/out
        ])
        if self.config.model:
            cmd.extend(["--model", self.config.model])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            raise ClaudeCliError(
                f"claude CLI timed out after {self.config.timeout_seconds}s. "
                f"Try increasing `timeout_seconds` in .crev.toml or shrinking the diff."
            )
        except FileNotFoundError as e:
            raise ClaudeCliError(f"failed to spawn claude CLI: {e}")

        if result.returncode != 0:
            stderr = result.stderr.strip() or "(no stderr)"
            raise ClaudeCliError(
                f"claude CLI exited with code {result.returncode}.\n"
                f"  stderr: {stderr[:500]}\n"
                f"  hint: try `claude` interactively to confirm you're signed in."
            )

        # --output-format json envelope:
        #   {"type": "result", "subtype": "success", "is_error": false,
        #    "result": "<text>", "total_cost_usd": ..., ...}
        # NOTE: claude can return subtype="success" with is_error=true when the
        # API call itself succeeded but produced an error message (e.g. "Not
        # logged in"). Check is_error explicitly.
        try:
            envelope = json.loads(result.stdout)
        except json.JSONDecodeError:
            return result.stdout

        if envelope.get("is_error") or envelope.get("subtype") == "error":
            msg = envelope.get("result") or "(no message)"
            hint = ""
            if "logged in" in str(msg).lower() or "login" in str(msg).lower():
                hint = "\n  hint: run `claude` and use /login to sign in."
            elif self.config.bare_mode:
                hint = (
                    "\n  hint: --bare mode skips OAuth/keychain auth. "
                    "Either set ANTHROPIC_API_KEY, or set bare_mode = false in .crev.toml."
                )
            raise ClaudeCliError(f"claude CLI returned an error: {msg}{hint}")

        return envelope.get("result", "")


def parse_findings(text: str) -> list[Finding]:
    """Robustly parse the model's JSON response into Finding objects."""
    text = text.strip()

    # Strip markdown code fences if Claude included any
    fence = re.match(r"^```(?:json)?\s*\n(.*)\n```\s*$", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1)

    # Find the JSON object — be lenient if there's any leading/trailing prose
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return []

    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []

    raw_findings = data.get("findings", [])
    findings: list[Finding] = []
    for raw in raw_findings:
        if not isinstance(raw, dict):
            continue
        try:
            # Validate severity — coerce unknown values to "low" so an
            # unexpected response from the model can't crash downstream code.
            sev = str(raw.get("severity", "low")).lower().strip()
            if sev not in VALID_SEVERITIES:
                sev = "low"

            cat = str(raw.get("category", "style")).lower().strip()
            if cat not in VALID_CATEGORIES:
                cat = "style"

            # Coerce line to int safely (model sometimes returns strings or None)
            line_raw = raw.get("line")
            line: Optional[int]
            if isinstance(line_raw, bool):  # bool is a subclass of int — exclude it
                line = None
            elif isinstance(line_raw, int):
                line = line_raw
            elif isinstance(line_raw, str) and line_raw.strip().isdigit():
                line = int(line_raw.strip())
            else:
                line = None

            # Coerce optional string fields. None stays None; everything else
            # becomes a string, defending against the model returning a dict/list.
            def _opt_str(v: object) -> Optional[str]:
                if v is None:
                    return None
                return str(v)

            findings.append(
                Finding(
                    severity=sev,
                    category=cat,
                    file=str(raw.get("file", "")),
                    line=line,
                    title=str(raw.get("title", "")).strip(),
                    description=str(raw.get("description", "")).strip(),
                    suggestion=_opt_str(raw.get("suggestion")),
                    fix_diff=_opt_str(raw.get("fix_diff")),
                    rule_id=_opt_str(raw.get("rule_id")),
                )
            )
        except (TypeError, ValueError):
            continue
    return findings
