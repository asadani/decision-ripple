"""Decision delta and bounded lexical candidate retrieval."""

from __future__ import annotations

import hashlib
import re
from typing import Any

STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "when", "where", "what", "who", "whom", "which", "whose",
    "this", "that", "these", "those", "i", "me", "my", "we", "our", "you", "your", "he", "she", "it", "they", "them", "their",
    "be", "is", "are", "was", "were", "been", "being", "am", "do", "does", "did", "done", "have", "has", "had", "to", "of", "in",
    "on", "at", "by", "for", "from", "with", "as", "into", "about", "up", "down", "than", "so", "very",
})
_WORD = re.compile(r"[A-Za-z0-9]+")
_REFERENCE = re.compile(r"\[\[decision:([^\]\s]+)\]\]")
_FENCE_OPEN = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_FENCE_CLOSE = re.compile(r"^\s{0,3}(`{3,}|~{3,})\s*$")


class ValidationError(ValueError):
    """Expected user input validation problem."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def _nonempty(value: Any, field: str, allow_empty: bool = False) -> None:
    _require(isinstance(value, str), f"{field} must be a string")
    _require(allow_empty or bool(value.strip()), f"{field} must not be empty")


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def validate_decision(data: dict) -> None:
    """Validate the versioned decision record shape and normalized unique tags."""
    _require(isinstance(data, dict), "decision must be a JSON object")
    _require(type(data.get("schema_version")) is int and data["schema_version"] == 1,
             "schema_version must be integer 1")
    for field in ("id", "title", "statement", "rationale"):
        _nonempty(data.get(field), field, allow_empty=(field == "rationale"))
    tags = data.get("tags")
    _require(isinstance(tags, list), "tags must be an array")
    seen = set()
    for index, tag in enumerate(tags):
        _nonempty(tag, f"tags[{index}]")
        normalized = _normalized(tag)
        _require(normalized not in seen, f"duplicate normalized tag: {tag!r}")
        seen.add(normalized)


def tokenize(text: str) -> set[str]:
    """Return casefolded ASCII alphanumeric tokens excluding fixed stopwords."""
    if not isinstance(text, str):
        raise ValidationError("tokenize input must be a string")
    return {match.group(0).casefold() for match in _WORD.finditer(text) if match.group(0).casefold() not in STOPWORDS}


def _decision_tokens(data: dict) -> set[str]:
    parts = [data["title"], data["statement"], data["rationale"], *data["tags"]]
    return set().union(*(tokenize(part) for part in parts))


def decision_delta(old: dict, new: dict) -> dict:
    """Compare validated records and return normalized change/query evidence."""
    validate_decision(old)
    validate_decision(new)
    _require(old["id"] == new["id"], "old and new decision IDs must match")
    changed = []
    for field in ("title", "statement", "rationale"):
        if _normalized(old[field]) != _normalized(new[field]):
            changed.append(field)
    old_tags = {_normalized(tag) for tag in old["tags"]}
    new_tags = {_normalized(tag) for tag in new["tags"]}
    if old_tags != new_tags:
        changed.append("tags")
    old_tokens, new_tokens = _decision_tokens(old), _decision_tokens(new)
    return {
        "change_status": "changed" if changed else "unchanged",
        "changed_fields": changed,
        "query": {"changed_tokens": sorted(old_tokens ^ new_tokens), "all_tokens": sorted(old_tokens | new_tokens)},
        "old_tokens": old_tokens,
        "new_tokens": new_tokens,
    }


def extract_passages(text: str, path: str) -> list[dict]:
    """Split text into nonempty paragraphs, retaining line locations and references."""
    _nonempty(path, "path")
    if not isinstance(text, str):
        raise ValidationError("document text must be a string")
    passages = []
    block_lines: list[tuple[int, str]] = []
    fence: tuple[str, int] | None = None

    def flush() -> None:
        nonlocal block_lines
        if block_lines:
            paragraph = "\n".join(line for _, line in block_lines).strip()
            if paragraph:
                refs = [match.group(1) for match in _REFERENCE.finditer(paragraph)]
                passages.append({"path": path, "line_start": block_lines[0][0], "line_end": block_lines[-1][0],
                                 "text": paragraph, "reference_ids": refs})
        block_lines = []

    for line_number, line in enumerate(text.splitlines(), start=1):
        marker = _FENCE_OPEN.match(line)
        if fence:
            closer = _FENCE_CLOSE.match(line)
            if closer and closer.group(1)[0] == fence[0] and len(closer.group(1)) >= fence[1]:
                fence = None
            continue
        if marker:
            flush()
            token = marker.group(1)
            fence = (token[0], len(token))
            continue
        if not line.strip():
            flush()
            continue
        block_lines.append((line_number, line))
    flush()
    return passages


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _candidate_id(path: str, line_start: int, line_end: int, text: str) -> str:
    digest = hashlib.sha256(f"{path}\0{line_start}\0{line_end}\0{text}".encode("utf-8")).hexdigest()[:12]
    return f"candidate-{digest}"


def _validate_passages(passages: Any) -> None:
    _require(isinstance(passages, list), "passages must be an array")
    for index, passage in enumerate(passages):
        _require(isinstance(passage, dict), f"passages[{index}] must be an object")
        _nonempty(passage.get("path"), f"passages[{index}].path")
        _nonempty(passage.get("text"), f"passages[{index}].text")
        start, end = passage.get("line_start"), passage.get("line_end")
        _require(isinstance(start, int) and not isinstance(start, bool) and start > 0, f"passages[{index}].line_start must be a positive integer")
        _require(isinstance(end, int) and not isinstance(end, bool) and end >= start, f"passages[{index}].line_end must be an integer no less than line_start")
        references = passage.get("reference_ids", [])
        _require(isinstance(references, list) and all(isinstance(ref, str) for ref in references), f"passages[{index}].reference_ids must be strings")


def rank_candidates(old: dict, new: dict, passages: list[dict], threshold: float = .12, limit: int = 50) -> dict:
    """Rank explicit references first, then bounded lexical overlap candidates."""
    delta = decision_delta(old, new)
    _require(isinstance(threshold, (int, float)) and not isinstance(threshold, bool) and 0 <= threshold <= 1,
             "threshold must be a number in [0, 1]")
    _require(isinstance(limit, int) and not isinstance(limit, bool) and limit > 0, "limit must be a positive integer")
    _validate_passages(passages)
    if delta["change_status"] == "unchanged":
        candidates = []
        total = 0
    else:
        old_tokens, new_tokens = delta["old_tokens"], delta["new_tokens"]
        all_tokens = set(delta["query"]["all_tokens"])
        changed_tokens = set(delta["query"]["changed_tokens"])
        candidates = []
        seen_ids = set()
        for passage in passages:
            start, end = passage.get("line_start"), passage.get("line_end")
            references = passage.get("reference_ids", [])
            # Marker text is retrieval metadata, not prose evidence of lexical relevance.
            passage_tokens = tokenize(_REFERENCE.sub("", passage["text"]))
            matched = sorted(passage_tokens & all_tokens)
            changed_match = sorted(passage_tokens & changed_tokens)
            score = max(_jaccard(passage_tokens, old_tokens), _jaccard(passage_tokens, new_tokens))
            explicit = old["id"] in references
            if not explicit and (score < threshold or not matched):
                continue
            kind = "explicit_reference" if explicit else "lexical_candidate"
            candidate_id = _candidate_id(passage["path"], start, end, passage["text"])
            _require(candidate_id not in seen_ids, f"duplicate passage identity at {passage['path']}:{start}-{end}")
            seen_ids.add(candidate_id)
            excerpt = passage["text"][:1000]
            if explicit:
                reason = "Contains an explicit marker for this decision; reference presence does not confirm that an update is needed."
            else:
                reason = "Candidate for review based on literal token overlap; overlap does not establish a dependency."
            candidates.append({
                "id": candidate_id,
                "kind": kind,
                "source": {"path": passage["path"], "line_start": start, "line_end": end},
                "excerpt": excerpt,
                "excerpt_truncated": len(passage["text"]) > 1000,
                "reference_ids": list(references),
                "score": round(score, 6),
                "matched_tokens": matched,
                "matched_changed_tokens": changed_match,
                "review_status": "unreviewed",
                "reason": reason,
                "_changed_count": len(changed_match),
            })
        candidates.sort(key=lambda c: (0 if c["kind"] == "explicit_reference" else 1,
                                       -c["_changed_count"], -c["score"], c["source"]["path"], c["source"]["line_start"]))
        total = len(candidates)
    omitted = max(0, total - limit)
    candidates = candidates[:limit]
    for candidate in candidates:
        candidate.pop("_changed_count", None)
    return {
        "change_status": delta["change_status"],
        "changed_fields": delta["changed_fields"],
        "query": delta["query"],
        "method": {
            "name": "target marker lookup plus Jaccard lexical overlap",
            "threshold": float(threshold),
            "limitations": [
                "The corpus is limited to the explicitly requested files; no repository crawling or dependency graph is performed.",
                "Token overlap can miss paraphrases and can retrieve unrelated text; it does not establish a real dependency or impact.",
                "Tokens use ASCII letters and digits with a fixed stopword list; there is no stemming, synonym expansion, or semantic search.",
                "Explicit decision markers locate references but do not prove that a referenced passage requires revision.",
                "Scores measure lexical Jaccard overlap, not probability, impact, severity, or confidence.",
            ],
        },
        "total_candidates": total,
        "omitted_candidates": omitted,
        "candidates": candidates,
    }


def render_markdown(report: dict) -> str:
    """Render a compact review queue with scan and truncation counts."""
    candidates = report["candidates"]
    explicit = [c for c in candidates if c["kind"] == "explicit_reference"]
    lexical = [c for c in candidates if c["kind"] == "lexical_candidate"]
    truncated = sum(c["excerpt_truncated"] for c in candidates)
    lines = ["# Decision Ripple review", "", "Candidates are unreviewed passages for follow-up; retrieval does not confirm impact.", "",
             f"- Decision: {_inline(report['decision_id'])} — {report['change_status']}",
             f"- Scanned files: {len(report['corpus'])}",
             f"- Candidates found before limit: {report['total_candidates']}",
             f"- Candidates omitted by limit: {report['omitted_candidates']}",
             f"- Displayed excerpts truncated: {truncated}",
             f"- Threshold: {report['method']['threshold']:.3f}", "", "## Changed decision", ""]
    lines += [f"Changed fields: {', '.join(report['changed_fields']) if report['changed_fields'] else 'none'}.", ""]
    for field in ("title", "statement", "rationale", "tags"):
        lines += [f"**Old {field}:**", "", _fence(str(report["old_decision"][field])), "",
                  f"**New {field}:**", "", _fence(str(report["new_decision"][field])), ""]
    lines += ["## Retrieval limits", ""]
    lines.extend(f"- {item}" for item in report["method"]["limitations"])
    for heading, group in (("Explicit references", explicit), ("Lexical candidates", lexical)):
        lines += ["", f"## {heading}", ""]
        if not group:
            lines.append("None in the displayed candidate set.")
            continue
        for candidate in group:
            source = candidate["source"]
            lines += [f"### {_inline(candidate['id'])} — {_inline(source['path'])}:{source['line_start']}–{source['line_end']}", "",
                      f"Score: {candidate['score']:.3f} (lexical Jaccard; not probability or impact).  ",
                      f"Status: {candidate['review_status']}.  ", f"Reason: {candidate['reason']}", "",
                      f"Matched tokens: {_inline(candidate['matched_tokens'])}",
                      f"Matched changed tokens: {_inline(candidate['matched_changed_tokens'])}"]
            if candidate["reference_ids"]:
                lines.append(f"Reference markers: {_inline(candidate['reference_ids'])}")
            lines += ["", _fence(candidate["excerpt"]), ""]
            if candidate["excerpt_truncated"]:
                lines.append("Excerpt truncated at 1,000 characters; matching used the full paragraph.")
                lines.append("")
    lines += ["", "## Scanned corpus", ""]
    lines.extend(f"- {_inline(path['path'])} — SHA-256 `{path['sha256']}`" for path in report["corpus"])
    return "\n".join(lines).rstrip() + "\n"


def _fence(text: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{text}\n{fence}"


def _inline(value: Any) -> str:
    text = str(value).replace("\n", " ").replace("|", "\\|")
    ticks = max((len(run) for run in re.findall(r"`+", text)), default=0) + 1
    delimiter = "`" * ticks
    return f"{delimiter}{text}{delimiter}"
