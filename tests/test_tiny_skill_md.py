"""Tests for tiny-skill-md."""
import os
import tempfile
import unittest

from tiny_skill_md import (
    Issue, NAME_RE, SEMVER_RE, parse, parse_file, render, render_frontmatter,
    score, validate,
)


GOOD = """---
name: deploy-service
description: |
  Deploy a service. Use when shipping or releasing.
version: 0.2.1
author: ops@example.com
license: MIT
triggers:
  - deploy
  - ship
tags:
  - devops
  - ci
---

# Deploy Service

## Steps

1. Run the build.
2. Verify the health checks.
"""


BAD_NAME = """---
name: DeployService
description: ok
---

body
"""

NO_FRONTMATTER = """# Just a heading

body
"""

NO_DESCRIPTION = """---
name: deploy
---

body
"""

LONG_DESCRIPTION = """---
name: deploy
description: """ + ("x" * 600) + """
---

body
"""

BLOCK_SCALAR_FOLDED = """---
name: deploy
description: >
  Folded scalar
  second line.
---

body
"""

INLINE_LIST = """---
name: deploy
description: ok
tags: [a, b, c]
---

body
"""


class TestParse(unittest.TestCase):
    def test_parses_good_doc(self):
        d = parse(GOOD)
        self.assertEqual(d.name, "deploy-service")
        self.assertEqual(d.version, "0.2.1")
        self.assertEqual(d.triggers, ("deploy", "ship"))
        self.assertEqual(d.tags, ("devops", "ci"))
        self.assertIn("Deploy", d.body)

    def test_parses_block_scalar(self):
        d = parse(GOOD)
        # Description has newlines and is non-empty
        self.assertTrue(d.description)
        self.assertIn("Deploy", d.description)

    def test_parses_folded_block_scalar(self):
        d = parse(BLOCK_SCALAR_FOLDED)
        self.assertIn("Folded", d.description)
        # Folded -> newlines collapsed
        self.assertNotIn("\n", d.description)

    def test_inline_list(self):
        d = parse(INLINE_LIST)
        self.assertEqual(d.tags, ("a", "b", "c"))

    def test_no_frontmatter_warns(self):
        d = parse(NO_FRONTMATTER)
        self.assertEqual(d.body, NO_FRONTMATTER.strip())
        self.assertTrue(any(i.code == "no_frontmatter" for i in d.issues))


class TestValidate(unittest.TestCase):
    def test_good_doc_has_no_errors(self):
        d = parse(GOOD)
        issues = validate(d)
        errors = [i for i in issues if i.severity == "error"]
        self.assertEqual(errors, [], f"unexpected errors: {errors}")

    def test_bad_name_reports_error(self):
        d = parse(BAD_NAME)
        validate(d)
        self.assertTrue(any(i.code == "bad_name_format" for i in d.issues))

    def test_missing_description_errors(self):
        d = parse(NO_DESCRIPTION)
        validate(d)
        self.assertTrue(any(i.code == "missing_description" for i in d.issues))

    def test_long_description_warns(self):
        d = parse(LONG_DESCRIPTION)
        validate(d)
        # 600 chars > recommended 500 -> warn; < hard 1024 -> no error.
        self.assertTrue(any(i.code == "description_long" for i in d.issues))
        self.assertFalse(any(i.code == "description_too_long" for i in d.issues))

    def test_bad_version_warns(self):
        text = GOOD.replace("version: 0.2.1", "version: not-semver")
        d = parse(text)
        validate(d)
        self.assertTrue(any(i.code == "bad_version" for i in d.issues))

    def test_body_no_steps_info(self):
        text = "---\nname: deploy\ndescription: ok\n---\n\n# Title\n\nSome prose.\n"
        d = parse(text)
        validate(d)
        self.assertTrue(any(i.code == "no_steps_section" for i in d.issues))

    def test_body_with_steps_passes(self):
        text = "---\nname: deploy\ndescription: ok\n---\n\n## Steps\n\n1. do thing.\n2. verify result.\n"
        d = parse(text)
        validate(d)
        codes = [i.code for i in d.issues]
        self.assertNotIn("no_steps_section", codes)


class TestRender(unittest.TestCase):
    def test_roundtrip_preserves_fields(self):
        d = parse(GOOD)
        rendered = render(d)
        d2 = parse(rendered)
        self.assertEqual(d2.name, d.name)
        self.assertEqual(d2.version, d.version)
        self.assertEqual(d2.triggers, d.triggers)
        self.assertEqual(d2.tags, d.tags)

    def test_frontmatter_render_escapes(self):
        text = render_frontmatter({"name": "x", "description": "weird: colon"})
        d = parse(text + "\n\nbody\n")
        self.assertEqual(d.description, "weird: colon")


class TestScore(unittest.TestCase):
    def test_good_doc_scores_high(self):
        d = parse(GOOD)
        s = score(d)
        self.assertGreaterEqual(s["score"], 80)
        self.assertIn(s["grade"], ("A", "B"))

    def test_empty_doc_scores_zero(self):
        d = parse("# just a title\n")
        s = score(d)
        self.assertLess(s["score"], 30)
        self.assertEqual(s["grade"], "F")

    def test_no_frontmatter_low_score(self):
        d = parse(NO_FRONTMATTER)
        s = score(d)
        self.assertLess(s["score"], 50)


class TestParseFile(unittest.TestCase):
    def test_parse_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(GOOD)
            path = f.name
        try:
            d = parse_file(path)
            self.assertEqual(d.name, "deploy-service")
            self.assertEqual(d.path, path)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
