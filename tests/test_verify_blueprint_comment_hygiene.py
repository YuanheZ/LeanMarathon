from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / ".scripts" / "verify_blueprint.py"
SPEC = importlib.util.spec_from_file_location("verify_blueprint_under_test", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


VALID_NODE = """\
@[blueprint "lem:foo"
  (statement := /-- This is a valid statement. -/)
  (proof := /-- This is valid proof prose. -/)
  (title := /-- Foo -/)
  (latexEnv := "lemma")]
lemma foo : True := by
  sorry
"""


class CommentHygieneTests(unittest.TestCase):
    def failures(self, text: str) -> list[str]:
        return verifier.scan_comment_hygiene(text, Path("Main.lean"))

    def test_blueprint_prose_doc_comments_are_allowed(self) -> None:
        self.assertEqual([], self.failures(VALID_NODE))

    def test_commented_out_blueprint_node_is_rejected(self) -> None:
        text = (
            VALID_NODE
            + """
/-
@[blueprint "lem:archived"
  (statement := /-- Archived. -/)
  (proof := /-- Archived. -/)
  (title := /-- Archived -/)
  (latexEnv := "lemma")]
lemma archived : True := by
  sorry
-/
"""
        )
        failures = self.failures(text)
        self.assertEqual(1, len(failures))
        self.assertIn("block comment is not allowed", failures[0])

    def test_line_comment_is_rejected(self) -> None:
        failures = self.failures(VALID_NODE + "\n-- archived note\n")
        self.assertEqual(1, len(failures))
        self.assertIn("line comments are not allowed", failures[0])

    def test_stray_doc_comment_is_rejected(self) -> None:
        failures = self.failures("/-- Stray API doc. -/\n" + VALID_NODE)
        self.assertEqual(1, len(failures))
        self.assertIn("doc comment is not allowed", failures[0])

    def test_module_doc_comment_is_rejected(self) -> None:
        failures = self.failures("/-! Module docs. -/\n" + VALID_NODE)
        self.assertEqual(1, len(failures))
        self.assertIn("module doc comment is not allowed", failures[0])


if __name__ == "__main__":
    unittest.main()
