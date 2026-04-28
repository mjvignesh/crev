"""Tests for the JSON parsing in reviewer.parse_findings."""
from __future__ import annotations

from crev.reviewer import parse_findings


def test_parse_empty_findings():
    text = '{"findings": []}'
    assert parse_findings(text) == []


def test_parse_single_finding():
    text = '''
    {
      "findings": [
        {
          "severity": "high",
          "category": "bug",
          "file": "src/a.py",
          "line": 10,
          "title": "Off-by-one",
          "description": "Loop runs one extra time.",
          "suggestion": "Use range(n) not range(n+1).",
          "fix_diff": "--- a/src/a.py\\n+++ b/src/a.py\\n@@ @@\\n- range(n+1)\\n+ range(n)\\n",
          "rule_id": "bug/off-by-one"
        }
      ]
    }
    '''
    findings = parse_findings(text)
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == "high"
    assert f.category == "bug"
    assert f.file == "src/a.py"
    assert f.line == 10
    assert f.rule_id == "bug/off-by-one"


def test_parse_with_markdown_fences():
    text = '```json\n{"findings": [{"severity": "low", "category": "style", "file": "a.py", "title": "x", "description": "y"}]}\n```'
    findings = parse_findings(text)
    assert len(findings) == 1
    assert findings[0].severity == "low"


def test_parse_with_leading_prose():
    text = 'Sure, here is my review:\n{"findings": [{"severity": "info", "category": "style", "file": "a.py", "title": "t", "description": "d"}]}\nLet me know if you want more.'
    findings = parse_findings(text)
    assert len(findings) == 1


def test_parse_invalid_json_returns_empty():
    assert parse_findings("not json at all") == []
    assert parse_findings("") == []
    assert parse_findings("{broken") == []


def test_parse_skips_malformed_finding_entries():
    text = '{"findings": [null, "string", {"severity": "low", "category": "style", "file": "a.py", "title": "t", "description": "d"}]}'
    findings = parse_findings(text)
    # Should skip the bad entries but keep the valid one
    assert len(findings) >= 1
    assert any(f.title == "t" for f in findings)
