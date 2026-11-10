## Summary

<!-- Provide a brief, high-level summary of what this pull request accomplishes. -->

## Motivation

<!-- Why is this change necessary? What problem does it solve?
     If applicable, link to the related issue (e.g., Fixes #123, Closes #456). -->

Fixes #

## Changes

<!-- List the key changes introduced in this pull request.
     - Added ...
     - Updated ...
     - Fixed ...
-->

- 

## Type of Change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Code refactoring or performance optimization
- [ ] CI / Tooling / Infrastructure improvements

## Tests

<!-- Describe the tests you ran to verify your changes.
     Include details on unit tests, integration tests, manual CLI runs, and platforms tested. -->

- [ ] Added new unit/integration tests in `tests/`
- [ ] Ran full local verification via `make check` (format check, lint, mypy, pytest)
- [ ] Tested CLI commands manually on local machine

## Documentation

<!-- Does this change require updates to documentation? -->

- [ ] Updated `README.md` (if CLI commands, flags, or features changed)
- [ ] Updated relevant documentation in `docs/` (`installation.md`, `usage.md`, `configuration.md`, etc.)
- [ ] No documentation changes required

## Checklist

- [ ] My code adheres to the style guidelines of this project (`make format` and `make lint`).
- [ ] I have performed a self-review of my own code.
- [ ] I have commented my code, particularly in hard-to-understand areas.
- [ ] My code passes static type checking with Mypy in strict mode (`make typecheck`).
- [ ] All 65+ existing tests pass without errors (`make test`).
- [ ] My changes do not expose any environment variables, credentials, or secrets.
- [ ] Subprocess calls use safe argument vectors (`shell=False`) with explicit timeouts.
