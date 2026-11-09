"""Configuration schema for envdoctor (stored in this tool's own config directory)."""

from __future__ import annotations

from envdoctor.common.config import ConfigSchema, Field

SCHEMA = ConfigSchema(
    {
        "required_env": Field(
            type="list",
            default=[],
            description="Required environment variable names always checked in projects.",
        ),
        "command_timeout": Field(
            type="int",
            default=5,
            minimum=1,
            maximum=120,
            description="Timeout in seconds for runtime version and health checks.",
        ),
        "fix_timeout": Field(
            type="int",
            default=180,
            minimum=5,
            maximum=1800,
            description="Timeout in seconds for dependency install commands in 'deps --fix'.",
        ),
        "check_ports": Field(
            type="bool",
            default=True,
            description="Check configured project ports against active localhost listeners.",
        ),
        "ignore_checks": Field(
            type="list",
            default=[],
            description="Check names (e.g. 'node.lockfile', 'ports.conflict') to skip.",
        ),
    }
)
