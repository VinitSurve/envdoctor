"""Domain models for envdoctor diagnostics, runtimes, environment checks and reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from envdoctor.common.exceptions import ExitCode
from envdoctor.common.safety import redact_mapping, redact_text


class CheckStatus(StrEnum):
    """Outcome status for an individual diagnostic check."""

    OK = "ok"
    WARN = "warn"
    ERROR = "error"
    SKIP = "skip"


class Severity(StrEnum):
    """Impact severity of a diagnostic check."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class CheckResult:
    """Result of a single isolated diagnostic check."""

    name: str
    status: CheckStatus
    severity: Severity
    explanation: str
    suggestion: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.explanation = redact_text(self.explanation)
        self.suggestion = redact_text(self.suggestion)
        self.evidence = redact_mapping(self.evidence)


@dataclass
class PathSummary:
    """Summary of the process PATH environment variable."""

    total_entries: int
    unique_entries: int
    duplicates: list[str]
    missing_dirs: list[str]
    entries: list[str]


@dataclass
class DiskInfo:
    """Disk usage statistics for the active filesystem."""

    path: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent_used: float


@dataclass
class SystemInfo:
    """System, OS, hardware, Python, shell, Homebrew and PATH overview."""

    os_name: str
    os_version: str
    os_build: str
    kernel_version: str
    architecture: str
    hardware_arch: str
    rosetta_translated: bool
    python_version: str
    python_executable: str
    python_arch: str
    shell: str
    homebrew_available: bool
    homebrew_path: str | None
    homebrew_prefix: str | None
    cpu_brand: str
    cpu_cores_logical: int
    cpu_cores_physical: int | None
    memory_total_bytes: int | None
    disk: DiskInfo
    path_summary: PathSummary
    warnings: list[str] = field(default_factory=list)


@dataclass
class RuntimeInfo:
    """Detected status and health of a developer runtime or tool."""

    name: str
    binary: str
    found: bool
    healthy: bool
    status: str  # "ok", "warn", "error", "missing"
    version: str | None = None
    path: str | None = None
    duplicates: list[str] = field(default_factory=list)
    daemon_running: bool | None = None
    issue: str | None = None
    suggestion: str | None = None


@dataclass
class EnvVarEntry:
    """Status of a single required environment variable (values are never stored)."""

    name: str
    required_by: list[str]
    in_dotenv: bool
    dotenv_empty: bool
    in_environ: bool
    environ_empty: bool
    status: str  # "present", "empty", "missing"


@dataclass
class EnvReport:
    """Comparison of required environment variable names against .env and os.environ."""

    path: str
    sources: list[str]
    dotenv_files: list[str]
    variables: list[EnvVarEntry]
    missing_keys: list[str]
    empty_keys: list[str]
    present_keys: list[str]
    extra_dotenv_keys: list[str]
    healthy: bool


@dataclass
class DepFixAction:
    """A conservative, non-destructive dependency installation command."""

    ecosystem: str
    description: str
    command: list[str]
    cwd: str
    safe: bool = True
    reason: str = ""


@dataclass
class DepFixOutcome:
    """Outcome of running or previewing a DepFixAction."""

    action: DepFixAction
    executed: bool
    dry_run: bool
    ok: bool
    returncode: int | None = None
    output_tail: str = ""
    error: str | None = None


@dataclass
class DepsReport:
    """Result of 'envdoctor deps' diagnosis and optional conservative fix."""

    path: str
    project_types: list[str]
    checks: list[CheckResult]
    actions: list[DepFixAction]
    outcomes: list[DepFixOutcome]
    status: str


@dataclass
class ProjectCheckReport:
    """Result of 'envdoctor check' on a project directory."""

    path: str
    project_types: list[str]
    project_type_labels: list[str]
    checks: list[CheckResult]
    summary: dict[str, int]
    status: str


@dataclass
class FullReport:
    """Complete structured report produced by 'envdoctor report'."""

    path: str
    status: str
    system: SystemInfo
    runtimes: list[RuntimeInfo]
    project_types: list[str]
    project_type_labels: list[str]
    checks: list[CheckResult]
    summary: dict[str, int]


def summarize_checks(checks: list[CheckResult]) -> tuple[dict[str, int], str]:
    """Compute counts per status and overall status ('ok', 'warn', 'error')."""
    counts = {
        CheckStatus.OK.value: 0,
        CheckStatus.WARN.value: 0,
        CheckStatus.ERROR.value: 0,
        CheckStatus.SKIP.value: 0,
    }
    for item in checks:
        counts[item.status.value] = counts.get(item.status.value, 0) + 1
    if counts[CheckStatus.ERROR.value] > 0:
        overall = CheckStatus.ERROR.value
    elif counts[CheckStatus.WARN.value] > 0:
        overall = CheckStatus.WARN.value
    else:
        overall = CheckStatus.OK.value
    return counts, overall


def exit_code_for_status(status: str) -> ExitCode:
    """Map an overall status string ('ok', 'warn', 'error') to ExitCode."""
    if status == CheckStatus.ERROR.value:
        return ExitCode.ERROR
    if status == CheckStatus.WARN.value:
        return ExitCode.WARNING
    return ExitCode.OK
