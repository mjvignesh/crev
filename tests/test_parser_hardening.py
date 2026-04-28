"""Tests for hardened parser and severity/category validation."""
from __future__ import annotations

import json

from crev.reviewer import parse_findings


def test_unknown_severity_coerced_to_low():
    text = json.dumps({"findings": [{
        "severity": "🔥🔥🔥",
        "category": "bug",
        "file": "a.py",
        "title": "t",
        "description": "d",
    }]})
    findings = parse_findings(text)
    assert len(findings) == 1
    assert findings[0].severity == "low"


def test_unknown_category_coerced_to_style():
    text = json.dumps({"findings": [{
        "severity": "high",
        "category": "URGENT-FIX-NOW",
        "file": "a.py",
        "title": "t",
        "description": "d",
    }]})
    findings = parse_findings(text)
    assert len(findings) == 1
    assert findings[0].category == "style"


def test_severity_uppercase_normalized():
    text = json.dumps({"findings": [{
        "severity": "HIGH",
        "category": "BUG",
        "file": "a.py",
        "title": "t",
        "description": "d",
    }]})
    findings = parse_findings(text)
    assert findings[0].severity == "high"
    assert findings[0].category == "bug"


def test_line_as_string_coerced_to_int():
    text = json.dumps({"findings": [{
        "severity": "low", "category": "style",
        "file": "a.py", "line": "42",
        "title": "t", "description": "d",
    }]})
    findings = parse_findings(text)
    assert findings[0].line == 42


def test_line_invalid_becomes_none():
    text = json.dumps({"findings": [{
        "severity": "low", "category": "style",
        "file": "a.py", "line": "not a number",
        "title": "t", "description": "d",
    }]})
    findings = parse_findings(text)
    assert findings[0].line is None


def test_line_bool_treated_as_none():
    """bool is a subclass of int but shouldn't be treated as a line number."""
    text = json.dumps({"findings": [{
        "severity": "low", "category": "style",
        "file": "a.py", "line": True,
        "title": "t", "description": "d",
    }]})
    findings = parse_findings(text)
    assert findings[0].line is None


def test_dict_in_string_field_coerced_safely():
    """If model returns a dict where a string is expected, str() it without crashing."""
    text = json.dumps({"findings": [{
        "severity": "low", "category": "style",
        "file": "a.py", "title": "t", "description": "d",
        "suggestion": {"unexpected": "object"},
    }]})
    findings = parse_findings(text)
    assert len(findings) == 1
    assert findings[0].suggestion is not None
    assert "unexpected" in findings[0].suggestion
