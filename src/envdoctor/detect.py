"""Auto-detection of the 14 supported project types from manifests and directory structure."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

PROJECT_TYPE_LABELS: dict[str, str] = {
    "nodejs": "Node.js",
    "react": "React",
    "vite": "Vite",
    "nextjs": "Next.js",
    "python": "Python",
    "django": "Django",
    "flask": "Flask",
    "maven": "Java/Maven",
    "gradle": "Java/Gradle",
    "php": "PHP",
    "composer": "Composer",
    "rust": "Rust",
    "go": "Go",
    "docker": "Docker-based",
}

ALL_PROJECT_TYPES: tuple[str, ...] = tuple(PROJECT_TYPE_LABELS.keys())

_VITE_CONFIGS = (
    "vite.config.js",
    "vite.config.ts",
    "vite.config.mjs",
    "vite.config.cjs",
    "vite.config.mts",
)
_NEXT_CONFIGS = (
    "next.config.js",
    "next.config.mjs",
    "next.config.ts",
    "next.config.cjs",
)
_DOCKER_FILES = (
    "Dockerfile",
    "Containerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
    ".dockerignore",
)
_PYTHON_MARKERS = (
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "setup.py",
    "setup.cfg",
    "Pipfile",
    "Pipfile.lock",
    "poetry.lock",
    "uv.lock",
    ".python-version",
    "manage.py",
)
_GRADLE_MARKERS = (
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "gradlew",
)


def _safe_read_text(path: Path, max_bytes: int = 256_000) -> str:
    try:
        if not path.is_file() or path.is_symlink():
            return ""
        with path.open("rb") as fh:
            return fh.read(max_bytes).decode("utf-8", errors="replace")
    except OSError:
        return ""


def _collect_node_dep_names(pkg_json_path: Path) -> set[str]:
    raw = _safe_read_text(pkg_json_path)
    if not raw:
        return set()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Even if package.json is slightly malformed, check raw text for obvious framework names
        found: set[str] = set()
        for key in ("react", "react-dom", "vite", "next"):
            if f'"{key}"' in raw:
                found.add(key)
        return found
    if not isinstance(data, dict):
        return set()
    names: set[str] = set()
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        sec = data.get(section)
        if isinstance(sec, dict):
            names.update(str(k).lower() for k in sec)
    return names


def _collect_python_dep_names(root: Path) -> set[str]:
    deps: set[str] = set()
    for req_name in ("requirements.txt", "requirements-dev.txt", "requirements/base.txt"):
        req_file = root / req_name
        text = _safe_read_text(req_file)
        for line in text.splitlines():
            clean = line.split("#", 1)[0].strip()
            if not clean or clean.startswith("-"):
                continue
            match = re.match(r"^([A-Za-z0-9_.\-]+)", clean)
            if match:
                deps.add(match.group(1).lower().replace("_", "-"))

    pyproject = root / "pyproject.toml"
    py_text = _safe_read_text(pyproject)
    if py_text:
        try:
            data: dict[str, Any] = tomllib.loads(py_text)
            proj = data.get("project")
            if isinstance(proj, dict):
                for item in proj.get("dependencies", []) or []:
                    if isinstance(item, str):
                        m = re.match(r"^([A-Za-z0-9_.\-]+)", item.strip())
                        if m:
                            deps.add(m.group(1).lower().replace("_", "-"))
            tool_sec = data.get("tool")
            if isinstance(tool_sec, dict) and isinstance(tool_sec.get("poetry"), dict):
                p_deps = tool_sec["poetry"].get("dependencies")
                if isinstance(p_deps, dict):
                    deps.update(str(k).lower().replace("_", "-") for k in p_deps)
        except tomllib.TOMLDecodeError:
            if "django" in py_text.lower():
                deps.add("django")
            if "flask" in py_text.lower():
                deps.add("flask")

    pipfile = root / "Pipfile"
    pip_text = _safe_read_text(pipfile)
    if pip_text:
        if re.search(r"(?m)^\s*django\s*=", pip_text, re.IGNORECASE):
            deps.add("django")
        if re.search(r"(?m)^\s*flask\s*=", pip_text, re.IGNORECASE):
            deps.add("flask")

    return deps


def _has_NonSymlink_glob(directory: Path, pattern: str) -> bool:
    try:
        if not directory.is_dir() or directory.is_symlink():
            return False
        for item in directory.glob(pattern):
            if not item.is_symlink():
                return True
    except OSError:
        return False
    return False


def detect_project_types(root: Path) -> list[str]:
    """Return canonical project type IDs detected in ``root`` (in stable order)."""
    detected: list[str] = []

    def _add(kind: str) -> None:
        if kind not in detected:
            detected.append(kind)

    pkg_json = root / "package.json"
    node_Deps = _collect_node_dep_names(pkg_json) if pkg_json.exists() else set()
    has_vite_cfg = any((root / cfg).exists() for cfg in _VITE_CONFIGS)
    has_next_cfg = any((root / cfg).exists() for cfg in _NEXT_CONFIGS)

    if (
        pkg_json.exists()
        or (root / ".nvmrc").exists()
        or (root / ".node-version").exists()
        or (root / "package-lock.json").exists()
        or (root / "pnpm-lock.yaml").exists()
        or (root / "yarn.lock").exists()
        or has_vite_cfg
        or has_next_cfg
    ):
        _add("nodejs")

    if (
        "react" in node_Deps
        or "react-dom" in node_Deps
        or _has_NonSymlink_glob(root / "src", "*.jsx")
        or _has_NonSymlink_glob(root / "src", "*.tsx")
    ):
        _add("nodejs")
        _add("react")

    if "vite" in node_Deps or has_vite_cfg:
        _add("nodejs")
        _add("vite")

    if "next" in node_Deps or has_next_cfg:
        _add("nodejs")
        _add("nextjs")

    py_deps = _collect_python_dep_names(root)
    has_py_marker = any((root / m).exists() for m in _PYTHON_MARKERS) or (root / ".venv").is_dir()
    has_root_py = _has_NonSymlink_glob(root, "*.py") or _has_NonSymlink_glob(root / "src", "*.py")
    if has_py_marker or has_root_py or py_deps:
        _add("python")

    has_manage_py = (root / "manage.py").is_file()
    if has_manage_py or "django" in py_deps:
        _add("python")
        _add("django")

    has_flask_env = (root / ".flaskenv").is_file()
    has_flask_import = False
    for py_entry in ("app.py", "wsgi.py", "application.py", "main.py"):
        content = _safe_read_text(root / py_entry, max_bytes=32_000)
        if re.search(r"\b(?:from\s+flask\s+import|import\s+flask)\b", content):
            has_flask_import = True
            break
    if "flask" in py_deps or has_flask_env or has_flask_import:
        _add("python")
        _add("flask")

    if (root / "pom.xml").exists() or (root / ".mvn").is_dir():
        _add("maven")

    if any((root / m).exists() for m in _GRADLE_MARKERS):
        _add("gradle")

    has_composer = (root / "composer.json").exists() or (root / "composer.lock").exists()
    has_php_files = (
        (root / "index.php").exists()
        or (root / "artisan").exists()
        or _has_NonSymlink_glob(root, "*.php")
        or _has_NonSymlink_glob(root / "src", "*.php")
        or _has_NonSymlink_glob(root / "public", "*.php")
    )
    if has_php_files or has_composer:
        _add("php")
    if has_composer:
        _add("composer")

    if (
        (root / "Cargo.toml").exists()
        or (root / "rust-toolchain").exists()
        or (root / "rust-toolchain.toml").exists()
    ):
        _add("rust")

    if (root / "go.mod").exists() or (root / "go.sum").exists() or (root / "go.work").exists():
        _add("go")

    if any((root / f).exists() for f in _DOCKER_FILES):
        _add("docker")

    return detected


def labels_for_types(project_types: list[str]) -> list[str]:
    """Return human-readable project type labels for canonical IDs."""
    return [PROJECT_TYPE_LABELS.get(t, t) for t in project_types]
