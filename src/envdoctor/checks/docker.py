"""Docker and Docker Compose project checks."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from envdoctor.models import CheckResult, CheckStatus, RuntimeInfo, Severity

_FROM_RE = re.compile(r"^\s*FROM\s+(--platform=\S+\s+)?(\S+)", re.IGNORECASE)


def _check_dockerfile(root: Path) -> list[CheckResult]:
    results: list[CheckResult] = []
    for name in ("Dockerfile", "Containerfile"):
        dpath = root / name
        if not dpath.is_file() or dpath.is_symlink():
            continue
        try:
            text = dpath.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            results.append(
                CheckResult(
                    name="docker.dockerfile",
                    status=CheckStatus.ERROR,
                    severity=Severity.HIGH,
                    explanation=f"Cannot read '{name}': {exc}",
                    suggestion=f"Check file permissions on '{name}'.",
                    evidence={"file": name},
                )
            )
            continue

        images: list[str] = []
        for line in text.splitlines():
            clean = line.strip()
            if not clean or clean.startswith("#"):
                continue
            m = _FROM_RE.match(clean)
            if m:
                images.append(m.group(2))

        if not images:
            results.append(
                CheckResult(
                    name="docker.dockerfile",
                    status=CheckStatus.ERROR,
                    severity=Severity.HIGH,
                    explanation=f"'{name}' is invalid: missing a 'FROM <image>' instruction.",
                    suggestion=f"Add a valid 'FROM' base image instruction to '{name}'.",
                    evidence={"file": name, "base_images": []},
                )
            )
            continue

        unpinned = [
            img
            for img in images
            if img.lower() != "scratch"
            and (img.endswith(":latest") or (":" not in img and "@" not in img))
        ]
        if unpinned:
            results.append(
                CheckResult(
                    name="docker.dockerfile",
                    status=CheckStatus.WARN,
                    severity=Severity.LOW,
                    explanation=(
                        f"'{name}' uses unpinned or ':latest' base image(s): {', '.join(unpinned)}."
                    ),
                    suggestion=(
                        "Pin a specific base image version tag or digest for reproducible builds."
                    ),
                    evidence={"file": name, "base_images": images, "unpinned": unpinned},
                )
            )
        else:
            results.append(
                CheckResult(
                    name="docker.dockerfile",
                    status=CheckStatus.OK,
                    severity=Severity.INFO,
                    explanation=(
                        f"'{name}' is valid with pinned base image(s): {', '.join(images)}."
                    ),
                    evidence={"file": name, "base_images": images},
                )
            )
    return results


def _check_compose(root: Path) -> list[CheckResult]:
    results: list[CheckResult] = []
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        cpath = root / name
        if not cpath.is_file() or cpath.is_symlink():
            continue
        try:
            text = cpath.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            results.append(
                CheckResult(
                    name="docker.compose",
                    status=CheckStatus.ERROR,
                    severity=Severity.HIGH,
                    explanation=f"Cannot read '{name}': {exc}",
                    suggestion=f"Check file permissions on '{name}'.",
                    evidence={"file": name},
                )
            )
            continue

        if not text.strip():
            results.append(
                CheckResult(
                    name="docker.compose",
                    status=CheckStatus.ERROR,
                    severity=Severity.HIGH,
                    explanation=f"'{name}' is empty.",
                    suggestion=f"Add a 'services:' section to '{name}'.",
                    evidence={"file": name},
                )
            )
            continue

        has_tabs = any(
            line.startswith("\t")
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
        has_services = bool(re.search(r"(?m)^\s*services\s*:", text))
        if has_tabs or not has_services:
            reason = (
                "contains leading tab characters (invalid YAML indentation)"
                if has_tabs
                else "missing a 'services:' section"
            )
            results.append(
                CheckResult(
                    name="docker.compose",
                    status=CheckStatus.ERROR,
                    severity=Severity.HIGH,
                    explanation=f"'{name}' is invalid: {reason}.",
                    suggestion=(
                        f"Fix the YAML syntax and ensure 'services:' is defined in '{name}'."
                    ),
                    evidence={"file": name, "has_services": has_services, "has_tabs": has_tabs},
                )
            )
        else:
            results.append(
                CheckResult(
                    name="docker.compose",
                    status=CheckStatus.OK,
                    severity=Severity.INFO,
                    explanation=f"'{name}' has a valid 'services:' section.",
                    evidence={"file": name, "has_services": True},
                )
            )
    return results


def run_docker_checks(
    root: Path,
    project_types: Sequence[str],
    runtimes: Mapping[str, RuntimeInfo],
) -> list[CheckResult]:
    """Run Docker and Compose project checks."""
    if "docker" not in project_types:
        return []

    results: list[CheckResult] = []
    results.extend(_check_dockerfile(root))
    results.extend(_check_compose(root))

    docker_rt = runtimes.get("docker")
    if not docker_rt or not docker_rt.found:
        results.append(
            CheckResult(
                name="docker.runtime",
                status=CheckStatus.WARN,
                severity=Severity.MEDIUM,
                explanation=(
                    "Docker configuration files are present, "
                    "but 'docker' CLI is not installed on PATH."
                ),
                suggestion=(
                    "Install Docker Desktop, OrbStack, or Colima "
                    "if you build or run containers locally."
                ),
                evidence={"found": False, "daemon_running": None},
            )
        )
    elif not docker_rt.healthy:
        results.append(
            CheckResult(
                name="docker.runtime",
                status=CheckStatus.ERROR,
                severity=Severity.HIGH,
                explanation=docker_rt.issue or "Docker CLI is broken or unresponsive.",
                suggestion=docker_rt.suggestion or "Reinstall Docker.",
                evidence={"found": True, "healthy": False, "daemon_running": False},
            )
        )
    elif docker_rt.daemon_running is False:
        results.append(
            CheckResult(
                name="docker.runtime",
                status=CheckStatus.WARN,
                severity=Severity.MEDIUM,
                explanation=(
                    "Docker CLI is installed, but the Docker daemon is not currently running."
                ),
                suggestion="Start Docker Desktop, OrbStack, or Colima.",
                evidence={"found": True, "version": docker_rt.version, "daemon_running": False},
            )
        )
    else:
        results.append(
            CheckResult(
                name="docker.runtime",
                status=CheckStatus.OK,
                severity=Severity.INFO,
                explanation=f"Docker {docker_rt.version} and daemon are responsive.",
                evidence={"found": True, "version": docker_rt.version, "daemon_running": True},
            )
        )

    return results
