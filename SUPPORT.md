# Getting Support for EnvDoctor

Thank you for using `envdoctor`! This document outlines the best ways to get help, ask questions, report bugs, and connect with the project maintainer.

---

## 1. Documentation & Self-Help

Before submitting an issue or asking for support, check our documentation:

- [README](README.md): High-level overview, quick start, command reference, and safety guarantees.
- [Documentation Index](docs/):
  - [Installation Guide](docs/installation.md)
  - [Usage Guide](docs/usage.md)
  - [Configuration Reference](docs/configuration.md)
  - [Troubleshooting & FAQ](docs/troubleshooting.md)
  - [Development Guide](docs/development.md)
  - [Architecture Overview](docs/architecture.md)

You can also run CLI help commands at any time:
```bash
envdoctor --help
envdoctor <command> --help
```

---

## 2. GitHub Discussions (Questions, Ideas & Community)

For general questions, advice on setup, troubleshooting strange environment states, or sharing feature ideas:

- Visit [GitHub Discussions](https://github.com/VinitSurve/envdoctor/discussions)
- Search existing threads to see if your question has already been answered.
- Open a new discussion under the appropriate category (`Q&A`, `Ideas`, `General`).

---

## 3. GitHub Issues (Bug Reports & Feature Requests)

If you have identified a bug or have a concrete feature proposal:

- Browse open and closed [GitHub Issues](https://github.com/VinitSurve/envdoctor/issues) to ensure it hasn't already been reported.
- Open a new issue using our issue templates:
  - **Bug Report:** When an `envdoctor` check errors unexpectedly, crashes, or gives inaccurate results.
  - **Feature Request:** When proposing support for a new runtime, project framework, check rule, or CLI flag.
  - **Documentation:** When reporting incorrect, outdated, or missing documentation.

Please provide complete environment details:
```bash
envdoctor --version
python3 --version
sw_vers # on macOS
envdoctor info --json
```

---

## 4. Maintainer Profile

`envdoctor` is maintained by **Vinit Surve**.

- Maintainer GitHub Profile: [https://github.com/VinitSurve](https://github.com/VinitSurve)
- For direct project questions or collaboration inquiries, feel free to connect via the GitHub profile or sponsor page.

---

## 5. Security Inquiries

For reporting security vulnerabilities, please do **not** use public issues or discussions. Refer to [SECURITY.md](SECURITY.md) and use private [GitHub Security Advisories](https://github.com/VinitSurve/envdoctor/security/advisories/new).
