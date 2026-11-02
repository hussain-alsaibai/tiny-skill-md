"""Lint a SKILL.md catalog from the command line.

Usage:
    python examples/lint_catalog.py path/to/skill/dir [more/skill/dirs ...]

Walks each given path one level deep, parses every SKILL.md, validates
against the proposed schema, prints quality grades, and exits 1 if any
SKILL.md has a severity=error issue.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running from the repo without installing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tiny_skill_md import discover, validate, score


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    docs = discover(argv)
    if not docs:
        print("No SKILL.md files found in:", argv)
        return 1

    total = len(docs)
    passed = 0
    failures: list[tuple[str, list[str]]] = []

    print(f"{'name':32s} {'grade':5s} {'score':>6s}  issues")
    print("-" * 70)
    for d in docs:
        issues = validate(d)
        s = score(d)
        print(f"{d.name or '(no name)':32s} {s['grade']:5s} {s['score']:>6d}  {len(issues)}")
        errors = [i for i in issues if i.severity == "error"]
        for i in issues:
            print(f"   [{i.severity:7s}] {i.code}: {i.message}")
        if not errors:
            passed += 1
        else:
            failures.append((d.path or d.name, [i.message for i in errors]))

    print()
    print(f"{passed}/{total} pass validation")
    if failures:
        print("\nFailures:")
        for path, msgs in failures:
            print(f"  - {path}")
            for m in msgs:
                print(f"      • {m}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
