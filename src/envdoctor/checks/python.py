"""Python, Django and Flask project checks."""

from __future__ import annotations

import os
import re
import sys
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from envdoctor.common.safety import run_command
from envdoctor.models import CheckResult, CheckStatus, RuntimeInfo, Severity
from envdoctor.versions import match_pep440, match_semver_range

_REQ_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.\-]*)")


def _normalize_pkg_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip().lower())


def _parse_pyproject(root: Path) -> tuple[dict[str, Any] | None, CheckResult | None]:
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        return None, None
    try:
        text = pyproject.read_text(encoding="utf-8", errors="replace")
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return None, CheckResult(
            name="python.pyproject_toml",
            status=CheckStatus.ERROR,
            severity=Severity.HIGH,
            explanation=f"'pyproject.toml' is not valid TOML: {exc}",
            suggestion="Fix the TOML syntax error in 'pyproject.toml'.",
            evidence={"path": str(pyproject)},
        )
    except OSError as exc:
        return None, CheckResult(
            name="python.pyproject_toml",
            status=CheckStatus.ERROR,
            severity=Severity.HIGH,
            explanation=f"Cannot read 'pyproject.toml': {exc}",
            suggestion="Check file permissions on 'pyproject.toml'.",
            evidence={"path": str(pyproject)},
        )
    return data, CheckResult(
        name="python.pyproject_toml",
        status=CheckStatus.OK,
        severity=Severity.INFO,
        explanation="'pyproject.toml' is valid TOML.",
        evidence={"path": str(pyproject)},
    )


def _find_venv_dir(root: Path) -> Path | None:
    for candidate in (".venv", "venv", ".env_venv"):
        vdir = root / candidate
        if vdir.is_dir() and not vdir.is_symlink():
            return vdir
    return None


def _venv_python_binary(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _installed_venv_packages(venv_dir: Path) -> set[str]:
    """Inspect .venv site-packages *.dist-info / *.egg-info dirs to find installed packages."""
    installed: set[str] = set()
    lib_dir = venv_dir / "lib"
    if not lib_dir.is_dir():
        return installed
    try:
        for sp in lib_dir.glob("python*/site-packages"):
            if not sp.is_dir():
                continue
            for item in sp.iterdir():
                name = item.name
                if name.endswith(".dist-info") or name.endswith(".egg-info"):
                    stem = name.rsplit(".", 1)[0]
                    pkg_part = stem.split("-", 1)[0]
                    installed.add(_normalize_pkg_name(pkg_part))
    except OSError:
        pass
    return installed


def _declared_python_requirements(root: Path, pyproject: dict[str, Any] | None) -> list[str]:
    declared: list[str] = []
    seen: set[str] = set()

    def _add(raw_spec: str) -> None:
        clean = raw_spec.split("#", 1)[0].strip()
        if not clean or clean.startswith("-"):
            return
        # Skip environment markers that clearly target another platform
        if ";" in clean:
            req_part, marker_part = clean.split(";", 1)
            if "sys_platform" in marker_part and "win32" in marker_part and sys.platform != "win32":
                return
            clean = req_part.strip()
        m = _REQ_NAME_RE.match(clean)
        if m:
            norm = _normalize_pkg_name(m.group(1))
            if norm not in seen:
                seen.add(norm)
                declared.append(norm)

    req_txt = root / "requirements.txt"
    if req_txt.is_file() and not req_txt.is_symlink():
        try:
            for line in req_txt.read_text(encoding="utf-8", errors="replace").splitlines():
                _add(line)
        except OSError:
            pass

    if pyproject and isinstance(pyproject.get("project"), dict):
        deps = pyproject["project"].get("dependencies")
        if isinstance(deps, list):
            for item in deps:
                if isinstance(item, str):
                    _add(item)

    return declared


def _check_python_venv_and_deps(root: Path, pyproject: dict[str, Any] | None) -> list[CheckResult]:
    results: list[CheckResult] = []
    declared = _declared_python_requirements(root, pyproject)
    venv_dir = _find_venv_dir(root)

    # Check lockfiles for Poetry / Pipenv
    if (root / "Pipfile").is_file() and not (root / "Pipfile.lock").is_file():
        results.append(
            CheckResult(
                name="python.lockfile",
                status=CheckStatus.WARN,
                severity=Severity.LOW,
                explanation="'Pipfile' is present, but 'Pipfile.lock' is missing.",
                suggestion="Run 'pipenv lock' to generate 'Pipfile.lock'.",
                evidence={"manager": "pipenv", "lockfile_exists": False},
            )
        )
    if (
        pyproject
        and isinstance(pyproject.get("tool"), dict)
        and "poetry" in pyproject["tool"]
        and not (root / "poetry.lock").is_file()
    ):
        results.append(
            CheckResult(
                name="python.lockfile",
                status=CheckStatus.WARN,
                severity=Severity.LOW,
                explanation=(
                    "Poetry configuration found in 'pyproject.toml', but 'poetry.lock' is missing."
                ),
                suggestion="Run 'poetry lock' to generate 'poetry.lock'.",
                evidence={"manager": "poetry", "lockfile_exists": False},
            )
        )

    if venv_dir is None:
        if declared or (root / "requirements.txt").is_file() or (root / "pyproject.toml").is_file():
            results.append(
                CheckResult(
                    name="python.venv",
                    status=CheckStatus.WARN,
                    severity=Severity.MEDIUM,
                    explanation=(
                        "No local virtual environment ('.venv' or 'venv') found in project root."
                    ),
                    suggestion="Create one with 'python3 -m venv .venv' and install dependencies.",
                    evidence={"venv_exists": False, "declared_dependencies": len(declared)},
                )
            )
        return results

    py_bin = _venv_python_binary(venv_dir)
    # Check if symlink target exists and binary is executable
    try:
        bin_exists = py_bin.is_file() and os.access(py_bin, os.X_OK)
    except OSError:
        bin_exists = False

    if not bin_exists:
        results.append(
            CheckResult(
                name="python.venv",
                status=CheckStatus.ERROR,
                severity=Severity.HIGH,
                explanation=(
                    f"Virtual environment '{venv_dir.name}' is broken: "
                    f"'{py_bin}' is missing or not executable."
                ),
                suggestion=(
                    "Recreate the virtual environment "
                    f"('rm -rf {venv_dir.name} && python3 -m venv {venv_dir.name}')."
                ),
                evidence={"venv": venv_dir.name, "python_bin": str(py_bin), "healthy": False},
            )
        )
        return results

    results.append(
        CheckResult(
            name="python.venv",
            status=CheckStatus.OK,
            severity=Severity.INFO,
            explanation=(
                f"Virtual environment '{venv_dir.name}' is present with valid Python interpreter."
            ),
            evidence={"venv": venv_dir.name, "python_bin": str(py_bin), "healthy": True},
        )
    )

    if declared:
        installed = _installed_venv_packages(venv_dir)
        missing = [pkg for pkg in declared if pkg not in installed]
        if missing:
            results.append(
                CheckResult(
                    name="python.dependencies",
                    status=CheckStatus.ERROR,
                    severity=Severity.HIGH,
                    explanation=(
                        f"{len(missing)} declared Python dependency/dependencies "
                        f"missing from '{venv_dir.name}': {', '.join(missing[:10])}."
                    ),
                    suggestion=(
                        f"Run '{venv_dir.name}/bin/pip install -r requirements.txt' "
                        "or 'envdoctor deps --fix'."
                    ),
                    evidence={
                        "venv": venv_dir.name,
                        "missing_packages": missing,
                        "declared_count": len(declared),
                    },
                )
            )
        else:
            results.append(
                CheckResult(
                    name="python.dependencies",
                    status=CheckStatus.OK,
                    severity=Severity.INFO,
                    explanation=(
                        f"All {len(declared)} declared Python package(s) "
                        f"are installed in '{venv_dir.name}'."
                    ),
                    evidence={
                        "venv": venv_dir.name,
                        "missing_packages": [],
                        "declared_count": len(declared),
                    },
                )
            )

    return results


def _active_python_version(root: Path, runtimes: Mapping[str, RuntimeInfo]) -> str | None:
    venv_dir = _find_venv_dir(root)
    if venv_dir is not None:
        py_bin = _venv_python_binary(venv_dir)
        if py_bin.is_file() and os.access(py_bin, os.X_OK):
            res = run_command([str(py_bin), "--version"], timeout=3.0, env={"LC_ALL": "C"})
            if res.ok:
                m = re.search(r"(\d+\.\d+\.\d+)", f"{res.stdout} {res.stderr}")
                if m:
                    return m.group(1)
    py_rt = runtimes.get("python")
    if py_rt and py_rt.found and py_rt.healthy and py_rt.version:
        return py_rt.version
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def _check_python_version(
    root: Path,
    pyproject: dict[str, Any] | None,
    runtimes: Mapping[str, RuntimeInfo],
) -> list[CheckResult]:
    results: list[CheckResult] = []
    active_ver = _active_python_version(root, runtimes)
    if not active_ver:
        return results

    py_ver_file = root / ".python-version"
    if py_ver_file.is_file() and not py_ver_file.is_symlink():
        try:
            raw = py_ver_file.read_text(encoding="utf-8", errors="replace")
            pinned = next(
                (
                    ln.strip()
                    for ln in raw.splitlines()
                    if ln.strip() and not ln.strip().startswith("#")
                ),
                "",
            )
            if pinned:
                matched = match_semver_range(active_ver, pinned)
                if matched is None:
                    results.append(
                        CheckResult(
                            name="python.version",
                            status=CheckStatus.SKIP,
                            severity=Severity.INFO,
                            explanation=f"Could not parse '.python-version' constraint '{pinned}'.",
                            evidence={
                                "source": ".python-version",
                                "required": pinned,
                                "installed": active_ver,
                            },
                        )
                    )
                elif not matched:
                    results.append(
                        CheckResult(
                            name="python.version",
                            status=CheckStatus.WARN,
                            severity=Severity.MEDIUM,
                            explanation=(
                                f"Python version mismatch: '.python-version' specifies '{pinned}', "
                                f"but active Python is '{active_ver}'."
                            ),
                            suggestion=(
                                f"Install/activate Python {pinned} (e.g. via pyenv or uv) "
                                "and recreate '.venv'."
                            ),
                            evidence={
                                "source": ".python-version",
                                "required": pinned,
                                "installed": active_ver,
                            },
                        )
                    )
                else:
                    results.append(
                        CheckResult(
                            name="python.version",
                            status=CheckStatus.OK,
                            severity=Severity.INFO,
                            explanation=(
                                f"Active Python {active_ver} matches "
                                f"'.python-version' ('{pinned}')."
                            ),
                            evidence={
                                "source": ".python-version",
                                "required": pinned,
                                "installed": active_ver,
                            },
                        )
                    )
        except OSError:
            pass

    if pyproject and isinstance(pyproject.get("project"), dict):
        req_py = pyproject["project"].get("requires-python")
        if isinstance(req_py, str) and req_py.strip():
            spec = req_py.strip()
            matched = match_pep440(active_ver, spec)
            if matched is None:
                results.append(
                    CheckResult(
                        name="python.requires_python",
                        status=CheckStatus.SKIP,
                        severity=Severity.INFO,
                        explanation=f"Could not parse 'requires-python' specifier '{spec}'.",
                        evidence={
                            "source": "pyproject.toml:requires-python",
                            "required": spec,
                            "installed": active_ver,
                        },
                    )
                )
            elif not matched:
                results.append(
                    CheckResult(
                        name="python.requires_python",
                        status=CheckStatus.ERROR,
                        severity=Severity.HIGH,
                        explanation=(
                            f"Python version {active_ver} does not satisfy pyproject.toml "
                            f"requires-python '{spec}'."
                        ),
                        suggestion=f"Use a Python interpreter matching '{spec}'.",
                        evidence={
                            "source": "pyproject.toml:requires-python",
                            "required": spec,
                            "installed": active_ver,
                        },
                    )
                )
            else:
                results.append(
                    CheckResult(
                        name="python.requires_python",
                        status=CheckStatus.OK,
                        severity=Severity.INFO,
                        explanation=(
                            f"Active Python {active_ver} satisfies requires-python ('{spec}')."
                        ),
                        evidence={
                            "source": "pyproject.toml:requires-python",
                            "required": spec,
                            "installed": active_ver,
                        },
                    )
                )

    return results


def _check_django(root: Path) -> list[CheckResult]:
    results: list[CheckResult] = []
    manage_py = root / "manage.py"
    has_manage = manage_py.is_file()
    if not has_manage:
        results.append(
            CheckResult(
                name="django.manage_py",
                status=CheckStatus.WARN,
                severity=Severity.MEDIUM,
                explanation=(
                    "Django project detected, but 'manage.py' was not found in the project root."
                ),
                suggestion="Ensure you are in the Django project root or restore 'manage.py'.",
                evidence={"manage_py_exists": False},
            )
        )
    else:
        results.append(
            CheckResult(
                name="django.manage_py",
                status=CheckStatus.OK,
                severity=Severity.INFO,
                explanation="Django 'manage.py' entry point is present.",
                evidence={"manage_py_exists": True},
            )
        )

    # Look for settings.py or settings/ package one or two levels deep (without following symlinks)
    has_settings = False
    try:
        if (root / "settings.py").is_file():
            has_settings = True
        else:
            for child in root.iterdir():
                if child.is_symlink() or not child.is_dir() or child.name.startswith("."):
                    continue
                if (child / "settings.py").is_file() or (
                    child / "settings" / "__init__.py"
                ).is_file():
                    has_settings = True
                    break
    except OSError:
        has_settings = False

    if not has_settings:
        results.append(
            CheckResult(
                name="django.settings",
                status=CheckStatus.WARN,
                severity=Severity.MEDIUM,
                explanation=(
                    "Django settings module ('settings.py' or 'settings/__init__.py') "
                    "was not found."
                ),
                suggestion="Create a Django settings module or set DJANGO_SETTINGS_MODULE.",
                evidence={"settings_found": False},
            )
        )
    else:
        results.append(
            CheckResult(
                name="django.settings",
                status=CheckStatus.OK,
                severity=Severity.INFO,
                explanation="Django settings module found.",
                evidence={"settings_found": True},
            )
        )

    return results


def _check_flask(root: Path) -> list[CheckResult]:
    entry_candidates = ("app.py", "wsgi.py", "application.py", "run.py", "main.py")
    found_entry: str | None = None
    for name in entry_candidates:
        if (root / name).is_file():
            found_entry = name
            break
    if not found_entry:
        # Check package directories for __init__.py with create_app or Flask
        try:
            for child in root.iterdir():
                if child.is_symlink() or not child.is_dir() or child.name.startswith("."):
                    continue
                init_py = child / "__init__.py"
                if init_py.is_file() and not init_py.is_symlink():
                    text = init_py.read_text(encoding="utf-8", errors="replace")
                    if "Flask" in text or "create_app" in text:
                        found_entry = f"{child.name}/__init__.py"
                        break
        except OSError:
            pass

    if not found_entry and not (root / ".flaskenv").is_file():
        return [
            CheckResult(
                name="flask.entrypoint",
                status=CheckStatus.WARN,
                severity=Severity.MEDIUM,
                explanation=(
                    "Flask project has no standard entrypoint "
                    "('app.py', 'wsgi.py', package 'create_app', or '.flaskenv')."
                ),
                suggestion="Create 'app.py' / 'wsgi.py' or configure FLASK_APP in '.flaskenv'.",
                evidence={"entrypoint": None},
            )
        ]

    return [
        CheckResult(
            name="flask.entrypoint",
            status=CheckStatus.OK,
            severity=Severity.INFO,
            explanation=f"Flask entrypoint found ({found_entry or '.flaskenv'}).",
            evidence={"entrypoint": found_entry or ".flaskenv"},
        )
    ]


def run_python_checks(
    root: Path,
    project_types: Sequence[str],
    runtimes: Mapping[str, RuntimeInfo],
) -> list[CheckResult]:
    """Run all applicable Python, Django and Flask checks."""
    if not any(t in project_types for t in ("python", "django", "flask")):
        return []

    results: list[CheckResult] = []
    pyproject, py_check = _parse_pyproject(root)
    if py_check is not None:
        results.append(py_check)

    results.extend(_check_python_venv_and_deps(root, pyproject))
    results.extend(_check_python_version(root, pyproject, runtimes))

    if "django" in project_types:
        results.extend(_check_django(root))
    if "flask" in project_types:
        results.extend(_check_flask(root))

    return results
