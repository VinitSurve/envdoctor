# Usage Guide

`envdoctor` provides commands to inspect hardware, audit developer runtimes, diagnose project configurations across 14 ecosystems, repair missing dependencies, verify environment variables safely, and generate consolidated reports.

---

## Global Options

The following flags can be passed to `envdoctor` or any of its subcommands:

| Option | Short | Description |
|---|---|---|
| `--json` | | Output pure, machine-readable JSON on `stdout`. Useful for CI and scripting. |
| `--quiet` | `-q` | Suppress decorative banners, headings, and non-essential progress output. |
| `--verbose` | `-v` | Enable detailed diagnostic debugging output on `stderr`. |
| `--no-color` | | Disable ANSI color escapes (respects `NO_COLOR=1` environment variable). |
| `--version` | | Print `envdoctor` version and exit. |
| `--help` | `-h` | Display usage instructions and options. |

---

## Exit Codes

`envdoctor` returns standardized exit codes suitable for CI/CD pipelines and automated health checks:

| Code | Name | Meaning |
|---|---|---|
| `0` | `OK` | All diagnostics passed without warnings or errors. Environment is healthy. |
| `1` | `WARNING` | Completed with non-fatal warnings (e.g. shadowed PATH binary, missing lockfile, disk warning). |
| `2` | `ERROR` | Critical errors encountered (e.g. missing required runtime, port conflict, missing required env var). |
| `3` | `REFUSED` | Mutating operation cancelled or confirmation declined (non-interactive run without `--yes`). |
| `64` | `USAGE` | Invalid CLI arguments or syntax error. |
| `130` | `INTERRUPTED` | Execution interrupted via `SIGINT` (`Ctrl-C`). |

---

## Commands

### 1. `envdoctor info`

Inspects workstation hardware, operating system details, Apple Silicon / Rosetta 2 status, active shell, Homebrew installation, and `$PATH` health.

```bash
# Pretty terminal output
envdoctor info

# Machine-readable JSON output
envdoctor info --json
```

**What it inspects:**
- **OS & Kernel:** macOS release (`sw_vers`), build number, Darwin kernel version.
- **Hardware:** CPU model/brand, physical and logical CPU cores, total RAM.
- **Rosetta 2 Detection:** Detects whether the active process is running translated under Rosetta 2 (`sysctl sysctl.proc_translated`) on Apple Silicon.
- **Python Environment:** Python version, active interpreter path, and Python CPU architecture.
- **Homebrew:** Prefix (`/opt/homebrew` vs `/usr/local`) and binary availability.
- **Disk Usage:** APFS / root filesystem total, used, free space, and percentage used.
- **PATH Health:** Detects duplicate entries, missing directories, and invalid paths.

---

### 2. `envdoctor runtimes`

Probes installed compilers, interpreters, build tools, package managers, and container runtimes.

```bash
envdoctor runtimes
envdoctor runtimes --json
```

**Runtimes & Tools Probed:**
- **Python:** `python3`, `python`
- **Node.js Ecosystem:** `node`, `npm`, `pnpm`, `yarn`
- **Java:** `java`, `javac` (safely checks via `/usr/libexec/java_home` without triggering macOS GUI dialogs)
- **Version Control:** `git`
- **Go:** `go`
- **Rust:** `rustc`, `cargo`
- **Ruby:** `ruby`
- **PHP:** `php`, `composer`
- **Containers:** `docker` (checks CLI presence and daemon socket responsiveness)

---

### 3. `envdoctor check [PATH]`

Auto-detects project types in `[PATH]` (defaults to current working directory `.`) and runs isolated diagnostic checks.

```bash
# Check current directory
envdoctor check

# Check a specific project directory
envdoctor check /path/to/my-project

# Run in quiet mode for CI exit code testing
envdoctor check --quiet
```

**Supported Project Types (14 Ecosystems):**
1. **Node.js:** Detects `package.json`, validates dependencies, engines constraints, and lockfiles (`package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`).
2. **React:** Detects React manifests and scripts.
3. **Vite:** Detects `vite.config.*` and dev server settings.
4. **Next.js:** Detects `next.config.*` and framework dependencies.
5. **Python:** Detects `pyproject.toml`, `requirements.txt`, `setup.py`, `Pipfile`.
6. **Django:** Detects `manage.py` and Django configuration.
7. **Flask:** Detects Flask applications (`app.py`, `wsgi.py`).
8. **Java / Maven:** Detects `pom.xml`, validates JDK version compatibility against source/target levels.
9. **Java / Gradle:** Detects `build.gradle`, `build.gradle.kts`, `gradlew`.
10. **PHP:** Detects PHP source trees.
11. **Composer:** Detects `composer.json` and `composer.lock`.
12. **Rust:** Detects `Cargo.toml`, `Cargo.lock`, compiler toolchain.
13. **Go:** Detects `go.mod`, `go.sum`, Go toolchain version.
14. **Docker:** Detects `Dockerfile`, `docker-compose.yml`, `compose.yaml`.

**Port Conflict Scanning:**
Scans commonly used ports for detected frameworks (e.g. 3000 for Node/Next, 5000 for Flask, 8000 for Django, 8080 for Maven/Tomcat) and flags localhost socket collisions.

---

### 4. `envdoctor deps [PATH] [--fix] [--dry-run] [--yes]`

Inspects package manifests and flags missing dependency directories (`node_modules`, `.venv`, `vendor/`).

```bash
# Check status of dependency folders
envdoctor deps

# Preview repair commands without modifying anything
envdoctor deps --fix --dry-run

# Execute repair commands with interactive confirmation prompt
envdoctor deps --fix

# Execute repair automatically without prompts (for CI)
envdoctor deps --fix --yes
```

**Conservative Healing Actions:**
- Node.js: Runs `npm install` (or `pnpm install`, `yarn install` depending on lockfile).
- Python: Proposes `python3 -m venv .venv` and requirements installation.
- Composer: Proposes `composer install`.
- Maven/Gradle: Conservative by design; will **never** automatically run build tools without explicit user command.

---

### 5. `envdoctor env [PATH] [--check]`

Audits required environment variables by comparing `.env.example`, `.env.sample`, `docker-compose.yml`, and configured team requirements against `.env` and `os.environ`.

```bash
# Audit environment variable presence
envdoctor env

# Force strict check mode (fails if required keys are missing or empty)
envdoctor env --check
```

**Zero-Secret Guarantee:**
- Inspects **key names only**.
- Values are **never** logged, printed, or saved in memory structures.
- Reports whether variables are `present`, `empty`, or `missing`.

---

### 6. `envdoctor report [PATH] [--json] [--output FILE] [--force]`

Runs the complete unified diagnostic suite (system info, runtimes, project checks, dependencies, environment) and outputs a consolidated report.

```bash
# Output full terminal report
envdoctor report

# Generate single-file JSON report
envdoctor report --json --output report.json

# Overwrite existing report file
envdoctor report --json --output report.json --force
```

---

### 7. `envdoctor config [show|get|set|path|reset]`

Manages persistent preferences. See [Configuration Reference](configuration.md) for complete details.

```bash
envdoctor config show
envdoctor config get command_timeout
envdoctor config set command_timeout 10
envdoctor config path
envdoctor config reset --yes
```
