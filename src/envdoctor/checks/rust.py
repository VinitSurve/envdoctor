"""Rust (Cargo / rustc) project checks."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from envdoctor.models import CheckResult, CheckStatus, RuntimeInfo, Severity
from envdoctor.versions import match_semver_range


def _parse_cargo_toml(root: Path) -> tuple[dict[str, Any] | None, CheckResult | None]:
    cargo_path = root / "Cargo.toml"
    if not cargo_path.exists():
        return None, CheckResult(
            name="rust.cargo_toml",
            status=CheckStatus.WARN,
            severity=Severity.MEDIUM,
            explanation="Rust toolchain file found, but 'Cargo.toml' is missing.",
            suggestion="Run 'cargo init' or restore 'Cargo.toml'.",
            evidence={"path": str(cargo_path), "exists": False},
        )
    try:
        raw = cargo_path.read_text(encoding="utf-8", errors="replace")
        data = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        return None, CheckResult(
            name="rust.cargo_toml",
            status=CheckStatus.ERROR,
            severity=Severity.HIGH,
            explanation=f"'Cargo.toml' is not valid TOML: {exc}",
            suggestion="Fix the TOML syntax error in 'Cargo.toml'.",
            evidence={"path": str(cargo_path)},
        )
    except OSError as exc:
        return None, CheckResult(
            name="rust.cargo_toml",
            status=CheckStatus.ERROR,
            severity=Severity.HIGH,
            explanation=f"Cannot read 'Cargo.toml': {exc}",
            suggestion="Check file permissions on 'Cargo.toml'.",
            evidence={"path": str(cargo_path)},
        )
    if "package" not in data and "workspace" not in data:
        return None, CheckResult(
            name="rust.cargo_toml",
            status=CheckStatus.ERROR,
            severity=Severity.HIGH,
            explanation="'Cargo.toml' must contain a [package] or [workspace] section.",
            suggestion="Add a [package] or [workspace] table to 'Cargo.toml'.",
            evidence={"path": str(cargo_path)},
        )
    return data, CheckResult(
        name="rust.cargo_toml",
        status=CheckStatus.OK,
        severity=Severity.INFO,
        explanation="'Cargo.toml' is valid TOML.",
        evidence={"path": str(cargo_path)},
    )


def _read_rust_toolchain(root: Path) -> tuple[str | None, str | None]:
    tc_toml = root / "rust-toolchain.toml"
    if tc_toml.is_file() and not tc_toml.is_symlink():
        try:
            data = tomllib.loads(tc_toml.read_text(encoding="utf-8", errors="replace"))
            tc = data.get("toolchain")
            if isinstance(tc, dict) and isinstance(tc.get("channel"), str):
                return tc["channel"].strip(), "rust-toolchain.toml"
        except (OSError, tomllib.TOMLDecodeError):
            pass

    tc_plain = root / "rust-toolchain"
    if tc_plain.is_file() and not tc_plain.is_symlink():
        try:
            raw = tc_plain.read_text(encoding="utf-8", errors="replace").strip()
            if raw.startswith("["):
                data = tomllib.loads(raw)
                tc = data.get("toolchain")
                if isinstance(tc, dict) and isinstance(tc.get("channel"), str):
                    return tc["channel"].strip(), "rust-toolchain"
            else:
                first = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
                if first:
                    return first, "rust-toolchain"
        except (OSError, tomllib.TOMLDecodeError):
            pass

    return None, None


def run_rust_checks(
    root: Path,
    project_types: Sequence[str],
    runtimes: Mapping[str, RuntimeInfo],
) -> list[CheckResult]:
    """Run Rust project checks."""
    if "rust" not in project_types:
        return []

    results: list[CheckResult] = []
    cargo_data, cargo_check = _parse_cargo_toml(root)
    if cargo_check is not None:
        results.append(cargo_check)

    if cargo_data and "package" in cargo_data and "workspace" not in cargo_data:
        has_src = (
            (root / "src" / "main.rs").is_file()
            or (root / "src" / "lib.rs").is_file()
            or isinstance(cargo_data.get("bin"), list)
            or isinstance(cargo_data.get("lib"), dict)
        )
        if not has_src:
            results.append(
                CheckResult(
                    name="rust.targets",
                    status=CheckStatus.WARN,
                    severity=Severity.MEDIUM,
                    explanation="No Cargo target ('src/main.rs' or 'src/lib.rs') found.",
                    suggestion=(
                        "Create 'src/main.rs' or 'src/lib.rs', "
                        "or declare [[bin]]/[lib] in Cargo.toml."
                    ),
                    evidence={"has_target": False},
                )
            )
        else:
            results.append(
                CheckResult(
                    name="rust.targets",
                    status=CheckStatus.OK,
                    severity=Severity.INFO,
                    explanation="Cargo crate target source files are present.",
                    evidence={"has_target": True},
                )
            )

        if (root / "src" / "main.rs").is_file() and not (root / "Cargo.lock").is_file():
            results.append(
                CheckResult(
                    name="rust.lockfile",
                    status=CheckStatus.WARN,
                    severity=Severity.LOW,
                    explanation="Binary crate has no 'Cargo.lock' file.",
                    suggestion="Run 'cargo generate-lockfile' and commit 'Cargo.lock'.",
                    evidence={"lockfile_exists": False},
                )
            )

    rustc_rt = runtimes.get("rustc")
    channel, channel_src = _read_rust_toolchain(root)
    msrv: str | None = None
    if cargo_data and isinstance(cargo_data.get("package"), dict):
        rv = cargo_data["package"].get("rust-version")
        if isinstance(rv, str) and rv.strip():
            msrv = rv.strip()

    if not rustc_rt or not rustc_rt.found or not rustc_rt.healthy or not rustc_rt.version:
        if channel or msrv:
            results.append(
                CheckResult(
                    name="rust.version",
                    status=CheckStatus.ERROR,
                    severity=Severity.HIGH,
                    explanation=(
                        "Rust project specifies a compiler version, "
                        "but 'rustc' is not available on PATH."
                    ),
                    suggestion="Install Rust via rustup ('https://rustup.rs').",
                    evidence={"installed": None, "toolchain": channel, "rust_version": msrv},
                )
            )
        return results

    if channel and channel not in ("stable", "beta", "nightly"):
        # Extract version prefix before target triple if any (e.g. "1.76.0-aarch64-apple-darwin")
        ver_part = channel.split("-")[0]
        matched = match_semver_range(rustc_rt.version, ver_part)
        if matched is None:
            results.append(
                CheckResult(
                    name="rust.version",
                    status=CheckStatus.SKIP,
                    severity=Severity.INFO,
                    explanation=(
                        f"Could not compare rust-toolchain channel '{channel}' "
                        f"against rustc {rustc_rt.version}."
                    ),
                    evidence={
                        "source": channel_src,
                        "required": channel,
                        "installed": rustc_rt.version,
                    },
                )
            )
        elif not matched:
            results.append(
                CheckResult(
                    name="rust.version",
                    status=CheckStatus.WARN,
                    severity=Severity.MEDIUM,
                    explanation=(
                        f"Rust toolchain mismatch: {channel_src} specifies '{channel}', "
                        f"but active rustc is '{rustc_rt.version}'."
                    ),
                    suggestion=f"Run 'rustup toolchain install {ver_part}'.",
                    evidence={
                        "source": channel_src,
                        "required": channel,
                        "installed": rustc_rt.version,
                    },
                )
            )
        else:
            results.append(
                CheckResult(
                    name="rust.version",
                    status=CheckStatus.OK,
                    severity=Severity.INFO,
                    explanation=(
                        f"Active rustc {rustc_rt.version} matches {channel_src} ('{channel}')."
                    ),
                    evidence={
                        "source": channel_src,
                        "required": channel,
                        "installed": rustc_rt.version,
                    },
                )
            )

    if msrv:
        matched = match_semver_range(rustc_rt.version, f">={msrv}")
        if matched is False:
            results.append(
                CheckResult(
                    name="rust.msrv",
                    status=CheckStatus.ERROR,
                    severity=Severity.HIGH,
                    explanation=(
                        f"Installed rustc {rustc_rt.version} is older than Cargo.toml "
                        f"rust-version (MSRV) '{msrv}'."
                    ),
                    suggestion="Run 'rustup update' to upgrade your Rust toolchain.",
                    evidence={"required_msrv": msrv, "installed": rustc_rt.version},
                )
            )
        elif matched is True:
            results.append(
                CheckResult(
                    name="rust.msrv",
                    status=CheckStatus.OK,
                    severity=Severity.INFO,
                    explanation=(
                        f"Installed rustc {rustc_rt.version} satisfies Cargo.toml MSRV '{msrv}'."
                    ),
                    evidence={"required_msrv": msrv, "installed": rustc_rt.version},
                )
            )

    return results
