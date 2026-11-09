"""Unit tests for envdoctor version matching and domain models."""

from __future__ import annotations

import pytest

from envdoctor.common.exceptions import ExitCode
from envdoctor.models import (
    CheckResult,
    CheckStatus,
    Severity,
    exit_code_for_status,
    summarize_checks,
)
from envdoctor.versions import (
    match_pep440,
    match_semver_range,
    parse_java_version,
    parse_version,
)


def test_parse_version_variants() -> None:
    assert parse_version("20.11.1") == (20, 11, 1)
    assert parse_version("v18.2") == (18, 2, 0)
    assert parse_version("V3") == (3, 0, 0)
    assert parse_version("1.76.0-aarch64-apple-darwin") == (1, 76, 0)
    assert parse_version("Node.js v22.4.0 (LTS)") == (22, 4, 0)
    assert parse_version("") is None
    assert parse_version("18.x") is None
    assert parse_version("not-a-version") is None


def test_parse_java_version() -> None:
    assert parse_java_version("1.8.0_392") == 8
    assert parse_java_version("1.8") == 8
    assert parse_java_version("11.0.22") == 11
    assert parse_java_version("17") == 17
    assert parse_java_version("21.0.2+13-LTS") == 21
    assert parse_java_version("17.0.21.0.2") == 17
    assert parse_java_version("") is None
    assert parse_java_version("invalid") is None


@pytest.mark.parametrize(
    ("version", "spec", "expected"),
    [
        ("20.11.0", ">=18", True),
        ("16.20.2", ">=18", False),
        ("18.19.0", "^18.17 || >=20", True),
        ("18.12.0", "^18.17 || >=20", False),
        ("21.0.0", "^18.17 || >=20", True),
        ("18.4.2", "18.x", True),
        ("19.0.0", "18.x", False),
        ("20.1.5", "~20.1", True),
        ("20.2.0", "~20.1", False),
        ("20.5.0", "~20", True),
        ("19.0.0", "18.0.0 - 20.0.0", True),
        ("21.0.0", "18.0.0 - 20.0.0", False),
        ("0.2.3", "^0.2.1", True),
        ("0.3.0", "^0.2.1", False),
        ("0.0.4", "^0.0.4", True),
        ("0.0.5", "^0.0.4", False),
        ("18.0.0", "*", True),
        ("18.0.0", ">=18.0.0 <20.0.0", True),
        ("20.0.0", ">=18.0.0 <20.0.0", False),
        ("18.0.0", "!=18.0.0", False),
        ("18.1.0", "!=18.0.0", True),
        ("18.1.0", ">18.0.0 <=18.2.0", True),
    ],
)
def test_match_semver_range(version: str, spec: str, expected: bool) -> None:
    assert match_semver_range(version, spec) is expected


def test_match_semver_range_conservative_on_unparseable() -> None:
    assert match_semver_range("20.0.0", "lts/*") is None
    assert match_semver_range("20.0.0", "node") is None
    assert match_semver_range("20.0.0", "") is None
    assert match_semver_range("bad", ">=18") is None


@pytest.mark.parametrize(
    ("version", "spec", "expected"),
    [
        ("3.11.8", ">=3.11,<4", True),
        ("3.10.12", ">=3.11,<4", False),
        ("4.0.0", ">=3.11,<4", False),
        ("3.12.1", "~=3.11", True),
        ("4.0.0", "~=3.11", False),
        ("3.11.5", "~=3.11.2", True),
        ("3.12.0", "~=3.11.2", False),
        ("3.11.9", "==3.11.*", True),
        ("3.12.0", "==3.11.*", False),
        ("3.11.9", "!=3.10.*", True),
        ("3.10.4", "!=3.10.*", False),
    ],
)
def test_match_pep440(version: str, spec: str, expected: bool) -> None:
    assert match_pep440(version, spec) is expected


def test_match_pep440_unparseable_returns_none() -> None:
    assert match_pep440("3.11.0", "===3.11") is None
    assert match_pep440("3.11.0", "") is None
    assert match_pep440("unknown", ">=3.11") is None


def test_check_result_redacts_secrets_automatically() -> None:
    chk = CheckResult(
        name="demo.secret",
        status=CheckStatus.WARN,
        severity=Severity.HIGH,
        explanation="Found password=SuperSecret12345 in output",
        suggestion="Remove token=ghp_1234567890abcdefABCDEF",
        evidence={
            "api_key": "sk-1234567890abcdef1234567890",
            "safe_count": 3,
        },
    )
    assert "SuperSecret12345" not in chk.explanation
    assert "ghp_1234567890abcdefABCDEF" not in chk.suggestion
    assert chk.evidence["api_key"] == "***REDACTED***"
    assert chk.evidence["safe_count"] == 3


def test_summarize_checks_and_exit_codes() -> None:
    ok_only = [
        CheckResult("a", CheckStatus.OK, Severity.INFO, "ok"),
        CheckResult("b", CheckStatus.SKIP, Severity.INFO, "skip"),
    ]
    counts, status = summarize_checks(ok_only)
    assert status == "ok"
    assert counts == {"ok": 1, "warn": 0, "error": 0, "skip": 1}
    assert exit_code_for_status(status) == ExitCode.OK

    with_warn = [*ok_only, CheckResult("c", CheckStatus.WARN, Severity.LOW, "warn")]
    counts, status = summarize_checks(with_warn)
    assert status == "warn"
    assert exit_code_for_status(status) == ExitCode.WARNING

    with_err = [*with_warn, CheckResult("d", CheckStatus.ERROR, Severity.HIGH, "err")]
    counts, status = summarize_checks(with_err)
    assert status == "error"
    assert exit_code_for_status(status) == ExitCode.ERROR
