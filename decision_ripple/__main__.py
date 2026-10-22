"""CLI for a bounded Decision Ripple scan."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Sequence

from . import __version__
from .core import ValidationError, extract_passages, rank_candidates, render_markdown, validate_decision


def _json_file(path: Path, label: str) -> dict:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValidationError(f"cannot read {label} {path}: {exc}") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValidationError(f"{label} is not valid UTF-8: {path} (byte offset {exc.start})") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid {label} JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a JSON object: {path}")
    return value


def _resolve_file(root: Path, relative: str) -> tuple[Path, str]:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValidationError(f"file path must be a non-empty relative path using forward slashes: {relative!r}")
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or relative in (".", ""):
        raise ValidationError(f"file path must stay relative to root: {relative!r}")
    try:
        root = root.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValidationError(f"cannot access root directory {root}: {exc}") from exc
    candidate = root.joinpath(*path.parts)
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValidationError(f"cannot read requested file {relative!r}: {exc}") from exc
    if resolved != root and root not in resolved.parents:
        raise ValidationError(f"requested file escapes root through a symlink: {relative!r}")
    if not resolved.is_file():
        raise ValidationError(f"requested path is not a regular file: {relative!r}")
    canonical = resolved.relative_to(root).as_posix()
    return resolved, canonical


def _read_corpus(root: Path, file_args: list[str]) -> tuple[list[dict], list[dict]]:
    if not file_args:
        raise ValidationError("provide at least one --file relative path")
    try:
        root = root.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValidationError(f"cannot access root directory {root}: {exc}") from exc
    if not root.is_dir():
        raise ValidationError(f"root is not a directory: {root}")
    resolved_paths: dict[str, Path] = {}
    for path in file_args:
        resolved, canonical = _resolve_file(root, path)
        if canonical in resolved_paths:
            raise ValidationError(f"duplicate corpus path after resolving aliases: {canonical!r}")
        resolved_paths[canonical] = resolved
    corpus, passages = [], []
    for relative, path in sorted(resolved_paths.items()):
        try:
            raw = path.read_bytes()
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValidationError(f"cannot read requested file {relative!r}: {exc}") from exc
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError(f"requested file {relative!r} is not valid UTF-8 (byte offset {exc.start})") from exc
        corpus.append({"path": relative, "sha256": hashlib.sha256(raw).hexdigest()})
        passages.extend(extract_passages(text, relative))
    return corpus, passages


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _ensure_output_distinct(output: Path, inputs: list[Path]) -> None:
    destination = output.resolve(strict=False)
    for source in inputs:
        try:
            source_resolved = source.resolve(strict=True)
        except OSError:
            continue
        if destination == source_resolved:
            raise ValidationError(f"output path would overwrite an input: {source}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="decision-ripple", description="Rank explicit references and lexical review candidates for a changed decision.")
    parser.add_argument("--version", action="version", version=f"decision-ripple {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    compare = commands.add_parser("compare", help="compare decision records against selected corpus files")
    compare.add_argument("before", type=Path)
    compare.add_argument("after", type=Path)
    compare.add_argument("--root", type=Path, default=Path.cwd())
    compare.add_argument("--file", action="append", required=True, help="root-relative UTF-8 file; repeat for each file")
    compare.add_argument("--format", choices=("json", "markdown"), default="json")
    compare.add_argument("--threshold", type=float, default=.12)
    compare.add_argument("--limit", type=int, default=50)
    compare.add_argument("--out", type=Path, help="write to this file; default is stdout")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if not 0 <= args.threshold <= 1:
            raise ValidationError("threshold must be a number in [0, 1]")
        if args.limit <= 0:
            raise ValidationError("limit must be a positive integer")
        old = _json_file(args.before, "old decision")
        new = _json_file(args.after, "new decision")
        validate_decision(old)
        validate_decision(new)
        if old["id"] != new["id"]:
            raise ValidationError("old and new decision IDs must match")
        corpus, passages = _read_corpus(args.root, args.file)
        report = rank_candidates(old, new, passages, args.threshold, args.limit)
        report.update({"schema_version": 1, "decision_id": old["id"], "old_decision": old, "new_decision": new, "corpus": corpus})
        if args.format == "markdown":
            output = render_markdown(report)
        else:
            output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.out:
            corpus_paths = [args.root.resolve(strict=True).joinpath(*PurePosixPath(item["path"]).parts) for item in corpus]
            _ensure_output_distinct(args.out, [args.before, args.after, *corpus_paths])
            _atomic_write(args.out, output.encode("utf-8"))
        else:
            sys.stdout.write(output)
        return 0
    except ValidationError as exc:
        print(f"decision-ripple: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"decision-ripple: invalid input: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"decision-ripple: I/O error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
