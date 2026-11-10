# Contributing to EnvDoctor

Thank you for your interest in contributing to `envdoctor`! We welcome contributions from everyone, whether you are fixing a bug, adding support for a new runtime, improving documentation, or proposing new features.

Please take a moment to review this guide before submitting issues or pull requests.

---

## Code of Conduct

All contributors and maintainers are expected to abide by the [Contributor Covenant Code of Conduct](.github/CODE_OF_CONDUCT.md). Please treat all members of the community with respect and kindness.

---

## Getting Started

### Prerequisites

- **Python 3.11+** installed on your workstation.
- **Git** version control.
- **Make** (standard on macOS and POSIX systems).
- Optional: `pipx` or virtualenv tools.

### Repository Setup

1. Fork the repository on GitHub and clone your fork locally:
   ```bash
   git clone https://github.com/<your-username>/envdoctor.git
   cd envdoctor
   ```

2. Set up the development virtual environment and install dependencies in editable mode:
   ```bash
   make dev
   ```
   This creates a virtual environment at `.venv/` and installs the package with all development dependencies.

3. Activate the virtual environment:
   ```bash
   source .venv/bin/activate
   ```

4. (Recommended) Install pre-commit hooks to automatically check your changes before committing:
   ```bash
   pip install pre-commit
   pre-commit install
   ```

---

## Development Workflow

We use a `Makefile` to simplify common development tasks.

### Available Make Targets

| Target | Description |
|---|---|
| `make dev` | Creates `.venv/` and installs editable package with `[dev]` dependencies |
| `make format` | Formats code using `ruff format` |
| `make lint` | Runs lint checks with `ruff check` |
| `make typecheck` | Runs static type checking using `mypy` in strict mode |
| `make test` | Runs the full test suite with `pytest -v` |
| `make build` | Builds wheel and sdist distributions under `dist/` |
| `make check` | Runs full CI checks locally (format check, lint, mypy, pytest) |
| `make release-dry-run` | Cleans, builds distributions, and validates packages |
| `make clean` | Removes build artifacts, caches, and temporary files |

---

## Coding Standards & Guidelines

### 1. Code Formatting & Linting
- We use **Ruff** for both formatting and linting.
- Line length limit is **100 characters**.
- Target Python version is **3.11+**.
- Run `make format` to automatically reformat modified files.
- Run `make lint` to detect lint issues.

### 2. Static Typing
- All production code in `src/envdoctor` must be **strictly typed**.
- Type checking is enforced with `mypy` (`strict = true`).
- Ensure all functions, parameters, and return values include type hints.
- Type stubs (`py.typed`) are included to support downstream type checkers.

### 3. Defensive Programming & Safety
- **Zero Secret Exposure:** Never log, store, or display secret values. Environment audits inspect keys and check for empty/present status only.
- **Safe Subprocesses:** Subprocesses must **always** be invoked with argument vectors (`shell=False`) and explicit timeouts.
- **Non-destructive Diagnostics:** All diagnostic checks (`info`, `runtimes`, `check`, `env`) must remain strictly read-only. Mutating actions (`deps --fix`, `config reset`) require user confirmation or `--yes`.
- **macOS Safety:** When probing tools like Java, never execute shims like `/usr/bin/java` directly without checking `/usr/libexec/java_home` first, to avoid triggering macOS system GUI install popups.

---

## Testing Guidelines

- We use **pytest** with `pytest-timeout`.
- Tests are located in the `tests/` directory.
- Test files should mirror the structure of the module being tested.
- Whenever you add a feature or fix a bug, include corresponding unit and/or integration tests.

### Running Tests

```bash
# Run all tests verbosely
make test

# Or run pytest directly
pytest -v

# Run a specific test module
pytest tests/test_detect_and_checks.py -v

# Run fast tests (skipping slow markers)
pytest -m "not slow" -q
```

---

## Documentation Guidelines

- If you introduce a new command, option, check rule, or runtime detection, update:
  - `README.md`
  - Relevant guides under `docs/` (`usage.md`, `configuration.md`, etc.)
- Keep documentation clear, concise, and accurate with real-world examples.

---

## Pull Request Guidelines

1. **Create a Feature Branch:**
   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/issue-description
   ```

2. **Commit Messages:**
   - Write clear, concise commit messages in imperative mood (e.g. `Add support for Bun runtime detection`).
   - Group related changes into logical commits.

3. **Verify Everything Locally:**
   Before pushing, ensure that all checks pass:
   ```bash
   make check
   ```

4. **Submit the Pull Request:**
   - Push your branch to your fork on GitHub.
   - Open a pull request against the `main` branch of `VinitSurve/envdoctor`.
   - Fill out the PR template completely (summary, motivation, changes, test evidence, checklist).
   - Link any related issues (e.g., `Fixes #42`).

5. **Review Process:**
   - Automated CI workflows will run against your pull request (testing Python 3.11, 3.12, 3.13, 3.14 on macOS and Linux, plus CodeQL and security audits).
   - Address any feedback from review or CI failures promptly.
