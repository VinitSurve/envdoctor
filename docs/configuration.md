# Configuration Reference

`envdoctor` supports persistent configuration to customize check behavior, execution timeouts, team-mandated environment variables, and check exclusions.

---

## Configuration File Locations

`envdoctor` stores user configuration following OS standard application directory specifications (via `platformdirs`):

| Operating System | Configuration & Data Directory | Log File |
|---|---|---|
| **macOS** | `~/Library/Application Support/devtoolkit/envdoctor/config.json` | `~/Library/Logs/devtoolkit/envdoctor/envdoctor.log` |
| **Linux / POSIX** | `~/.config/devtoolkit/envdoctor/config.json` | `~/.local/state/devtoolkit/envdoctor/envdoctor.log` |

### Overriding the Config Directory

You can override the storage root directory by setting the `DEVTOOLKIT_HOME` environment variable:

```bash
export DEVTOOLKIT_HOME="/custom/storage/path"
```

---

## Configuration Schema

The following configuration settings are supported:

| Key | Type | Default | Constraints | Description |
|---|---|---|---|---|
| `required_env` | `list[str]` | `[]` | List of string variable names | Environment variable names that must always be present and non-empty in projects diagnosed by `envdoctor env`. |
| `command_timeout` | `int` | `5` | `1` to `120` seconds | Timeout for runtime version probes and health checks (e.g. `python3 --version`, `docker info`). |
| `fix_timeout` | `int` | `180` | `5` to `1800` seconds | Timeout for dependency installation commands executed via `envdoctor deps --fix`. |
| `check_ports` | `bool` | `true` | `true` or `false` | Whether to scan localhost network ports used by detected project frameworks for conflicts. |
| `ignore_checks` | `list[str]` | `[]` | List of check names | Specific diagnostic check names (e.g. `node.lockfile`, `ports.conflict`, `system.rosetta`) to skip during execution. |

---

## CLI Configuration Management

You can inspect and update your configuration directly via the `envdoctor config` subcommands:

### 1. View Current Configuration
```bash
envdoctor config show
```

Output:
```json
{
  "required_env": [],
  "command_timeout": 5,
  "fix_timeout": 180,
  "check_ports": true,
  "ignore_checks": []
}
```

### 2. View Configuration File Path
```bash
envdoctor config path
```

Output:
```text
/Users/username/Library/Application Support/devtoolkit/envdoctor/config.json
```

### 3. Read a Specific Key
```bash
envdoctor config get command_timeout
```

### 4. Update a Setting
```bash
# Update integer timeout
envdoctor config set command_timeout 10

# Disable port checking
envdoctor config set check_ports false

# Set team-wide required environment variables
envdoctor config set required_env '["DATABASE_URL", "API_SECRET_KEY", "REDIS_HOST"]'

# Ignore specific check rules
envdoctor config set ignore_checks '["ports.conflict", "node.engines"]'
```

### 5. Reset to Factory Defaults
```bash
# Interactive reset prompt
envdoctor config reset

# Non-interactive reset
envdoctor config reset --yes
```

---

## Example `config.json`

```json
{
  "required_env": [
    "DATABASE_URL",
    "APP_ENV",
    "SECRET_KEY_BASE"
  ],
  "command_timeout": 8,
  "fix_timeout": 300,
  "check_ports": true,
  "ignore_checks": [
    "node.engines"
  ]
}
```
