"""Functional, security, negative and end-to-end tests for env, deps, report and config."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from envdoctor.common.exceptions import ExitCode


def _make_fake_bin(directory: Path, name: str, script: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(f"#!/bin/sh\n{script}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_env_command_and_secret_never_exposed(run: Callable[..., Any], tmp_path: Path) -> None:
    proj = tmp_path / "secret_proj"
    proj.mkdir()

    planted_secrets = (
        "PLANTED_DB_PASS_998877",
        "mock_stripe_key_999999",
        "mock_github_token_value_12345",
        "MOCK_AWS_KEY_123",
        "SuperSecretArbitraryValue_X9Y8Z7",
    )

    (proj / ".env.example").write_text(
        "# Example template\n"
        "DATABASE_URL=\n"
        "STRIPE_SECRET_KEY=\n"
        "GITHUB_TOKEN=\n"
        "AWS_ACCESS_KEY_ID=\n"
        "APP_CUSTOM_VAR=\n"
        "EMPTY_REQUIRED_VAR=\n"
        "MISSING_REQUIRED_VAR=\n",
        encoding="utf-8",
    )
    (proj / ".env").write_text(
        f'DATABASE_URL="postgres://admin:{planted_secrets[0]}@db.internal:5432/prod"\n'
        f"export STRIPE_SECRET_KEY='{planted_secrets[1]}'\n"
        f"GITHUB_TOKEN={planted_secrets[2]} # inline comment\n"
        f"AWS_ACCESS_KEY_ID={planted_secrets[3]}\n"
        f"APP_CUSTOM_VAR={planted_secrets[4]}\n"
        'EMPTY_REQUIRED_VAR=""\n'
        "EXTRA_UNLISTED_KEY=AnotherSecretValue_777666\n",
        encoding="utf-8",
    )

    # 1. env (without --check) exits 0 and shows missing/empty/present
    r_env_human = run("envdoctor", "env", str(proj))
    assert r_env_human.exit_code == int(ExitCode.OK)
    assert "MISSING_REQUIRED_VAR" in r_env_human.stdout
    assert "EMPTY_REQUIRED_VAR" in r_env_human.stdout
    assert "DATABASE_URL" in r_env_human.stdout

    # 2. env --check exits ERROR (2) when keys are missing
    r_env_json = run("envdoctor", "env", str(proj), "--check", "--json")
    assert r_env_json.exit_code == int(ExitCode.ERROR)
    env_data = r_env_json.json()
    assert env_data["missing_keys"] == ["MISSING_REQUIRED_VAR"]
    assert env_data["empty_keys"] == ["EMPTY_REQUIRED_VAR"]
    assert "DATABASE_URL" in env_data["present_keys"]
    assert "EXTRA_UNLISTED_KEY" in env_data["extra_dotenv_keys"]

    # 3. check & report (human, --json, and --output file)
    report_file = tmp_path / "out_report.json"
    r_check_human = run("envdoctor", "check", str(proj))
    r_check_json = run("envdoctor", "check", str(proj), "--json")
    r_rep_out = run("envdoctor", "report", str(proj), "--output", str(report_file))
    report_text = report_file.read_text(encoding="utf-8")

    # Assert NO planted secret value ever appears in any output or file!
    combined_blobs = "\n".join(
        [
            r_env_human.output,
            r_env_json.output,
            r_check_human.output,
            r_check_json.output,
            r_rep_out.output,
            report_text,
        ]
    )
    for secret in (*planted_secrets, "AnotherSecretValue_777666"):
        assert secret not in combined_blobs, f"Secret {secret!r} leaked!"

    # 4. When missing key is provided via process environment, only empty key remains -> WARNING (1)
    r_env_warn = run(
        "envdoctor",
        "env",
        str(proj),
        "--check",
        "--json",
        env={"MISSING_REQUIRED_VAR": "provided_in_env"},
    )
    assert r_env_warn.exit_code == int(ExitCode.WARNING)
    assert "provided_in_env" not in r_env_warn.output

    # 5. When both missing and empty keys are non-empty in process env -> OK (0)
    r_env_ok = run(
        "envdoctor",
        "env",
        str(proj),
        "--check",
        "--json",
        env={
            "MISSING_REQUIRED_VAR": "provided_in_env",
            "EMPTY_REQUIRED_VAR": "also_provided",
        },
    )
    assert r_env_ok.exit_code == int(ExitCode.OK)


def test_deps_diagnose_dry_run_and_conservative_fix(
    run: Callable[..., Any], tmp_path: Path
) -> None:
    fake_bin = tmp_path / "fake_bin"
    # Fake npm that creates node_modules/left-pad/package.json when `npm ci` is called
    _make_fake_bin(
        fake_bin,
        "node",
        'echo "v20.11.0"',
    )
    _make_fake_bin(
        fake_bin,
        "npm",
        'if [ "$1" = "--version" ]; then echo "10.4.0"; exit 0; fi\n'
        'if [ "$1" = "ci" ]; then\n'
        "  mkdir -p node_modules/left-pad\n"
        '  echo \'{"name":"left-pad"}\' > node_modules/left-pad/package.json\n'
        '  echo "added 1 package"\n'
        "  exit 0\n"
        "fi\nexit 1",
    )

    proj = tmp_path / "node_fix_proj"
    proj.mkdir()
    (proj / "package.json").write_text(
        json.dumps({"name": "fix-demo", "dependencies": {"left-pad": "1.3.0"}})
    )
    (proj / "package-lock.json").write_text("{}")

    env = {"PATH": f"{fake_bin}:/bin:/usr/bin"}

    # 1. Diagnose without --fix -> reports error (missing node_modules) and planned action
    r_diag = run("envdoctor", "deps", str(proj), "--json", env=env)
    assert r_diag.exit_code == int(ExitCode.ERROR)
    diag_json = r_diag.json()
    assert len(diag_json["actions"]) == 1
    assert diag_json["actions"][0]["command"] == ["npm", "ci"]
    assert not (proj / "node_modules").exists()

    # 2. --dry-run shows plan and does NOT create node_modules
    r_dry = run("envdoctor", "deps", str(proj), "--dry-run", "--json", env=env)
    assert r_dry.exit_code == int(ExitCode.ERROR)
    assert r_dry.json()["outcomes"][0]["dry_run"] is True
    assert not (proj / "node_modules").exists()

    # 3. Non-interactive --fix without --yes is refused (ExitCode.REFUSED = 3)
    r_refused = run("envdoctor", "deps", str(proj), "--fix", "--json", env=env)
    assert r_refused.exit_code == int(ExitCode.REFUSED)
    assert not (proj / "node_modules").exists()

    # 4. Interactive --fix declined with 'n' -> refused (3)
    r_declined = run(
        "envdoctor", "deps", str(proj), "--fix", input="n\n", interactive=True, env=env
    )
    assert r_declined.exit_code == int(ExitCode.REFUSED)
    assert not (proj / "node_modules").exists()

    # 5. --fix --yes executes 'npm ci' and resolves the missing dependency!
    r_fixed = run("envdoctor", "deps", str(proj), "--fix", "--yes", "--json", env=env)
    assert r_fixed.exit_code == int(ExitCode.OK)
    fixed_data = r_fixed.json()
    assert fixed_data["outcomes"][0]["executed"] is True
    assert fixed_data["outcomes"][0]["ok"] is True
    assert (proj / "node_modules" / "left-pad" / "package.json").is_file()


def test_deps_never_runs_maven_and_supports_pnpm_yarn_composer_python(
    run: Callable[..., Any], tmp_path: Path
) -> None:
    # Maven project: mvn dependency:resolve is NEVER planned
    mvn_proj = tmp_path / "mvn_proj"
    mvn_proj.mkdir()
    (mvn_proj / "pom.xml").write_text("<project><modelVersion>4.0.0</modelVersion></project>")
    r_mvn = run("envdoctor", "deps", str(mvn_proj), "--json")
    assert r_mvn.json()["actions"] == []

    # pnpm + composer + python(.venv) project plans safe commands
    multi = tmp_path / "multi_deps"
    multi.mkdir()
    (multi / "package.json").write_text(json.dumps({"name": "m", "dependencies": {"a": "1.0.0"}}))
    (multi / "pnpm-lock.yaml").write_text("lockfileVersion: '6.0'\n")
    (multi / "composer.json").write_text(
        json.dumps({"name": "m/p", "require": {"monolog/monolog": "^3.0"}})
    )
    (multi / "requirements.txt").write_text("requests>=2.31.0\n")
    venv_bin = multi / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    fake_py = venv_bin / "python"
    fake_py.write_text('#!/bin/sh\necho "Python 3.12.0"\n')
    fake_py.chmod(0o755)

    r_multi = run("envdoctor", "deps", str(multi), "--json")
    ecosystems = {a["ecosystem"]: a["command"] for a in r_multi.json()["actions"]}
    assert ecosystems["nodejs"] == ["pnpm", "install", "--frozen-lockfile"]
    assert ecosystems["composer"] == ["composer", "install", "--no-interaction"]
    assert ecosystems["python"] == [str(fake_py), "-m", "pip", "install", "-r", "requirements.txt"]


def test_report_output_file_safety_and_force(run: Callable[..., Any], tmp_path: Path) -> None:
    fake_bin = tmp_path / "rep_bin"
    _make_fake_bin(fake_bin, "node", 'echo "v20.11.0"')
    env = {"PATH": f"{fake_bin}:/bin:/usr/bin"}

    proj = tmp_path / "rep_proj"
    proj.mkdir()
    (proj / "package.json").write_text(json.dumps({"name": "clean-pkg"}))

    out_file = tmp_path / "report.json"
    r1 = run("envdoctor", "report", str(proj), "--output", str(out_file), "--json", env=env)
    assert r1.exit_code in (int(ExitCode.OK), int(ExitCode.WARNING))
    assert out_file.is_file()
    saved = json.loads(out_file.read_text(encoding="utf-8"))
    assert saved["path"] == str(proj)
    assert isinstance(saved["checks"], list) and len(saved["checks"]) > 0

    # Refuses to overwrite existing file without --force (ExitCode.REFUSED = 3)
    r_overwrite = run("envdoctor", "report", str(proj), "--output", str(out_file), env=env)
    assert r_overwrite.exit_code == int(ExitCode.REFUSED)

    # Overwrites when --force is given
    r_force = run("envdoctor", "report", str(proj), "--output", str(out_file), "--force", env=env)
    assert r_force.exit_code in (int(ExitCode.OK), int(ExitCode.WARNING))

    # Refuses nonexistent output directory
    missing_parent = tmp_path / "no_such_dir" / "report.json"
    r_no_dir = run("envdoctor", "report", str(proj), "--output", str(missing_parent), env=env)
    assert r_no_dir.exit_code == int(ExitCode.ERROR)

    # Refuses symlink target for --output
    sym_target = tmp_path / "real_target.json"
    sym_target.write_text("{}")
    sym_link = tmp_path / "symlink_report.json"
    os.symlink(sym_target, sym_link)
    r_sym = run("envdoctor", "report", str(proj), "--output", str(sym_link), "--force", env=env)
    assert r_sym.exit_code == int(ExitCode.REFUSED)


def test_config_ignore_checks_and_required_env(run: Callable[..., Any], tmp_path: Path) -> None:
    proj = tmp_path / "cfg_proj"
    proj.mkdir()
    (proj / "package.json").write_text(
        json.dumps({"name": "cfg-app", "dependencies": {"left-pad": "1.0.0"}})
    )

    assert (
        run(
            "envdoctor",
            "config",
            "set",
            "ignore_checks",
            "node.node_modules,node.lockfile",
        ).exit_code
        == 0
    )
    assert run("envdoctor", "config", "set", "required_env", "CUSTOM_CFG_TOKEN").exit_code == 0

    # Check reflects ignored checks as 'skip' and checks CUSTOM_CFG_TOKEN
    r_chk = run("envdoctor", "check", str(proj), "--json")
    checks = {c["name"]: c for c in r_chk.json()["checks"]}
    assert checks["node.node_modules"]["status"] == "skip"
    assert checks["node.lockfile"]["status"] == "skip"
    assert checks["env.required_keys"]["status"] == "error"
    assert "CUSTOM_CFG_TOKEN" in checks["env.required_keys"]["evidence"]["missing_keys"]


def test_negative_paths_permissions_unicode_and_subprocess(
    run: Callable[..., Any],
    run_proc: Callable[..., Any],
    tmp_path: Path,
) -> None:
    # 1. Nonexistent path -> ExitCode.ERROR (2)
    r_missing = run("envdoctor", "check", str(tmp_path / "does_not_exist"))
    assert r_missing.exit_code == int(ExitCode.ERROR)

    # 2. File passed where directory expected -> ExitCode.USAGE (64)
    some_file = tmp_path / "file.txt"
    some_file.write_text("hi")
    r_file = run("envdoctor", "check", str(some_file))
    assert r_file.exit_code == int(ExitCode.USAGE)

    # 3. Unknown CLI option -> ExitCode.USAGE (64)
    r_bad_flag = run("envdoctor", "check", "--no-such-option")
    assert r_bad_flag.exit_code == int(ExitCode.USAGE)

    # 4. Unicode and spaces in project path
    unicode_dir = tmp_path / "Projet Café ☕ With Spaces"
    unicode_dir.mkdir()
    (unicode_dir / "go.mod").write_text("module example.com/cafe\n\ngo 1.21\n")
    r_uni = run("envdoctor", "check", str(unicode_dir), "--json")
    assert r_uni.exit_code in (int(ExitCode.OK), int(ExitCode.WARNING), int(ExitCode.ERROR))
    assert "go" in r_uni.json()["project_types"]

    # 5. Permission denied directory (skip if running as root)
    if os.geteuid() != 0:
        locked = tmp_path / "locked_dir"
        locked.mkdir()
        locked.chmod(0o000)
        try:
            r_perm = run("envdoctor", "check", str(locked))
            assert r_perm.exit_code == int(ExitCode.ERROR)
        finally:
            locked.chmod(0o755)

    # 6. End-to-end subprocess invocation via run_proc
    r_e2e = run_proc("envdoctor", "check", str(unicode_dir), "--json")
    assert r_e2e.exit_code in (int(ExitCode.OK), int(ExitCode.WARNING), int(ExitCode.ERROR))
    assert r_e2e.json()["path"] == str(unicode_dir)
