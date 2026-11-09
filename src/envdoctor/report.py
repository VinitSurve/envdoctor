"""Structured report generation and safe atomic file export for 'envdoctor report'."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from envdoctor.checks import run_project_checks
from envdoctor.common.exceptions import (
    NotFoundError,
    PermissionDeniedError,
    SafetyError,
    UsageError,
)
from envdoctor.common.fsutil import atomic_write_text, file_kind
from envdoctor.common.output import dumps_json
from envdoctor.common.paths import ensure_not_protected, resolve_user_path
from envdoctor.models import (
    CheckResult,
    CheckStatus,
    FullReport,
    Severity,
    summarize_checks,
)
from envdoctor.runtimes import detect_runtimes, runtime_checks, runtime_map
from envdoctor.system import collect_system_info, system_checks


def build_full_report(
    root: Path,
    *,
    required_env: Sequence[str] = (),
    check_ports_enabled: bool = True,
    ignore_checks: Sequence[str] = (),
    timeout: float = 5.0,
) -> FullReport:
    """Collect system info, runtimes and project checks into one structured FullReport."""
    ignored = {c.strip() for c in ignore_checks if c.strip()}
    sys_info = collect_system_info(target_path=root, timeout=min(timeout, 3.0))
    runtimes = detect_runtimes(timeout=timeout)
    rt_map = runtime_map(runtimes)

    all_checks: list[CheckResult] = []
    for chk in system_checks(sys_info) + runtime_checks(runtimes):
        if chk.name in ignored:
            all_checks.append(
                CheckResult(
                    name=chk.name,
                    status=CheckStatus.SKIP,
                    severity=Severity.INFO,
                    explanation=f"Skipped via ignore_checks configuration ({chk.name}).",
                    evidence={"ignored": True},
                )
            )
        else:
            all_checks.append(chk)

    proj_report = run_project_checks(
        root,
        runtimes=rt_map,
        required_env=required_env,
        check_ports_enabled=check_ports_enabled,
        ignore_checks=ignore_checks,
        timeout=timeout,
    )
    all_checks.extend(proj_report.checks)
    counts, overall = summarize_checks(all_checks)

    return FullReport(
        path=str(root),
        status=overall,
        system=sys_info,
        runtimes=runtimes,
        project_types=proj_report.project_types,
        project_type_labels=proj_report.project_type_labels,
        checks=all_checks,
        summary=counts,
    )


def write_report_file(report: FullReport, raw_output: str | Path, *, force: bool = False) -> Path:
    """Write ``report`` as JSON atomically to ``raw_output`` with strict safety checks.

    - Refuses protected system paths.
    - Refuses paths whose parent directory does not already exist.
    - Refuses to overwrite an existing file unless ``force=True``.
    - Refuses to write through a symlink target.
    """
    out_path = resolve_user_path(raw_output)
    ensure_not_protected(out_path, "write report to")

    parent = out_path.parent
    if not parent.exists():
        raise NotFoundError(
            f"Output directory does not exist: {parent}",
            hint="Choose an existing directory for --output.",
        )
    if not parent.is_dir():
        raise UsageError(f"Output parent path is not a directory: {parent}")

    kind = file_kind(out_path)
    if kind == "symlink":
        raise SafetyError(
            f"Refusing to write report to symlink: {out_path}",
            hint="Specify a regular file path instead.",
        )
    if kind == "dir":
        raise UsageError(f"Output path is a directory, not a file: {out_path}")
    if kind in ("file", "special") and not force:
        raise SafetyError(
            f"Output file already exists: {out_path}",
            hint="Pass --force to overwrite the existing file.",
        )

    if not os.access(parent, os.W_OK | os.X_OK):
        raise PermissionDeniedError(
            f"Permission denied writing to directory: {parent}",
            hint="Choose a writable output directory.",
        )

    try:
        atomic_write_text(out_path, dumps_json(report) + "\n")
    except PermissionError as exc:
        raise PermissionDeniedError(
            f"Permission denied writing report file: {out_path}",
            hint="Check file and directory permissions.",
        ) from exc
    except OSError as exc:
        raise PermissionDeniedError(f"Could not write report file {out_path}: {exc}") from exc

    return out_path
