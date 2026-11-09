"""Node.js, React, Vite and Next.js project checks."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from envdoctor.models import CheckResult, CheckStatus, RuntimeInfo, Severity
from envdoctor.versions import match_semver_range

LOCKFILES: tuple[str, ...] = (
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lockb",
    "bun.lock",
)


def _read_package_json(root: Path) -> tuple[dict[str, Any] | None, CheckResult | None]:
    pkg_path = root / "package.json"
    if not pkg_path.exists():
        return None, CheckResult(
            name="node.package_json",
            status=CheckStatus.WARN,
            severity=Severity.MEDIUM,
            explanation="Node.js markers found, but 'package.json' is missing.",
            suggestion="Run 'npm init -y' or restore 'package.json'.",
            evidence={"path": str(pkg_path), "exists": False},
        )
    try:
        raw = pkg_path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, CheckResult(
            name="node.package_json",
            status=CheckStatus.ERROR,
            severity=Severity.HIGH,
            explanation=(
                f"'package.json' is not valid JSON "
                f"({exc.msg} at line {exc.lineno}, column {exc.colno})."
            ),
            suggestion="Fix the JSON syntax error in 'package.json'.",
            evidence={"path": str(pkg_path), "line": exc.lineno, "column": exc.colno},
        )
    except OSError as exc:
        return None, CheckResult(
            name="node.package_json",
            status=CheckStatus.ERROR,
            severity=Severity.HIGH,
            explanation=f"Cannot read 'package.json': {exc}",
            suggestion="Check file permissions on 'package.json'.",
            evidence={"path": str(pkg_path)},
        )
    if not isinstance(data, dict):
        return None, CheckResult(
            name="node.package_json",
            status=CheckStatus.ERROR,
            severity=Severity.HIGH,
            explanation="'package.json' must contain a top-level JSON object.",
            suggestion="Ensure 'package.json' starts with '{' and ends with '}'.",
            evidence={"path": str(pkg_path)},
        )
    return data, CheckResult(
        name="node.package_json",
        status=CheckStatus.OK,
        severity=Severity.INFO,
        explanation="'package.json' is valid JSON.",
        evidence={"name": str(data.get("name", "")), "version": str(data.get("version", ""))},
    )


def _check_node_version(
    root: Path, pkg: dict[str, Any] | None, runtimes: Mapping[str, RuntimeInfo]
) -> list[CheckResult]:
    constraints: list[tuple[str, str]] = []
    if pkg and isinstance(pkg.get("engines"), dict):
        eng_node = pkg["engines"].get("node")
        if isinstance(eng_node, str) and eng_node.strip():
            constraints.append(("package.json:engines.node", eng_node.strip()))

    for fname in (".nvmrc", ".node-version"):
        fpath = root / fname
        if fpath.is_file() and not fpath.is_symlink():
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace").strip()
                first = next(
                    (
                        ln.strip()
                        for ln in content.splitlines()
                        if ln.strip() and not ln.strip().startswith("#")
                    ),
                    "",
                )
                if first:
                    constraints.append((fname, first))
            except OSError:
                pass

    node_rt = runtimes.get("node")
    if not constraints:
        if node_rt and node_rt.found and node_rt.healthy:
            return [
                CheckResult(
                    name="node.version",
                    status=CheckStatus.OK,
                    severity=Severity.INFO,
                    explanation=(
                        f"Node.js {node_rt.version} is available "
                        "(no version constraint pinned in project)."
                    ),
                    evidence={"installed": node_rt.version, "constraints": []},
                )
            ]
        if not node_rt or not node_rt.found:
            return [
                CheckResult(
                    name="node.version",
                    status=CheckStatus.WARN,
                    severity=Severity.MEDIUM,
                    explanation="Node.js runtime is not installed on PATH for this Node project.",
                    suggestion="Install Node.js (e.g. 'brew install node' or via fnm/nvm).",
                    evidence={"installed": None},
                )
            ]
        return []

    if not node_rt or not node_rt.found or not node_rt.healthy or not node_rt.version:
        return [
            CheckResult(
                name="node.version",
                status=CheckStatus.ERROR,
                severity=Severity.HIGH,
                explanation=(
                    f"Project requires Node.js ({', '.join(f'{s}={c}' for s, c in constraints)}), "
                    "but no healthy 'node' binary was found on PATH."
                ),
                suggestion="Install a matching Node.js version (e.g. 'fnm use' or 'nvm use').",
                evidence={
                    "installed": None,
                    "constraints": [{"source": s, "spec": c} for s, c in constraints],
                },
            )
        ]

    results: list[CheckResult] = []
    for source, spec in constraints:
        matched = match_semver_range(node_rt.version, spec)
        if matched is None:
            results.append(
                CheckResult(
                    name="node.version",
                    status=CheckStatus.SKIP,
                    severity=Severity.INFO,
                    explanation=(
                        f"Could not parse Node.js version constraint '{spec}' from {source}."
                    ),
                    suggestion="Use a standard semver range (e.g. '>=18', '^20.10.0', '20.x').",
                    evidence={"source": source, "required": spec, "installed": node_rt.version},
                )
            )
        elif not matched:
            results.append(
                CheckResult(
                    name="node.version",
                    status=CheckStatus.ERROR,
                    severity=Severity.HIGH,
                    explanation=(
                        f"Node.js version mismatch: {source} requires '{spec}', "
                        f"but active node is '{node_rt.version}'."
                    ),
                    suggestion=(
                        f"Switch Node.js version to satisfy '{spec}' (e.g. 'nvm use' or 'fnm use')."
                    ),
                    evidence={"source": source, "required": spec, "installed": node_rt.version},
                )
            )
        else:
            results.append(
                CheckResult(
                    name="node.version",
                    status=CheckStatus.OK,
                    severity=Severity.INFO,
                    explanation=f"Active Node.js {node_rt.version} satisfies {source} ('{spec}').",
                    evidence={"source": source, "required": spec, "installed": node_rt.version},
                )
            )
    return results


def _declared_node_deps(pkg: dict[str, Any]) -> dict[str, str]:
    declared: dict[str, str] = {}
    for section in ("dependencies", "devDependencies"):
        sec = pkg.get(section)
        if isinstance(sec, dict):
            for k, v in sec.items():
                if isinstance(k, str) and isinstance(v, str):
                    declared[k] = v
    return declared


def _check_node_dependencies(root: Path, pkg: dict[str, Any]) -> list[CheckResult]:
    results: list[CheckResult] = []
    declared = _declared_node_deps(pkg)

    existing_locks = [lf for lf in LOCKFILES if (root / lf).is_file()]
    if len(existing_locks) > 1:
        results.append(
            CheckResult(
                name="node.lockfile",
                status=CheckStatus.WARN,
                severity=Severity.MEDIUM,
                explanation=(
                    f"Multiple Node lockfiles found ({', '.join(existing_locks)}), "
                    "which can cause inconsistent installs."
                ),
                suggestion=(
                    "Keep only the lockfile for your active package manager and remove the others."
                ),
                evidence={"lockfiles": existing_locks},
            )
        )
    elif len(existing_locks) == 0 and declared:
        results.append(
            CheckResult(
                name="node.lockfile",
                status=CheckStatus.WARN,
                severity=Severity.LOW,
                explanation="No lockfile (package-lock.json, pnpm-lock.yaml, or yarn.lock) found.",
                suggestion="Commit a lockfile so dependency installs are reproducible.",
                evidence={"lockfiles": []},
            )
        )
    elif existing_locks:
        results.append(
            CheckResult(
                name="node.lockfile",
                status=CheckStatus.OK,
                severity=Severity.INFO,
                explanation=f"Found lockfile: {existing_locks[0]}.",
                evidence={"lockfiles": existing_locks},
            )
        )

    if not declared:
        return results

    nm_dir = root / "node_modules"
    if not nm_dir.is_dir():
        results.append(
            CheckResult(
                name="node.node_modules",
                status=CheckStatus.ERROR,
                severity=Severity.HIGH,
                explanation=(
                    "'node_modules' directory is missing "
                    f"({len(declared)} package(s) declared in package.json)."
                ),
                suggestion=(
                    "Run 'envdoctor deps --fix' or 'npm install' / 'pnpm install' / 'yarn install'."
                ),
                evidence={"declared_count": len(declared), "node_modules_exists": False},
            )
        )
        return results

    missing_pkgs: list[str] = []
    for pkg_name in sorted(declared):
        pkg_dir = nm_dir / pkg_name
        if not pkg_dir.is_dir() or not (pkg_dir / "package.json").is_file():
            missing_pkgs.append(pkg_name)

    if missing_pkgs:
        results.append(
            CheckResult(
                name="node.deps_integrity",
                status=CheckStatus.ERROR,
                severity=Severity.HIGH,
                explanation=(
                    f"'node_modules' exists, but {len(missing_pkgs)} declared package(s) "
                    f"are missing: {', '.join(missing_pkgs[:10])}."
                ),
                suggestion=(
                    "Run 'npm install' (or your package manager's install command) "
                    "to repair node_modules."
                ),
                evidence={"missing_packages": missing_pkgs, "declared_count": len(declared)},
            )
        )
    else:
        results.append(
            CheckResult(
                name="node.deps_integrity",
                status=CheckStatus.OK,
                severity=Severity.INFO,
                explanation=(
                    f"All {len(declared)} declared package(s) are present in 'node_modules'."
                ),
                evidence={"missing_packages": [], "declared_count": len(declared)},
            )
        )

    bin_dir = nm_dir / ".bin"
    if bin_dir.is_dir() and not bin_dir.is_symlink():
        broken_bins: list[str] = []
        try:
            for entry in bin_dir.iterdir():
                if entry.is_symlink():
                    try:
                        target = entry.resolve()
                        if not target.exists():
                            broken_bins.append(entry.name)
                    except OSError:
                        broken_bins.append(entry.name)
                elif not os.access(entry, os.X_OK):
                    broken_bins.append(entry.name)
        except OSError:
            pass
        if broken_bins:
            results.append(
                CheckResult(
                    name="node.bin_links",
                    status=CheckStatus.ERROR,
                    severity=Severity.MEDIUM,
                    explanation=(
                        "Broken executable link(s) in 'node_modules/.bin': "
                        f"{', '.join(sorted(broken_bins)[:10])}."
                    ),
                    suggestion="Run 'npm rebuild' or reinstall dependencies.",
                    evidence={"broken_links": sorted(broken_bins)},
                )
            )

    return results


def _check_frameworks(
    root: Path, pkg: dict[str, Any] | None, project_types: Sequence[str]
) -> list[CheckResult]:
    results: list[CheckResult] = []
    declared = _declared_node_deps(pkg) if pkg else {}
    lower_deps = {k.lower() for k in declared}

    has_ts_files = False
    try:
        src_dir = root / "src"
        if src_dir.is_dir() and not src_dir.is_symlink():
            has_ts_files = any(src_dir.glob("*.ts")) or any(src_dir.glob("*.tsx"))
    except OSError:
        has_ts_files = False

    if "typescript" in lower_deps or has_ts_files:
        tsconfig = root / "tsconfig.json"
        if not tsconfig.is_file():
            results.append(
                CheckResult(
                    name="node.tsconfig",
                    status=CheckStatus.WARN,
                    severity=Severity.MEDIUM,
                    explanation=(
                        "TypeScript is used in this project, but 'tsconfig.json' is missing."
                    ),
                    suggestion="Create a 'tsconfig.json' (e.g. 'npx tsc --init').",
                    evidence={"tsconfig_exists": False},
                )
            )
        else:
            results.append(
                CheckResult(
                    name="node.tsconfig",
                    status=CheckStatus.OK,
                    severity=Severity.INFO,
                    explanation="'tsconfig.json' is present.",
                    evidence={"tsconfig_exists": True},
                )
            )

    if "react" in project_types:
        if (
            "react" in lower_deps
            and "react-dom" not in lower_deps
            and "react-native" not in lower_deps
        ):
            results.append(
                CheckResult(
                    name="react.peer_deps",
                    status=CheckStatus.WARN,
                    severity=Severity.MEDIUM,
                    explanation="'react' is listed in dependencies, but 'react-dom' is missing.",
                    suggestion=(
                        "Install 'react-dom' with a matching version if building a web application."
                    ),
                    evidence={"react_present": True, "react_dom_present": False},
                )
            )
        else:
            results.append(
                CheckResult(
                    name="react.peer_deps",
                    status=CheckStatus.OK,
                    severity=Severity.INFO,
                    explanation="React core packages are configured.",
                    evidence={
                        "react_present": "react" in lower_deps,
                        "react_dom_present": "react-dom" in lower_deps,
                    },
                )
            )

    if "vite" in project_types:
        has_index = (root / "index.html").is_file() or (root / "public" / "index.html").is_file()
        if not has_index:
            results.append(
                CheckResult(
                    name="vite.index_html",
                    status=CheckStatus.WARN,
                    severity=Severity.MEDIUM,
                    explanation="Vite project is missing 'index.html' in project root.",
                    suggestion=(
                        "Add an 'index.html' entry point in the project root "
                        "(unless building in Vite library mode)."
                    ),
                    evidence={"index_html_exists": False},
                )
            )
        else:
            results.append(
                CheckResult(
                    name="vite.index_html",
                    status=CheckStatus.OK,
                    severity=Severity.INFO,
                    explanation="Vite 'index.html' entry point exists.",
                    evidence={"index_html_exists": True},
                )
            )

    if "nextjs" in project_types:
        route_dirs = ("app", "pages", "src/app", "src/pages")
        found_routes = [d for d in route_dirs if (root / d).is_dir()]
        if not found_routes:
            results.append(
                CheckResult(
                    name="nextjs.routes_dir",
                    status=CheckStatus.ERROR,
                    severity=Severity.HIGH,
                    explanation=(
                        "Next.js project has no 'app/', 'pages/', "
                        "'src/app/', or 'src/pages/' directory."
                    ),
                    suggestion=(
                        "Create an 'app/' (App Router) or 'pages/' (Pages Router) directory."
                    ),
                    evidence={"found_route_dirs": []},
                )
            )
        else:
            results.append(
                CheckResult(
                    name="nextjs.routes_dir",
                    status=CheckStatus.OK,
                    severity=Severity.INFO,
                    explanation=f"Next.js routing directory found: {', '.join(found_routes)}.",
                    evidence={"found_route_dirs": found_routes},
                )
            )

    return results


def run_node_checks(
    root: Path,
    project_types: Sequence[str],
    runtimes: Mapping[str, RuntimeInfo],
) -> list[CheckResult]:
    """Run all applicable Node.js, React, Vite and Next.js checks."""
    if not any(t in project_types for t in ("nodejs", "react", "vite", "nextjs")):
        return []

    results: list[CheckResult] = []
    pkg_data, pkg_check = _read_package_json(root)
    if pkg_check is not None:
        results.append(pkg_check)

    results.extend(_check_node_version(root, pkg_data, runtimes))
    if pkg_data is not None:
        results.extend(_check_node_dependencies(root, pkg_data))
    results.extend(_check_frameworks(root, pkg_data, project_types))
    return results
