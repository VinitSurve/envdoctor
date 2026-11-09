"""Common project checks: .env files, port conflict detection and directory health."""

from __future__ import annotations

import json
import re
import socket
from collections.abc import Sequence
from pathlib import Path

from envdoctor.envfiles import DOTENV_FILES, env_checks, extract_dotenv_ports
from envdoctor.models import CheckResult, CheckStatus, Severity

_SCRIPT_PORT_RE = re.compile(r"(?:--port|-p|PORT=)\s*[=:]?\s*(\d{2,5})\b")
_VITE_PORT_RE = re.compile(r"\bport\s*:\s*(\d{2,5})\b")
_COMPOSE_PORT_RE = re.compile(
    r'^\s*-\s*["\']?(?:127\.0\.0\.1:|0\.0\.0\.0:)?(\d{2,5}):\d{2,5}(?:/tcp)?["\']?\s*$'
)


def is_localhost_port_listening(port: int, *, timeout: float = 0.15) -> bool:
    """Return True if a TCP listener is currently accepting connections on 127.0.0.1:port."""
    if not (1 <= port <= 65535):
        return False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return sock.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


def discover_configured_ports(root: Path) -> list[tuple[int, str]]:
    """Discover local TCP ports configured in .env, package.json, vite.config, or docker-compose."""
    discovered: list[tuple[int, str]] = []
    seen: set[int] = set()

    def _add(port: int, source: str) -> None:
        if 1 <= port <= 65535 and port not in seen:
            seen.add(port)
            discovered.append((port, source))

    for env_name in DOTENV_FILES:
        env_path = root / env_name
        for key, port_num in extract_dotenv_ports(env_path).items():
            _add(port_num, f"{env_name}:{key}")

    pkg_json = root / "package.json"
    if pkg_json.is_file() and not pkg_json.is_symlink():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8", errors="replace"))
            if isinstance(data, dict) and isinstance(data.get("scripts"), dict):
                for script_name, cmd in data["scripts"].items():
                    if isinstance(cmd, str):
                        for m in _SCRIPT_PORT_RE.finditer(cmd):
                            _add(int(m.group(1)), f"package.json:scripts.{script_name}")
        except (OSError, json.JSONDecodeError):
            pass

    for vite_cfg in ("vite.config.ts", "vite.config.js", "vite.config.mjs", "vite.config.cjs"):
        vpath = root / vite_cfg
        if vpath.is_file() and not vpath.is_symlink():
            try:
                text = vpath.read_text(encoding="utf-8", errors="replace")
                for m in _VITE_PORT_RE.finditer(text):
                    _add(int(m.group(1)), vite_cfg)
            except OSError:
                pass

    for compose_name in (
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
    ):
        cpath = root / compose_name
        if cpath.is_file() and not cpath.is_symlink():
            try:
                text = cpath.read_text(encoding="utf-8", errors="replace")
                for line in text.splitlines():
                    cm = _COMPOSE_PORT_RE.match(line)
                    if cm:
                        _add(int(cm.group(1)), compose_name)
            except OSError:
                pass

    return discovered


def check_ports(root: Path, *, enabled: bool = True) -> list[CheckResult]:
    """Check whether any project-configured port is already listening on 127.0.0.1."""
    if not enabled:
        return [
            CheckResult(
                name="ports.conflict",
                status=CheckStatus.SKIP,
                severity=Severity.INFO,
                explanation="Port conflict check disabled via configuration (check_ports=false).",
                evidence={"enabled": False},
            )
        ]

    configured = discover_configured_ports(root)
    if not configured:
        return []

    conflicts: list[dict[str, object]] = []
    checked: list[dict[str, object]] = []
    for port, source in configured:
        in_use = is_localhost_port_listening(port)
        entry = {"port": port, "source": source, "in_use": in_use}
        checked.append(entry)
        if in_use:
            conflicts.append(entry)

    if conflicts:
        desc = ", ".join(f"{c['port']} ({c['source']})" for c in conflicts)
        return [
            CheckResult(
                name="ports.conflict",
                status=CheckStatus.WARN,
                severity=Severity.MEDIUM,
                explanation=f"Configured local port(s) already in use on 127.0.0.1: {desc}.",
                suggestion=(
                    "Stop the process using the port (e.g. 'lsof -i :<port>') "
                    "or change the configured port."
                ),
                evidence={"conflicts": conflicts, "checked": checked},
            )
        ]

    return [
        CheckResult(
            name="ports.conflict",
            status=CheckStatus.OK,
            severity=Severity.INFO,
            explanation=f"All {len(checked)} configured local port(s) are available on 127.0.0.1.",
            evidence={"conflicts": [], "checked": checked},
        )
    ]


def run_common_checks(
    root: Path,
    *,
    required_env: Sequence[str] = (),
    check_ports_enabled: bool = True,
) -> list[CheckResult]:
    """Run environment-file and port-conflict checks."""
    results: list[CheckResult] = []
    results.extend(env_checks(root, required_from_config=required_env))
    results.extend(check_ports(root, enabled=check_ports_enabled))
    return results
