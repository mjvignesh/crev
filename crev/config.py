"""Configuration loading for crev.

Looks for config in this order:
  1. Path passed via --config
  2. .crev.toml in repo root
  3. [tool.crev] section in pyproject.toml
  4. Built-in defaults

Environment overrides:
  CREV_MODEL, CREV_MIN_SEVERITY, CREV_CLAUDE_BIN
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import tomllib  # py311+
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


# Empty string = let the claude CLI use its own configured default model.
DEFAULT_MODEL = ""
DEFAULT_CHECKS = ["bugs", "security", "style"]
DEFAULT_MIN_SEVERITY = "low"

DEFAULT_CONFIG_TOML = """\
# crev configuration
# https://github.com/yourname/crev
#
# crev shells out to the `claude` CLI (Claude Code) to do reviews,
# so it uses your existing Claude subscription / login. No API key
# management required.

[crev]
# Claude model to use. Leave empty to use whatever the claude CLI
# is configured to use by default. Examples: "opus", "sonnet", "haiku".
model = ""

# Which checks to run. Available: "bugs", "security", "style"
checks = ["bugs", "security", "style"]

# Minimum severity to display: info | low | medium | high | critical
min_severity = "low"

# Exit non-zero (block commit) when high/critical issues are found.
fail_on_blocking = true

# Path to .crevignore (glob patterns of files to skip).
ignore_file = ".crevignore"

# Maximum tokens of file context to send per review (keeps cost predictable).
max_context_tokens = 30000

# Run `claude` in --bare mode. Skips loading project CLAUDE.md, hooks,
# MCP servers, plugins, etc. — useful for reproducible CI reviews.
# WARNING: --bare also skips OAuth/keychain auth. Only enable this if
# you authenticate via ANTHROPIC_API_KEY (not via `claude /login`).
bare_mode = false

# Hard timeout for each claude CLI invocation (seconds).
timeout_seconds = 180
"""


@dataclass
class Config:
    model: str = DEFAULT_MODEL
    checks: list[str] = field(default_factory=lambda: list(DEFAULT_CHECKS))
    min_severity: str = DEFAULT_MIN_SEVERITY
    fail_on_blocking: bool = True
    ignore_file: str = ".crevignore"
    max_context_tokens: int = 30_000
    bare_mode: bool = False
    timeout_seconds: int = 180


def load_config(explicit_path: Optional[Path] = None) -> Config:
    """Load configuration from disk, falling back to defaults."""
    cfg = Config()
    data: dict = {}

    if explicit_path is not None:
        if not explicit_path.exists():
            raise FileNotFoundError(f"Config file not found: {explicit_path}")
        with explicit_path.open("rb") as f:
            data = tomllib.load(f)
    else:
        crev_toml = Path(".crev.toml")
        pyproject = Path("pyproject.toml")
        if crev_toml.exists():
            with crev_toml.open("rb") as f:
                data = tomllib.load(f)
        elif pyproject.exists():
            with pyproject.open("rb") as f:
                pp = tomllib.load(f)
            data = pp.get("tool", {}).get("crev", {}) or {}

    section = data.get("crev", data) if data else {}

    cfg.model = section.get("model", cfg.model)
    cfg.checks = list(section.get("checks", cfg.checks))
    cfg.min_severity = section.get("min_severity", cfg.min_severity)
    cfg.fail_on_blocking = bool(section.get("fail_on_blocking", cfg.fail_on_blocking))
    cfg.ignore_file = section.get("ignore_file", cfg.ignore_file)
    cfg.max_context_tokens = int(section.get("max_context_tokens", cfg.max_context_tokens))
    cfg.bare_mode = bool(section.get("bare_mode", cfg.bare_mode))
    cfg.timeout_seconds = int(section.get("timeout_seconds", cfg.timeout_seconds))

    # Env overrides
    cfg.model = os.environ.get("CREV_MODEL", cfg.model)
    cfg.min_severity = os.environ.get("CREV_MIN_SEVERITY", cfg.min_severity)

    return cfg


def write_default_config(path: Path = Path(".crev.toml")) -> Path:
    """Write the default config TOML to disk if it doesn't already exist."""
    if path.exists():
        return path
    path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")
    return path
