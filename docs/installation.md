# Installation Guide

`envdoctor` is a cross-stack development environment diagnostics utility for macOS (Apple Silicon M-series & Intel) and POSIX workstations.

---

## System Requirements

- **Operating System:** macOS 12+ (Monterey, Ventura, Sonoma, Sequoia) or modern POSIX/Linux distributions (Ubuntu, Debian, Fedora, Arch, Alpine).
- **Python:** Python 3.11, 3.12, 3.13, or 3.14.
- **Hardware Architecture:** Apple Silicon (`arm64`), Intel (`x86_64`), or Linux (`aarch64` / `x86_64`).

---

## Installation Methods

### Method 1: Using `pipx` (Recommended for standalone CLI use)

[`pipx`](https://pypa.github.io/pipx/) installs the CLI in an isolated virtual environment and exposes the executable globally on your `$PATH`.

#### Install directly from GitHub:
```bash
pipx install git+https://github.com/VinitSurve/envdoctor.git
```

#### Install from a local clone:
```bash
git clone https://github.com/VinitSurve/envdoctor.git
cd envdoctor
pipx install .
```

#### Upgrading via `pipx`:
```bash
pipx upgrade envdoctor
```

---

### Method 2: Using `pip` (Inside a Virtual Environment)

To install into an active virtual environment:

```bash
# Create and activate a virtual environment
python3 -m venv ~/.venvs/envdoctor
source ~/.venvs/envdoctor/bin/activate

# Install the package
pip install .
```

Or install from git:
```bash
pip install git+https://github.com/VinitSurve/envdoctor.git
```

---

### Method 3: Development Setup (From Source)

For contributors and local development:

```bash
# Clone the repository
git clone https://github.com/VinitSurve/envdoctor.git
cd envdoctor

# Bootstrap virtualenv and install in editable mode with development tools
make dev

# Activate the virtual environment
source .venv/bin/activate
```

---

## Verifying the Installation

Verify that the CLI is accessible and report the installed version:

```bash
envdoctor --version
```

Expected output:
```text
envdoctor 1.0.0
```

Inspect basic command line options:
```bash
envdoctor --help
```

Run a fast sanity check on your system environment:
```bash
envdoctor info
```

---

## Shell Completion (Optional)

`envdoctor` is built with Typer and supports shell completion for bash, zsh, and fish:

```bash
# Install shell completion for your current shell
envdoctor --install-completion

# Show completion script without installing
envdoctor --show-completion
```

---

## Uninstallation

### Via pipx:
```bash
pipx uninstall envdoctor
```

### Via pip:
```bash
pip uninstall envdoctor
```
