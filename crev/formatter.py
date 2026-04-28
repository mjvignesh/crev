"""Pretty terminal output for findings."""
from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from crev.reviewer import Finding


SEVERITY_COLORS = {
    "critical": "magenta",
    "high": "red",
    "medium": "yellow",
    "low": "blue",
    "info": "cyan",
}

SEVERITY_ICONS = {
    "critical": "🔴",
    "high": "🔴",
    "medium": "🟡",
    "low": "🔵",
    "info": "ℹ️ ",
}


def _color(text: str, color: str, use_color: bool, bold: bool = False) -> str:
    if not use_color:
        return text
    return click.style(text, fg=color, bold=bold)


def format_findings(findings: list["Finding"], use_color: bool = True) -> None:
    """Print all findings to stdout in a readable format."""
    if not findings:
        click.echo(_color("✓ No issues found.", "green", use_color, bold=True))
        return

    # Group by file for readability
    by_file: dict[str, list["Finding"]] = {}
    for f in findings:
        by_file.setdefault(f.file or "(unknown)", []).append(f)

    for file_path, file_findings in by_file.items():
        click.echo()
        click.echo(_color(f"── {file_path} ──", "white", use_color, bold=True))
        for finding in file_findings:
            _print_finding(finding, use_color)


def _print_finding(finding: "Finding", use_color: bool) -> None:
    color = SEVERITY_COLORS.get(finding.severity, "white")
    icon = SEVERITY_ICONS.get(finding.severity, "•")

    location = f":{finding.line}" if finding.line else ""
    severity_label = _color(f"[{finding.severity.upper()}]", color, use_color, bold=True)
    category_label = _color(f"({finding.category})", "white", use_color)

    click.echo()
    click.echo(f"  {icon} {severity_label} {category_label} {finding.title}{location}")
    if finding.description:
        for line in finding.description.splitlines():
            click.echo(f"     {line}")
    if finding.suggestion:
        click.echo(f"     {_color('→', 'green', use_color)} {finding.suggestion}")
    if finding.fix_diff:
        click.echo(f"     {_color('proposed fix:', 'cyan', use_color)}")
        for line in finding.fix_diff.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                click.echo(_color(f"       {line}", "green", use_color))
            elif line.startswith("-") and not line.startswith("---"):
                click.echo(_color(f"       {line}", "red", use_color))
            else:
                click.echo(f"       {line}")


def print_summary(findings: list["Finding"], use_color: bool = True) -> None:
    """Print a one-line summary at the end of the run."""
    if not findings:
        return
    counts = Counter(f.severity for f in findings)
    parts = []
    for sev in ("critical", "high", "medium", "low", "info"):
        if counts.get(sev):
            color = SEVERITY_COLORS[sev]
            parts.append(_color(f"{counts[sev]} {sev}", color, use_color, bold=True))

    click.echo()
    click.echo("─" * 50)
    click.echo("Summary: " + ", ".join(parts))
