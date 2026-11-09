"""Runtime discovery, PATH duplicate detection and active health verification."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from envdoctor.common.safety import run_command
from envdoctor.models import CheckResult, CheckStatus, RuntimeInfo, Severity


@dataclass(frozen=True)
class RuntimeSpec:
    """Specification of a developer runtime to probe."""

    name: str
    binaries: tuple[str, ...]
    version_args: tuple[str, ...]
    version_pattern: str


RUNTIME_SPECS: tuple[RuntimeSpec, ...] = (
    RuntimeSpec(
        "python", ("python3", "python"), ("--version",), r"Python\s+([0-9][0-9A-Za-z.\-_+]*)"
    ),
    RuntimeSpec("node", ("node",), ("--version",), r"v?([0-9]+\.[0-9]+\.[0-9]+[0-9A-Za-z.\-_+]*)"),
    RuntimeSpec("npm", ("npm",), ("--version",), r"v?([0-9]+\.[0-9]+\.[0-9]+[0-9A-Za-z.\-_+]*)"),
    RuntimeSpec("pnpm", ("pnpm",), ("--version",), r"v?([0-9]+\.[0-9]+\.[0-9]+[0-9A-Za-z.\-_+]*)"),
    RuntimeSpec("yarn", ("yarn",), ("--version",), r"v?([0-9]+\.[0-9]+\.[0-9]+[0-9A-Za-z.\-_+]*)"),
    RuntimeSpec(
        "java",
        ("java",),
        ("-version",),
        r'(?:version\s+"|openjdk\s+|java\s+)([0-9][0-9A-Za-z._\-+]*)',
    ),
    RuntimeSpec("git", ("git",), ("--version",), r"git version\s+([0-9][0-9A-Za-z.\-_+()]*)"),
    RuntimeSpec("go", ("go",), ("version",), r"go version go([0-9][0-9A-Za-z.\-_+]*)"),
    RuntimeSpec("rustc", ("rustc",), ("--version",), r"rustc\s+([0-9][0-9A-Za-z.\-_+]*)"),
    RuntimeSpec("cargo", ("cargo",), ("--version",), r"cargo\s+([0-9][0-9A-Za-z.\-_+]*)"),
    RuntimeSpec("ruby", ("ruby",), ("--version",), r"ruby\s+([0-9][0-9A-Za-z.\-_+]*)"),
    RuntimeSpec("php", ("php",), ("--version",), r"PHP\s+([0-9][0-9A-Za-z.\-_+]*)"),
    RuntimeSpec(
        "docker", ("docker",), ("--version",), r"Docker version\s+([0-9][0-9A-Za-z.\-_+]*)"
    ),
)

_BROKEN_SHIM_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (
        "Unable to locate a Java Runtime",
        "macOS /usr/bin/java stub is present, but no Java Runtime (JDK/JRE) is installed.",
        "Install a JDK (for example 'brew install openjdk') and add its bin directory to PATH.",
    ),
    (
        "No Java runtime present",
        "macOS Java stub is present, but no Java Runtime is installed.",
        "Install a JDK (for example 'brew install openjdk') and configure JAVA_HOME.",
    ),
    (
        "xcode-select: note: no developer tools were found",
        "macOS Xcode Command Line Tools shim is present, but developer tools are not installed.",
        "Run 'xcode-select --install' to install the Command Line Tools.",
    ),
    (
        "xcrun: error: invalid active developer path",
        "macOS Xcode Command Line Tools path is invalid or missing after an OS update.",
        "Run 'xcode-select --install' or 'sudo xcode-select --reset'.",
    ),
    (
        "rustup could not choose a version",
        "rustup proxy shim is present, but no default Rust toolchain is configured.",
        "Run 'rustup default stable' to configure a default Rust toolchain.",
    ),
)


def find_all_executables(binary_names: tuple[str, ...], raw_path: str | None = None) -> list[str]:
    """Find all executable matches for ``binary_names`` across PATH directories in order."""
    env_path = os.environ.get("PATH", "") if raw_path is None else raw_path
    dirs = [d for d in env_path.split(os.pathsep) if d]
    found: list[str] = []
    seen_paths: set[str] = set()

    for directory in dirs:
        expanded_dir = Path(os.path.expanduser(directory))
        for name in binary_names:
            candidate = expanded_dir / name
            norm = os.path.abspath(candidate)
            if norm in seen_paths:
                continue
            try:
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    seen_paths.add(norm)
                    found.append(str(candidate))
            except OSError:
                continue
    return found


def _extract_version(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    generic = re.search(r"v?(\d+\.\d+(?:\.\d+)?(?:-[A-Za-z0-9._\-]+)?)", first_line)
    if generic:
        return generic.group(1)
    return first_line[:64] if first_line else None


def probe_runtime(
    spec: RuntimeSpec, *, timeout: float = 5.0, raw_path: str | None = None
) -> RuntimeInfo:
    """Locate and verify a single runtime, including broken shims and Docker daemon health."""
    matches = find_all_executables(spec.binaries, raw_path=raw_path)
    if not matches:
        return RuntimeInfo(
            name=spec.name,
            binary=spec.binaries[0],
            found=False,
            healthy=False,
            status="missing",
            version=None,
            path=None,
            duplicates=[],
        )

    primary = matches[0]
    binary_name = Path(primary).name
    duplicates = matches[1:]
    probe_env = {
        "LC_ALL": "C",
        "GIT_TERMINAL_PROMPT": "0",
        "CI": "1",
    }
    res = run_command([primary, *spec.version_args], timeout=timeout, env=probe_env)
    combined = f"{res.stdout}\n{res.stderr}".strip()

    if res.timed_out:
        return RuntimeInfo(
            name=spec.name,
            binary=binary_name,
            found=True,
            healthy=False,
            status="error",
            version=None,
            path=primary,
            duplicates=duplicates,
            issue=(
                f"Command '{primary} {' '.join(spec.version_args)}' timed out after {timeout:g}s."
            ),
            suggestion=f"Verify that {primary} is not hanging or prompting interactively.",
        )

    for marker, shim_explanation, shim_suggestion in _BROKEN_SHIM_PATTERNS:
        if marker.lower() in combined.lower():
            return RuntimeInfo(
                name=spec.name,
                binary=binary_name,
                found=True,
                healthy=False,
                status="error",
                version=None,
                path=primary,
                duplicates=duplicates,
                issue=shim_explanation,
                suggestion=shim_suggestion,
            )

    if not res.ok:
        first_err = next(
            (ln.strip() for ln in combined.splitlines() if ln.strip()),
            res.error or "exit non-zero",
        )
        return RuntimeInfo(
            name=spec.name,
            binary=binary_name,
            found=True,
            healthy=False,
            status="error",
            version=None,
            path=primary,
            duplicates=duplicates,
            issue=(
                f"Executable at {primary} failed version check "
                f"(exit {res.returncode}): {first_err[:140]}"
            ),
            suggestion=f"Reinstall {spec.name} or check PATH ordering.",
        )

    version = _extract_version(spec.version_pattern, combined)
    daemon_running: bool | None = None
    issue: str | None = None
    suggestion: str | None = None
    status = "ok"

    if spec.name == "docker":
        daemon_timeout = min(timeout, 3.0)
        d_res = run_command(
            [primary, "info", "--format", "{{.ServerVersion}}"],
            timeout=daemon_timeout,
            env=probe_env,
        )
        if d_res.ok:
            daemon_running = True
        else:
            daemon_running = False
            status = "warn"
            issue = "Docker CLI is installed, but the Docker daemon is not responding."
            suggestion = (
                "Start Docker Desktop, OrbStack, or Colima before running container commands."
            )

    if duplicates and status == "ok":
        status = "warn"
        issue = f"Multiple {spec.name} executables on PATH ({len(duplicates) + 1} found)."
        suggestion = f"Active binary is {primary}; shadowed: {', '.join(duplicates[:3])}."

    return RuntimeInfo(
        name=spec.name,
        binary=binary_name,
        found=True,
        healthy=True,
        status=status,
        version=version,
        path=primary,
        duplicates=duplicates,
        daemon_running=daemon_running,
        issue=issue,
        suggestion=suggestion,
    )


def detect_runtimes(*, timeout: float = 5.0, raw_path: str | None = None) -> list[RuntimeInfo]:
    """Probe all supported developer runtimes in order."""
    return [probe_runtime(spec, timeout=timeout, raw_path=raw_path) for spec in RUNTIME_SPECS]


def runtime_map(runtimes: list[RuntimeInfo]) -> dict[str, RuntimeInfo]:
    """Index RuntimeInfo list by runtime name."""
    return {rt.name: rt for rt in runtimes}


def runtime_checks(runtimes: list[RuntimeInfo]) -> list[CheckResult]:
    """Convert probed runtimes into structured CheckResult items for 'envdoctor report'."""
    results: list[CheckResult] = []
    for rt in runtimes:
        if not rt.found:
            results.append(
                CheckResult(
                    name=f"runtime.{rt.name}",
                    status=CheckStatus.SKIP,
                    severity=Severity.INFO,
                    explanation=f"{rt.name} is not installed on PATH.",
                    evidence={"found": False, "binary": rt.binary},
                )
            )
            continue
        if not rt.healthy:
            results.append(
                CheckResult(
                    name=f"runtime.{rt.name}",
                    status=CheckStatus.ERROR,
                    severity=Severity.HIGH,
                    explanation=rt.issue or f"{rt.name} at {rt.path} is broken or unresponsive.",
                    suggestion=rt.suggestion or f"Reinstall {rt.name}.",
                    evidence={
                        "found": True,
                        "healthy": False,
                        "path": rt.path,
                        "duplicates": rt.duplicates,
                    },
                )
            )
            continue
        if rt.status == "warn":
            results.append(
                CheckResult(
                    name=f"runtime.{rt.name}",
                    status=CheckStatus.WARN,
                    severity=Severity.LOW,
                    explanation=rt.issue or f"{rt.name} {rt.version} has warnings.",
                    suggestion=rt.suggestion or "",
                    evidence={
                        "found": True,
                        "healthy": True,
                        "version": rt.version,
                        "path": rt.path,
                        "duplicates": rt.duplicates,
                        "daemon_running": rt.daemon_running,
                    },
                )
            )
        else:
            results.append(
                CheckResult(
                    name=f"runtime.{rt.name}",
                    status=CheckStatus.OK,
                    severity=Severity.INFO,
                    explanation=f"{rt.name} {rt.version or ''} is healthy at {rt.path}.".strip(),
                    evidence={
                        "found": True,
                        "healthy": True,
                        "version": rt.version,
                        "path": rt.path,
                        "duplicates": rt.duplicates,
                        "daemon_running": rt.daemon_running,
                    },
                )
            )
    return results
