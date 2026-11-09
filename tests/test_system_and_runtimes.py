"""Unit and functional tests for envdoctor system info and runtime probing."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from envdoctor.common.exceptions import ExitCode
from envdoctor.models import DiskInfo, PathSummary, SystemInfo
from envdoctor.runtimes import (
    RUNTIME_SPECS,
    detect_runtimes,
    find_all_executables,
    probe_runtime,
    runtime_checks,
)
from envdoctor.system import (
    collect_system_info,
    inspect_disk,
    inspect_path,
    system_checks,
)


def _make_fake_binary(directory: Path, name: str, script_body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    binary = directory / name
    binary.write_text(f"#!/bin/sh\n{script_body}\n", encoding="utf-8")
    binary.chmod(0o755)
    return binary


def test_inspect_path_detects_duplicates_and_missing_dirs(tmp_path: Path) -> None:
    real_a = tmp_path / "bin_a"
    real_b = tmp_path / "bin_b"
    real_a.mkdir()
    real_b.mkdir()
    missing = tmp_path / "does_not_exist"

    raw = os.pathsep.join([str(real_a), str(real_b), str(real_a), str(missing)])
    summary = inspect_path(raw)
    assert summary.total_entries == 4
    assert summary.unique_entries == 3
    assert summary.duplicates == [str(real_a)]
    assert summary.missing_dirs == [str(missing)]


def test_inspect_disk_returns_valid_metrics(tmp_path: Path) -> None:
    disk = inspect_disk(tmp_path)
    assert disk.total_bytes > 0
    assert disk.free_bytes >= 0
    assert 0.0 <= disk.percent_used <= 100.0


def test_system_checks_flags_rosetta_and_low_disk() -> None:
    user_shell = "/bin/zsh"
    info = SystemInfo(
        os_name="macOS",
        os_version="15.0",
        os_build="24A335",
        kernel_version="24.0.0",
        architecture="x86_64",
        hardware_arch="arm64",
        rosetta_translated=True,
        python_version="3.11.9",
        python_executable="/usr/local/bin/python3",
        python_arch="64bit (x86_64)",
        shell=user_shell,
        homebrew_available=True,
        homebrew_path="/usr/local/bin/brew",
        homebrew_prefix="/usr/local",
        cpu_brand="Apple M3",
        cpu_cores_logical=8,
        cpu_cores_physical=8,
        memory_total_bytes=16_000_000_000,
        disk=DiskInfo(
            path="/",
            total_bytes=100_000_000_000,
            used_bytes=99_000_000_000,
            free_bytes=1_000_000_000,
            percent_used=99.0,
        ),
        path_summary=PathSummary(
            total_entries=3,
            unique_entries=2,
            duplicates=["/usr/local/bin"],
            missing_dirs=["/nonexistent/bin"],
            entries=["/usr/local/bin", "/usr/local/bin", "/nonexistent/bin"],
        ),
        warnings=["Rosetta warning"],
    )
    checks = {c.name: c for c in system_checks(info)}
    assert checks["system.architecture"].status.value == "warn"
    assert checks["system.path_duplicates"].status.value == "warn"
    assert checks["system.path_missing_dirs"].status.value == "warn"
    assert checks["system.disk_space"].status.value == "warn"


def test_collect_system_info_runs_cleanly(tmp_path: Path) -> None:
    info = collect_system_info(target_path=tmp_path, timeout=2.0)
    assert info.python_version
    assert info.architecture
    assert info.disk.total_bytes > 0


def test_find_all_executables_and_duplicates(tmp_path: Path) -> None:
    dir1 = tmp_path / "d1"
    dir2 = tmp_path / "d2"
    b1 = _make_fake_binary(dir1, "node", 'echo "v20.11.0"')
    b2 = _make_fake_binary(dir2, "node", 'echo "v18.19.0"')
    raw_path = os.pathsep.join([str(dir1), str(dir2)])

    matches = find_all_executables(("node",), raw_path=raw_path)
    assert matches == [str(b1), str(b2)]

    node_spec = next(s for s in RUNTIME_SPECS if s.name == "node")
    rt = probe_runtime(node_spec, raw_path=raw_path)
    assert rt.found is True
    assert rt.healthy is True
    assert rt.version == "20.11.0"
    assert rt.path == str(b1)
    assert rt.duplicates == [str(b2)]
    assert rt.status == "warn"


def test_probe_runtime_detects_macos_java_stub(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    _make_fake_binary(
        bin_dir,
        "java",
        'echo "The operation couldn’t be completed. Unable to locate a Java Runtime." >&2\nexit 1',
    )
    java_spec = next(s for s in RUNTIME_SPECS if s.name == "java")
    rt = probe_runtime(java_spec, raw_path=str(bin_dir))
    assert rt.found is True
    assert rt.healthy is False
    assert rt.status == "error"
    assert rt.issue is not None and "Java Runtime" in rt.issue


def test_probe_runtime_detects_xcode_clt_shim(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    _make_fake_binary(
        bin_dir,
        "git",
        'echo "xcode-select: note: no developer tools were found" >&2\nexit 1',
    )
    git_spec = next(s for s in RUNTIME_SPECS if s.name == "git")
    rt = probe_runtime(git_spec, raw_path=str(bin_dir))
    assert rt.found is True
    assert rt.healthy is False
    assert rt.status == "error"
    assert rt.issue is not None and "Xcode Command Line Tools" in rt.issue


def test_probe_runtime_detects_timeout_and_nonzero_exit(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    _make_fake_binary(bin_dir, "ruby", "sleep 5\nexit 0")
    _make_fake_binary(bin_dir, "php", 'echo "Segmentation fault" >&2\nexit 139')

    ruby_spec = next(s for s in RUNTIME_SPECS if s.name == "ruby")
    rt_timeout = probe_runtime(ruby_spec, timeout=0.2, raw_path=f"{bin_dir}:/bin:/usr/bin")
    assert rt_timeout.found is True
    assert rt_timeout.healthy is False
    assert rt_timeout.status == "error"
    assert rt_timeout.issue is not None and "timed out" in rt_timeout.issue

    php_spec = next(s for s in RUNTIME_SPECS if s.name == "php")
    rt_crash = probe_runtime(php_spec, timeout=2.0, raw_path=str(bin_dir))
    assert rt_crash.found is True
    assert rt_crash.healthy is False
    assert rt_crash.status == "error"
    assert rt_crash.issue is not None and "failed version check" in rt_crash.issue


def test_probe_runtime_docker_daemon_states(tmp_path: Path) -> None:
    docker_spec = next(s for s in RUNTIME_SPECS if s.name == "docker")

    # 1. Docker CLI + responsive daemon
    dir_ok = tmp_path / "docker_ok"
    _make_fake_binary(
        dir_ok,
        "docker",
        'if [ "$1" = "--version" ]; then echo "Docker version 26.1.0, build 9714adc"; exit 0; fi\n'
        'if [ "$1" = "info" ]; then echo "26.1.0"; exit 0; fi\nexit 1',
    )
    rt_ok = probe_runtime(docker_spec, raw_path=str(dir_ok))
    assert rt_ok.found is True and rt_ok.healthy is True
    assert rt_ok.version == "26.1.0"
    assert rt_ok.daemon_running is True
    assert rt_ok.status == "ok"

    # 2. Docker CLI + daemon down
    dir_down = tmp_path / "docker_down"
    _make_fake_binary(
        dir_down,
        "docker",
        'if [ "$1" = "--version" ]; then echo "Docker version 26.1.0, build 9714adc"; exit 0; fi\n'
        'echo "Cannot connect to the Docker daemon" >&2\nexit 1',
    )
    rt_down = probe_runtime(docker_spec, raw_path=str(dir_down))
    assert rt_down.found is True and rt_down.healthy is True
    assert rt_down.daemon_running is False
    assert rt_down.status == "warn"


def test_detect_runtimes_when_all_tools_absent(tmp_path: Path) -> None:
    empty_bin = tmp_path / "empty_bin"
    empty_bin.mkdir()
    runtimes = detect_runtimes(raw_path=str(empty_bin))
    assert len(runtimes) == len(RUNTIME_SPECS)
    assert all(not rt.found for rt in runtimes)
    checks = runtime_checks(runtimes)
    assert all(c.status.value == "skip" for c in checks)


def test_cli_info_and_runtimes(run: Callable[..., Any], tmp_path: Path) -> None:
    res_info = run("envdoctor", "info", "--json")
    assert res_info.exit_code == 0
    payload = res_info.json()
    assert "os_name" in payload and "python_version" in payload and "path_summary" in payload

    res_human = run("envdoctor", "info")
    assert res_human.exit_code == 0
    assert "System & Environment Overview" in res_human.stdout

    # Test runtimes with a broken shim on PATH -> exit code 1 (WARNING)
    bad_bin = tmp_path / "bad_bin"
    _make_fake_binary(
        bad_bin,
        "java",
        'echo "Unable to locate a Java Runtime." >&2\nexit 1',
    )
    res_rt = run("envdoctor", "runtimes", "--json", env={"PATH": f"{bad_bin}:/bin:/usr/bin"})
    assert res_rt.exit_code == int(ExitCode.WARNING)
    rt_data = res_rt.json()
    assert rt_data["broken_count"] >= 1

    # Test runtimes when all present tools are healthy -> exit code 0
    good_bin = tmp_path / "good_bin"
    _make_fake_binary(good_bin, "node", 'echo "v20.12.0"')
    res_rt_ok = run("envdoctor", "runtimes", "--json", env={"PATH": str(good_bin)})
    assert res_rt_ok.exit_code == int(ExitCode.OK)
    assert res_rt_ok.json()["broken_count"] == 0
