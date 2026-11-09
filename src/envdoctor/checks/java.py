"""Java (Maven and Gradle) project checks."""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from pathlib import Path

from envdoctor.models import CheckResult, CheckStatus, RuntimeInfo, Severity
from envdoctor.versions import parse_java_version

_GRADLE_JAVA_VER_RE = re.compile(
    r"(?:sourceCompatibility|targetCompatibility|jvmToolchain)\s*[=(]?\s*['\"]?(?:JavaVersion\.VERSION_)?(\d+(?:\.\d+)?)['\"]?"
)


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _check_maven(root: Path, runtimes: Mapping[str, RuntimeInfo]) -> list[CheckResult]:
    results: list[CheckResult] = []
    pom_path = root / "pom.xml"
    if not pom_path.exists():
        results.append(
            CheckResult(
                name="java.pom_xml",
                status=CheckStatus.WARN,
                severity=Severity.MEDIUM,
                explanation="Maven directory '.mvn' found, but 'pom.xml' is missing.",
                suggestion="Restore 'pom.xml' in the project root.",
                evidence={"path": str(pom_path), "exists": False},
            )
        )
        return results

    try:
        raw_xml = pom_path.read_text(encoding="utf-8", errors="replace")
        if "<!DOCTYPE" in raw_xml.upper() or "<!ENTITY" in raw_xml.upper():
            return [
                CheckResult(
                    name="java.pom_xml",
                    status=CheckStatus.ERROR,
                    severity=Severity.HIGH,
                    explanation=(
                        "'pom.xml' contains DOCTYPE/ENTITY declarations "
                        "which are rejected for safety."
                    ),
                    suggestion="Remove DTD/ENTITY declarations from 'pom.xml'.",
                    evidence={"path": str(pom_path)},
                )
            ]
        root_elem = ET.fromstring(raw_xml)  # noqa: S314 - DTD/ENTITY rejected above
    except ET.ParseError as exc:
        return [
            CheckResult(
                name="java.pom_xml",
                status=CheckStatus.ERROR,
                severity=Severity.HIGH,
                explanation=f"'pom.xml' is not valid XML: {exc}",
                suggestion="Fix the XML syntax error in 'pom.xml'.",
                evidence={"path": str(pom_path)},
            )
        ]
    except OSError as exc:
        return [
            CheckResult(
                name="java.pom_xml",
                status=CheckStatus.ERROR,
                severity=Severity.HIGH,
                explanation=f"Cannot read 'pom.xml': {exc}",
                suggestion="Check file permissions on 'pom.xml'.",
                evidence={"path": str(pom_path)},
            )
        ]

    if _strip_ns(root_elem.tag) != "project":
        return [
            CheckResult(
                name="java.pom_xml",
                status=CheckStatus.ERROR,
                severity=Severity.HIGH,
                explanation=(
                    f"'pom.xml' root element must be <project>, found <{_strip_ns(root_elem.tag)}>."
                ),
                suggestion="Ensure 'pom.xml' is a valid Maven POM.",
                evidence={"path": str(pom_path), "root_tag": _strip_ns(root_elem.tag)},
            )
        ]

    results.append(
        CheckResult(
            name="java.pom_xml",
            status=CheckStatus.OK,
            severity=Severity.INFO,
            explanation="'pom.xml' is valid XML.",
            evidence={"path": str(pom_path)},
        )
    )

    props: dict[str, str] = {}
    for child in root_elem:
        if _strip_ns(child.tag) == "properties":
            for prop in child:
                if prop.text and prop.text.strip():
                    props[_strip_ns(prop.tag)] = prop.text.strip()

    req_raw = (
        props.get("maven.compiler.release")
        or props.get("maven.compiler.target")
        or props.get("maven.compiler.source")
        or props.get("java.version")
    )
    results.extend(_compare_java_version(req_raw, "pom.xml", runtimes))
    return results


def _check_gradle(root: Path, runtimes: Mapping[str, RuntimeInfo]) -> list[CheckResult]:
    results: list[CheckResult] = []
    build_files = [
        root / name for name in ("build.gradle", "build.gradle.kts") if (root / name).is_file()
    ]
    if not build_files:
        results.append(
            CheckResult(
                name="java.gradle_build",
                status=CheckStatus.WARN,
                severity=Severity.MEDIUM,
                explanation=(
                    "Gradle markers found, "
                    "but neither 'build.gradle' nor 'build.gradle.kts' exists."
                ),
                suggestion="Add a 'build.gradle' or 'build.gradle.kts' file.",
                evidence={"exists": False},
            )
        )
    else:
        bf = build_files[0]
        try:
            content = bf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = ""
        if not content.strip():
            results.append(
                CheckResult(
                    name="java.gradle_build",
                    status=CheckStatus.WARN,
                    severity=Severity.MEDIUM,
                    explanation=f"'{bf.name}' is empty.",
                    suggestion=f"Configure plugins and dependencies in '{bf.name}'.",
                    evidence={"file": bf.name, "empty": True},
                )
            )
        else:
            results.append(
                CheckResult(
                    name="java.gradle_build",
                    status=CheckStatus.OK,
                    severity=Severity.INFO,
                    explanation=f"Gradle build script '{bf.name}' is present.",
                    evidence={"file": bf.name},
                )
            )
            match = _GRADLE_JAVA_VER_RE.search(content)
            req_raw = match.group(1).replace("_", ".") if match else None
            results.extend(_compare_java_version(req_raw, bf.name, runtimes))

    gradlew = root / "gradlew"
    if gradlew.is_file() and not gradlew.is_symlink():
        if not os.access(gradlew, os.X_OK):
            results.append(
                CheckResult(
                    name="java.gradlew_permissions",
                    status=CheckStatus.WARN,
                    severity=Severity.MEDIUM,
                    explanation="'gradlew' wrapper exists but is not executable.",
                    suggestion="Run 'chmod +x gradlew'.",
                    evidence={"gradlew": str(gradlew), "executable": False},
                )
            )
        else:
            results.append(
                CheckResult(
                    name="java.gradlew_permissions",
                    status=CheckStatus.OK,
                    severity=Severity.INFO,
                    explanation="'gradlew' wrapper is present and executable.",
                    evidence={"gradlew": str(gradlew), "executable": True},
                )
            )

    return results


def _compare_java_version(
    req_raw: str | None,
    source: str,
    runtimes: Mapping[str, RuntimeInfo],
) -> list[CheckResult]:
    java_rt = runtimes.get("java")
    if not java_rt or not java_rt.found or not java_rt.healthy or not java_rt.version:
        return [
            CheckResult(
                name="java.version",
                status=CheckStatus.ERROR,
                severity=Severity.HIGH,
                explanation=(
                    java_rt.issue
                    if (java_rt and java_rt.issue)
                    else "No healthy Java Runtime (JDK) is installed on PATH."
                ),
                suggestion=(
                    java_rt.suggestion
                    if (java_rt and java_rt.suggestion)
                    else "Install a JDK (e.g. 'brew install openjdk') and set JAVA_HOME."
                ),
                evidence={"installed": None, "required": req_raw, "source": source},
            )
        ]

    if not req_raw:
        return [
            CheckResult(
                name="java.version",
                status=CheckStatus.OK,
                severity=Severity.INFO,
                explanation=f"Java {java_rt.version} is available.",
                evidence={"installed": java_rt.version, "required": None, "source": source},
            )
        ]

    req_major = parse_java_version(req_raw)
    inst_major = parse_java_version(java_rt.version)
    if req_major is None or inst_major is None:
        return [
            CheckResult(
                name="java.version",
                status=CheckStatus.SKIP,
                severity=Severity.INFO,
                explanation=(
                    f"Could not compare Java version constraint '{req_raw}' from {source} "
                    f"against '{java_rt.version}'."
                ),
                evidence={"installed": java_rt.version, "required": req_raw, "source": source},
            )
        ]

    if inst_major < req_major:
        return [
            CheckResult(
                name="java.version",
                status=CheckStatus.ERROR,
                severity=Severity.HIGH,
                explanation=(
                    f"Java version mismatch: {source} targets Java {req_major} ('{req_raw}'), "
                    f"but installed Java is {java_rt.version} (Java {inst_major})."
                ),
                suggestion=f"Install or switch to JDK {req_major}+.",
                evidence={
                    "installed": java_rt.version,
                    "installed_major": inst_major,
                    "required": req_raw,
                    "required_major": req_major,
                    "source": source,
                },
            )
        ]

    return [
        CheckResult(
            name="java.version",
            status=CheckStatus.OK,
            severity=Severity.INFO,
            explanation=(
                f"Installed Java {java_rt.version} (Java {inst_major}) "
                f"satisfies {source} target Java {req_major}."
            ),
            evidence={
                "installed": java_rt.version,
                "installed_major": inst_major,
                "required": req_raw,
                "required_major": req_major,
                "source": source,
            },
        )
    ]


def run_java_checks(
    root: Path,
    project_types: Sequence[str],
    runtimes: Mapping[str, RuntimeInfo],
) -> list[CheckResult]:
    """Run all applicable Java Maven and Gradle checks."""
    results: list[CheckResult] = []
    if "maven" in project_types:
        results.extend(_check_maven(root, runtimes))
    if "gradle" in project_types:
        results.extend(_check_gradle(root, runtimes))
    return results
