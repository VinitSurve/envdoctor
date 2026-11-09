"""Conservative version parsing and semver / PEP 440 range matching.

If a version string or constraint cannot be parsed reliably, matchers return ``None``
so callers can mark the check as ``skip`` with an explanation rather than raising a
false error.
"""

from __future__ import annotations

import re

_VERSION_TUPLE_RE = re.compile(
    r"^\s*[vV=]?\s*(\d+)(?:\.(\d+|\*|x|X))?(?:\.(\d+|\*|x|X))?(?:[-+][A-Za-z0-9._\-]+)?\s*$"
)
_FIRST_VERSION_RE = re.compile(r"(?<![\d.])(\d+\.\d+(?:\.\d+)?)(?![\d.])")
_OP_SPEC_RE = re.compile(
    r"^\s*(>=|<=|!=|==|~=|~|\^|>|<|=)?\s*[vV]?\s*(\d+|\*|x|X)"
    r"(?:\.(\d+|\*|x|X))?(?:\.(\d+|\*|x|X))?(?:[-+][A-Za-z0-9._\-]+)?\s*$"
)
_HYPHEN_RE = re.compile(r"^\s*[vV]?(\d+(?:\.\d+){0,2})\s+-\s+[vV]?(\d+(?:\.\d+){0,2})\s*$")


def parse_version(raw: str) -> tuple[int, int, int] | None:
    """Parse a version like ``20.11.1``, ``v18.2``, ``3.11.9`` into ``(major, minor, patch)``."""
    text = raw.strip()
    if not text:
        return None
    match = _VERSION_TUPLE_RE.match(text)
    if match:
        g1, g2, g3 = match.group(1), match.group(2), match.group(3)
        if g2 in ("*", "x", "X") or g3 in ("*", "x", "X"):
            return None
        return (int(g1), int(g2) if g2 is not None else 0, int(g3) if g3 is not None else 0)
    found = _FIRST_VERSION_RE.search(text)
    if found:
        parts = [int(p) for p in found.group(1).split(".")]
        while len(parts) < 3:
            parts.append(0)
        return (parts[0], parts[1], parts[2])
    return None


def parse_java_version(raw: str) -> int | None:
    """Extract major Java feature version (e.g. ``1.8.0_392`` -> ``8``, ``21.0.2`` -> ``21``)."""
    text = raw.strip().strip('"').strip("'")
    if not text:
        return None
    if text.startswith("1."):
        rest = text[2:].split(".")[0].split("_")[0]
        if rest.isdigit():
            return int(rest)
    match = re.search(r"(?<![\d.])(\d+)(?:\.(\d+))?", text)
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2)) if match.group(2) is not None else 0
    if major == 1 and minor > 0:
        return minor
    return major


def _match_single_token(ver: tuple[int, int, int], token: str) -> bool | None:
    tok = token.strip()
    if not tok or tok in ("*", "x", "X", "latest"):
        return True
    match = _OP_SPEC_RE.match(tok)
    if not match:
        return None
    op = match.group(1) or ""
    g1, g2, g3 = match.group(2), match.group(3), match.group(4)
    if g1 in ("*", "x", "X"):
        return True
    major = int(g1)
    minor_wild = g2 is None or g2 in ("*", "x", "X")
    patch_wild = g3 is None or g3 in ("*", "x", "X")
    minor = 0 if minor_wild or g2 is None else int(g2)
    patch = 0 if patch_wild or g3 is None else int(g3)
    target = (major, minor, patch)

    if op in ("", "=", "=="):
        if minor_wild:
            return ver[0] == major
        if patch_wild:
            return ver[0] == major and ver[1] == minor
        return ver == target
    if op == "!=":
        if minor_wild:
            return ver[0] != major
        if patch_wild:
            return not (ver[0] == major and ver[1] == minor)
        return ver != target
    if op == ">=":
        return ver >= target
    if op == ">":
        if minor_wild:
            return ver >= (major + 1, 0, 0)
        if patch_wild:
            return ver >= (major, minor + 1, 0)
        return ver > target
    if op == "<=":
        if minor_wild:
            return ver < (major + 1, 0, 0)
        if patch_wild:
            return ver < (major, minor + 1, 0)
        return ver <= target
    if op == "<":
        return ver < target
    if op == "^":
        if ver < target:
            return False
        if major > 0:
            return ver < (major + 1, 0, 0)
        if minor > 0 or minor_wild:
            return ver < (0, minor + 1, 0) if not minor_wild else ver[0] == 0
        return ver == target
    if op in ("~", "~="):
        if ver < target:
            return False
        if op == "~" and minor_wild:
            return ver < (major + 1, 0, 0)
        if op == "~=" and g3 is None:
            return ver < (major + 1, 0, 0)
        return ver < (major, minor + 1, 0)
    return None


def _normalize_conjunction(branch: str) -> list[str] | None:
    """Split an AND branch like ``>=18.0.0 <20.0.0`` or ``>=18, <20`` into atomic comparators."""
    text = branch.strip()
    if not text:
        return []
    hyphen = _HYPHEN_RE.match(text)
    if hyphen:
        low, high = hyphen.group(1), hyphen.group(2)
        return [f">={low}", f"<={high}"]
    # Collapse spaces between operator and version: ">= 18.0" -> ">=18.0"
    collapsed = re.sub(r"(>=|<=|!=|==|~=|~|\^|>|<|=)\s+", r"\1", text)
    parts = [p.strip() for p in re.split(r"[\s,]+", collapsed) if p.strip()]
    return parts


def match_semver_range(version: str, spec: str) -> bool | None:
    """Check whether ``version`` satisfies an npm/Cargo/Composer-style semver range.

    Supports ``>=18``, ``^18.17 || >=20``, ``18.x``, ``~20.1``, ``18 - 20``, ``*``.
    Returns ``None`` if either input cannot be parsed conservatively.
    """
    ver = parse_version(version)
    if ver is None:
        return None
    raw_spec = spec.strip()
    if not raw_spec:
        return None
    branches = [b.strip() for b in raw_spec.split("||")]
    any_unparseable = False
    for branch in branches:
        if not branch:
            any_unparseable = True
            continue
        tokens = _normalize_conjunction(branch)
        if tokens is None or not tokens:
            any_unparseable = True
            continue
        branch_ok = True
        branch_bad = False
        for tok in tokens:
            res = _match_single_token(ver, tok)
            if res is None:
                branch_bad = True
                break
            if not res:
                branch_ok = False
        if branch_bad:
            any_unparseable = True
            continue
        if branch_ok:
            return True
    if any_unparseable:
        return None
    return False


def match_pep440(version: str, spec: str) -> bool | None:
    """Check whether ``version`` satisfies a PEP 440 ``requires-python`` specifier.

    Supports comma-separated clauses like ``>=3.11,<4``, ``~=3.11``, ``==3.11.*``, ``!=3.10.*``.
    Returns ``None`` if unparseable.
    """
    ver = parse_version(version)
    if ver is None:
        return None
    raw_spec = spec.strip()
    if not raw_spec:
        return None
    clauses = [c.strip() for c in raw_spec.split(",") if c.strip()]
    if not clauses:
        return None
    for clause in clauses:
        res = _match_single_token(ver, clause)
        if res is None:
            return None
        if not res:
            return False
    return True
