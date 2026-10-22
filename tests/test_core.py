from __future__ import annotations

import unittest

from decision_ripple import decision_delta, extract_passages, rank_candidates, render_markdown, tokenize, validate_decision
from decision_ripple.core import ValidationError


def decision(statement: str, *, title="Guest invitations", rationale="", tags=None, ident="sharing-01"):
    return {"schema_version": 1, "id": ident, "title": title, "statement": statement,
            "rationale": rationale, "tags": list(tags or [])}


class CoreTests(unittest.TestCase):
    def test_tokenization_preserves_negation_and_modals(self):
        self.assertEqual(tokenize("THE guest MAY NOT invite 24 users, and no owner!"),
                         {"guest", "may", "not", "invite", "24", "users", "no", "owner"})

    def test_tag_order_and_normalized_whitespace_are_not_changes(self):
        old = decision("Guests may invite members.", rationale="Keep access clear.", tags=["Guest access", "Sharing"])
        new = decision("  guests   may invite members. ", rationale="keep access CLEAR.", tags=["sharing", "guest   access"])
        delta = decision_delta(old, new)
        self.assertEqual(delta["change_status"], "unchanged")
        self.assertEqual(delta["changed_fields"], [])
        self.assertEqual(delta["query"]["changed_tokens"], [])
        self.assertEqual(rank_candidates(old, new, [{"path": "x.md", "line_start": 1, "line_end": 1, "text": "Guests may invite members."}])["candidates"], [])

    def test_statement_and_rationale_changes_are_reported(self):
        old = decision("Guests may join.", rationale="Open collaboration.")
        new = decision("Guests must request approval to join.", rationale="Approval records accountability.")
        delta = decision_delta(old, new)
        self.assertEqual(delta["changed_fields"], ["statement", "rationale"])
        self.assertIn("may", delta["query"]["changed_tokens"])
        self.assertIn("approval", delta["query"]["changed_tokens"])

    def test_validation_rejects_bool_schema_duplicate_normalized_tags_and_mismatched_ids(self):
        invalid = decision("Guests may join.", tags=["Guest", " guest "])
        with self.assertRaisesRegex(ValidationError, "duplicate normalized tag"):
            validate_decision(invalid)
        invalid = decision("Guests may join.")
        invalid["schema_version"] = True
        with self.assertRaises(ValidationError):
            validate_decision(invalid)
        with self.assertRaisesRegex(ValidationError, "IDs must match"):
            decision_delta(decision("Old."), decision("New.", ident="other"))

    def test_passages_keep_inclusive_lines_and_ignore_code_fences(self):
        text = "# Guide\n\nFirst line\nsecond line [[decision:sharing-01]].\n\n```md\n[[decision:sharing-01]] code only\n```\n\nFinal paragraph.\n"
        passages = extract_passages(text, "guide.md")
        self.assertEqual([(p["line_start"], p["line_end"]) for p in passages], [(1, 1), (3, 4), (10, 10)])
        self.assertEqual(passages[1]["reference_ids"], ["sharing-01"])
        self.assertEqual(passages[2]["reference_ids"], [])

    def test_explicit_reference_without_overlap_and_other_reference(self):
        old = decision("Blue account owners may approve requests.")
        new = decision("Blue account owners must approve requests.")
        passages = [
            {"path": "a.md", "line_start": 2, "line_end": 2, "text": "Archived minutes remain available.", "reference_ids": ["sharing-01"]},
            {"path": "b.md", "line_start": 1, "line_end": 1, "text": "Archived minutes remain available.", "reference_ids": ["different-02"]},
            {"path": "z.md", "line_start": 1, "line_end": 1, "text": "The renderer paints icon geometry.", "reference_ids": []},
        ]
        report = rank_candidates(old, new, passages, threshold=0)
        self.assertEqual([(c["kind"], c["source"]["path"]) for c in report["candidates"]], [("explicit_reference", "a.md")])
        explicit = report["candidates"][0]
        self.assertEqual(explicit["score"], 0)
        self.assertEqual(explicit["matched_tokens"], [])
        self.assertEqual(explicit["review_status"], "unreviewed")
        self.assertIn("does not confirm", explicit["reason"])

    def test_lexical_ranking_and_zero_threshold_still_requires_overlap(self):
        old = decision("Owners may invite guest accounts.")
        new = decision("Owners must approve guest invitations.")
        passages = [
            {"path": "support.md", "line_start": 4, "line_end": 4, "text": "Support routes guest invitations to owners; owners must approve before sending."},
            {"path": "random.md", "line_start": 1, "line_end": 1, "text": "The renderer paints vector icons."},
        ]
        candidates = rank_candidates(old, new, passages, threshold=0)["candidates"]
        self.assertEqual([c["source"]["path"] for c in candidates], ["support.md"])
        self.assertEqual(candidates[0]["kind"], "lexical_candidate")
        self.assertIn("must", candidates[0]["matched_changed_tokens"])
        self.assertIn("not establish a dependency", candidates[0]["reason"])

    def test_ties_sort_by_path_limit_counts_and_output_is_deterministic(self):
        old = decision("Guest invitations may proceed.")
        new = decision("Guest invitations must proceed.")
        passages = [
            {"path": "z.md", "line_start": 1, "line_end": 1, "text": "Guest invitations must proceed."},
            {"path": "a.md", "line_start": 7, "line_end": 7, "text": "Guest invitations must proceed."},
            {"path": "a.md", "line_start": 3, "line_end": 3, "text": "Guest invitations must proceed."},
        ]
        first = rank_candidates(old, new, passages, limit=2)
        self.assertEqual([(c["source"]["path"], c["source"]["line_start"]) for c in first["candidates"]], [("a.md", 3), ("a.md", 7)])
        self.assertEqual((first["total_candidates"], first["omitted_candidates"]), (3, 1))
        self.assertEqual(first, rank_candidates(old, new, passages, limit=2))
        markdown_report = {**first, "decision_id": old["id"], "old_decision": old, "new_decision": new,
                           "corpus": [{"path": "a.md", "sha256": "0" * 64}]}
        markdown = render_markdown(markdown_report)
        self.assertIn("Candidates found before limit: 3", markdown)
        self.assertIn("Candidates omitted by limit: 1", markdown)

    def test_long_paragraph_scoring_uses_text_after_excerpt_limit(self):
        old = decision("Guest policy may proceed.")
        new = decision("Guest policy must require approval.")
        full = "ordinary " * 120 + "approval is required for this guest policy."
        passage = {"path": "long.md", "line_start": 1, "line_end": 1, "text": full}
        report = rank_candidates(old, new, [passage], threshold=0)
        candidate = report["candidates"][0]
        self.assertEqual(len(candidate["excerpt"]), 1000)
        self.assertTrue(candidate["excerpt_truncated"])
        self.assertIn("approval", candidate["matched_changed_tokens"])
        self.assertGreater(candidate["score"], 0)
        md = render_markdown({**report, "decision_id": old["id"], "old_decision": old, "new_decision": new,
                              "corpus": [{"path": "long.md", "sha256": "a" * 64}]})
        self.assertIn("matching used the full paragraph", md)

    def test_bounds_and_passage_types_are_validated(self):
        old, new = decision("Guests may join."), decision("Guests must join.")
        for threshold, limit in ((-0.1, 1), (1.1, 1), (0.2, 0), (0.2, True)):
            with self.assertRaises(ValidationError):
                rank_candidates(old, new, [], threshold, limit)
        with self.assertRaises(ValidationError):
            rank_candidates(old, old, [{"path": "x", "line_start": True, "line_end": 1, "text": "some text"}])


if __name__ == "__main__":
    unittest.main()
