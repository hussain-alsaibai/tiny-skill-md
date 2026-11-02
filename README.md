# tiny-skill-md

> **Parse, validate, and score SKILL.md files — without PyYAML.**

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-zero-brightgreen.svg)](tiny_skill_md.py)
[![Part of the tiny-* ecosystem](https://img.shields.io/badge/tiny--*-ecosystem-purple.svg)](#ecosystem)
[![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](tiny_skill_md.py)
[![CI](https://github.com/hussain-alsaibai/tiny-skill-md/actions/workflows/ci.yml/badge.svg)](https://github.com/hussain-alsaibai/tiny-skill-md/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-18%2F18-brightgreen.svg)](tests/test_tiny_skill_md.py)

`tiny-skill-md` is a single-file, zero-dependency library for parsing
**SKILL.md** files (Anthropic/Claude-style agent skill descriptions with
YAML frontmatter), validating them against a proposed schema, rendering
them back to markdown, and computing a heuristic quality score.

Designed for tooling that needs to index, lint, and ship skill catalogs
without taking on a YAML dependency. Usable by any agent framework that
adopts SKILL.md.

## Why this exists

The agent-skill ecosystem has converged on **SKILL.md** — a markdown file
with YAML frontmatter that describes what a skill does, when to use it,
and how to invoke it. But:

- PyYAML is a heavy dependency for what is, in practice, a strict subset
  of YAML (flat keys, scalar/list values, block scalars).
- Existing tools either bundle PyYAML or punt to a generic markdown
  parser, leaving skill authors with no validation feedback.
- Skill catalogs need a **quality score** for ranking — is this skill
  description trustworthy enough to surface in an agent's system prompt?

`tiny-skill-md` answers all three with one file.

## ✨ Features

- **Zero dependencies** — pure stdlib. No PyYAML.
- **Strict-subset YAML** parser — flat keys, scalars, lists, block
  scalars (`|`, `>`), inline lists (`[a, b, c]`).
- **Validation** with stable error codes: `missing_name`,
  `bad_name_format`, `description_too_long`, `bad_version`,
  `no_steps_section`, `no_verify_step`, and more.
- **Quality score** (0..100, A–F grade) — combines description length,
  trigger count, body structure, version validity, and metadata.
- **Round-trip render** — `parse(...)` → `render(...)` preserves the
  schema.
- **Catalog discovery** — `discover(paths)` walks directories and picks
  up every `SKILL.md`.

## 🚀 Quick Start

```python
from tiny_skill_md import parse, validate, render, score, discover

# Parse one file
doc = parse(open("SKILL.md").read())
issues = validate(doc)
quality = score(doc)
print(f"{doc.name}: {quality['grade']} ({quality['score']}/100)")
for issue in issues:
    print(f"  [{issue.severity}] {issue.code}: {issue.message}")

# Round-trip
rebuilt = render(doc)
print(parse(rebuilt).name == doc.name)   # True

# Walk a whole catalog
docs = discover(["./skills/", "./more-skills/"])
for d in docs:
    validate(d)
    print(f"{d.name}: {score(d)['grade']}")
```

## 📐 Frontmatter schema

```yaml
---
name: my-skill                  # required, kebab-case, <= 64 chars
description: |                  # required, <= 1024 (recommended <= 500)
  One paragraph. Leading phrase
  before the first period lists
  triggers; remainder explains
  what the skill produces.
version: 0.1.0                  # optional, must be semver
author: name <email>            # optional
license: MIT                    # optional
triggers:                       # optional list (alternative to description triggers)
  - deploy
  - release
tags:                           # optional list
  - devops
  - agent
---
```

The body is markdown. `## Steps` (or a numbered list) is recommended, as
is at least one mention of **verify / test / check / validate / assert**.

## 📊 Quality score components

| Component | Max | What it measures |
|---|---|---|
| description | 30 | present + ≤ 500 chars |
| triggers | 15 | 5 pts each, capped at 15 |
| tags | 10 | 5 pts each, capped at 10 |
| version | 10 | valid semver |
| body | 25 | present + steps + verify step |
| meta | 10 | license + author |

Grades: A ≥ 90 · B ≥ 75 · C ≥ 60 · D ≥ 40 · F < 40.

## 🧪 Validation error codes

| Code | Severity | Meaning |
|---|---|---|
| `no_frontmatter` | warn | missing YAML frontmatter |
| `missing_name` | error | frontmatter is missing `name` |
| `bad_name_format` | error | `name` is not kebab-case (≤ 64 chars) |
| `missing_description` | error | frontmatter is missing `description` |
| `description_too_long` | error | `description` > 1024 chars |
| `description_long` | warn | `description` > 500 chars |
| `description_head_long` | info | leading trigger phrase > 60 chars |
| `bad_version` | warn | `version` is not semver |
| `bad_triggers_type` | error | `triggers` is not a list |
| `no_steps_section` | info | body has no `## Steps` or numbered list |
| `no_verify_step` | info | body has no verify/test/check keyword |

## 📚 Example: lint a real catalog

```python
import sys, json
from tiny_skill_md import parse_file, validate, score

total = 0
ok = 0
for path in sys.argv[1:]:
    doc = parse_file(path)
    issues = validate(doc)
    s = score(doc)
    print(f"{doc.name:30s} {s['grade']} ({s['score']:3d}/100) issues={len(issues)}")
    for i in issues:
        print(f"  [{i.severity}] {i.code}: {i.message}")
    total += 1
    if not [x for x in issues if x.severity == "error"]:
        ok += 1

print(f"\n{ok}/{total} pass validation")
sys.exit(0 if ok == total else 1)
```

## 🧪 Testing

```bash
cd tiny-skill-md
python -m pytest -v
```

18 unit tests covering parsing, validation, rendering, scoring, and file IO.
CI runs them on Python 3.8 through 3.12.

## 🌱 Ecosystem

`tiny-skill-md` parses SKILL.md without pulling in PyYAML, which makes it
useful for any tool that needs to ingest skill catalogs.

| Repo | Job |
|------|-----|
| [`tiny-skill-lint`](https://github.com/hussain-alsaibai/tiny-skill-lint) | frontmatter linter with an 18-code catalogue and a CI-gate exit code |
| [`tiny-agentskills`](https://github.com/hussain-alsaibai/tiny-agentskills) | catalog indexer and skill runtime |
| [`tiny-agent`](https://github.com/hussain-alsaibai/tiny-agent) | zero-dep agent framework |
| [`tiny-eval`](https://github.com/hussain-alsaibai/tiny-eval) | eval suite + regression tracker |
| [`tiny-context`](https://github.com/hussain-alsaibai/tiny-context) | LLM context window manager |

`tiny-skill-md` and `tiny-skill-lint` are deliberately separate: this library
parses, validates and scores a skill, while the linter is a standalone CLI
that gates a catalog in CI.

## License

MIT © 2026 Hussain Al-Saibai
