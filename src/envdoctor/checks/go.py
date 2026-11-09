"""Go (go.mod / go.sum) project checks."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from envdoctor.models import CheckResult, CheckStatus, RuntimeInfo, Severity
from envdoctor.versions import match_semver_range

_MODULE_RE = re.compile(r"^\s*module\s+(\S+)\s*$")
_GO_VER_RE = re.compile(r"^\s*go\s+(\d+\.\d+(?:\.\d+)?)\s*$")
_REQUIRE_RE = re.compile(r"^\s*require\b")


def run_go_checks(
    root: Path,
    project_types: Sequence[str],
    runtimes: Mapping[str, RuntimeInfo],
) -> list[CheckResult]:
    """Run Go project checks."""
    if "go" not in project_types:
        return []

    results: list[CheckResult] = []
    go_mod = root / "go.mod"
    if not go_mod.exists():
        results.append(
            CheckResult(
                name="go.go_mod",
                status=CheckStatus.WARN,
                severity=Severity.MEDIUM,
                explanation="Go project files found, but 'go.mod' is missing.",
                suggestion="Run 'go mod init <module>' to initialize a Go module.",
                evidence={"exists": False},
            )
        )
        return results

    try:
        text = go_mod.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [
            CheckResult(
                name="go.go_mod",
                status=CheckStatus.ERROR,
                severity=Severity.HIGH,
                explanation=f"Cannot read 'go.mod': {exc}",
                suggestion="Check file permissions on 'go.mod'.",
                evidence={"path": str(go_mod)},
            )
        ]

    module_name: str | None = None
    go_directive: str | None = None
    has_require = False

    for line in text.splitlines():
        clean = line.split("//", 1)[0].strip()
        if not clean:
            continue
        m_mod = _MODULE_RE.match(clean)
        if m_mod:
            module_name = m_mod.group(1)
        m_go = _GO_VER_RE.match(clean)
        if m_go:
            go_directive = m_go.group(1)
        if _REQUIRE_RE.match(clean):
            has_require = True

    if not module_name:
        results.append(
            CheckResult(
                name="go.go_mod",
                status=CheckStatus.ERROR,
                severity=Severity.HIGH,
                explanation="'go.mod' is invalid: missing 'module <name>' directive.",
                suggestion="Add a valid 'module <path>' directive at the top of 'go.mod'.",
                evidence={"path": str(go_mod), "module": None},
            )
        )
        return results

    results.append(
        CheckResult(
            name="go.go_mod",
            status=CheckStatus.OK,
            severity=Severity.INFO,
            explanation=f"'go.mod' is valid (module '{module_name}').",
            evidence={"module": module_name, "go_directive": go_directive},
        )
    )

    if has_require and not (root / "go.sum").is_file():
        results.append(
            CheckResult(
                name="go.go_sum",
                status=CheckStatus.WARN,
                severity=Severity.MEDIUM,
                explanation="'go.mod' declares dependencies, but 'go.sum' is missing.",
                suggestion="Run 'go mod tidy' to generate 'go.sum'.",
                evidence={"go_sum_exists": False},
            )
        )
    elif has_require:
        results.append(
            CheckResult(
                name="go.go_sum",
                status=CheckStatus.OK,
                severity=Severity.INFO,
                explanation="'go.sum' checksum file is present.",
                evidence={"go_sum_exists": True},
            )
        )

    go_rt = runtimes.get("go")
    if go_directive:
        if not go_rt or not go_rt.found or not go_rt.healthy or not go_rt.version:
            results.append(
                CheckResult(
                    name="go.version",
                    status=CheckStatus.ERROR,
                    severity=Severity.HIGH,
                    explanation=(
                        f"'go.mod' requires Go >= {go_directive}, "
                        "but 'go' is not installed on PATH."
                    ),
                    suggestion="Install Go (e.g. 'brew install go').",
                    evidence={"required": go_directive, "installed": None},
                )
            )
        else:
            matched = match_semver_range(go_rt.version, f">={go_directive}")
            if matched is None:
                results.append(
                    CheckResult(
                        name="go.version",
                        status=CheckStatus.SKIP,
                        severity=Severity.INFO,
                        explanation=(
                            f"Could not compare Go version '{go_rt.version}' "
                            f"with go.mod directive '{go_directive}'."
                        ),
                        evidence={"required": go_directive, "installed": go_rt.version},
                    )
                )
            elif not matched:
                results.append(
                    CheckResult(
                        name="go.version",
                        status=CheckStatus.ERROR,
                        severity=Severity.HIGH,
                        explanation=(
                            f"Go version mismatch: 'go.mod' specifies 'go {go_directive}', "
                            f"but installed Go is '{go_rt.version}'."
                        ),
                        suggestion=f"Upgrade Go to {go_directive} or newer.",
                        evidence={"required": go_directive, "installed": go_rt.version},
                    )
                )
            else:
                results.append(
                    CheckResult(
                        name="go.version",
                        status=CheckStatus.OK,
                        severity=Severity.INFO,
                        explanation=(
                            f"Installed Go {go_rt.version} satisfies "
                            f"'go.mod' directive 'go {go_directive}'."
                        ),
                        evidence={"required": go_directive, "installed": go_rt.version},
                    )
                )

    return results
