"""Isolated check runner that orchestrates ecosystem and common checks."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from envdoctor.checks.common import run_common_checks
from envdoctor.checks.docker import run_docker_checks
from envdoctor.checks.go import run_go_checks
from envdoctor.checks.java import run_java_checks
from envdoctor.checks.node import run_node_checks
from envdoctor.checks.php import run_php_checks
from envdoctor.checks.python import run_python_checks
from envdoctor.checks.rust import run_rust_checks
from envdoctor.detect import detect_project_types, labels_for_types
from envdoctor.models import (
    CheckResult,
    CheckStatus,
    ProjectCheckReport,
    RuntimeInfo,
    Severity,
    summarize_checks,
)
from envdoctor.runtimes import detect_runtimes, runtime_map


def run_isolated(name: str, fn: Callable[[], list[CheckResult]]) -> list[CheckResult]:
    """Execute a check function in isolation so an unhandled error never aborts the run."""
    try:
        return fn()
    except Exception as exc:
        return [
            CheckResult(
                name=f"{name}.internal_error",
                status=CheckStatus.ERROR,
                severity=Severity.MEDIUM,
                explanation=(
                    f"Check '{name}' encountered an unexpected error: {type(exc).__name__}: {exc}"
                ),
                suggestion="Re-run with --verbose for details.",
                evidence={"check": name, "error_type": type(exc).__name__},
            )
        ]


def run_project_checks(
    root: Path,
    *,
    runtimes: Mapping[str, RuntimeInfo] | None = None,
    required_env: Sequence[str] = (),
    check_ports_enabled: bool = True,
    ignore_checks: Sequence[str] = (),
    timeout: float = 5.0,
) -> ProjectCheckReport:
    """Detect project types in ``root`` and run all applicable checks safely."""
    project_types = detect_project_types(root)
    labels = labels_for_types(project_types)
    rt_map = (
        dict(runtimes) if runtimes is not None else runtime_map(detect_runtimes(timeout=timeout))
    )
    ignored = {c.strip() for c in ignore_checks if c.strip()}

    raw_checks: list[CheckResult] = []
    if not project_types:
        raw_checks.append(
            CheckResult(
                name="project.detection",
                status=CheckStatus.SKIP,
                severity=Severity.INFO,
                explanation="No known project manifests found in this directory.",
                suggestion="Run 'envdoctor check PATH' inside a project directory.",
                evidence={"path": str(root), "project_types": []},
            )
        )
    else:
        raw_checks.append(
            CheckResult(
                name="project.detection",
                status=CheckStatus.OK,
                severity=Severity.INFO,
                explanation=f"Detected project type(s): {', '.join(labels)}.",
                evidence={"project_types": project_types, "labels": labels},
            )
        )

    suites: list[tuple[str, Callable[[], list[CheckResult]]]] = [
        (
            "common",
            lambda: run_common_checks(
                root, required_env=required_env, check_ports_enabled=check_ports_enabled
            ),
        ),
        ("node", lambda: run_node_checks(root, project_types, rt_map)),
        ("python", lambda: run_python_checks(root, project_types, rt_map)),
        ("java", lambda: run_java_checks(root, project_types, rt_map)),
        ("php", lambda: run_php_checks(root, project_types, rt_map)),
        ("rust", lambda: run_rust_checks(root, project_types, rt_map)),
        ("go", lambda: run_go_checks(root, project_types, rt_map)),
        ("docker", lambda: run_docker_checks(root, project_types, rt_map)),
    ]

    for suite_name, suite_fn in suites:
        raw_checks.extend(run_isolated(suite_name, suite_fn))

    final_checks: list[CheckResult] = []
    for chk in raw_checks:
        if chk.name in ignored:
            final_checks.append(
                CheckResult(
                    name=chk.name,
                    status=CheckStatus.SKIP,
                    severity=Severity.INFO,
                    explanation=f"Skipped via ignore_checks configuration ({chk.name}).",
                    evidence={"ignored": True},
                )
            )
        else:
            final_checks.append(chk)

    counts, overall = summarize_checks(final_checks)
    return ProjectCheckReport(
        path=str(root),
        project_types=project_types,
        project_type_labels=labels,
        checks=final_checks,
        summary=counts,
        status=overall,
    )
