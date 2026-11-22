"""Transcript ingest: the ONE documented v0.1 format.

GhostReplay v0.1 supports exactly one transcript shape, the
Claude Code session transcript as saved locally by Claude Code
(verified shape, Oct 2026), in either of its two on-disk forms:

Form A - JSONL (the normal on-disk form, e.g.
``~/.claude/projects/<project-slug>/<session-id>.jsonl``):
one JSON object per line. Each object ("entry") may carry:

  type        "user" | "assistant" | "summary" | "system" | ...
  sessionId   string, same for the whole file when present
  cwd         string, the project directory when present
  timestamp   ISO-8601 string when present
  uuid        string when present
  message     object when type is "user"/"assistant":
    role        "user" | "assistant"
    content     a string, OR a list of content blocks:
      {"type": "text", "text": "..."}
      {"type": "tool_use", "name": "Read", "input": {...}}
         tool names seen: Read / Edit / Write / Grep / Glob /
         Bash / NotebookEdit and others; file-bearing inputs use
         "file_path" (also accepted: "path", "notebook_path")
      {"type": "tool_result", "content": "..." or [blocks]}
    usage       optional {"input_tokens": n, "output_tokens": n}
                provider-REPORTED figures; GhostReplay stores them
                under "reported_*" and never blends them with its
                own estimates
    model       optional string

Form B - a single JSON document: either a list of entries in the
Form A shape, or an object {"messages": [entries...]} (the shape
produced by some export helpers). Same entry fields.

Anything else is UNRECOGNISED and ingest fails loudly (exit 2)
naming the problem line/field, rather than analysing a shape it
does not understand badly (PLAN.md format-fragility risk).

A "turn" is one user entry plus the assistant entries that follow
it up to the next user entry (turn numbering starts at 1; entries
before the first user entry belong to turn 0).

Ingest normalises a transcript into a canonical session document
(format "ghostreplay-session/1") holding per-turn events: text
(with token estimates), file references (path + how: tool_use /
tool_result / text mention is decided later against the bundle;
transcript only records candidate paths from tool inputs and raw
text), symbol mentions are computed in analysis, and instruction
blocks (user text blocks) for rule-repetition analysis.

The canonical document stores NO raw secret-shaped strings: text
is passed through secrets.sanitize at ingest time, and findings
are recorded as {source, line, type} only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import secrets
from .tokens import estimate_tokens

CANONICAL_FORMAT = "ghostreplay-session/1"
_FILE_INPUT_KEYS = ("file_path", "notebook_path", "path")


class TranscriptError(ValueError):
    """Unrecognised transcript shape (loud, never guessed at)."""


def _content_blocks(message: dict) -> list[dict]:
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if isinstance(content, list):
        out = []
        for block in content:
            if isinstance(block, dict):
                out.append(block)
            elif isinstance(block, str):
                out.append({"type": "text", "text": block})
        return out
    return []


def _block_text(block: dict) -> str:
    if block.get("type") == "text":
        return str(block.get("text") or "")
    if block.get("type") == "tool_result":
        inner = block.get("content")
        if isinstance(inner, str):
            return inner
        if isinstance(inner, list):
            return "\n".join(_block_text(b) for b in inner
                             if isinstance(b, dict))
    return ""


def _tool_file_paths(block: dict) -> list[str]:
    inp = block.get("input")
    paths: list[str] = []
    if isinstance(inp, dict):
        for key in _FILE_INPUT_KEYS:
            val = inp.get(key)
            if isinstance(val, str) and val:
                paths.append(val)
        # Grep/Glob style inputs name a search root in "path" and a
        # pattern; a bare directory path is not a file reference.
    return paths


def _entries_from_raw(raw_text: str, source_name: str) -> list[dict]:
    text = raw_text.strip()
    if not text:
        raise TranscriptError(f"{source_name}: empty transcript")
    # Form A: JSONL. Detect by trying the first non-empty line as a
    # standalone object with an entry-like shape.
    lines = [ln for ln in raw_text.splitlines() if ln.strip()]
    jsonl_entries: list[dict] | None = None
    try:
        first = json.loads(lines[0])
        if isinstance(first, dict) and ("type" in first or "message" in first):
            jsonl_entries = []
            for i, ln in enumerate(lines, start=1):
                try:
                    obj = json.loads(ln)
                except ValueError as exc:
                    raise TranscriptError(
                        f"{source_name}: line {i} is not valid JSON "
                        f"({exc}); not the documented JSONL shape") from exc
                if not isinstance(obj, dict):
                    raise TranscriptError(
                        f"{source_name}: line {i} is not a JSON object; "
                        "not the documented JSONL shape")
                jsonl_entries.append(obj)
    except ValueError as exc:
        if isinstance(exc, TranscriptError):
            raise
        jsonl_entries = None
    if jsonl_entries is not None:
        return jsonl_entries
    # Form B: one JSON document.
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise TranscriptError(
            f"{source_name}: not valid JSON or JSONL ({exc}); "
            "unrecognised transcript shape") from exc
    if isinstance(doc, list):
        entries = doc
    elif isinstance(doc, dict) and isinstance(doc.get("messages"), list):
        entries = doc["messages"]
    elif isinstance(doc, dict) and doc.get("format") == CANONICAL_FORMAT:
        raise TranscriptError(
            f"{source_name}: this is already a GhostReplay canonical "
            "session; pass it to analyse, not ingest")
    else:
        raise TranscriptError(
            f"{source_name}: unrecognised transcript shape (expected "
            "Claude Code JSONL entries, a JSON list of entries, or "
            '{"messages": [...]})')
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise TranscriptError(
                f"{source_name}: entry {i} is not a JSON object")
    return entries


def parse_transcript(path: str | Path) -> dict:
    """Parse a transcript file into the canonical session dict.

    Raises :class:`TranscriptError` naming the offending line or
    field when the file is not the one documented format: ingest
    fails loudly rather than analysing an unknown shape badly.
    """
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise TranscriptError(f"{path}: cannot read transcript: {exc}") from exc
    findings = secrets.scan_lines(raw.splitlines(), str(path))
    entries = _entries_from_raw(raw, str(path))

    session_id = None
    cwd = None
    for entry in entries:
        if session_id is None and isinstance(entry.get("sessionId"), str):
            session_id = entry["sessionId"]
        if cwd is None and isinstance(entry.get("cwd"), str):
            cwd = entry["cwd"]
    if session_id is None:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        session_id = f"sha256-{digest[:12]}"

    turns: list[dict] = []
    current: dict | None = None
    turn_no = 0
    reported_in = 0
    reported_out = 0
    models: set[str] = set()
    first_ts = None
    last_ts = None

    def _new_turn(n: int) -> dict:
        return {"turn": n, "texts": [], "tool_uses": [],
                "file_inputs": [], "instruction_blocks": []}

    for entry in entries:
        ts = entry.get("timestamp")
        if isinstance(ts, str):
            first_ts = first_ts or ts
            last_ts = ts
        etype = entry.get("type")
        message = entry.get("message")
        if not isinstance(message, dict):
            # summary/system/file-history entries carry no message
            # content GhostReplay can attribute; they are counted
            # in entry_count only.
            continue
        role = message.get("role") or etype
        if role == "user":
            turn_no += 1
            current = _new_turn(turn_no)
            turns.append(current)
        if current is None:
            current = _new_turn(0)
            turns.append(current)
        usage = message.get("usage")
        if isinstance(usage, dict):
            # bool is a subclass of int: a JSON true/false in a
            # usage field is not a token count and must not be
            # silently counted as 1/0 reported tokens.
            if type(usage.get("input_tokens")) is int:
                reported_in += usage["input_tokens"]
            if type(usage.get("output_tokens")) is int:
                reported_out += usage["output_tokens"]
        if isinstance(message.get("model"), str):
            models.add(message["model"])
        for block in _content_blocks(message):
            btype = block.get("type")
            if btype == "text" or btype == "tool_result":
                text = _block_text(block)
                if text:
                    text = secrets.sanitize(text)
                    current["texts"].append({
                        "role": role, "kind": btype, "text": text,
                        "estimated_tokens": estimate_tokens(text, "markdown"),
                    })
                    if role == "user" and btype == "text":
                        current["instruction_blocks"].append(text)
            elif btype == "tool_use":
                name = str(block.get("name") or "")
                paths = [secrets.sanitize(p) for p in _tool_file_paths(block)]
                current["tool_uses"].append(
                    {"name": name, "file_paths": paths})
                for p in paths:
                    current["file_inputs"].append(
                        {"path": p, "tool": name, "turn": current["turn"]})

    all_file_inputs: list[dict] = []
    for t in turns:
        all_file_inputs.extend(t["file_inputs"])
    canonical = {
        "format": CANONICAL_FORMAT,
        "tool": "ghostreplay",
        "session_id": session_id,
        "source_transcript": str(path),
        "transcript_sha256": hashlib.sha256(
            raw.encode("utf-8")).hexdigest(),
        "cwd": cwd,
        "started_at": first_ts,
        "ended_at": last_ts,
        "entry_count": len(entries),
        "turn_count": turn_no,
        "models": sorted(models),
        "reported_input_tokens": reported_in,
        "reported_output_tokens": reported_out,
        "secret_findings": findings,
        "turns": turns,
        "file_inputs": all_file_inputs,
    }
    return canonical


def load_session(path: str | Path) -> dict:
    """Load a session for analysis.

    Accepts either a canonical session file written by ``ingest``
    (format ``ghostreplay-session/1``) or a raw transcript, which
    is parsed on the fly. This is why ``analyse`` and ``propose``
    work with or without a prior ``ingest`` step.
    """
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise TranscriptError(f"{path}: cannot read: {exc}") from exc
    stripped = raw.lstrip()
    if stripped.startswith("{"):
        try:
            doc = json.loads(raw)
        except ValueError:
            doc = None
        if isinstance(doc, dict) and doc.get("format") == CANONICAL_FORMAT:
            _validate_canonical(doc, str(path))
            return doc
    return parse_transcript(path)


def _validate_canonical(doc: dict, source: str) -> None:
    """A file that merely claims the canonical format but lacks the
    fields analysis relies on must fail loudly (TranscriptError),
    not crash later with a bare KeyError/TypeError."""
    if not isinstance(doc.get("session_id"), str) or not doc["session_id"]:
        raise TranscriptError(
            f"{source}: canonical session has no string 'session_id'")
    turns = doc.get("turns")
    if not isinstance(turns, list):
        raise TranscriptError(
            f"{source}: canonical session 'turns' must be a list")
    for i, turn in enumerate(turns):
        if not isinstance(turn, dict) or type(turn.get("turn")) is not int:
            raise TranscriptError(
                f"{source}: canonical session turns[{i}] must be an "
                "object with an integer 'turn'")
        for key in ("texts", "tool_uses", "file_inputs",
                    "instruction_blocks"):
            if key in turn and not isinstance(turn[key], list):
                raise TranscriptError(
                    f"{source}: canonical session turns[{i}].{key} "
                    "must be a list")


def dump_canonical(session: dict) -> str:
    """Deterministic serialisation (sorted keys): the same
    transcript always ingests to identical bytes."""
    return json.dumps(session, indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"
