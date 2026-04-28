"""Install/uninstall crev as a git pre-commit hook."""
from __future__ import annotations

from pathlib import Path

from crev.git_utils import get_repo_root


HOOK_SCRIPT = """\
#!/bin/sh
# crev pre-commit hook (installed by `crev install-hook`)
# To skip: git commit --no-verify

if ! command -v crev >/dev/null 2>&1; then
    echo "warning: crev not found on PATH; skipping AI review" >&2
    exit 0
fi

crev
"""

HOOK_MARKER = "# crev pre-commit hook (installed by `crev install-hook`)"


def install_hook(force: bool = False) -> Path:
    """Install crev as the repo's pre-commit hook. Returns the hook path."""
    root = get_repo_root()
    hook_path = root / ".git" / "hooks" / "pre-commit"

    if hook_path.exists() and not force:
        existing = hook_path.read_text(encoding="utf-8", errors="replace")
        if HOOK_MARKER in existing:
            # Already ours, just ensure executable
            hook_path.chmod(0o755)
            return hook_path
        raise FileExistsError(str(hook_path))

    hook_path.parent.mkdir(parents=True, exist_ok=True)
    hook_path.write_text(HOOK_SCRIPT, encoding="utf-8")
    hook_path.chmod(0o755)
    return hook_path


def uninstall_hook() -> bool:
    """Remove the crev pre-commit hook. Returns True if removed."""
    root = get_repo_root()
    hook_path = root / ".git" / "hooks" / "pre-commit"
    if not hook_path.exists():
        return False
    content = hook_path.read_text(encoding="utf-8", errors="replace")
    if HOOK_MARKER not in content:
        # Not our hook; don't touch it
        return False
    hook_path.unlink()
    return True
