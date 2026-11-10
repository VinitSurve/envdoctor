# Development Guide

This guide provides instructions for developers contributing to the `envdoctor` codebase.

---

## 1. Prerequisites

- **Python 3.11+**
- **Git**
- **GNU Make**
- Recommended: `pre-commit`

---

## 2. Environment Setup

Clone the repository and set up your virtual environment using the provided `Makefile`:

```bash
# Clone the repository
git clone https://github.com/VinitSurve/envdoctor.git
cd envdoctor

# Create virtualenv and install editable package with dev dependencies
make dev

# Activate the virtual environment
source .venv/bin/activate
```

### Install Pre-commit Hooks

We provide a `.pre-commit-config.yaml` configuration to run Ruff linting/formatting and Mypy checks on commit:

```bash
pip install pre-commit
pre-commit install
```

---

## 3. Makefile Commands

The `Makefile` automates routine developer workflows:

| Command | Action |
|---|---|
| `make dev` | Installs virtual environment `.venv/` and editable package with `[dev]` dependencies |
| `make format` | Formats Python code across `src` and `tests` using `ruff format` |
| `make lint` | Performs static analysis and lint checks using `ruff check` |
| `make typecheck` | Validates strict type annotations using `mypy` |
| `make test` | Executes the complete test suite with `pytest -v` |
| `make build` | Cleans and compiles sdist and wheel packages into `dist/` using `python -m build` |
| `make check` | Runs full CI verification locally (format check, lint, mypy, pytest) |
| `make release-dry-run` | Cleans, builds distribution packages, and validates metadata with `twine check` |
| `make clean` | Cleans build directories, pytest cache, mypy cache, and `__pycache__` folders |

---

## 4. Code Quality & Style Standards

### Ruff Formatting & Linting
- Maximum line length is **100 characters**.
- Targeted to **Python 3.11+**.
- Rules enabled: `E`, `F`, `W`, `I` (isort), `B` (flake8-bugbear), `UP` (pyupgrade), `SIM` (flake8-simplify), `S` (flake8-bandit), `C4` (flake8-comprehensions), `RUF` (ruff-specific), `PTH` (flake8-use-pathlib), `PL` (pylint).
- Run `make format` and `make lint` prior to committing.

### Strict Typing (Mypy)
- All production code in `src/envdoctor` is strictly typed.
- `strict = true`, `warn_unused_ignores = true`, `warn_return_any = true`.
- Functions and methods must have complete type annotations for all arguments and return values.

### Subprocess Safety Rules
- **NEVER** use `shell=True`.
- **ALWAYS** pass commands as lists of strings (`["git", "status"]`).
- **ALWAYS** define explicit timeouts (`timeout=5.0`) to avoid hanging processes.
- Handle `subprocess.TimeoutExpired` and `FileNotFoundError` gracefully.

### Secret Redaction
- All `CheckResult` instances automatically pass explanations, suggestions, and evidence dictionaries through `redact_text` and `redact_mapping`.
- Never print or store environment variable values.

---

## 5. Adding a New Project Check

To add a check for a new framework or ecosystem:

1. Create a module under `src/envdoctor/checks/<ecosystem>.py`.
2. Define a check function that accepts `(path: Path, context: CheckContext)` and returns `list[CheckResult]`.
3. Add detection patterns in `src/envdoctor/detect.py`.
4. Register the check function in `src/envdoctor/checks/__init__.py`.
5. Add comprehensive unit tests in `tests/test_detect_and_checks.py`.

Example check implementation:
```python
from pathlib import Path
from envdoctor.models import CheckResult, CheckStatus, Severity

def check_bun_project(project_path: Path) -> list[CheckResult]:
    results: list[CheckResult] = []
    lockfile = project_path / "bun.lockb"
    if not lockfile.exists():
        results.append(
            CheckResult(
                name="bun.lockfile",
                status=CheckStatus.WARN,
                severity=Severity.MEDIUM,
                explanation="bun.lockb is missing from the project root.",
                suggestion="Run 'bun install' to generate a reproducible lockfile.",
            )
        )
    return results
```

---

## 6. Running Tests

We use `pytest` with `pytest-timeout`:

```bash
# Run all tests verbosely
make test

# Run a specific test file
pytest tests/test_system_and_runtimes.py -v

# Run tests matching an expression
pytest -k "test_probe_runtime" -v

# Run excluding slow tests
pytest -m "not slow" -q
```
