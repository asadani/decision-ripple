# Decision Ripple v0.1 implementation plan

## User job and CLI

Given two versions of one explicit decision and a bounded document corpus, produce a ranked queue of located passages to review.

```sh
python -m decision_ripple compare fixtures/decision-before.json fixtures/decision-after.json --root fixtures/corpus --file sharing-guide.md --file support.md --file rendering.md --format json --out ripple.json
python -m decision_ripple compare fixtures/decision-before.json fixtures/decision-after.json --root fixtures/corpus --file sharing-guide.md --file support.md --file rendering.md --format markdown --out ripple.md
```

Repeatable `--file` explicitly identifies scanned UTF-8 text/Markdown files. `--threshold` float in [0,1], default 0.12, applies to lexical candidates only; `--limit` positive integer defaults to 50 overall. Explicit references are ranked first but may also be truncated by the limit; report pre-limit counts and omitted counts. A successfully generated report returns 0 regardless of candidate count; malformed decision, root escape, or unreadable requested file returns 2 rather than producing an apparently complete partial scan.

## Decision and report formats

Decision JSON: `{schema_version:1,id,title,statement,rationale,tags:[string]}`. ID/title/statement are nonempty strings; rationale may be empty; tags unique normalized strings. Old/new IDs must match. All fields are user-stated content, not machine-approved facts. Changes compare normalized text for title/statement/rationale and sorted normalized tags; if nothing changes, return `change_status: unchanged` and no candidates while disclosing the requested corpus. Keep the original statements for display. Changed rationale alone is a real decision-record change but not proof that policy behavior changed.

Report: `{schema_version:1,decision_id,change_status,old_decision,new_decision,changed_fields,query:{changed_tokens,all_tokens},corpus:[{path,sha256}],method:{name,threshold,limitations},total_candidates,omitted_candidates,candidates:[...]}`. Each candidate has `{id,kind:"explicit_reference"|"lexical_candidate",source:{path,line_start,line_end},excerpt,excerpt_truncated,reference_ids,score,matched_tokens,matched_changed_tokens,review_status:"unreviewed",reason}`. Stable ID derives from path/line span/content hash. Score is a lexical similarity number, never a probability or impact severity.

## Retrieval algorithm

1. Split documents into nonempty paragraphs, preserving 1-based line spans. Ignore fenced code blocks for lexical matching but explicit `[[decision:ID]]` markers outside fences are recognized exactly. A paragraph containing the target ID is an explicit-reference candidate even if its token overlap is zero.
2. Tokenize lowercased/casefolded title, statement, rationale, and tags with `[A-Za-z0-9]+` (English/ASCII lexical v0.1). Exclude a small documented constant stopword set, e.g. common articles, pronouns, and conjunctions. Keep negation/modal words because they can matter. Use token sets; no stemming, embeddings, or synonyms.
3. `all_tokens` is the union of old/new token sets. `changed_tokens` is their symmetric difference. Score each paragraph as Jaccard intersection/union against old and new query sets and keep the larger score; empty union scores zero. A lexical candidate requires score >= threshold AND at least one shared query token, so threshold zero does not return completely unrelated text.
4. Keep both matched query tokens and matched changed tokens as literal evidence. Rank explicit references first, then descending count of matched changed tokens, then descending score, then relative path and starting line. Explicit references to other decisions do not confer explicit-reference status for this decision, although their text can qualify lexically.
5. Truncate displayed excerpts at 1000 characters with a flag; scoring uses the full paragraph. Never alter the corpus or mark a candidate confirmed. Markdown groups explicit references and lexical candidates and includes retrieval reasons beside each passage.

No term overlap can establish a real dependency. Preserve statements such as “candidate for review” throughout output. Scan manifest and truncation counts must be prominent enough that a reader cannot infer exhaustive impact coverage.

## Core API

- `validate_decision(data: dict) -> None`
- `tokenize(text: str) -> set[str]`
- `decision_delta(old: dict, new: dict) -> dict`
- `extract_passages(text: str, path: str) -> list[dict]`
- `rank_candidates(old: dict, new: dict, passages: list[dict], threshold: float = 0.12, limit: int = 50) -> dict`
- `render_markdown(report: dict) -> str`

Pure retrieval functions take content, while CLI enforces root-relative paths, reads bytes, and records corpus hashes. Stable sorting makes the report reproducible. Validate all inputs before writing output.

## Fixtures and acceptance tests

1. Sharing decision changes approval requirements. Corpus includes one explicit target reference, a relevant support paragraph lacking the marker, an unrelated rendering paragraph, and an explicit reference to a different decision. Test candidate kinds, exact source lines, literal matched tokens, and first-ranked explicit reference.
2. An explicit marker with no query-token overlap is still retrieved; an unrelated paragraph is excluded even at threshold zero. The other decision marker alone is insufficient.
3. Identical normalized decision records yield unchanged/no candidates. Different IDs fail. Tag order alone is not a change; a statement or rationale change is recorded in changed_fields.
4. Ties resolve by path and line and repeated runs produce identical results. Excerpt truncation leaves full-text scoring intact and is disclosed. Limit preserves exact total/omitted counts.
5. Code-fenced examples are excluded, missing files cause clear failure, and traversal/symlink escapes are rejected. Threshold/limit type and bounds errors are actionable.
6. CLI JSON and Markdown demos succeed with a substantive candidate queue; output includes method limits and scanned paths. Neither report labels a lexical candidate as confirmed impact.

## Non-goals and milestone

Required: decision delta, explicit markers, lexical ranking, provenance, scan completeness disclosure, JSON/Markdown reports, tests. Deferred: transitive dependency graphs, semantic search, repository crawling, issue creation, automatic document edits, ownership routing, reviewer ledger. These would change the product's evidence and authorization requirements.

Build decision validation and passage/token handling, then ranking, then reports/fixtures. Done means the demo yields a useful ordered review queue with an explicit-reference item, a clearly labeled inferred candidate, and no fabricated certainty.
