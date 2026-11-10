# Security Policy

The `envdoctor` project takes the security of developer environments, local workstations, and system diagnostics seriously.

## Supported Versions

Security updates and critical fixes are applied to the latest released minor version.

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues, pull requests, or discussions.**

To report a potential security issue responsibly:

1. Use GitHub's private vulnerability reporting feature via [GitHub Security Advisories](https://github.com/VinitSurve/envdoctor/security/advisories/new).
2. If private reporting is unavailable, browse to the [Security Advisories tab](https://github.com/VinitSurve/envdoctor/security/advisories) of the repository to submit a confidential report.

### Information to Include in Your Report

To help us triage and resolve the issue quickly, please provide:

- A clear description of the vulnerability.
- Steps to reproduce the issue (including any minimal reproduction scripts, environment configs, or payloads).
- The version of `envdoctor` and Python where the issue was observed.
- The operating system and architecture (e.g. macOS 14 Sonoma on Apple Silicon M-series or Ubuntu 22.04 x86_64).
- Any potential impact, attack scenarios, or mitigation strategies you have identified.

### Response Timeline

- **Initial Acknowledgment:** We aim to acknowledge receipt of your report within 48 to 72 hours.
- **Triage & Assessment:** We will investigate and confirm the impact within 5 business days.
- **Resolution & Release:** A patch will be prepared and tested. Once ready, a security release will be published alongside a coordinated security advisory crediting the reporter (unless anonymity is requested).

## Security Design Principles in EnvDoctor

`envdoctor` is built with defensive defaults:
- **Zero Secret Exposure:** Environment auditing inspects keys and presence, never displaying, logging, or storing secret values.
- **Safe Subprocess Execution:** System and runtime probes use argument vectors (`shell=False`) with strict timeouts to prevent shell injection.
- **Non-destructive Diagnostics:** Routine commands (`check`, `info`, `runtimes`, `env`) are strictly read-only. Mutating actions require explicit user confirmation.
