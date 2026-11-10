#!/usr/bin/env python3
"""Convert pip-audit JSON report into SARIF v2.1.0 format."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def convert_audit_to_sarif(json_path: Path, sarif_path: Path) -> int:
    with json_path.open(encoding="utf-8") as f:
        data = json.load(f)

    rules_map: dict[str, dict] = {}
    results: list[dict] = []

    dependencies = data.get("dependencies", [])
    vuln_count = 0

    for dep in dependencies:
        dep_name = dep.get("name", "unknown")
        dep_version = dep.get("version", "unknown")
        for vuln in dep.get("vulns", []):
            vuln_count += 1
            vuln_id = vuln.get("id", "UNKNOWN")
            desc = vuln.get("description") or "Known dependency vulnerability."
            aliases = vuln.get("aliases") or []
            alias_str = f" ({', '.join(aliases)})" if aliases else ""
            fix_versions = vuln.get("fix_versions") or []
            fix_str = f" Fixed in: {', '.join(fix_versions)}" if fix_versions else ""

            if vuln_id not in rules_map:
                rules_map[vuln_id] = {
                    "id": vuln_id,
                    "name": f"DependencyVulnerability/{vuln_id}",
                    "shortDescription": {"text": f"Vulnerable dependency: {dep_name}{alias_str}"},
                    "fullDescription": {"text": f"{desc}{fix_str}"},
                    "defaultConfiguration": {"level": "error"},
                    "help": {
                        "text": f"Vulnerability {vuln_id} detected in {dep_name} {dep_version}.{fix_str}"
                    },
                }

            results.append(
                {
                    "ruleId": vuln_id,
                    "level": "error",
                    "message": {
                        "text": f"Package '{dep_name}' version {dep_version} has known vulnerability {vuln_id}.{fix_str}"
                    },
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {"uri": "pyproject.toml"},
                                "region": {"startLine": 1},
                            }
                        }
                    ],
                }
            )

    sarif = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "pip-audit",
                        "informationUri": "https://github.com/pypa/pip-audit",
                        "rules": list(rules_map.values()),
                    }
                },
                "results": results,
            }
        ],
    }

    with sarif_path.open("w", encoding="utf-8") as out:
        json.dump(sarif, out, indent=2)

    print(
        f"Converted {json_path} -> {sarif_path}: {len(results)} vulnerabilities across {len(rules_map)} rules."
    )
    return vuln_count


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: pip_audit_to_sarif.py <input.json> <output.sarif>", file=sys.stderr)
        sys.exit(1)

    json_file = Path(sys.argv[1])
    sarif_file = Path(sys.argv[2])

    if not json_file.exists():
        print(f"Error: input file {json_file} does not exist", file=sys.stderr)
        sys.exit(1)

    convert_audit_to_sarif(json_file, sarif_file)


if __name__ == "__main__":
    main()
