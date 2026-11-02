"""
tiny-skill-md — zero-dependency SKILL.md parser, validator, and renderer.

Parses and validates SKILL.md files (Anthropic/Claude-style agent skill
descriptions with YAML frontmatter) without PyYAML. Renders them back to
markdown. Computes a heuristic quality score. Designed for tooling that
needs to index, lint, and ship skill catalogs without taking on a YAML
dependency.

Frontmatter schema (proposed)
-----------------------------
    ---
    name: my-skill                # required, kebab-case, <= 64 chars
    description: |                # required, <= 1024 chars (recommended <= 500)
      One paragraph. Leading phrase
      before the first period lists
      triggers; remainder explains
      what the skill produces.
    version: 0.1.0                # optional, semver
    author: name <email>          # optional
    license: MIT                  # optional
    triggers:                     # optional list (alternative to description triggers)
      - deploy
      - release
    tags:                         # optional list
      - devops
      - agent
    ---

The body is markdown. `## Steps` (numbered or ordered) is recommended.
The validator reports missing frontmatter, oversized description, malformed
version, and other rule violations.

Usage
-----
    from tiny_skill_md import parse, validate, render, score

    doc = parse(open("SKILL.md").read())
    issues = validate(doc)
    md = render(doc)
    s = score(doc)

License: MIT
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Constants & regexes
# ---------------------------------------------------------------------------

__version__ = "0.1.0"

MAX_NAME_LEN = 64
MAX_DESC_LEN = 1024        # hard cap
RECOMMENDED_DESC_LEN = 500  # soft cap; score deducts over this
MAX_BODY_BYTES = 256_000
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?$")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Issue:
    """A single validation finding."""
    severity: str   # "error" | "warn" | "info"
    code: str       # short stable code, e.g. "missing_name"
    message: str
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"severity": self.severity, "code": self.code,
                "message": self.message, "line": self.line}


@dataclass
class SkillDoc:
    """A parsed SKILL.md."""
    path: str | None = None
    raw: str = ""
    frontmatter: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    issues: list[Issue] = field(default_factory=list)

    @property
    def name(self) -> str:
        return str(self.frontmatter.get("name", ""))

    @property
    def description(self) -> str:
        return str(self.frontmatter.get("description", ""))

    @property
    def version(self) -> str:
        return str(self.frontmatter.get("version", ""))

    @property
    def triggers(self) -> tuple[str, ...]:
        t = self.frontmatter.get("triggers", [])
        if isinstance(t, list):
            return tuple(str(x) for x in t)
        return ()

    @property
    def tags(self) -> tuple[str, ...]:
        t = self.frontmatter.get("tags", [])
        if isinstance(t, list):
            return tuple(str(x) for x in t)
        return ()


# ---------------------------------------------------------------------------
# Tiny YAML frontmatter parser
# ---------------------------------------------------------------------------
#
# We do NOT need full YAML. SKILL.md frontmatter uses a strict subset:
#   - top-level keys are flat (no nesting)
#   - values are scalars, lists, or block-scalars (|)
#   - lists are written as "- value", one per line, single-level
#   - strings may be quoted (single or double)
#
# This is enough for SKILL.md while keeping zero deps.

def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], list[Issue]]:
    issues: list[Issue] = []
    fm: dict[str, Any] = {}

    lines = text.split("\n")
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        # "key:" must start the line
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_\-]*)\s*:\s*(.*)$", line)
        if not m:
            issues.append(Issue("error", "bad_yaml", f"cannot parse line: {line!r}", line=i + 1))
            i += 1
            continue
        key = m.group(1)
        rest = m.group(2).strip()

        # Block scalar: "|" or ">"
        if rest in ("|", ">"):
            block_lines: list[str] = []
            i += 1
            while i < n:
                bl = lines[i]
                if re.match(r"^\s+", bl) and bl.strip():
                    block_lines.append(bl.strip())
                    i += 1
                elif not bl.strip():
                    block_lines.append("")
                    i += 1
                else:
                    break
            # Strip leading/trailing empties
            while block_lines and not block_lines[0]:
                block_lines.pop(0)
            while block_lines and not block_lines[-1]:
                block_lines.pop()
            value = "\n".join(block_lines)
            if rest == ">":  # folded
                value = re.sub(r"\n+", " ", value)
            fm[key] = value
            continue

        # Empty value -> look for list on following lines
        if rest == "":
            items: list[str] = []
            i += 1
            while i < n:
                bl = lines[i]
                m2 = re.match(r"^\s+-\s+(.*)$", bl)
                if m2:
                    items.append(_strip_quotes(m2.group(1)))
                    i += 1
                elif not bl.strip():
                    i += 1
                else:
                    break
            fm[key] = items
            continue

        # Inline list: [a, b, c]
        if rest.startswith("[") and rest.endswith("]"):
            inner = rest[1:-1].strip()
            if not inner:
                fm[key] = []
            else:
                fm[key] = [_strip_quotes(p) for p in re.split(r",\s*", inner) if p.strip()]
            i += 1
            continue

        # Scalar
        fm[key] = _strip_quotes(rest)
        i += 1

    return fm, issues


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse(text: str, path: str | None = None) -> SkillDoc:
    """Parse a SKILL.md string into a SkillDoc.

    Always returns a doc; on bad frontmatter the doc has issues[] populated.
    """
    doc = SkillDoc(path=path, raw=text)

    if len(text.encode("utf-8")) > MAX_BODY_BYTES:
        doc.issues.append(Issue("error", "too_large",
                                f"file exceeds {MAX_BODY_BYTES} bytes"))
        return doc

    m = FRONTMATTER_RE.match(text)
    if not m:
        # No frontmatter is OK if there's a body, but flagged as warn.
        doc.issues.append(Issue("warn", "no_frontmatter",
                                "missing YAML frontmatter; recommended for agent skills"))
        doc.body = text.strip()
        return doc

    fm_text, body = m.group(1), m.group(2)
    fm, fm_issues = _parse_frontmatter(fm_text)
    doc.frontmatter = fm
    doc.body = body.strip()
    doc.issues.extend(fm_issues)
    return doc


def parse_file(path: str) -> SkillDoc:
    with open(path, "r", encoding="utf-8") as f:
        return parse(f.read(), path=path)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate(doc: SkillDoc, *, max_desc_len: int = MAX_DESC_LEN) -> list[Issue]:
    """Append validation issues to doc.issues; also returns the list."""
    fm = doc.frontmatter

    # name
    name = fm.get("name")
    if not name:
        doc.issues.append(Issue("error", "missing_name", "frontmatter is missing 'name'"))
    elif not isinstance(name, str):
        doc.issues.append(Issue("error", "bad_name_type", "'name' must be a string"))
    elif not NAME_RE.match(name):
        doc.issues.append(Issue(
            "error", "bad_name_format",
            f"'name' must match {NAME_RE.pattern} (kebab-case, <= 64 chars)",
        ))

    # description
    desc = fm.get("description")
    if not desc:
        doc.issues.append(Issue("error", "missing_description",
                                "frontmatter is missing 'description'"))
    elif not isinstance(desc, str):
        doc.issues.append(Issue("error", "bad_description_type",
                                "'description' must be a string"))
    else:
        if len(desc) > max_desc_len:
            doc.issues.append(Issue("error", "description_too_long",
                                    f"'description' is {len(desc)} chars; max {max_desc_len}"))
        elif len(desc) > RECOMMENDED_DESC_LEN:
            doc.issues.append(Issue(
                "warn", "description_long",
                f"'description' is {len(desc)} chars; recommend <= {RECOMMENDED_DESC_LEN}",
            ))
        # Trigger heuristic: first clause should be < 60 chars and end with ":" or "."
        first_period = desc.find(".")
        head = desc if first_period == -1 else desc[:first_period]
        if head and len(head) > 60:
            doc.issues.append(Issue(
                "info", "description_head_long",
                "consider a leading trigger phrase (<=60 chars) before the first period",
            ))

    # version
    version = fm.get("version")
    if version is not None:
        if not isinstance(version, str) or not SEMVER_RE.match(str(version)):
            doc.issues.append(Issue("warn", "bad_version",
                                    f"'version' {version!r} is not valid semver"))

    # triggers
    if "triggers" in fm and not isinstance(fm["triggers"], list):
        doc.issues.append(Issue("error", "bad_triggers_type",
                                "'triggers' must be a list of strings"))
    elif fm.get("triggers") and not all(isinstance(t, str) for t in fm["triggers"]):
        doc.issues.append(Issue("error", "bad_trigger_item",
                                "each trigger must be a string"))

    # tags
    if "tags" in fm and not isinstance(fm["tags"], list):
        doc.issues.append(Issue("error", "bad_tags_type",
                                "'tags' must be a list of strings"))

    # body sections — recommend a "## Steps" or numbered list
    body = doc.body
    if not body:
        doc.issues.append(Issue("warn", "empty_body", "body is empty"))
    else:
        has_steps = bool(re.search(r"^##\s*Steps\b", body, re.MULTILINE | re.IGNORECASE)) \
            or bool(re.search(r"^\s*\d+\.\s", body, re.MULTILINE))
        if not has_steps:
            doc.issues.append(Issue(
                "info", "no_steps_section",
                "consider adding a '## Steps' section with ordered actions",
            ))
        # Recommend verification step
        has_verify = bool(re.search(r"\b(verify|test|check|validate|assert)\b", body, re.IGNORECASE))
        if not has_verify:
            doc.issues.append(Issue(
                "info", "no_verify_step",
                "consider including a verification or test step",
            ))

    return doc.issues


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _escape_yaml_string(s: str) -> str:
    if any(c in s for c in (":", "#", "\n", '"', "'")) or s.strip() != s:
        return json.dumps(s)
    return s


def render_frontmatter(fm: dict[str, Any]) -> str:
    """Render a dict back to YAML frontmatter (the strict subset)."""
    out: list[str] = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            if all(isinstance(x, str) and "\n" not in x for x in v) and len(v) <= 5:
                # Use inline form for short flat lists
                out.append(f"{k}: [{', '.join(_escape_yaml_string(x) for x in v)}]")
            else:
                out.append(f"{k}:")
                for x in v:
                    out.append(f"  - {_escape_yaml_string(str(x))}")
        elif isinstance(v, str) and "\n" in v:
            out.append(f"{k}: |")
            for line in v.split("\n"):
                out.append(f"  {line}" if line else "  ")
        else:
            out.append(f"{k}: {_escape_yaml_string(str(v))}")
    out.append("---")
    return "\n".join(out)


def render(doc: SkillDoc) -> str:
    """Render a parsed SkillDoc back to a full SKILL.md string."""
    fm_text = render_frontmatter(doc.frontmatter) if doc.frontmatter else "---"
    body = doc.body
    if not body.endswith("\n"):
        body += "\n"
    if fm_text != "---":
        return f"{fm_text}\n\n{body}"
    return body


# ---------------------------------------------------------------------------
# Quality score (heuristic)
# ---------------------------------------------------------------------------

def score(doc: SkillDoc) -> dict[str, Any]:
    """Heuristic 0..100 quality score.

    Components:
      - description (0..30): present + <= RECOMMENDED_DESC_LEN
      - triggers    (0..15): present + at least 3
      - tags        (0..10): present + at least 2
      - version     (0..10): valid semver
      - body        (0..25): present + has steps + has verify
      - license/author (0..10): both present

    Returns dict with score, components, grade (A/B/C/D/F).
    """
    breakdown: dict[str, int] = {}
    fm = doc.frontmatter

    # description
    desc = fm.get("description", "")
    if desc and len(desc) <= RECOMMENDED_DESC_LEN:
        breakdown["description"] = 30
    elif desc:
        breakdown["description"] = max(15, 30 - (len(desc) - RECOMMENDED_DESC_LEN) // 20)
    else:
        breakdown["description"] = 0

    # triggers
    trig = fm.get("triggers", [])
    if isinstance(trig, list):
        breakdown["triggers"] = min(15, 5 * len([t for t in trig if t]))
    else:
        breakdown["triggers"] = 0

    # tags
    tags = fm.get("tags", [])
    if isinstance(tags, list):
        breakdown["tags"] = min(10, 5 * len([t for t in tags if t]))
    else:
        breakdown["tags"] = 0

    # version
    breakdown["version"] = 10 if (isinstance(fm.get("version"), str) and SEMVER_RE.match(fm["version"])) else 0

    # body
    body = doc.body or ""
    if not body:
        breakdown["body"] = 0
    else:
        b = 10
        if re.search(r"^##\s*Steps\b", body, re.MULTILINE | re.IGNORECASE):
            b += 10
        elif re.search(r"^\s*\d+\.\s", body, re.MULTILINE):
            b += 5
        if re.search(r"\b(verify|test|check|validate|assert)\b", body, re.IGNORECASE):
            b += 5
        breakdown["body"] = min(25, b)

    # license + author
    breakdown["meta"] = 0
    if fm.get("license"):
        breakdown["meta"] += 5
    if fm.get("author"):
        breakdown["meta"] += 5

    total = sum(breakdown.values())
    if total >= 90:
        grade = "A"
    elif total >= 75:
        grade = "B"
    elif total >= 60:
        grade = "C"
    elif total >= 40:
        grade = "D"
    else:
        grade = "F"

    return {"score": total, "grade": grade, "components": breakdown}


# ---------------------------------------------------------------------------
# Catalog utilities
# ---------------------------------------------------------------------------

def discover(paths: list[str]) -> list[SkillDoc]:
    """Walk a list of file/dir paths, parsing every SKILL.md found.

    Directories are searched one level deep for files named SKILL.md.
    """
    import os
    out: list[SkillDoc] = []
    for p in paths:
        if os.path.isfile(p):
            if os.path.basename(p).upper() == "SKILL.MD":
                out.append(parse_file(p))
            continue
        if os.path.isdir(p):
            for entry in os.listdir(p):
                full = os.path.join(p, entry, "SKILL.md")
                if os.path.isfile(full):
                    out.append(parse_file(full))
    return out


def to_dict(doc: SkillDoc) -> dict[str, Any]:
    return {
        "path": doc.path,
        "name": doc.name,
        "description": doc.description,
        "version": doc.version,
        "triggers": list(doc.triggers),
        "tags": list(doc.tags),
        "frontmatter": doc.frontmatter,
        "body_bytes": len(doc.body.encode("utf-8")),
        "issues": [i.to_dict() for i in doc.issues],
    }


# ---------------------------------------------------------------------------
# CLI / demo
# ---------------------------------------------------------------------------

def _demo() -> None:
    sample = """---
name: deploy-service
description: |
  Deploy a service. Use when the user asks to ship, deploy, release, or roll
  out a service to staging or production. Verifies health checks before
  completion.
version: 0.2.1
author: ops@example.com
license: MIT
triggers:
  - deploy
  - ship
  - release
tags:
  - devops
  - ci
---

# Deploy Service

## Steps

1. Run the build.
2. Push to the registry.
3. Roll out to staging.
4. Verify health checks.
"""
    doc = parse(sample)
    issues = validate(doc)
    print(f"Name: {doc.name}")
    print(f"Description length: {len(doc.description)}")
    print(f"Issues: {len(issues)}")
    for i in issues:
        print(f"  - [{i.severity}] {i.code}: {i.message}")
    print(f"Score: {score(doc)}")
    print()
    print("Rendered:")
    print(render(doc))


if __name__ == "__main__":  # pragma: no cover
    _demo()
