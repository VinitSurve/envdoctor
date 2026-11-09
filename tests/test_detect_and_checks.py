"""Tests for project type detection (all 14 types) and ecosystem checks."""

from __future__ import annotations

import json
import os
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

from envdoctor.checks import run_isolated, run_project_checks
from envdoctor.common.exceptions import ExitCode
from envdoctor.detect import ALL_PROJECT_TYPES, detect_project_types
from envdoctor.models import CheckResult, RuntimeInfo


def _healthy_runtimes() -> dict[str, RuntimeInfo]:
    return {
        "python": RuntimeInfo(
            "python", "python3", True, True, "ok", version="3.12.2", path="/bin/python3"
        ),
        "node": RuntimeInfo("node", "node", True, True, "ok", version="20.11.1", path="/bin/node"),
        "npm": RuntimeInfo("npm", "npm", True, True, "ok", version="10.4.0", path="/bin/npm"),
        "java": RuntimeInfo("java", "java", True, True, "ok", version="21.0.2", path="/bin/java"),
        "php": RuntimeInfo("php", "php", True, True, "ok", version="8.3.4", path="/bin/php"),
        "rustc": RuntimeInfo(
            "rustc", "rustc", True, True, "ok", version="1.77.0", path="/bin/rustc"
        ),
        "cargo": RuntimeInfo(
            "cargo", "cargo", True, True, "ok", version="1.77.0", path="/bin/cargo"
        ),
        "go": RuntimeInfo("go", "go", True, True, "ok", version="1.22.1", path="/bin/go"),
        "docker": RuntimeInfo(
            "docker",
            "docker",
            True,
            True,
            "ok",
            version="26.1.0",
            path="/bin/docker",
            daemon_running=True,
        ),
    }


def test_all_14_project_types_detected(tmp_path: Path) -> None:
    assert len(ALL_PROJECT_TYPES) == 14

    # 1. Node.js + 2. React + 3. Vite
    react_vite = tmp_path / "react_vite"
    react_vite.mkdir()
    (react_vite / "package.json").write_text(
        json.dumps(
            {
                "name": "rv-app",
                "dependencies": {"react": "^18.2.0", "react-dom": "^18.2.0"},
                "devDependencies": {"vite": "^5.0.0"},
            }
        )
    )
    (react_vite / "vite.config.ts").write_text("export default { server: { port: 5173 } }\n")
    types_rv = detect_project_types(react_vite)
    assert {"nodejs", "react", "vite"}.issubset(set(types_rv))

    # 4. Next.js
    next_dir = tmp_path / "next_app"
    next_dir.mkdir()
    (next_dir / "package.json").write_text(
        json.dumps({"name": "next-app", "dependencies": {"next": "14.1.0", "react": "18.2.0"}})
    )
    assert {"nodejs", "react", "nextjs"}.issubset(set(detect_project_types(next_dir)))

    # 5. Python + 6. Django
    django_dir = tmp_path / "django_app"
    django_dir.mkdir()
    (django_dir / "manage.py").write_text("#!/usr/bin/env python\n")
    (django_dir / "requirements.txt").write_text("Django>=5.0\n")
    assert {"python", "django"}.issubset(set(detect_project_types(django_dir)))

    # 7. Flask
    flask_dir = tmp_path / "flask_app"
    flask_dir.mkdir()
    (flask_dir / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n")
    assert {"python", "flask"}.issubset(set(detect_project_types(flask_dir)))

    # 8. Java Maven
    maven_dir = tmp_path / "maven_app"
    maven_dir.mkdir()
    (maven_dir / "pom.xml").write_text("<project></project>")
    assert "maven" in detect_project_types(maven_dir)

    # 9. Java Gradle
    gradle_dir = tmp_path / "gradle_app"
    gradle_dir.mkdir()
    (gradle_dir / "build.gradle.kts").write_text("plugins { java }\n")
    assert "gradle" in detect_project_types(gradle_dir)

    # 10. PHP + 11. Composer
    php_dir = tmp_path / "php_app"
    php_dir.mkdir()
    (php_dir / "index.php").write_text("<?php echo 'hi';\n")
    (php_dir / "composer.json").write_text(json.dumps({"name": "demo/php"}))
    assert {"php", "composer"}.issubset(set(detect_project_types(php_dir)))

    # 12. Rust
    rust_dir = tmp_path / "rust_app"
    rust_dir.mkdir()
    (rust_dir / "Cargo.toml").write_text('[package]\nname = "demo"\nversion = "0.1.0"\n')
    assert "rust" in detect_project_types(rust_dir)

    # 13. Go
    go_dir = tmp_path / "go_app"
    go_dir.mkdir()
    (go_dir / "go.mod").write_text("module example.com/demo\n\ngo 1.22\n")
    assert "go" in detect_project_types(go_dir)

    # 14. Docker
    docker_dir = tmp_path / "docker_app"
    docker_dir.mkdir()
    (docker_dir / "Dockerfile").write_text("FROM alpine:3.19\n")
    assert "docker" in detect_project_types(docker_dir)


def test_node_react_vite_nextjs_checks_broken_and_healthy(tmp_path: Path) -> None:
    rts = _healthy_runtimes()

    # Broken Node/React/Vite/Next project
    proj = tmp_path / "broken_node"
    proj.mkdir()
    (proj / "package.json").write_text(
        json.dumps(
            {
                "name": "broken",
                "engines": {"node": ">=22.0.0"},
                "dependencies": {"react": "^18.2.0", "next": "14.1.0", "vite": "^5.0.0"},
                "devDependencies": {"typescript": "^5.3.0"},
            }
        )
    )
    (proj / ".nvmrc").write_text("lts/*\n")  # unparseable -> skip
    (proj / "package-lock.json").write_text("{}")
    (proj / "yarn.lock").write_text("")
    # Partial node_modules + broken .bin symlink
    nm = proj / "node_modules"
    (nm / "react").mkdir(parents=True)
    (nm / "react" / "package.json").write_text("{}")
    bin_dir = nm / ".bin"
    bin_dir.mkdir(parents=True)
    os.symlink(proj / "nonexistent_target", bin_dir / "vite")

    rep = run_project_checks(proj, runtimes=rts, check_ports_enabled=False)
    by_name = {c.name: c for c in rep.checks}
    assert by_name["node.package_json"].status.value == "ok"
    assert by_name["node.lockfile"].status.value == "warn"  # conflicting lockfiles
    assert by_name["node.deps_integrity"].status.value == "error"  # missing next, vite, typescript
    assert by_name["node.bin_links"].status.value == "error"  # broken .bin/vite symlink
    assert by_name["node.tsconfig"].status.value == "warn"  # missing tsconfig.json
    assert by_name["react.peer_deps"].status.value == "warn"  # missing react-dom
    assert by_name["vite.index_html"].status.value == "warn"  # missing index.html
    assert by_name["nextjs.routes_dir"].status.value == "error"  # missing app/ or pages/
    # Version checks: one error (>=22.0.0 vs 20.11.1) and one skip (lts/*)
    ver_statuses = [c.status.value for c in rep.checks if c.name == "node.version"]
    assert "error" in ver_statuses and "skip" in ver_statuses

    # Healthy Node/React/Vite project
    good = tmp_path / "good_rv"
    good.mkdir()
    (good / "package.json").write_text(
        json.dumps(
            {
                "name": "good-rv",
                "engines": {"node": ">=18 <21"},
                "dependencies": {"react": "^18.2.0", "react-dom": "^18.2.0"},
                "devDependencies": {"vite": "^5.0.0", "typescript": "^5.3.0"},
            }
        )
    )
    (good / "package-lock.json").write_text("{}")
    (good / "tsconfig.json").write_text("{}")
    (good / "index.html").write_text("<!doctype html><html></html>")
    for pkg in ("react", "react-dom", "vite", "typescript"):
        pdir = good / "node_modules" / pkg
        pdir.mkdir(parents=True)
        (pdir / "package.json").write_text(json.dumps({"name": pkg}))

    rep_good = run_project_checks(good, runtimes=rts, check_ports_enabled=False)
    assert rep_good.status == "ok"


def test_python_django_flask_checks(tmp_path: Path) -> None:
    rts = _healthy_runtimes()

    # Broken Python + Django + Flask project
    py_bad = tmp_path / "py_bad"
    py_bad.mkdir()
    (py_bad / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nrequires-python = ">=3.13"\n'
        'dependencies = ["django>=5.0", "flask>=3.0"]\n'
        "[tool.poetry]\nname = 'demo'\n"
    )
    (py_bad / ".python-version").write_text("3.11.0\n")
    # Create a broken .venv (directory exists, bin/python missing)
    (py_bad / ".venv" / "bin").mkdir(parents=True)

    rep_bad = run_project_checks(py_bad, runtimes=rts, check_ports_enabled=False)
    by_name = {c.name: c for c in rep_bad.checks}
    assert by_name["python.pyproject_toml"].status.value == "ok"
    assert by_name["python.lockfile"].status.value == "warn"  # missing poetry.lock
    assert by_name["python.venv"].status.value == "error"  # broken .venv/bin/python
    assert by_name["python.version"].status.value == "warn"  # 3.12.2 != 3.11.0
    assert by_name["python.requires_python"].status.value == "error"  # 3.12.2 < 3.13
    assert by_name["django.manage_py"].status.value == "warn"
    assert by_name["django.settings"].status.value == "warn"
    assert by_name["flask.entrypoint"].status.value == "warn"

    # Healthy Python + Django + Flask project with valid .venv and dist-info
    py_ok = tmp_path / "py_ok"
    py_ok.mkdir()
    (py_ok / "pyproject.toml").write_text(
        '[project]\nname = "ok"\nrequires-python = ">=3.11,<4"\n'
        'dependencies = ["django>=5.0", "flask>=3.0"]\n'
    )
    (py_ok / "manage.py").write_text("#!/usr/bin/env python\n")
    (py_ok / "mysite").mkdir()
    (py_ok / "mysite" / "settings.py").write_text("SECRET_KEY = 'dev'\n")
    (py_ok / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n")

    venv_bin = py_ok / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    fake_py = venv_bin / "python"
    fake_py.write_text('#!/bin/sh\necho "Python 3.12.2"\n')
    fake_py.chmod(0o755)
    sp = py_ok / ".venv" / "lib" / "python3.12" / "site-packages"
    (sp / "django-5.0.dist-info").mkdir(parents=True)
    (sp / "flask-3.0.dist-info").mkdir(parents=True)

    rep_ok = run_project_checks(py_ok, runtimes=rts, check_ports_enabled=False)
    assert rep_ok.status == "ok"


def test_java_maven_and_gradle_checks(tmp_path: Path) -> None:
    rts = _healthy_runtimes()  # Java 21.0.2

    # Maven with higher required Java (25) and Gradle with non-executable gradlew
    jv = tmp_path / "java_proj"
    jv.mkdir()
    (jv / "pom.xml").write_text(
        "<project><modelVersion>4.0.0</modelVersion>"
        "<properties><maven.compiler.release>25</maven.compiler.release></properties>"
        "</project>"
    )
    (jv / "build.gradle").write_text("sourceCompatibility = '17'\n")
    gradlew = jv / "gradlew"
    gradlew.write_text("#!/bin/sh\n")
    gradlew.chmod(0o644)  # not executable

    rep = run_project_checks(jv, runtimes=rts, check_ports_enabled=False)
    by_name = {c.name: c for c in rep.checks}
    assert by_name["java.pom_xml"].status.value == "ok"
    assert by_name["java.gradlew_permissions"].status.value == "warn"
    ver_Statuses = [c.status.value for c in rep.checks if c.name == "java.version"]
    assert "error" in ver_Statuses and "ok" in ver_Statuses

    # Reject XXE DOCTYPE in pom.xml
    xxe = tmp_path / "maven_xxe"
    xxe.mkdir()
    (xxe / "pom.xml").write_text(
        '<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><project/>'
    )
    rep_xxe = run_project_checks(xxe, runtimes=rts, check_ports_enabled=False)
    assert any(c.name == "java.pom_xml" and c.status.value == "error" for c in rep_xxe.checks)


def test_php_rust_go_and_docker_checks(tmp_path: Path) -> None:
    rts = _healthy_runtimes()

    # PHP Composer missing vendor + version mismatch
    php_dir = tmp_path / "php_proj"
    php_dir.mkdir()
    (php_dir / "composer.json").write_text(
        json.dumps({"name": "acme/app", "require": {"php": ">=8.4.0", "monolog/monolog": "^3.0"}})
    )
    rep_php = run_project_checks(php_dir, runtimes=rts, check_ports_enabled=False)
    php_map = {c.name: c for c in rep_php.checks}
    assert php_map["php.vendor"].status.value == "error"
    assert php_map["php.composer_lock"].status.value == "warn"
    assert php_map["php.version"].status.value == "error"

    # Rust crate with MSRV higher than installed rustc (1.77.0) and missing src/main.rs
    rust_dir = tmp_path / "rust_proj"
    rust_dir.mkdir()
    (rust_dir / "Cargo.toml").write_text(
        '[package]\nname = "app"\nversion = "0.1.0"\nrust-version = "1.85"\n'
    )
    (rust_dir / "rust-toolchain").write_text("1.85.0\n")
    rep_rust = run_project_checks(rust_dir, runtimes=rts, check_ports_enabled=False)
    rust_map = {c.name: c for c in rep_rust.checks}
    assert rust_map["rust.targets"].status.value == "warn"
    assert rust_map["rust.version"].status.value == "warn"
    assert rust_map["rust.msrv"].status.value == "error"

    # Go project with missing go.sum and higher go directive
    go_dir = tmp_path / "go_proj"
    go_dir.mkdir()
    (go_dir / "go.mod").write_text(
        "module example.com/app\n\ngo 1.24\n\nrequire github.com/pkg/errors v0.9.1\n"
    )
    rep_go = run_project_checks(go_dir, runtimes=rts, check_ports_enabled=False)
    go_map = {c.name: c for c in rep_go.checks}
    assert go_map["go.go_mod"].status.value == "ok"
    assert go_map["go.go_sum"].status.value == "warn"
    assert go_map["go.version"].status.value == "error"

    # Docker project with :latest tag and tab-indented compose
    dk_dir = tmp_path / "dk_proj"
    dk_dir.mkdir()
    (dk_dir / "Dockerfile").write_text("FROM node:latest\n")
    (dk_dir / "docker-compose.yml").write_text("services:\n\tweb:\n\t\timage: nginx\n")
    rep_dk = run_project_checks(dk_dir, runtimes=rts, check_ports_enabled=False)
    dk_map = {c.name: c for c in rep_dk.checks}
    assert dk_map["docker.dockerfile"].status.value == "warn"
    assert dk_map["docker.compose"].status.value == "error"
    assert dk_map["docker.runtime"].status.value == "ok"


def test_corrupt_manifests_reported_cleanly(tmp_path: Path) -> None:
    rts = _healthy_runtimes()
    corrupt = tmp_path / "corrupt"
    corrupt.mkdir()
    (corrupt / "package.json").write_text("{not valid json")
    (corrupt / "pyproject.toml").write_text("[project\nbroken = ")
    (corrupt / "pom.xml").write_text("<project><unclosed>")
    (corrupt / "composer.json").write_text("{broken")
    (corrupt / "Cargo.toml").write_text("[package\n")
    (corrupt / "go.mod").write_text("not_a_module_line\n")
    (corrupt / "Dockerfile").write_text("RUN echo no_from\n")

    rep = run_project_checks(corrupt, runtimes=rts, check_ports_enabled=False)
    by_name = {c.name: c for c in rep.checks}
    assert by_name["node.package_json"].status.value == "error"
    assert by_name["python.pyproject_toml"].status.value == "error"
    assert by_name["java.pom_xml"].status.value == "error"
    assert by_name["php.composer_json"].status.value == "error"
    assert by_name["rust.cargo_toml"].status.value == "error"
    assert by_name["go.go_mod"].status.value == "error"
    assert by_name["docker.dockerfile"].status.value == "error"


def test_port_conflict_detection_with_real_localhost_socket(tmp_path: Path) -> None:
    rts = _healthy_runtimes()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]

        proj = tmp_path / "port_proj"
        proj.mkdir()
        (proj / ".env").write_text(f"PORT={port}\n")
        (proj / "package.json").write_text(
            json.dumps({"name": "p", "scripts": {"dev": f"vite --port {port}"}})
        )

        rep = run_project_checks(proj, runtimes=rts, check_ports_enabled=True)
        port_chk = next(c for c in rep.checks if c.name == "ports.conflict")
        assert port_chk.status.value == "warn"
        assert port_chk.evidence["conflicts"][0]["port"] == port


def test_run_isolated_contains_exceptions() -> None:
    def _boom() -> list[CheckResult]:
        raise ValueError("unexpected crash in check")

    res = run_isolated("demo", _boom)
    assert len(res) == 1
    assert res[0].name == "demo.internal_error"
    assert res[0].status.value == "error"


def test_cli_check_command_exit_codes(run: Callable[..., Any], tmp_path: Path) -> None:
    # Empty directory -> skip -> exit 0
    empty = tmp_path / "empty"
    empty.mkdir()
    r0 = run("envdoctor", "check", str(empty), "--json")
    assert r0.exit_code == int(ExitCode.OK)
    assert r0.json()["status"] == "ok"

    # Project with error -> exit 2
    bad = tmp_path / "bad_pkg"
    bad.mkdir()
    (bad / "package.json").write_text("{corrupt")
    r2 = run("envdoctor", "check", str(bad), "--json")
    assert r2.exit_code == int(ExitCode.ERROR)
    assert r2.json()["status"] == "error"
