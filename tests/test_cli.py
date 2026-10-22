from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
FILES = ["sharing-guide.md", "support.md", "rendering.md"]


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)
        self.root = self.work / "corpus"
        shutil.copytree(REPO / "fixtures" / "corpus", self.root)
        self.before = self.work / "before.json"
        self.after = self.work / "after.json"
        shutil.copyfile(REPO / "fixtures" / "decision-before.json", self.before)
        shutil.copyfile(REPO / "fixtures" / "decision-after.json", self.after)
        self.output = self.work / "ripple.json"

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args, expected=0):
        result = subprocess.run([sys.executable, "-m", "decision_ripple", *map(str, args)], cwd=REPO,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, expected, result.stderr)
        return result

    def base_args(self, fmt="json"):
        args = ["compare", self.before, self.after, "--root", self.root]
        for path in FILES:
            args.extend(["--file", path])
        args.extend(["--format", fmt])
        return args

    def test_documented_cli_reports_explicit_first_and_lexical_candidates(self):
        self.cli(*self.base_args(), "--out", self.output)
        report = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(report["change_status"], "changed")
        self.assertEqual(report["changed_fields"], ["statement", "rationale"])
        self.assertEqual([item["path"] for item in report["corpus"]], sorted(FILES))
        candidates = report["candidates"]
        self.assertEqual(candidates[0]["kind"], "explicit_reference")
        self.assertEqual(candidates[0]["source"], {"path": "sharing-guide.md", "line_start": 3, "line_end": 3})
        self.assertEqual(candidates[0]["matched_tokens"], [])
        self.assertEqual(candidates[1]["kind"], "lexical_candidate")
        self.assertEqual(candidates[1]["source"]["path"], "sharing-guide.md")
        self.assertEqual(candidates[2]["kind"], "lexical_candidate")
        self.assertEqual(candidates[2]["source"]["path"], "support.md")
        self.assertNotIn("rendering.md", [c["source"]["path"] for c in candidates])
        self.assertNotIn("rendering.md", [c["source"]["path"] for c in candidates])
        self.assertTrue(all(c["review_status"] == "unreviewed" for c in candidates))
        self.assertTrue(all("not establish" in c["reason"] or "does not confirm" in c["reason"] for c in candidates))
        self.assertEqual((report["total_candidates"], report["omitted_candidates"]), (3, 0))

        markdown = self.work / "ripple.md"
        self.cli(*self.base_args("markdown"), "--out", markdown)
        content = markdown.read_text(encoding="utf-8")
        self.assertIn("Candidates found before limit: 3", content)
        self.assertIn("## Explicit references", content)
        self.assertIn("## Lexical candidates", content)
        self.assertIn("does not confirm", content)
        self.assertIn("status: unreviewed", content.lower())

    def test_limit_counts_explicit_candidates_in_overall_limit(self):
        self.cli(*self.base_args(), "--limit", "1", "--out", self.output)
        report = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(report["total_candidates"], 3)
        self.assertEqual(report["omitted_candidates"], 2)
        self.assertEqual(len(report["candidates"]), 1)
        self.assertEqual(report["candidates"][0]["kind"], "explicit_reference")

    def test_unchanged_decision_yields_no_candidates_but_discloses_corpus(self):
        shutil.copyfile(self.before, self.after)
        self.cli(*self.base_args(), "--out", self.output)
        report = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(report["change_status"], "unchanged")
        self.assertEqual(report["changed_fields"], [])
        self.assertEqual(report["candidates"], [])
        self.assertEqual(report["total_candidates"], 0)
        self.assertEqual(len(report["corpus"]), len(FILES))

    def test_malformed_inputs_missing_files_and_escapes_do_not_write_output(self):
        bad_id = self.work / "bad-id.json"
        data = json.loads(self.after.read_text(encoding="utf-8"))
        data["id"] = "another-id"
        bad_id.write_text(json.dumps(data), encoding="utf-8")
        self.cli(*["compare", self.before, bad_id, "--root", self.root, "--file", FILES[0], "--out", self.output], expected=2)
        self.assertFalse(self.output.exists())
        self.cli(*self.base_args(), "--threshold", "1.2", "--out", self.output, expected=2)
        self.cli(*self.base_args(), "--limit", "0", "--out", self.output, expected=2)
        self.cli("compare", self.before, self.after, "--root", self.root, "--file", "../outside.md", "--out", self.output, expected=2)
        self.cli("compare", self.before, self.after, "--root", self.root, "--file", "missing.md", "--out", self.output, expected=2)
        self.assertFalse(self.output.exists())

    def test_output_cannot_overwrite_any_input(self):
        source = self.root / "support.md"
        original = source.read_bytes()
        self.cli(*self.base_args(), "--out", source, expected=2)
        self.assertEqual(source.read_bytes(), original)
        decision_bytes = self.after.read_bytes()
        self.cli(*self.base_args(), "--out", self.after, expected=2)
        self.assertEqual(self.after.read_bytes(), decision_bytes)

    def test_symlink_escape_and_alias_duplicate_are_rejected(self):
        outside = self.work / "outside.md"
        outside.write_text("Guest approval.", encoding="utf-8")
        (self.root / "escape.md").symlink_to(outside)
        self.cli("compare", self.before, self.after, "--root", self.root, "--file", "escape.md", "--out", self.output, expected=2)
        self.cli("compare", self.before, self.after, "--root", self.root, "--file", "support.md", "--file", "./support.md", "--out", self.output, expected=2)
        self.assertFalse(self.output.exists())

    def test_invalid_utf8_corpus_is_not_a_partial_success(self):
        (self.root / "broken.md").write_bytes(b"bad\xfftext")
        self.cli("compare", self.before, self.after, "--root", self.root, "--file", "support.md", "--file", "broken.md", "--out", self.output, expected=2)
        self.assertFalse(self.output.exists())

    def test_repeated_cli_reports_are_deterministic_and_help_version_work(self):
        self.cli(*self.base_args(), "--out", self.output)
        first = self.output.read_bytes()
        self.cli(*self.base_args(), "--out", self.output)
        self.assertEqual(self.output.read_bytes(), first)
        help_result = subprocess.run([sys.executable, "-m", "decision_ripple", "--help"], cwd=REPO, text=True, capture_output=True)
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("compare", help_result.stdout)
        version = subprocess.run([sys.executable, "-m", "decision_ripple", "--version"], cwd=REPO, text=True, capture_output=True)
        self.assertEqual(version.stdout.strip(), "decision-ripple 0.1.0")


if __name__ == "__main__":
    unittest.main()
