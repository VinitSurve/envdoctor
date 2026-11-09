"""System, macOS, architecture, Rosetta, Homebrew, disk, CPU/memory and PATH inspection."""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path

from envdoctor.common.fsutil import human_size
from envdoctor.common.safety import run_command, which
from envdoctor.models import (
    CheckResult,
    CheckStatus,
    DiskInfo,
    PathSummary,
    Severity,
    SystemInfo,
)


def inspect_path(raw_path: str | None = None) -> PathSummary:
    """Analyze PATH entries for count, duplicates and nonexistent directories."""
    env_path = os.environ.get("PATH", "") if raw_path is None else raw_path
    entries = [p for p in env_path.split(os.pathsep) if p != ""]
    seen: set[str] = set()
    duplicates: list[str] = []
    missing_dirs: list[str] = []

    for entry in entries:
        norm = os.path.normpath(os.path.expanduser(entry))
        if norm in seen:
            if entry not in duplicates:
                duplicates.append(entry)
        else:
            seen.add(norm)
            expanded = Path(os.path.expanduser(entry))
            try:
                exists = expanded.is_dir()
            except OSError:
                exists = False
            if not exists:
                missing_dirs.append(entry)

    return PathSummary(
        total_entries=len(entries),
        unique_entries=len(seen),
        duplicates=duplicates,
        missing_dirs=missing_dirs,
        entries=entries,
    )


def inspect_disk(target: Path | None = None) -> DiskInfo:
    """Return disk space statistics for ``target`` (defaults to cwd or root)."""
    probe = target or Path.cwd()
    try:
        if not probe.exists():
            probe = Path("/")
        usage = shutil.disk_usage(probe)
    except OSError:
        usage = shutil.disk_usage("/")
        probe = Path("/")
    pct = round((usage.used / usage.total) * 100.0, 1) if usage.total > 0 else 0.0
    return DiskInfo(
        path=str(probe),
        total_bytes=int(usage.total),
        used_bytes=int(usage.used),
        free_bytes=int(usage.free),
        percent_used=pct,
    )


def _sysctl_value(key: str, *, timeout: float = 2.0) -> str | None:
    if sys.platform != "darwin":
        return None
    res = run_command(["sysctl", "-n", key], timeout=timeout, env={"LC_ALL": "C"})
    if res.ok and res.stdout.strip():
        return res.stdout.strip()
    return None


def _macos_sw_vers(*, timeout: float = 2.0) -> tuple[str, str, str]:
    """Return ``(product_name, product_version, build_version)`` on macOS."""
    if sys.platform == "darwin":
        res = run_command(["sw_vers"], timeout=timeout, env={"LC_ALL": "C"})
        if res.ok and res.stdout:
            values: dict[str, str] = {}
            for line in res.stdout.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    values[k.strip()] = v.strip()
            name = values.get("ProductName", "macOS")
            ver = values.get("ProductVersion", platform.mac_ver()[0] or platform.release())
            build = values.get("BuildVersion", "")
            return name, ver, build
        mac_ver = platform.mac_ver()[0]
        if mac_ver:
            return "macOS", mac_ver, ""
    return platform.system() or "Unknown", platform.release() or "Unknown", ""


def _detect_architecture(*, timeout: float = 2.0) -> tuple[str, str, bool]:
    """Return ``(process_arch, hardware_arch, rosetta_translated)``."""
    uname_res = run_command(["uname", "-m"], timeout=timeout, env={"LC_ALL": "C"})
    proc_arch = uname_res.stdout.strip() if uname_res.ok and uname_res.stdout.strip() else ""
    if not proc_arch:
        proc_arch = platform.machine() or "unknown"

    translated = _sysctl_value("sysctl.proc_translated", timeout=timeout) == "1"
    arm64_capable = _sysctl_value("hw.optional.arm64", timeout=timeout) == "1"
    hw_arch = "arm64" if arm64_capable else proc_arch

    py_machine = platform.machine()
    rosetta = translated or (
        hw_arch == "arm64" and (proc_arch == "x86_64" or py_machine == "x86_64")
    )
    return proc_arch, hw_arch, rosetta


def _detect_homebrew() -> tuple[bool, str | None, str | None]:
    """Check if Homebrew is available on PATH or standard macOS locations."""
    brew_bin = which("brew")
    if not brew_bin:
        for candidate in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
            cpath = Path(candidate)
            if cpath.is_file() and os.access(cpath, os.X_OK):
                brew_bin = candidate
                break
    if not brew_bin:
        return False, None, None
    prefix = str(Path(brew_bin).resolve().parent.parent)
    return True, brew_bin, prefix


def _detect_cpu_and_memory(*, timeout: float = 2.0) -> tuple[str, int, int | None, int | None]:
    logical = os.cpu_count() or 1
    brand = _sysctl_value("machdep.cpu.brand_string", timeout=timeout)
    if not brand:
        brand = platform.processor() or platform.machine() or "unknown"

    phys_raw = _sysctl_value("hw.physicalcpu", timeout=timeout)
    physical = int(phys_raw) if phys_raw and phys_raw.isdigit() else None

    mem_raw = _sysctl_value("hw.memsize", timeout=timeout)
    memory_bytes: int | None = int(mem_raw) if mem_raw and mem_raw.isdigit() else None
    if memory_bytes is None:
        try:
            page_size = os.sysconf("SC_PAGE_SIZE")
            phys_pages = os.sysconf("SC_PHYS_PAGES")
            if (
                isinstance(page_size, int)
                and isinstance(phys_pages, int)
                and page_size > 0
                and phys_pages > 0
            ):
                memory_bytes = page_size * phys_pages
        except (AttributeError, ValueError, OSError):
            memory_bytes = None

    return brand, logical, physical, memory_bytes


def collect_system_info(*, target_path: Path | None = None, timeout: float = 3.0) -> SystemInfo:
    """Gather comprehensive system, OS, architecture, Python, Homebrew, PATH and disk info."""
    os_name, os_version, os_build = _macos_sw_vers(timeout=timeout)
    proc_arch, hw_arch, rosetta = _detect_architecture(timeout=timeout)
    brew_avail, brew_path, brew_prefix = _detect_homebrew()
    cpu_brand, logical_cores, physical_cores, mem_bytes = _detect_cpu_and_memory(timeout=timeout)
    path_summary = inspect_path()
    disk_info = inspect_disk(target_path)
    py_arch = f"{platform.architecture()[0]} ({platform.machine()})"
    shell = os.environ.get("SHELL", "") or "unknown"

    warnings: list[str] = []
    if rosetta:
        warnings.append(
            "Running under Rosetta (x86_64 translation) on Apple Silicon; "
            "native arm64 Python/tools are recommended."
        )
    if hw_arch == "arm64" and brew_prefix and brew_prefix.startswith("/usr/local"):
        warnings.append(
            f"Homebrew is installed under {brew_prefix} (Intel prefix) on Apple Silicon "
            "instead of /opt/homebrew."
        )
    if path_summary.duplicates:
        dup_preview = ", ".join(path_summary.duplicates[:5])
        warnings.append(
            f"PATH contains {len(path_summary.duplicates)} duplicate entry/entries: {dup_preview}."
        )
    if path_summary.missing_dirs:
        miss_preview = ", ".join(path_summary.missing_dirs[:5])
        warnings.append(
            f"PATH references {len(path_summary.missing_dirs)} nonexistent "
            f"directory/directories: {miss_preview}."
        )
    if disk_info.free_bytes < 2 * 1000**3 or disk_info.percent_used >= 95.0:
        free_str = human_size(disk_info.free_bytes)
        warnings.append(
            f"Low free disk space on {disk_info.path}: {free_str} free "
            f"({disk_info.percent_used:.1f}% used)."
        )

    return SystemInfo(
        os_name=os_name,
        os_version=os_version,
        os_build=os_build,
        kernel_version=platform.release(),
        architecture=proc_arch,
        hardware_arch=hw_arch,
        rosetta_translated=rosetta,
        python_version=platform.python_version(),
        python_executable=sys.executable,
        python_arch=py_arch,
        shell=shell,
        homebrew_available=brew_avail,
        homebrew_path=brew_path,
        homebrew_prefix=brew_prefix,
        cpu_brand=cpu_brand,
        cpu_cores_logical=logical_cores,
        cpu_cores_physical=physical_cores,
        memory_total_bytes=mem_bytes,
        disk=disk_info,
        path_summary=path_summary,
        warnings=warnings,
    )


def system_checks(info: SystemInfo) -> list[CheckResult]:
    """Convert SystemInfo observations into structured CheckResult items for reports."""
    results: list[CheckResult] = []

    if info.rosetta_translated:
        results.append(
            CheckResult(
                name="system.architecture",
                status=CheckStatus.WARN,
                severity=Severity.MEDIUM,
                explanation=(
                    f"Process is running as {info.architecture} under Rosetta translation on "
                    f"Apple Silicon ({info.hardware_arch})."
                ),
                suggestion="Install a native arm64 Python and terminal configuration.",
                evidence={
                    "process_arch": info.architecture,
                    "hardware_arch": info.hardware_arch,
                    "rosetta_translated": True,
                },
            )
        )
    else:
        results.append(
            CheckResult(
                name="system.architecture",
                status=CheckStatus.OK,
                severity=Severity.INFO,
                explanation=(
                    f"Native {info.architecture} execution ({info.os_name} {info.os_version})."
                ),
                evidence={
                    "process_arch": info.architecture,
                    "hardware_arch": info.hardware_arch,
                    "rosetta_translated": False,
                },
            )
        )

    if info.path_summary.duplicates:
        dup_count = len(info.path_summary.duplicates)
        results.append(
            CheckResult(
                name="system.path_duplicates",
                status=CheckStatus.WARN,
                severity=Severity.LOW,
                explanation=f"PATH has {dup_count} duplicate directory entry/entries.",
                suggestion=(
                    "Deduplicate PATH entries in ~/.zshrc or ~/.zprofile "
                    "(e.g. 'typeset -U path PATH')."
                ),
                evidence={"duplicates": info.path_summary.duplicates},
            )
        )
    else:
        results.append(
            CheckResult(
                name="system.path_duplicates",
                status=CheckStatus.OK,
                severity=Severity.INFO,
                explanation=(
                    f"PATH has {info.path_summary.total_entries} entries with no duplicates."
                ),
                evidence={"total_entries": info.path_summary.total_entries},
            )
        )

    if info.path_summary.missing_dirs:
        miss_count = len(info.path_summary.missing_dirs)
        results.append(
            CheckResult(
                name="system.path_missing_dirs",
                status=CheckStatus.WARN,
                severity=Severity.LOW,
                explanation=f"PATH contains {miss_count} nonexistent directory/directories.",
                suggestion="Remove stale PATH entries from your shell configuration.",
                evidence={"missing_dirs": info.path_summary.missing_dirs},
            )
        )
    else:
        results.append(
            CheckResult(
                name="system.path_missing_dirs",
                status=CheckStatus.OK,
                severity=Severity.INFO,
                explanation="All directories in PATH exist.",
                evidence={"missing_dirs": []},
            )
        )

    if info.disk.free_bytes < 2 * 1000**3 or info.disk.percent_used >= 95.0:
        results.append(
            CheckResult(
                name="system.disk_space",
                status=CheckStatus.WARN,
                severity=Severity.HIGH,
                explanation=(
                    f"Low disk space on {info.disk.path}: {human_size(info.disk.free_bytes)} free "
                    f"({info.disk.percent_used:.1f}% used)."
                ),
                suggestion=(
                    "Free up disk space (try 'disklens' to inspect large directories and caches)."
                ),
                evidence={
                    "free_bytes": info.disk.free_bytes,
                    "total_bytes": info.disk.total_bytes,
                    "percent_used": info.disk.percent_used,
                },
            )
        )
    else:
        results.append(
            CheckResult(
                name="system.disk_space",
                status=CheckStatus.OK,
                severity=Severity.INFO,
                explanation=(
                    f"Disk space healthy: {human_size(info.disk.free_bytes)} free of "
                    f"{human_size(info.disk.total_bytes)} ({info.disk.percent_used:.1f}% used)."
                ),
                evidence={
                    "free_bytes": info.disk.free_bytes,
                    "total_bytes": info.disk.total_bytes,
                    "percent_used": info.disk.percent_used,
                },
            )
        )

    return results
