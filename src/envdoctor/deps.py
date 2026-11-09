"""Dependency diagnostics and conservative '--fix' installation runner."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

from envdoctor.checks import run_isolated
from envdoctor.checks.go import run_go_checks
from envdoctor.checks.java import run_java_checks
from envdoctor.checks.node import run_node_checks
from envdoctor.checks.php import run_php_checks
from envdoctor.checks.python import run_python_checks
from envdoctor.checks.rust import run_rust_checks
from envdoctor.common.paths import ensure_not_protected
from envdoctor.common.safety import redact_text, run_command
from envdoctor.detect import detect_project_types
from envdoctor.models import (
    CheckResult,
    DepFixAction,
    DepFixOutcome,
    DepsReport,
    RuntimeInfo,
    summarize_checks,
)
from envdoctor.runtimes import detect_runtimes, runtime_map

_DEP_CHECK_PREFIXES = (
    "node.package_json",
    "node.lockfile",
    "node.node_modules",
    "node.deps_integrity",
    "node.bin_links",
    "python.pyproject_toml",
    "python.lockfile",
    "python.venv",
    "python.dependencies",
    "php.composer_json",
    "php.composer_lock",
    "php.vendor",
    "rust.cargo_toml",
    "rust.lockfile",
    "go.go_mod",
    "go.go_sum",
    "java.pom_xml",
    "java.gradle_build",
)


def _tail_lines(text: str, max_lines: int = 20) -> str:
    lines = [ln for ln in redact_text(text).splitlines() if ln.strip()]
    if not lines:
        return ""
    return "\n".join(lines[-max_lines:])


def plan_dependency_fixes(root: Path, checks: list[CheckResult]) -> list[DepFixAction]:
    """Build conservative install commands for missing dependencies only.

    Rules:
    - Never delete existing dependency directories or lockfiles.
    - Never upgrade packages.
    - Never run ``mvn dependency:resolve``.
    """
    actions: list[DepFixAction] = []
    check_by_name = {c.name: c for c in checks}

    # 1. Node.js: only when node_modules is completely absent and package.json is valid
    nm_check = check_by_name.get("node.node_modules")
    pkg_check = check_by_name.get("node.package_json")
    if (
        nm_check is not None
        and nm_check.status.value == "error"
        and not (root / "node_modules").exists()
        and (pkg_check is None or pkg_check.status.value == "ok")
    ):
        if (root / "pnpm-lock.yaml").is_file():
            cmd = ["pnpm", "install", "--frozen-lockfile"]
            desc = "Install missing Node.js dependencies using pnpm lockfile"
        elif (root / "yarn.lock").is_file():
            cmd = ["yarn", "install", "--frozen-lockfile"]
            desc = "Install missing Node.js dependencies using yarn lockfile"
        elif (root / "package-lock.json").is_file():
            cmd = ["npm", "ci"]
            desc = "Clean-install missing Node.js dependencies from package-lock.json"
        else:
            cmd = ["npm", "install"]
            desc = "Install missing Node.js dependencies from package.json"
        actions.append(
            DepFixAction(
                ecosystem="nodejs",
                description=desc,
                command=cmd,
                cwd=str(root),
                safe=True,
                reason="node_modules directory is absent.",
            )
        )

    # 2. Python: only when a healthy local .venv/venv exists and requirements.txt is present
    py_dep_check = check_by_name.get("python.dependencies")
    py_venv_check = check_by_name.get("python.venv")
    if (
        py_dep_check is not None
        and py_dep_check.status.value in ("error", "warn")
        and py_venv_check is not None
        and py_venv_check.status.value == "ok"
        and (root / "requirements.txt").is_file()
    ):
        venv_name = str(py_venv_check.evidence.get("venv", ".venv"))
        venv_py = root / venv_name / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if venv_py.is_file() and os.access(venv_py, os.X_OK):
            actions.append(
                DepFixAction(
                    ecosystem="python",
                    description=f"Install missing Python requirements into existing '{venv_name}'",
                    command=[str(venv_py), "-m", "pip", "install", "-r", "requirements.txt"],
                    cwd=str(root),
                    safe=True,
                    reason=f"Packages from requirements.txt are missing in {venv_name}.",
                )
            )

    # 3. PHP / Composer: only when vendor/ is absent and composer.json is valid JSON
    php_vendor = check_by_name.get("php.vendor")
    php_json = check_by_name.get("php.composer_json")
    if (
        php_vendor is not None
        and php_vendor.status.value == "error"
        and not (root / "vendor").exists()
        and (php_json is None or php_json.status.value == "ok")
        and (root / "composer.json").is_file()
    ):
        try:
            json.loads((root / "composer.json").read_text(encoding="utf-8", errors="replace"))
            actions.append(
                DepFixAction(
                    ecosystem="composer",
                    description="Install missing Composer dependencies into vendor/",
                    command=["composer", "install", "--no-interaction"],
                    cwd=str(root),
                    safe=True,
                    reason="vendor/ directory is absent.",
                )
            )
        except (OSError, json.JSONDecodeError):
            pass

    return actions


def collect_dep_checks(
    root: Path,
    *,
    runtimes: Mapping[str, RuntimeInfo] | None = None,
    timeout: float = 5.0,
) -> tuple[list[str], list[CheckResult]]:
    """Run dependency-focused checks for ``root``."""
    project_types = detect_project_types(root)
    rt_map = (
        dict(runtimes) if runtimes is not None else runtime_map(detect_runtimes(timeout=timeout))
    )

    raw: list[CheckResult] = []
    raw.extend(run_isolated("node", lambda: run_node_checks(root, project_types, rt_map)))
    raw.extend(run_isolated("python", lambda: run_python_checks(root, project_types, rt_map)))
    raw.extend(run_isolated("java", lambda: run_java_checks(root, project_types, rt_map)))
    raw.extend(run_isolated("php", lambda: run_php_checks(root, project_types, rt_map)))
    raw.extend(run_isolated("rust", lambda: run_rust_checks(root, project_types, rt_map)))
    raw.extend(run_isolated("go", lambda: run_go_checks(root, project_types, rt_map)))

    filtered = [c for c in raw if c.name in _DEP_CHECK_PREFIXES]
    return project_types, filtered


def diagnose_dependencies(
    root: Path,
    *,
    runtimes: Mapping[str, RuntimeInfo] | None = None,
    timeout: float = 5.0,
) -> DepsReport:
    """Diagnose project dependencies and compute safe fix actions without executing them."""
    project_types, checks = collect_dep_checks(root, runtimes=runtimes, timeout=timeout)
    actions = plan_dependency_fixes(root, checks)
    _counts, overall = summarize_checks(checks)
    return DepsReport(
        path=str(root),
        project_types=project_types,
        checks=checks,
        actions=actions,
        outcomes=[],
        status=overall,
    )


def execute_dependency_fixes(
    report: DepsReport,
    *,
    dry_run: bool = False,
    fix_timeout: float = 180.0,
) -> DepsReport:
    """Execute (or preview in dry_run mode) the planned dependency installation actions."""
    root = Path(report.path)
    ensure_not_protected(root, "install dependencies in")

    outcomes: list[DepFixOutcome] = []
    if dry_run:
        for action in report.actions:
            outcomes.append(
                DepFixOutcome(
                    action=action,
                    executed=False,
                    dry_run=True,
                    ok=True,
                    returncode=0,
                    output_tail=f"[dry-run] Would run: {' '.join(action.command)}",
                )
            )
        return DepsReport(
            path=report.path,
            project_types=report.project_types,
            checks=report.checks,
            actions=report.actions,
            outcomes=outcomes,
            status=report.status,
        )

    any_failed = False
    for action in report.actions:
        res = run_command(
            action.command,
            cwd=Path(action.cwd),
            timeout=fix_timeout,
            env={"CI": "1", "LC_ALL": "C"},
        )
        combined = f"{res.stdout}\n{res.stderr}".strip()
        tail = _tail_lines(combined)
        if not res.ok:
            any_failed = True
        outcomes.append(
            DepFixOutcome(
                action=action,
                executed=True,
                dry_run=False,
                ok=res.ok,
                returncode=res.returncode,
                output_tail=tail,
                error=redact_text(res.error) if res.error else None,
            )
        )

    # Re-evaluate dependency checks after running fixes
    _, post_checks = collect_dep_checks(root)
    _, post_status = summarize_checks(post_checks)
    if any_failed:
        post_status = "error"

    return DepsReport(
        path=report.path,
        project_types=report.project_types,
        checks=post_checks,
        actions=report.actions,
        outcomes=outcomes,
        status=post_status,
    )
