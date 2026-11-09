"""Safe .env parsing and environment variable comparison.

Security invariant: values read from ``.env`` files or ``os.environ`` are NEVER stored,
returned, logged, or included in check evidence. Only variable names and boolean
presence/emptiness flags are retained.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from envdoctor.models import (
    CheckResult,
    CheckStatus,
    EnvReport,
    EnvVarEntry,
    Severity,
)

TEMPLATE_FILES: tuple[str, ...] = (
    ".env.example",
    ".env.sample",
    ".env.template",
    ".env.dist",
)
DOTENV_FILES: tuple[str, ...] = (
    ".env",
    ".env.local",
)

_ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*(?:=(.*))?$")
_COMPOSE_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:[:?+\-][^}]*)?\}")
_COMPOSE_BARE_ENV_RE = re.compile(r"^\s*-\s*([A-Za-z_][A-Za-z0-9_]*)\s*$")
_PORT_KEYS = {
    "PORT",
    "APP_PORT",
    "SERVER_PORT",
    "VITE_PORT",
    "NEXT_PORT",
    "DJANGO_PORT",
    "FLASK_RUN_PORT",
    "HTTP_PORT",
}


def _is_value_non_empty(raw_val: str | None) -> bool:
    """Return True if the right-hand side of KEY=VALUE is non-empty, discarding the value."""
    if raw_val is None:
        return False
    val = raw_val.strip()
    if not val:
        return False
    if (val.startswith('"') and val.endswith('"') and len(val) >= 2) or (
        val.startswith("'") and val.endswith("'") and len(val) >= 2
    ):
        inner = val[1:-1]
        return len(inner) > 0
    # Strip inline comment if preceded by whitespace
    uncommented = re.split(r"\s+#", val, maxsplit=1)[0].strip()
    return len(uncommented) > 0


def parse_dotenv_keys(path: Path) -> dict[str, bool]:
    """Parse a dotenv file into ``{VAR_NAME: is_non_empty}`` without retaining any values."""
    result: dict[str, bool] = {}
    try:
        if not path.is_file() or path.is_symlink():
            return result
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for idx, line in enumerate(handle):
                if idx > 10_000:
                    break
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                match = _ENV_LINE_RE.match(stripped)
                if not match:
                    continue
                key = match.group(1)
                rhs = match.group(2)
                result[key] = _is_value_non_empty(rhs)
    except OSError:
        return result
    return result


def extract_dotenv_ports(path: Path) -> dict[str, int]:
    """Extract only validated integer port numbers (1..65535) for known ``*PORT`` keys."""
    ports: dict[str, int] = {}
    try:
        if not path.is_file() or path.is_symlink():
            return ports
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for idx, line in enumerate(handle):
                if idx > 5_000:
                    break
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                match = _ENV_LINE_RE.match(stripped)
                if not match:
                    continue
                key = match.group(1)
                if key.upper() not in _PORT_KEYS and not key.upper().endswith("_PORT"):
                    continue
                rhs = (match.group(2) or "").strip().strip('"').strip("'")
                rhs = re.split(r"\s+#", rhs, maxsplit=1)[0].strip()
                if rhs.isdigit():
                    port_num = int(rhs)
                    if 1 <= port_num <= 65535:
                        ports[key] = port_num
    except OSError:
        return ports
    return ports


def _discover_compose_required_vars(root: Path) -> dict[str, str]:
    """Find variable names referenced in docker-compose files without defaults."""
    found: dict[str, str] = {}
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        cpath = root / name
        if not cpath.is_file() or cpath.is_symlink():
            continue
        try:
            text = cpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in _COMPOSE_VAR_RE.finditer(text):
            full = match.group(0)
            var_name = match.group(1)
            # Skip variables that provide a fallback default (${VAR:-default} or ${VAR-default})
            if ":-" in full or (f"${{{var_name}-" in full and ":?" not in full):
                continue
            found.setdefault(var_name, name)
        for line in text.splitlines():
            bare = _COMPOSE_BARE_ENV_RE.match(line)
            if bare:
                found.setdefault(bare.group(1), name)
    return found


def _discover_manifest_required_vars(root: Path) -> dict[str, str]:
    """Find required env variable names declared in package.json or pyproject.toml if any."""
    found: dict[str, str] = {}
    pkg_json = root / "package.json"
    if pkg_json.is_file() and not pkg_json.is_symlink():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8", errors="replace"))
            if isinstance(data, dict):
                env_list = data.get("requiredEnv") or data.get("env")
                if isinstance(env_list, list):
                    for item in env_list:
                        if isinstance(item, str) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", item):
                            found.setdefault(item, "package.json")
        except (OSError, json.JSONDecodeError):
            pass
    return found


def inspect_env(
    root: Path,
    *,
    required_from_config: Sequence[str] = (),
    environ: Mapping[str, str] | None = None,
) -> EnvReport:
    """Compare required variable names against project ``.env`` files and ``os.environ``."""
    proc_env = os.environ if environ is None else environ
    sources: list[str] = []
    required_sources: dict[str, list[str]] = {}

    def _record_req(var_name: str, src: str) -> None:
        if src not in sources:
            sources.append(src)
        bucket = required_sources.setdefault(var_name, [])
        if src not in bucket:
            bucket.append(src)

    for tmpl_name in TEMPLATE_FILES:
        tmpl_path = root / tmpl_name
        if tmpl_path.is_file() and not tmpl_path.is_symlink():
            if tmpl_name not in sources:
                sources.append(tmpl_name)
            for key in parse_dotenv_keys(tmpl_path):
                _record_req(key, tmpl_name)

    for var_name, src in _discover_compose_required_vars(root).items():
        _record_req(var_name, src)

    for var_name, src in _discover_manifest_required_vars(root).items():
        _record_req(var_name, src)

    for cfg_key in required_from_config:
        clean = cfg_key.strip()
        if clean:
            _record_req(clean, "config:required_env")

    dotenv_files: list[str] = []
    merged_dotenv: dict[str, bool] = {}
    for env_name in DOTENV_FILES:
        env_path = root / env_name
        if env_path.is_file() and not env_path.is_symlink():
            dotenv_files.append(env_name)
            for k, non_empty in parse_dotenv_keys(env_path).items():
                merged_dotenv[k] = merged_dotenv.get(k, False) or non_empty

    variables: list[EnvVarEntry] = []
    missing_keys: list[str] = []
    empty_keys: list[str] = []
    present_keys: list[str] = []

    for var_name in sorted(required_sources):
        in_dotenv = var_name in merged_dotenv
        dotenv_non_empty = merged_dotenv.get(var_name, False)
        dotenv_empty = in_dotenv and not dotenv_non_empty

        in_environ = var_name in proc_env
        environ_non_empty = bool(proc_env.get(var_name, "")) if in_environ else False
        environ_empty = in_environ and not environ_non_empty

        if dotenv_non_empty or environ_non_empty:
            status = "present"
            present_keys.append(var_name)
        elif in_dotenv or in_environ:
            status = "empty"
            empty_keys.append(var_name)
        else:
            status = "missing"
            missing_keys.append(var_name)

        variables.append(
            EnvVarEntry(
                name=var_name,
                required_by=required_sources[var_name],
                in_dotenv=in_dotenv,
                dotenv_empty=dotenv_empty,
                in_environ=in_environ,
                environ_empty=environ_empty,
                status=status,
            )
        )

    extra_dotenv_keys = sorted(k for k in merged_dotenv if k not in required_sources)
    healthy = len(missing_keys) == 0 and len(empty_keys) == 0

    return EnvReport(
        path=str(root),
        sources=sources,
        dotenv_files=dotenv_files,
        variables=variables,
        missing_keys=missing_keys,
        empty_keys=empty_keys,
        present_keys=present_keys,
        extra_dotenv_keys=extra_dotenv_keys,
        healthy=healthy,
    )


def env_checks(
    root: Path,
    *,
    required_from_config: Sequence[str] = (),
    environ: Mapping[str, str] | None = None,
) -> list[CheckResult]:
    """Generate CheckResult items for .env presence and required variable coverage."""
    results: list[CheckResult] = []
    report = inspect_env(root, required_from_config=required_from_config, environ=environ)

    existing_templates = [
        name
        for name in TEMPLATE_FILES
        if (root / name).is_file() and not (root / name).is_symlink()
    ]
    has_dotenv = len(report.dotenv_files) > 0

    if existing_templates and not has_dotenv:
        tmpl = existing_templates[0]
        results.append(
            CheckResult(
                name="env.dotenv_file",
                status=CheckStatus.WARN if not report.missing_keys else CheckStatus.ERROR,
                severity=Severity.HIGH if report.missing_keys else Severity.MEDIUM,
                explanation=f"Template '{tmpl}' exists, but '.env' is missing.",
                suggestion=f"Copy the template with 'cp {tmpl} .env' and fill in required values.",
                evidence={
                    "templates": existing_templates,
                    "dotenv_exists": False,
                    "missing_count": len(report.missing_keys),
                },
            )
        )
    elif existing_templates and has_dotenv:
        results.append(
            CheckResult(
                name="env.dotenv_file",
                status=CheckStatus.OK,
                severity=Severity.INFO,
                explanation=(
                    f"Found {', '.join(report.dotenv_files)} matching template "
                    f"{', '.join(existing_templates)}."
                ),
                evidence={
                    "templates": existing_templates,
                    "dotenv_exists": True,
                    "dotenv_files": report.dotenv_files,
                },
            )
        )

    if not report.variables:
        if has_dotenv:
            results.append(
                CheckResult(
                    name="env.required_keys",
                    status=CheckStatus.OK,
                    severity=Severity.INFO,
                    explanation=(
                        f"Loaded {len(report.extra_dotenv_keys)} key(s) from "
                        f"{', '.join(report.dotenv_files)} (no template constraints)."
                    ),
                    evidence={
                        "defined_keys": report.extra_dotenv_keys,
                        "missing_keys": [],
                        "empty_keys": [],
                    },
                )
            )
        return results

    if report.missing_keys:
        results.append(
            CheckResult(
                name="env.required_keys",
                status=CheckStatus.ERROR,
                severity=Severity.HIGH,
                explanation=(
                    f"{len(report.missing_keys)} required environment variable(s) missing: "
                    f"{', '.join(report.missing_keys)}."
                ),
                suggestion=(
                    "Define the missing keys in '.env' or export them in your shell environment."
                ),
                evidence={
                    "missing_keys": report.missing_keys,
                    "empty_keys": report.empty_keys,
                    "present_keys": report.present_keys,
                    "sources": report.sources,
                },
            )
        )
    elif report.empty_keys:
        results.append(
            CheckResult(
                name="env.required_keys",
                status=CheckStatus.WARN,
                severity=Severity.MEDIUM,
                explanation=(
                    f"{len(report.empty_keys)} required environment variable(s) "
                    f"are set to empty values: {', '.join(report.empty_keys)}."
                ),
                suggestion=(
                    "Populate non-empty values for these keys in '.env' "
                    "if your application requires them."
                ),
                evidence={
                    "missing_keys": [],
                    "empty_keys": report.empty_keys,
                    "present_keys": report.present_keys,
                    "sources": report.sources,
                },
            )
        )
    else:
        results.append(
            CheckResult(
                name="env.required_keys",
                status=CheckStatus.OK,
                severity=Severity.INFO,
                explanation=(
                    f"All {len(report.present_keys)} required environment variable(s) are present."
                ),
                evidence={
                    "missing_keys": [],
                    "empty_keys": [],
                    "present_keys": report.present_keys,
                    "sources": report.sources,
                },
            )
        )

    return results
