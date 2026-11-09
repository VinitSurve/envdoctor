# EnvDoctor (`envdoctor`)

> Development Environment Diagnostics for macOS & POSIX

[![CI](https://github.com/VinitSurve/envdoctor/actions/workflows/ci.yml/badge.svg)](https://github.com/VinitSurve/envdoctor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11%2B-brightgreen.svg)](https://www.python.org/)

`envdoctor` is a local-first, zero-telemetry development environment diagnostics utility designed for macOS (Apple Silicon M-series and Intel) and POSIX workstations. It auto-detects project ecosystems, validates toolchains, inspects PATH health, flags broken operating system shims, audits environment variables without leaking secrets, and produces machine-readable diagnostic reports.

---

## Features

- **14 Project Types Detected:** Auto-detects Node.js, React, Vite, Next.js, Python, Django, Flask, Java/Maven, Java/Gradle, PHP, Composer, Rust, Go, and Docker-based projects.
- **Deep System Probing:** Checks macOS version (`sw_vers`), Apple Silicon CPU cores, RAM allocation, APFS storage, Rosetta 2 translation (`sysctl sysctl.proc_translated`), Homebrew installation, and Xcode Command Line Tools.
- **Runtime & Toolchain Diagnostics:** Probes Python, Node.js, npm, pnpm, yarn, Java, Git, Go, Rust (`rustc` / `cargo`), Ruby, PHP, and Docker. Detects broken OS shims (e.g. `/usr/bin/java` without a JDK), CLT prompts, shadowed PATH duplicates, and daemon responsiveness.
- **Secret-Safe Environment Auditing:** Compares required keys in `.env.example`, `.env.sample`, `docker-compose.yml`, or configuration against `.env` and `os.environ`. Flags missing or empty keys while **never printing, logging, or storing secret values**.
- **Automated Dependency Health:** Diagnoses missing dependency folders (`node_modules`, `.venv`, `vendor/`) and offers safe, confirmed one-step repairs.
- **Unified Diagnostic Reports:** Outputs rich terminal tables or clean, single-document JSON (`--json` or `--output report.json`).
- **Defensive & Local-First:** No cloud dependencies, no tracking, no daemons, read-only by default, and safe subprocess invocation without shell expansion.

---

## Installation

### Using pipx (Recommended for standalone CLI use)

```bash
pipx install git+https://github.com/VinitSurve/envdoctor.git
```

Or install from a local checkout:

```bash
git clone https://github.com/VinitSurve/envdoctor.git
cd envdoctor
pipx install .
```

### Using pip (in an active virtual environment)

```bash
pip install .
```

---

## Quick Start

```bash
# Inspect host hardware, macOS version, Rosetta 2, and PATH health
envdoctor info

# Probe compilers, runtimes, and Docker daemon responsiveness
envdoctor runtimes

# Diagnose the project in your current working directory
envdoctor check

# Audit environment variable presence against .env.example
envdoctor env --check

# Generate a complete diagnostic report in JSON format
envdoctor report --json --output envdoctor-report.json
```

---

## Command Reference

| Command | Description |
|---|---|
| `envdoctor info` | Inspect system hardware, CPU, RAM, macOS release, Rosetta 2 status, active shell, and PATH entry health. |
| `envdoctor runtimes` | Probe all installed compilers, package managers, and container runtimes; reports paths and version constraints. |
| `envdoctor check [PATH]` | Detect project types in `[PATH]` (defaults to `.`) and validate manifests, lockfiles, runtimes, and port conflicts. |
| `envdoctor deps [PATH] [--fix] [--dry-run] [--yes]` | Check dependency directories (`node_modules`, `.venv`, `vendor/`); optionally run verified package installations. |
| `envdoctor env [PATH] [--check]` | Compare required keys from templates/compose against active `.env` and environment variables. |
| `envdoctor report [PATH] [--json] [--output FILE] [--force]` | Run unified diagnostic suite and generate comprehensive report. |
| `envdoctor config [show\|get\|set\|path\|reset]` | Manage persistent configuration stored in `~/Library/Application Support/devtoolkit/envdoctor/config.json`. |

### Global Flags

All commands support the following global flags:

- `--json`: Output machine-readable JSON on `stdout`.
- `--quiet`: Suppress decorative banners, headings, and progress indicators.
- `--verbose`: Print diagnostic debugging details to `stderr`.
- `--no-color`: Disable ANSI color escapes (respects `NO_COLOR=1`).
- `--help`, `-h`: Show usage assistance.
- `--version`: Display `envdoctor` version.

### Standard Exit Codes

- `0` (`OK`): All checks passed / healthy environment.
- `1` (`WARNING`): Completed with warnings, or broken runtime detected.
- `2` (`ERROR`): Critical errors found, missing required environment variables, or check failures.
- `3` (`REFUSED`): Operation cancelled by user, confirmation declined, or non-interactive run without `--yes`.
- `64` (`USAGE`): Invalid command line arguments.
- `130` (`INTERRUPTED`): Interrupted via `Ctrl-C` (`SIGINT`).

---

## Configuration

`envdoctor` stores its persistent configuration in macOS standard platform directories:
- **Config & Data:** `~/Library/Application Support/devtoolkit/envdoctor/config.json`
- **Logs:** `~/Library/Logs/devtoolkit/envdoctor/envdoctor.log`

Override the configuration directory for testing or custom environments by setting `DEVTOOLKIT_HOME=/custom/path`.

Example configuration management:
```bash
# View active configuration
envdoctor config show

# Set command timeout to 10 seconds
envdoctor config set command_timeout 10.0

# Add a required environment variable for your team
envdoctor config set required_env '["DATABASE_URL", "REDIS_HOST"]'

# Reset configuration to defaults
envdoctor config reset --yes
```

---

## Safety & Security Guarantees

1. **Zero Secret Leakage:** `.env` parsers read keys strictly to test presence and non-emptiness. Secret values are discarded immediately and are never printed, written to logs, or retained in memory structures.
2. **Read-Only by Default:** `envdoctor check`, `info`, `runtimes`, and `env` perform strictly read-only diagnostics.
3. **Safe Subprocesses:** Subprocesses are invoked with discrete argument vectors (`shell=False`) and explicit execution timeouts.
4. **Interactive Guardrails:** Any mutating operation (`deps --fix`, `config reset`) requires explicit interactive confirmation or `--yes`.

---

## Development Setup

```bash
# Clone repository
git clone https://github.com/VinitSurve/envdoctor.git
cd envdoctor

# Create development virtual environment and install dependencies
make dev

# Run full test suite
make test

# Format and lint code
make format
make lint
make typecheck

# Full CI validation check
make check
```

---

## Running Tests

```bash
# Run tests with pytest
pytest -v

# Run fast tests excluding slow system probes
pytest -m "not slow" -q
```

---

## Known Limitations

- **Java Stub Prompts:** On macOS without Java installed, running `/usr/bin/java` triggers an Apple GUI dialog. `envdoctor` uses `/usr/libexec/java_home` and path inspection to prevent triggering GUI prompts.
- **Docker Detection:** Testing Docker daemon responsiveness requires the Docker desktop application or daemon to be actively running.
- **Port Conflict Scanning:** Port conflict checks inspect local socket bindings; root-owned processes may mask their process name unless run with sufficient permissions.

---

## License

This project is licensed under the [MIT License](LICENSE).
