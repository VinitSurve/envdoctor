# Troubleshooting & FAQ

This document addresses common warnings, environmental diagnostics, and system edge cases detected by `envdoctor`.

---

## 1. Rosetta 2 Translation Warning

### Symptom
`envdoctor info` reports:
```text
WARNING: Running under Rosetta 2 translation (x86_64 emulation on Apple Silicon)
```

### Cause
Your active shell, terminal emulator, or Python binary is running as an Intel `x86_64` binary on an Apple Silicon (M1/M2/M3/M4) Mac. While Rosetta 2 allows Intel software to run, it incurs a performance overhead and may cause native compiler errors (e.g. building C extensions, Rust crates, or Node native addons).

### Resolution
1. Check your terminal architecture:
   ```bash
   uname -m
   # If output is 'x86_64', your terminal or shell is running under Rosetta
   ```
2. Verify if Terminal is set to "Open using Rosetta":
   - Open Finder -> Applications -> Utilities.
   - Right-click `Terminal.app` (or iTerm2) -> **Get Info**.
   - Ensure **Open using Rosetta** is **unchecked**.
3. Use native ARM64 Homebrew (`/opt/homebrew` instead of `/usr/local`):
   ```bash
   which brew
   # Should be: /opt/homebrew/bin/brew
   ```
4. Install a native ARM64 Python interpreter:
   ```bash
   arch -arm64 brew install python@3.11
   ```

---

## 2. Java Stub Popups on macOS

### Symptom
Running developer tools prompts an Apple dialog box:
> "To use the 'java' command-line tool you need to install a JDK."

### How EnvDoctor Protects You
macOS installs `/usr/bin/java` by default as an Apple shim. Executing `/usr/bin/java` directly without an installed JDK triggers an OS modal dialog. `envdoctor` defensively checks `/usr/libexec/java_home` and validates the real JDK path before attempting invocation, preventing unwanted GUI popups.

### Resolution
If you need Java for your project:
```bash
# Install OpenJDK via Homebrew
brew install openjdk@21

# Symlink system Java wrappers (if required)
sudo ln -sfn /opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk /Library/Java/JavaVirtualMachines/openjdk-21.jdk

# Add to ~/.zshrc or ~/.bashrc
export JAVA_HOME="/opt/homebrew/opt/openjdk@21"
export PATH="$JAVA_HOME/bin:$PATH"
```

---

## 3. Broken Xcode Command Line Tools (CLT)

### Symptom
Compilers fail with `xcrun: error: invalid active developer path (/Library/Developer/CommandLineTools)` or `envdoctor runtimes` flags Xcode CLT issues.

### Cause
Major macOS system updates often delete or invalidate the Command Line Tools developer path.

### Resolution
Reinstall or reset the active developer directory:
```bash
# Trigger reinstallation
xcode-select --install

# Or reset to default path if already installed
sudo xcode-select --reset
```

---

## 4. Docker Daemon Unresponsive

### Symptom
`envdoctor runtimes` displays `docker: found` but status is `warn` or `error` with daemon unresponsive.

### Cause
The Docker CLI binary exists on your `$PATH`, but the Docker Engine background daemon (`dockerd`, Docker Desktop, Colima, or OrbStack) is not running or the socket permissions are restricted.

### Resolution
- **Docker Desktop:** Launch the Docker Desktop application from Applications.
- **Colima:** Start the instance:
  ```bash
  colima start
  ```
- **Socket Check:** Verify socket existence:
  ```bash
  ls -l /var/run/docker.sock ~/.docker/run/docker.sock
  ```

---

## 5. Shadowed `$PATH` Entries and Duplicate Binaries

### Symptom
`envdoctor info` reports duplicate executables on `$PATH`.

### Cause
Multiple package managers or version managers (e.g. Homebrew, pyenv, nvm, conda, system `/usr/bin`) have added competing paths to your environment. The first matching binary in `$PATH` takes precedence, which can cause confusion when tools resolve to an unexpected version.

### Resolution
1. Check executable resolution order:
   ```bash
   which -a python3
   which -a node
   ```
2. Review your shell configuration (`~/.zshrc`, `~/.bashrc`, `~/.zprofile`) and eliminate duplicate `$PATH` exports.
3. Ensure user-managed paths (`/opt/homebrew/bin`, `~/.local/bin`) precede system directories (`/usr/bin`, `/bin`).

---

## 6. Port Conflict Collisions

### Symptom
`envdoctor check` exits with status `error` or `warn` noting port conflicts (e.g. port 3000, 5000, 8000, 8080 already bound).

### Cause
Another local process, previously terminated background worker, or system service is currently listening on localhost on a port required by the diagnosed project.

### Resolution
1. Identify the occupying process:
   ```bash
   # On macOS / Linux:
   lsof -nP -iTCP:<PORT> -sTCP:LISTEN
   ```
2. Terminate the stale process:
   ```bash
   kill -9 <PID>
   ```
3. Alternatively, reconfigure your project's development server to listen on a non-conflicting port (e.g. `PORT=3001 npm run dev`).

---

## 7. Secrets and Security in EnvDoctor

### Question: Is my `.env` file safe when running `envdoctor env` or `envdoctor report`?
**Yes.** `envdoctor` was architected with a strict zero-secret leakage model:
- The parser extracts variable **names** only.
- Values are never saved in data structures, never printed to stdout/stderr, and never included in JSON reports.
- Reports only indicate whether keys are `present`, `empty`, or `missing`.
