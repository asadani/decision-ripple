<p align="center"><img src="assets/logo.svg" alt="Decision Ripple" width="310"></p>

Decision Ripple compares two versions of one explicit decision and ranks passages in a bounded, user-selected document set that may be worth reviewing. It distinguishes exact decision markers from lexical overlap and explains why each passage appeared. It does not infer a complete dependency graph or decide whether any document must change.

## Quickstart

Requires Python 3.11 or newer. The package uses only the standard library. Run from this repository root:

```sh
out_dir="$(mktemp -d)"
python -m decision_ripple compare fixtures/decision-before.json fixtures/decision-after.json --root fixtures/corpus --file sharing-guide.md --file support.md --file rendering.md --format json --out "$out_dir/ripple.json"
python -m decision_ripple compare fixtures/decision-before.json fixtures/decision-after.json --root fixtures/corpus --file sharing-guide.md --file support.md --file rendering.md --format markdown --out "$out_dir/ripple.md"
```

Both runs exit `0` when a report is generated, whether or not candidates appear. The fixture report has three candidates before the limit: an explicit marker in `sharing-guide.md`, a lexical candidate in that guide, and a lexical candidate in `support.md`. The explicit marker is ranked first even though the paragraph has no decision-token overlap. The renderer notes and a marker for a different decision are excluded.

The JSON report includes exact source lines, corpus hashes, matched terms, changed terms, the retrieval reason, and an `unreviewed` status for each candidate. A lexical score is a Jaccard overlap value, not a probability or impact estimate.

## Decision record

The old and new UTF-8 JSON files use the same decision ID and this shape:

```json
{
  "schema_version": 1,
  "id": "sharing-approval-01",
  "title": "Guest invitations",
  "statement": "Workspace owners must approve guest invitations.",
  "rationale": "Approval keeps guest access accountable.",
  "tags": ["sharing", "guest access"]
}
```

`id`, `title`, and `statement` must be nonempty strings; `rationale` may be empty. Tags must be unique after trimming, case folding, and whitespace collapse. Old and new IDs must match. Reordering tags alone is not a change. Normalized title, statement, rationale, and tag differences are reported in `changed_fields`; a rationale-only change is a decision-record change, not proof that policy behavior changed. See [decision schema](docs/decision.schema.json) and [report schema](docs/report.schema.json).

## Retrieval and ranking

Only files passed with repeatable `--file` are read. Paths are relative to `--root` (current directory by default), resolve inside that root, and must identify regular UTF-8 files. The report's corpus manifest lists every scanned canonical path and SHA-256 hash. If a requested file is missing, unreadable, malformed UTF-8, or escapes through a symlink, the command exits `2` without writing a partial report. The report output cannot overwrite either decision input or a scanned corpus file.

An explicit marker such as `[[decision:sharing-approval-01]]` is recognized outside fenced code blocks. A matching marker makes its paragraph an explicit-reference candidate even when its prose has zero token overlap. A marker for another ID does not have that status, though the surrounding prose can still match lexically.

The lexical query is the union of casefolded title, statement, rationale, and tag tokens from both decision versions. Tokens use ASCII letters and digits. The fixed stopword set is: `a, about, am, an, and, are, as, at, be, been, being, but, by, did, do, does, done, down, else, for, from, had, has, have, he, i, if, in, into, is, it, me, my, of, on, or, our, she, so, than, that, the, their, them, then, these, they, this, those, to, up, very, was, we, were, what, when, where, which, who, whom, whose, with, you, your`. Negation and modal terms remain available for matching. There is no stemming, synonym expansion, or semantic search. `changed_tokens` is the symmetric difference of old and new decision token sets.

For each paragraph, Decision Ripple computes Jaccard overlap against old and new query tokens and keeps the larger score. A lexical candidate must meet `--threshold` and share at least one query token; threshold `0` still does not retrieve unrelated text. Explicit references rank before lexical candidates. Within each kind, candidates sort by descending count of matched changed tokens, descending score, relative path, then starting line. `--limit` applies to the overall ranked queue, including explicit references. Reports show the full pre-limit candidate total and omitted count.

Paragraph excerpts display up to 1,000 characters. `excerpt_truncated` and the Markdown report disclose truncation among displayed candidates; matching still uses the full paragraph. Candidate IDs derive deterministically from relative path, line span, and full paragraph content.

## CLI and output

```sh
python -m decision_ripple compare BEFORE.json AFTER.json --root CORPUS --file RELATIVE_PATH [--file RELATIVE_PATH ...] [--format json|markdown] [--threshold 0.12] [--limit 50] [--out FILE]
```

Without `--out`, output goes to stdout. JSON uses `schema_version: 1` and includes the two decision records, normalized change fields, query tokens, scan manifest, method and limitations, pre-limit and omitted counts, and ranked candidates. Markdown groups explicit references and lexical candidates and presents their reasons and excerpts.

Expected validation and file errors go to stderr without a traceback. Exit codes are `0` when the report is written, even if candidates are found, and `2` for malformed decisions, mismatched IDs, invalid threshold or limit, or any requested corpus problem. `--help` and `--version` are available.

## Boundaries

This is a review queue, not a dependency graph. A reference marker identifies an authored link but does not prove the passage must change. Token overlap can miss paraphrases or surface unrelated text, and a document can depend on a decision without sharing words. The scan is limited to the explicitly selected files and has no transitive traversal, ownership routing, semantic search, or automatic edits. Scores do not express confidence, severity, or impact. Every candidate remains unreviewed until a person checks it in context.

## Development

```sh
python -m unittest discover -s tests -v
```

The pure API consists of `validate_decision`, `tokenize`, `decision_delta`, `extract_passages`, `rank_candidates`, and `render_markdown`. It does not read or write files; the CLI reads and hashes the inputs and produces the output artifact.

See [verification coverage](docs/VERIFICATION.md) and [the design plan](docs/PLAN.md) for tested behavior and remaining limits.
