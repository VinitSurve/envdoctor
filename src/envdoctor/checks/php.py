"""PHP and Composer project checks."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from envdoctor.models import CheckResult, CheckStatus, RuntimeInfo, Severity
from envdoctor.versions import match_semver_range


def _read_composer_json(root: Path) -> tuple[dict[str, Any] | None, CheckResult | None]:
    cpath = root / "composer.json"
    if not cpath.exists():
        return None, None
    try:
        raw = cpath.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, CheckResult(
            name="php.composer_json",
            status=CheckStatus.ERROR,
            severity=Severity.HIGH,
            explanation=f"'composer.json' is not valid JSON ({exc.msg} at line {exc.lineno}).",
            suggestion="Fix the JSON syntax error in 'composer.json'.",
            evidence={"path": str(cpath), "line": exc.lineno},
        )
    except OSError as exc:
        return None, CheckResult(
            name="php.composer_json",
            status=CheckStatus.ERROR,
            severity=Severity.HIGH,
            explanation=f"Cannot read 'composer.json': {exc}",
            suggestion="Check file permissions on 'composer.json'.",
            evidence={"path": str(cpath)},
        )
    if not isinstance(data, dict):
        return None, CheckResult(
            name="php.composer_json",
            status=CheckStatus.ERROR,
            severity=Severity.HIGH,
            explanation="'composer.json' must contain a JSON object.",
            suggestion="Ensure 'composer.json' contains a top-level object.",
            evidence={"path": str(cpath)},
        )
    return data, CheckResult(
        name="php.composer_json",
        status=CheckStatus.OK,
        severity=Severity.INFO,
        explanation="'composer.json' is valid JSON.",
        evidence={"name": str(data.get("name", ""))},
    )


def run_php_checks(
    root: Path,
    project_types: Sequence[str],
    runtimes: Mapping[str, RuntimeInfo],
) -> list[CheckResult]:
    """Run PHP and Composer project checks."""
    if not any(t in project_types for t in ("php", "composer")):
        return []

    results: list[CheckResult] = []
    composer_data, composer_check = _read_composer_json(root)
    if composer_check is not None:
        results.append(composer_check)

    php_rt = runtimes.get("php")
    req_php: str | None = None
    pkg_deps: list[str] = []

    if composer_data:
        for sec_name in ("require", "require-dev"):
            sec = composer_data.get(sec_name)
            if isinstance(sec, dict):
                for k, v in sec.items():
                    if k.lower() == "php" and isinstance(v, str):
                        req_php = v.strip()
                    elif not k.lower().startswith("ext-") and "/" in k:
                        pkg_deps.append(k)

        if pkg_deps:
            if not (root / "composer.lock").is_file():
                results.append(
                    CheckResult(
                        name="php.composer_lock",
                        status=CheckStatus.WARN,
                        severity=Severity.LOW,
                        explanation="'composer.lock' is missing.",
                        suggestion="Run 'composer install' and commit 'composer.lock'.",
                        evidence={"lockfile_exists": False},
                    )
                )
            else:
                results.append(
                    CheckResult(
                        name="php.composer_lock",
                        status=CheckStatus.OK,
                        severity=Severity.INFO,
                        explanation="'composer.lock' is present.",
                        evidence={"lockfile_exists": True},
                    )
                )

            vendor_dir = root / "vendor"
            autoload = vendor_dir / "autoload.php"
            if not vendor_dir.is_dir() or not autoload.is_file():
                results.append(
                    CheckResult(
                        name="php.vendor",
                        status=CheckStatus.ERROR,
                        severity=Severity.HIGH,
                        explanation=(
                            "Composer 'vendor/autoload.php' is missing "
                            f"({len(pkg_deps)} package(s) declared)."
                        ),
                        suggestion="Run 'composer install' or 'envdoctor deps --fix'.",
                        evidence={
                            "vendor_exists": vendor_dir.is_dir(),
                            "autoload_exists": autoload.is_file(),
                        },
                    )
                )
            else:
                results.append(
                    CheckResult(
                        name="php.vendor",
                        status=CheckStatus.OK,
                        severity=Severity.INFO,
                        explanation="Composer 'vendor/autoload.php' is present.",
                        evidence={"vendor_exists": True, "autoload_exists": True},
                    )
                )

    if req_php:
        if not php_rt or not php_rt.found or not php_rt.healthy or not php_rt.version:
            results.append(
                CheckResult(
                    name="php.version",
                    status=CheckStatus.ERROR,
                    severity=Severity.HIGH,
                    explanation=(
                        f"'composer.json' requires PHP '{req_php}', "
                        "but PHP is not installed on PATH."
                    ),
                    suggestion="Install PHP (e.g. 'brew install php').",
                    evidence={"required": req_php, "installed": None},
                )
            )
        else:
            matched = match_semver_range(php_rt.version, req_php)
            if matched is None:
                results.append(
                    CheckResult(
                        name="php.version",
                        status=CheckStatus.SKIP,
                        severity=Severity.INFO,
                        explanation=(
                            f"Could not parse PHP version constraint '{req_php}' "
                            "from composer.json."
                        ),
                        evidence={"required": req_php, "installed": php_rt.version},
                    )
                )
            elif not matched:
                results.append(
                    CheckResult(
                        name="php.version",
                        status=CheckStatus.ERROR,
                        severity=Severity.HIGH,
                        explanation=(
                            f"PHP version mismatch: composer.json requires '{req_php}', "
                            f"but installed PHP is '{php_rt.version}'."
                        ),
                        suggestion=f"Install or switch to a PHP version matching '{req_php}'.",
                        evidence={"required": req_php, "installed": php_rt.version},
                    )
                )
            else:
                results.append(
                    CheckResult(
                        name="php.version",
                        status=CheckStatus.OK,
                        severity=Severity.INFO,
                        explanation=(
                            f"Installed PHP {php_rt.version} satisfies composer.json ('{req_php}')."
                        ),
                        evidence={"required": req_php, "installed": php_rt.version},
                    )
                )
    elif php_rt and php_rt.found and php_rt.healthy:
        results.append(
            CheckResult(
                name="php.version",
                status=CheckStatus.OK,
                severity=Severity.INFO,
                explanation=f"PHP {php_rt.version} is available.",
                evidence={"installed": php_rt.version, "required": None},
            )
        )

    return results
