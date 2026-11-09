"""Command line interface for envdoctor."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any

import typer

from envdoctor.checks import run_project_checks
from envdoctor.common.cli import (
    ToolContext,
    add_config_commands,
    create_app,
    exit_with,
    get_ctx,
    run_app,
)
from envdoctor.common.config import ConfigStore
from envdoctor.common.exceptions import ExitCode
from envdoctor.common.fsutil import human_size
from envdoctor.common.output import Output
from envdoctor.common.paths import require_directory, resolve_user_path
from envdoctor.common.safety import require_confirmation
from envdoctor.config import SCHEMA
from envdoctor.deps import diagnose_dependencies, execute_dependency_fixes
from envdoctor.envfiles import inspect_env
from envdoctor.models import (
    CheckResult,
    DepsReport,
    EnvReport,
    FullReport,
    ProjectCheckReport,
    RuntimeInfo,
    SystemInfo,
    exit_code_for_status,
)
from envdoctor.report import build_full_report, write_report_file
from envdoctor.runtimes import detect_runtimes
from envdoctor.system import collect_system_info

TOOL = "envdoctor"


def _load_cfg(tctx: ToolContext) -> dict[str, Any]:
    store = ConfigStore(tctx.paths, SCHEMA)
    return store.load()


def _resolve_project_dir(raw_path: str) -> Path:
    resolved = resolve_user_path(raw_path)
    return require_directory(resolved, what="Project path")


def _render_system_info(out: Output, info: SystemInfo) -> None:
    out.banner()
    out.heading("System & Environment Overview")
    os_label = f"{info.os_name} {info.os_version}"
    if info.os_build:
        os_label += f" ({info.os_build})"
    arch_label = info.architecture
    if info.rosetta_translated:
        arch_label += f" (Rosetta on {info.hardware_arch})"
    elif info.hardware_arch and info.hardware_arch != info.architecture:
        arch_label += f" (hardware: {info.hardware_arch})"

    brew_str = (
        f"{info.homebrew_path} (prefix: {info.homebrew_prefix})"
        if info.homebrew_available
        else "not found"
    )
    cores_str = str(info.cpu_cores_logical)
    if info.cpu_cores_physical:
        cores_str = f"{info.cpu_cores_physical} physical / {info.cpu_cores_logical} logical"
    mem_str = human_size(info.memory_total_bytes) if info.memory_total_bytes else "unknown"
    disk_str = (
        f"{human_size(info.disk.free_bytes)} free / {human_size(info.disk.total_bytes)} total "
        f"({info.disk.percent_used:.1f}% used)"
    )
    path_str = (
        f"{info.path_summary.total_entries} entries "
        f"({info.path_summary.unique_entries} unique, "
        f"{len(info.path_summary.duplicates)} duplicates, "
        f"{len(info.path_summary.missing_dirs)} missing)"
    )

    out.kv(
        [
            ("OS", os_label),
            ("Kernel", info.kernel_version),
            ("Architecture", arch_label),
            ("CPU", f"{info.cpu_brand} ({cores_str})"),
            ("Memory", mem_str),
            ("Python", f"{info.python_version} ({info.python_arch}) — {info.python_executable}"),
            ("Shell", info.shell),
            ("Homebrew", brew_str),
            ("Disk", disk_str),
            ("PATH", path_str),
        ]
    )

    if info.warnings:
        out.text()
        out.heading("Observations")
        for warn_msg in info.warnings:
            out.status("warn", warn_msg)
    else:
        out.text()
        out.success("System environment looks healthy.")


def _render_runtimes(out: Output, runtimes: list[RuntimeInfo]) -> None:
    out.banner()
    out.heading("Developer Runtimes")
    rows: list[list[str]] = []
    for rt in runtimes:
        if not rt.found:
            status_cell = "– missing"
            ver_cell = "—"
            loc_cell = "not on PATH"
            notes = ""
        elif not rt.healthy:
            status_cell = "✗ broken"
            ver_cell = "error"
            loc_cell = rt.path or rt.binary
            notes = rt.issue or "broken install"
        elif rt.status == "warn":
            status_cell = "⚠ warn"
            ver_cell = rt.version or "unknown"
            loc_cell = rt.path or rt.binary
            notes = rt.issue or ""
        else:
            status_cell = "✓ ok"
            ver_cell = rt.version or "ok"
            loc_cell = rt.path or rt.binary
            notes = (
                "daemon running"
                if rt.name == "docker" and rt.daemon_running
                else (f"+{len(rt.duplicates)} dup" if rt.duplicates else "")
            )
        rows.append([rt.name, status_cell, ver_cell, loc_cell, notes])

    out.table(["Runtime", "Status", "Version", "Executable", "Notes"], rows)

    broken = [r for r in runtimes if r.found and not r.healthy]
    if broken:
        out.text()
        out.heading("Broken Runtimes")
        for r in broken:
            out.status("error", f"{r.name}: {r.issue}")
            if r.suggestion:
                out.muted(f"  Suggestion: {r.suggestion}")


def _render_checks_table(
    out: Output, checks: list[CheckResult], *, title: str | None = None
) -> None:
    rows: list[list[str]] = []
    for chk in checks:
        sym = {
            "ok": "✓ ok",
            "warn": "⚠ warn",
            "error": "✗ error",
            "skip": "– skip",
        }.get(chk.status.value, chk.status.value)
        detail = chk.explanation
        if chk.suggestion and chk.status.value in ("warn", "error"):
            detail = f"{detail} → {chk.suggestion}"
        rows.append([chk.name, sym, chk.severity.value, detail])
    out.table(["Check", "Status", "Severity", "Details"], rows, title=title)


def _render_project_check(out: Output, report: ProjectCheckReport) -> None:
    out.banner()
    out.heading(f"Project Diagnostics: {report.path}")
    types_str = (
        ", ".join(report.project_type_labels) if report.project_type_labels else "None detected"
    )
    out.kv([("Detected Types", types_str), ("Overall Status", report.status.upper())])
    out.text()
    _render_checks_table(out, report.checks)
    out.summary(
        "Check Summary",
        [
            ("OK", str(report.summary.get("ok", 0))),
            ("Warnings", str(report.summary.get("warn", 0))),
            ("Errors", str(report.summary.get("error", 0))),
            ("Skipped", str(report.summary.get("skip", 0))),
        ],
    )


def _render_deps_report(out: Output, report: DepsReport) -> None:
    out.banner()
    out.heading(f"Dependency Diagnostics: {report.path}")
    if report.checks:
        _render_checks_table(out, report.checks)
    else:
        out.info("No dependency manifests detected in this directory.")

    if report.actions:
        out.text()
        out.heading("Planned Safe Fixes")
        for act in report.actions:
            out.status("info", f"[{act.ecosystem}] {act.description}: {' '.join(act.command)}")

    if report.outcomes:
        out.text()
        out.heading("Fix Execution Outcomes")
        for oc in report.outcomes:
            kind = "info" if oc.dry_run else ("ok" if oc.ok else "error")
            cmd_str = " ".join(oc.action.command)
            label = f"[dry-run] {cmd_str}" if oc.dry_run else f"{cmd_str} (exit {oc.returncode})"
            out.status(kind, label)
            if oc.output_tail:
                out.muted(oc.output_tail)
            if oc.error:
                out.status("error", oc.error)


def _render_env_report(out: Output, report: EnvReport) -> None:
    out.banner()
    out.heading(f"Environment Variable Inspection: {report.path}")
    out.kv(
        [
            ("Requirement Sources", ", ".join(report.sources) if report.sources else "none"),
            ("Dotenv Files", ", ".join(report.dotenv_files) if report.dotenv_files else "none"),
            ("Missing Keys", str(len(report.missing_keys))),
            ("Empty Keys", str(len(report.empty_keys))),
            ("Present Keys", str(len(report.present_keys))),
        ]
    )
    if report.variables:
        rows: list[list[str]] = []
        for var in report.variables:
            st = {
                "present": "✓ present",
                "empty": "⚠ empty",
                "missing": "✗ missing",
            }.get(var.status, var.status)
            dotenv_state = "empty" if var.dotenv_empty else ("yes" if var.in_dotenv else "no")
            env_state = "empty" if var.environ_empty else ("yes" if var.in_environ else "no")
            rows.append([var.name, st, dotenv_state, env_state, ", ".join(var.required_by)])
        out.table(["Variable", "Status", "In .env", "In Environ", "Required By"], rows)
    else:
        out.info("No required environment variable templates (.env.example) or rules found.")


def _render_full_report(out: Output, report: FullReport, saved_to: Path | None = None) -> None:
    out.banner()
    out.heading(f"Full Environment & Project Report: {report.path}")
    out.kv(
        [
            (
                "OS",
                f"{report.system.os_name} {report.system.os_version} "
                f"({report.system.architecture})",
            ),
            ("Python", f"{report.system.python_version} ({report.system.python_executable})"),
            (
                "Project Types",
                ", ".join(report.project_type_labels)
                if report.project_type_labels
                else "None detected",
            ),
            ("Overall Status", report.status.upper()),
        ]
    )
    out.text()
    _render_checks_table(out, report.checks, title="All Diagnostic Checks")
    out.summary(
        "Report Summary",
        [
            ("OK", str(report.summary.get("ok", 0))),
            ("Warnings", str(report.summary.get("warn", 0))),
            ("Errors", str(report.summary.get("error", 0))),
            ("Skipped", str(report.summary.get("skip", 0))),
        ],
    )
    if saved_to is not None:
        out.success(f"Report written to {saved_to}")


def _default_action(ctx: typer.Context) -> None:
    tctx = get_ctx(ctx)
    cfg = _load_cfg(tctx)
    info = collect_system_info(timeout=float(cfg["command_timeout"]))
    tctx.out.emit(info, lambda o: _render_system_info(o, info))


app = create_app(
    TOOL,
    "Diagnose your development environment: runtimes, projects, dependencies and env vars.",
    default=_default_action,
)
add_config_commands(app, TOOL, SCHEMA)


@app.command("info")
def cmd_info(ctx: typer.Context) -> None:
    """Show macOS/system version, architecture, Rosetta status, Python, Homebrew, PATH and disk."""
    tctx = get_ctx(ctx)
    cfg = _load_cfg(tctx)
    info = collect_system_info(timeout=float(cfg["command_timeout"]))
    tctx.out.emit(info, lambda o: _render_system_info(o, info))


@app.command("runtimes")
def cmd_runtimes(ctx: typer.Context) -> None:
    """Detect developer runtimes, locations, PATH duplicates and verify health."""
    tctx = get_ctx(ctx)
    cfg = _load_cfg(tctx)
    runtimes = detect_runtimes(timeout=float(cfg["command_timeout"]))
    broken = [rt for rt in runtimes if rt.found and not rt.healthy]
    payload = {
        "runtimes": runtimes,
        "broken_count": len(broken),
        "found_count": sum(1 for rt in runtimes if rt.found),
    }
    tctx.out.emit(payload, lambda o: _render_runtimes(o, runtimes))
    if broken:
        exit_with(ExitCode.WARNING)


@app.command("check")
def cmd_check(
    ctx: typer.Context,
    path: Annotated[
        str,
        typer.Argument(help="Project directory to inspect (defaults to current directory)."),
    ] = ".",
) -> None:
    """Auto-detect project types and run manifest, runtime, dependency, port and config checks."""
    tctx = get_ctx(ctx)
    cfg = _load_cfg(tctx)
    project_dir = _resolve_project_dir(path)
    report = run_project_checks(
        project_dir,
        required_env=cfg["required_env"],
        check_ports_enabled=bool(cfg["check_ports"]),
        ignore_checks=cfg["ignore_checks"],
        timeout=float(cfg["command_timeout"]),
    )
    tctx.out.emit(report, lambda o: _render_project_check(o, report))
    code = exit_code_for_status(report.status)
    if code != ExitCode.OK:
        exit_with(code)


@app.command("deps")
def cmd_deps(
    ctx: typer.Context,
    path: Annotated[
        str,
        typer.Argument(help="Project directory to inspect (defaults to current directory)."),
    ] = ".",
    fix: Annotated[
        bool,
        typer.Option("--fix", help="Conservatively install missing dependencies where safe."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Show the install commands that --fix would run without executing them.",
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Approve dependency installation non-interactively."),
    ] = False,
) -> None:
    """Diagnose project dependency problems and optionally install missing dependencies safely."""
    tctx = get_ctx(ctx)
    cfg = _load_cfg(tctx)
    project_dir = _resolve_project_dir(path)
    report = diagnose_dependencies(project_dir, timeout=float(cfg["command_timeout"]))

    if dry_run:
        report = execute_dependency_fixes(
            report, dry_run=True, fix_timeout=float(cfg["fix_timeout"])
        )
    elif fix and report.actions:
        cmd_preview = "; ".join(" ".join(a.command) for a in report.actions)
        require_confirmation(
            tctx.out,
            f"Run {len(report.actions)} dependency install command(s) "
            f"({cmd_preview}) in {project_dir}?",
            assume_yes=yes,
        )
        report = execute_dependency_fixes(
            report, dry_run=False, fix_timeout=float(cfg["fix_timeout"])
        )

    tctx.out.emit(report, lambda o: _render_deps_report(o, report))
    code = exit_code_for_status(report.status)
    if code != ExitCode.OK:
        exit_with(code)


@app.command("env")
def cmd_env(
    ctx: typer.Context,
    path: Annotated[
        str,
        typer.Argument(help="Project directory to inspect (defaults to current directory)."),
    ] = ".",
    check: Annotated[
        bool,
        typer.Option(
            "--check",
            help="Exit non-zero when required environment variables are missing or empty.",
        ),
    ] = False,
) -> None:
    """Compare required environment variable names against .env files and process environment."""
    tctx = get_ctx(ctx)
    cfg = _load_cfg(tctx)
    project_dir = _resolve_project_dir(path)
    report = inspect_env(project_dir, required_from_config=cfg["required_env"])
    tctx.out.emit(report, lambda o: _render_env_report(o, report))
    if check:
        if report.missing_keys:
            exit_with(ExitCode.ERROR)
        if report.empty_keys:
            exit_with(ExitCode.WARNING)


@app.command("report")
def cmd_report(
    ctx: typer.Context,
    path: Annotated[
        str,
        typer.Argument(help="Project directory to inspect (defaults to current directory)."),
    ] = ".",
    output: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Write the structured JSON report atomically to FILE."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Allow overwriting an existing --output file."),
    ] = False,
) -> None:
    """Generate a full structured diagnostic report covering system, runtimes and project checks."""
    tctx = get_ctx(ctx)
    cfg = _load_cfg(tctx)
    project_dir = _resolve_project_dir(path)
    report = build_full_report(
        project_dir,
        required_env=cfg["required_env"],
        check_ports_enabled=bool(cfg["check_ports"]),
        ignore_checks=cfg["ignore_checks"],
        timeout=float(cfg["command_timeout"]),
    )
    saved_path: Path | None = None
    if output is not None:
        saved_path = write_report_file(report, output, force=force)

    tctx.out.emit(report, lambda o: _render_full_report(o, report, saved_to=saved_path))
    code = exit_code_for_status(report.status)
    if code != ExitCode.OK:
        exit_with(code)


def main(argv: Sequence[str] | None = None) -> int:
    """Console-script entry point; returns the process exit code."""
    return run_app(app, tool=TOOL, argv=argv)
