"""crev - AI-powered code review using Claude.

Command-line interface entry point.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import click

from crev import __version__
from crev.config import Config, load_config
from crev.formatter import format_findings, print_summary
from crev.git_utils import (
    get_staged_diff,
    get_unstaged_diff,
    get_diff_for_files,
    get_file_contents_at_head,
    get_changed_files_staged,
    get_changed_files_all,
    is_git_repo,
)
from crev.hook import install_hook, uninstall_hook
from crev.reviewer import Reviewer, ClaudeCliError, find_claude_cli
from crev.ignore import IgnoreRules


SEVERITY_LEVELS = ["info", "low", "medium", "high", "critical"]


@click.group(invoke_without_command=True)
@click.version_option(__version__, prog_name="crev")
@click.option("--all", "review_all", is_flag=True, help="Review all uncommitted changes (staged + unstaged).")
@click.option("--files", "files", multiple=True, type=click.Path(exists=True), help="Review specific files instead of git diff.")
@click.option("--severity", type=click.Choice(SEVERITY_LEVELS), default=None, help="Minimum severity to show (default: from config).")
@click.option("--fix", is_flag=True, help="Interactively apply suggested auto-fixes.")
@click.option("--json", "json_output", is_flag=True, help="Output findings as JSON.")
@click.option("--no-color", is_flag=True, help="Disable colored output.")
@click.option("--model", default=None, help="Claude model to use (default: from config).")
@click.option("--config", "config_path", type=click.Path(), default=None, help="Path to config file.")
@click.pass_context
def cli(
    ctx: click.Context,
    review_all: bool,
    files: tuple[str, ...],
    severity: Optional[str],
    fix: bool,
    json_output: bool,
    no_color: bool,
    model: Optional[str],
    config_path: Optional[str],
) -> None:
    """crev — AI-powered code review using Claude.

    Run with no arguments to review your staged git changes.
    """
    # If a subcommand was invoked, defer to it
    if ctx.invoked_subcommand is not None:
        return

    config = load_config(Path(config_path) if config_path else None)
    if model:
        config.model = model
    if severity:
        config.min_severity = severity

    # Make sure we're in a git repo unless reviewing explicit files
    if not files and not is_git_repo():
        click.echo(click.style("error:", fg="red", bold=True) + " not a git repository (and no --files given)", err=True)
        sys.exit(2)

    # Verify the claude CLI is available before doing any work
    try:
        find_claude_cli()
    except ClaudeCliError as e:
        click.echo(click.style("error:", fg="red", bold=True) + f" {e}", err=True)
        sys.exit(2)

    # Resolve which diff to review
    if files:
        diff = get_diff_for_files(list(files))
        file_paths = list(files)
    elif review_all:
        diff = get_staged_diff() + "\n" + get_unstaged_diff()
        file_paths = get_changed_files_all()
    else:
        diff = get_staged_diff()
        file_paths = get_changed_files_staged()

    if not diff.strip():
        click.echo("No changes to review. (Try " + click.style("crev --all", bold=True) + " or stage some changes.)")
        return

    # Apply ignore rules
    ignore = IgnoreRules.load(config.ignore_file)
    file_paths = [p for p in file_paths if not ignore.is_ignored(p)]
    if not file_paths and files:
        click.echo("All requested files are ignored by .crevignore.")
        return

    # Pull file contents for context (so Claude sees the whole file, not just the diff)
    file_context = get_file_contents_at_head(file_paths) if file_paths else {}

    reviewer = Reviewer(config)

    # Send progress to stderr so `crev --json | jq` works cleanly.
    if json_output:
        click.echo("Reviewing with Claude...", err=True)
        findings = reviewer.review(diff=diff, file_context=file_context, checks=config.checks)
    else:
        with click.progressbar(length=1, label="Reviewing with Claude", show_pos=False, file=sys.stderr) as bar:
            findings = reviewer.review(diff=diff, file_context=file_context, checks=config.checks)
            bar.update(1)

    # Filter by severity threshold
    findings = [f for f in findings if _meets_severity(f.severity, config.min_severity)]

    if json_output:
        import json as _json
        click.echo(_json.dumps([f.to_dict() for f in findings], indent=2))
    else:
        format_findings(findings, use_color=not no_color)
        print_summary(findings, use_color=not no_color)

    if fix and findings:
        from crev.fixer import apply_fixes_interactive
        apply_fixes_interactive(findings)

    # Exit non-zero if blocking findings exist (for pre-commit hook usage)
    blocking = [f for f in findings if f.severity in ("high", "critical")]
    if blocking and config.fail_on_blocking:
        sys.exit(1)


@cli.command("install-hook")
@click.option("--force", is_flag=True, help="Overwrite existing pre-commit hook.")
def install_hook_cmd(force: bool) -> None:
    """Install crev as a git pre-commit hook in the current repo."""
    try:
        path = install_hook(force=force)
        click.echo(click.style("✓", fg="green") + f" Installed pre-commit hook at {path}")
    except FileExistsError:
        click.echo(click.style("✗", fg="red") + " A pre-commit hook already exists. Use --force to overwrite.", err=True)
        sys.exit(1)


@cli.command("uninstall-hook")
def uninstall_hook_cmd() -> None:
    """Remove the crev pre-commit hook."""
    if uninstall_hook():
        click.echo(click.style("✓", fg="green") + " Removed crev pre-commit hook.")
    else:
        click.echo("No crev hook found to remove.")


@cli.command("init")
@click.option("--no-hook", is_flag=True, help="Skip installing the git pre-commit hook.")
@click.option("--force", is_flag=True, help="Overwrite an existing pre-commit hook.")
def init_cmd(no_hook: bool, force: bool) -> None:
    """Set up crev in this repo: create config, ignore file, and install pre-commit hook."""
    from crev.config import write_default_config
    from crev.ignore import write_default_ignore

    cfg_path = write_default_config()
    ign_path = write_default_ignore()
    click.echo(click.style("✓", fg="green") + f" Created {cfg_path}")
    click.echo(click.style("✓", fg="green") + f" Created {ign_path}")

    if no_hook:
        click.echo()
        click.echo("Skipped pre-commit hook installation (--no-hook).")
        click.echo("Run " + click.style("crev install-hook", bold=True) + " later if you change your mind.")
        return

    if not is_git_repo():
        click.echo()
        click.echo(click.style("!", fg="yellow") + " Not a git repository — skipping pre-commit hook.")
        click.echo("  Run " + click.style("crev install-hook", bold=True) + " from inside a git repo to install it.")
        return

    try:
        hook_path = install_hook(force=force)
        click.echo(click.style("✓", fg="green") + f" Installed pre-commit hook at {hook_path}")
    except FileExistsError:
        click.echo()
        click.echo(click.style("!", fg="yellow") + " A pre-commit hook already exists at .git/hooks/pre-commit.")
        click.echo("  Re-run with " + click.style("crev init --force", bold=True) + " to overwrite it,")
        click.echo("  or use " + click.style("crev init --no-hook", bold=True) + " to skip the hook.")
        return

    click.echo()
    click.echo(click.style("All set.", fg="green", bold=True) + " crev will now run on every " + click.style("git commit", bold=True) + ".")
    click.echo("  Test it now:  " + click.style("crev", bold=True))
    click.echo("  Skip a commit: " + click.style("git commit --no-verify", bold=True))


@cli.command("doctor")
def doctor_cmd() -> None:
    """Check that crev's dependencies are installed and configured."""
    import subprocess

    ok = True

    # Check git
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        click.echo(click.style("✓", fg="green") + " git is installed")
    except (FileNotFoundError, subprocess.CalledProcessError):
        click.echo(click.style("✗", fg="red") + " git is not installed or not on PATH")
        ok = False

    # Check claude CLI
    try:
        bin_path = find_claude_cli()
        click.echo(click.style("✓", fg="green") + f" claude CLI found at {bin_path}")
    except ClaudeCliError as e:
        click.echo(click.style("✗", fg="red") + f" {e}")
        ok = False
        return

    # Try a tiny invocation to confirm auth works.
    # We deliberately do NOT use --bare here, because --bare skips OAuth/keychain
    # and would falsely report "not logged in" for subscription users.
    try:
        result = subprocess.run(
            [bin_path, "-p", "say OK", "--output-format", "json", "--max-turns", "1"],
            capture_output=True, text=True, timeout=60,
        )
        # Parse the envelope to surface inline errors (e.g. "Not logged in").
        envelope = {}
        if result.stdout.strip():
            try:
                envelope = json.loads(result.stdout)
            except json.JSONDecodeError:
                pass

        if result.returncode == 0 and not envelope.get("is_error", False) and envelope.get("subtype") != "error":
            click.echo(click.style("✓", fg="green") + " claude CLI is authenticated and responsive")
        else:
            click.echo(click.style("✗", fg="red") + " claude CLI failed a test call")
            inline_err = envelope.get("result") or result.stderr.strip() or "(no error message)"
            click.echo(f"   error: {inline_err[:300]}")
            if "logged in" in str(inline_err).lower() or "login" in str(inline_err).lower():
                click.echo("   hint: run `claude` and type /login to sign in")
            else:
                click.echo("   hint: try `claude` interactively to debug")
            ok = False
    except subprocess.TimeoutExpired:
        click.echo(click.style("✗", fg="red") + " claude CLI timed out on a 60s test call")
        ok = False

    if ok:
        click.echo()
        click.echo(click.style("All checks passed. You're ready to run `crev`.", fg="green", bold=True))
    else:
        sys.exit(1)


def _meets_severity(found: str, threshold: str) -> bool:
    """Return True if `found` severity is >= `threshold`. Unknown values fall back to 'low'."""
    try:
        f_idx = SEVERITY_LEVELS.index(found)
    except ValueError:
        f_idx = SEVERITY_LEVELS.index("low")
    try:
        t_idx = SEVERITY_LEVELS.index(threshold)
    except ValueError:
        t_idx = SEVERITY_LEVELS.index("low")
    return f_idx >= t_idx


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
