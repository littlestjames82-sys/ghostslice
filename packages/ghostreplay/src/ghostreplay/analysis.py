"""Session analysis: sent vs referenced, re-reads, mode friction,
rule repetition.

Qualifier that PLAN.md makes mandatory: a bundle file with no
reference in the transcript is reported as "not referenced in
transcript", NEVER as "not needed". Transcripts can omit silent
reads and provider-side context. Every surface uses that wording.

Definitions (deterministic, no model):
- referenced(file): the file's bundle-relative path appears as a
  tool_use file input matched to the bundle, OR the path (or its
  basename when unique in the bundle) appears in turn text, OR an
  Edit/Write tool targets it. Turn = the canonical turn it appears
  in; a file can be referenced in many turns.
- re-read(file): named as a tool_use file INPUT (Read, Edit, or
  any other tool carrying a file path) in >= 2 distinct turns.
  Text mentions count as references (they keep a file out of the
  not-referenced list) but NEVER as re-reads: mentioning a path in
  prose does not re-spend the file's context tokens, so charging
  sliced tokens for it would invent waste. Extra reads =
  distinct_input_turns - 1. Re-read cost = extra * the file's
  sliced_tokens (bundle), labelled an estimate.
- turn timeline: one row per turn (direct reads, edits, files
  referenced, and the re-read tokens spent in that turn with a
  running cumulative total). The per-turn re-read tokens always
  sum to the report's total re-read waste: the timeline is an
  accounting view of the same figure, not a second estimate.
- mode friction(file/symbol): a bundle file sent in a non-full
  mode that the session later pulls in directly via a Read
  tool_use (the agent asking for the body it was not given).
  Counted per file; per symbol when the bundle entry carries
  symbols_included and the symbol name is mentioned in turn text
  of the same or a later turn as such a Read.
- rule repetition: user instruction blocks (canonical
  instruction_blocks) compared pairwise by 3-line shingles
  (normalised lines, Jaccard >= 0.85, the GhostSlice duplicate
  method). Blocks in a cluster recurring across turns count once
  per turn; flagged as GhostRecall candidates, never auto-applied.

Provider-reported usage is carried through untouched under
reported_* keys and never mixed with estimates.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from . import secrets
from .bundle import match_path
from .tokens import estimate_tokens, language_for_path

_READ_TOOLS = {"Read", "NotebookRead"}
_EDIT_TOOLS = {"Edit", "Write", "NotebookEdit"}


def _inside_project(project: Path, rel: str) -> Path | None:
    """Resolve a bundle-relative path, refusing absolute paths and
    '..' escapes: a manifest is data, and a crafted entry must not
    make GhostReplay read files outside the project tree."""
    try:
        root = Path(project).resolve()
        fpath = (root / rel).resolve()
        fpath.relative_to(root)
    except (ValueError, OSError):
        return None
    return fpath


def _symbol_outline(project: Path | None, rel: str) -> list[str]:
    """Symbol names for one bundle file: def/class/function names
    from the file on disk, when present. Regex-level on purpose
    (GhostReplay does not re-implement Slice's slicers); used only
    to attribute friction mentions."""
    if project is None:
        return []
    fpath = _inside_project(Path(project), rel)
    if fpath is None:
        return []
    try:
        text = fpath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    names = re.findall(r"(?m)^\s*(?:def|class|function|func)\s+"
                       r"([A-Za-z_][A-Za-z0-9_]*)", text)
    names += re.findall(r"(?m)^\s*(?:const|let|var)\s+"
                        r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:\(|function|async)",
                        text)
    return sorted(set(names))


def shingle_set(text: str, size: int = 3) -> set[str]:
    """Set of normalised ``size``-line shingles, for duplicate detection."""
    lines = [ln.strip().lower() for ln in text.splitlines() if ln.strip()]
    if len(lines) < size:
        return {"\n".join(lines)} if lines else set()
    return {"\n".join(lines[i:i + size]) for i in range(len(lines) - size + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / len(a | b) if inter else 0.0


def repetition_clusters(blocks: list[dict]) -> list[dict]:
    """blocks: {session_id, turn, text}. Returns clusters of
    near-duplicate instruction blocks (Jaccard >= 0.85)."""
    items = []
    for b in blocks:
        # Only substantive instruction blocks count as rule
        # repetition: >= 3 non-empty lines or >= 160 characters.
        # A repeated one-line prompt ("check X again") is not a
        # project rule, and flagging it would pad the findings.
        nonempty = [ln for ln in b["text"].splitlines() if ln.strip()]
        if len(nonempty) < 3 and len(b["text"]) < 160:
            continue
        sh = shingle_set(b["text"])
        if not sh:
            continue
        items.append({**b, "shingles": sh,
                      "fingerprint": hashlib.sha256(
                          b["text"].encode("utf-8")).hexdigest()[:12],
                      "estimated_tokens": estimate_tokens(
                          b["text"], "markdown"),
                      "line_count": len([ln for ln in
                                          b["text"].splitlines()
                                          if ln.strip()])})
    clusters: list[dict] = []
    for item in items:
        placed = False
        for cluster in clusters:
            if _jaccard(item["shingles"], cluster["rep"]["shingles"]) >= 0.85:
                cluster["occurrences"].append(item)
                placed = True
                break
        if not placed:
            clusters.append({"rep": item, "occurrences": [item]})
    out = []
    for cluster in clusters:
        occ = cluster["occurrences"]
        if len(occ) < 2:
            continue
        out.append({
            "fingerprint": cluster["rep"]["fingerprint"],
            "line_count": cluster["rep"]["line_count"],
            "estimated_tokens_each": cluster["rep"]["estimated_tokens"],
            "occurrences": len(occ),
            "sessions": sorted({o["session_id"] for o in occ}),
            "turns": sorted({f"{o['session_id']}:{o['turn']}"
                             for o in occ}),
        })
    out.sort(key=lambda c: (-c["occurrences"], c["fingerprint"]))
    return out


def analyse_session(session: dict, bundle: dict | None,
                    project: str | Path | None = None) -> dict:
    """Analyse one canonical session. Pure: no I/O beyond optional
    symbol outlines from the project tree, no ledger writes, and
    the returned dict is deterministically ordered by the report
    writer (json sort_keys)."""
    project_path = Path(project) if project is not None else (
        Path(bundle["root"]) if bundle and bundle.get("root") else None)
    bundle_files = bundle["by_path"] if bundle else {}
    bundle_paths = sorted(bundle_files)
    basename_owner: dict[str, str] = {}
    ambiguous_basenames: set[str] = set()
    for p in bundle_paths:
        base = p.rsplit("/", 1)[-1]
        if base in basename_owner:
            ambiguous_basenames.add(base)
        basename_owner[base] = p

    ref_turns: dict[str, set[int]] = {p: set() for p in bundle_paths}
    ref_kinds: dict[str, set[str]] = {p: set() for p in bundle_paths}
    direct_reads: dict[str, list[int]] = {p: [] for p in bundle_paths}
    # Distinct turns in which a file was a tool_use file INPUT.
    # This (not ref_turns) is the re-read basis: text mentions are
    # references, but they do not re-spend the file's tokens.
    input_turns: dict[str, set[int]] = {p: set() for p in bundle_paths}
    # Per-turn accounting for the turn timeline.
    timeline_map: dict[int, dict] = {}
    blocks: list[dict] = []
    session_text_tokens = 0

    for turn in session.get("turns", []):
        tno = turn["turn"]
        slot = timeline_map.setdefault(tno, {
            "referenced": set(), "direct_reads": [],
            "edits": [], "tool_inputs": []})
        for block in turn.get("instruction_blocks", []):
            blocks.append({"session_id": session["session_id"],
                           "turn": tno, "text": block})
        for text_rec in turn.get("texts", []):
            session_text_tokens += text_rec.get("estimated_tokens", 0)
            if not bundle:
                continue
            text = text_rec["text"]
            for p in bundle_paths:
                if p in text:
                    ref_turns[p].add(tno)
                    ref_kinds[p].add("text-mention")
                    slot["referenced"].add(p)
                else:
                    base = p.rsplit("/", 1)[-1]
                    if base not in ambiguous_basenames and \
                            re.search(r"(?<![\w/.-])" + re.escape(base) +
                                      r"(?![\w.-])", text):
                        ref_turns[p].add(tno)
                        ref_kinds[p].add("text-mention")
                        slot["referenced"].add(p)
        for tool_use in turn.get("tool_uses", []):
            for cand in tool_use.get("file_paths", []):
                if not bundle:
                    break
                matched = match_path(cand, bundle_paths, project_path)
                if matched is None:
                    continue
                ref_turns[matched].add(tno)
                input_turns[matched].add(tno)
                slot["referenced"].add(matched)
                slot["tool_inputs"].append(matched)
                if tool_use["name"] in _EDIT_TOOLS:
                    ref_kinds[matched].add("edited")
                    slot["edits"].append(matched)
                elif tool_use["name"] in _READ_TOOLS:
                    ref_kinds[matched].add("direct-read")
                    direct_reads[matched].append(tno)
                    slot["direct_reads"].append(matched)
                else:
                    ref_kinds[matched].add("tool-input")

    # Re-reads also count transcript-level file inputs that repeat
    # across turns even without a bundle (cost from disk estimate).
    rereads: list[dict] = []
    unreferenced: list[dict] = []
    friction_files: list[dict] = []
    friction_symbols: list[dict] = []
    referenced_files: list[dict] = []
    total_sent_sliced = 0
    total_unreferenced = 0
    total_reread_cost = 0

    if bundle:
        outlines: dict[str, list[str]] = {}
        turn_texts = {t["turn"]: "\n".join(
            r["text"] for r in t.get("texts", []))
            for t in session.get("turns", [])}
        for p in bundle_paths:
            entry = bundle_files[p]
            sliced = entry["sliced_tokens"]
            total_sent_sliced += sliced
            turns = sorted(ref_turns[p])
            if not turns:
                unreferenced.append({
                    "path": p, "mode": entry["mode"],
                    "sliced_tokens": sliced,
                    "qualifier": "not referenced in transcript "
                                 "(may still have been read silently; "
                                 "transcripts can omit reads)",
                })
                total_unreferenced += sliced
                continue
            referenced_files.append({
                "path": p, "mode": entry["mode"],
                "turns": turns, "kinds": sorted(ref_kinds[p]),
                "sliced_tokens": sliced,
            })
            # Re-reads are charged on tool-input turns only (see
            # module docstring); `turns` above is every reference
            # turn, including text mentions, and stays as evidence.
            iturns = sorted(input_turns[p])
            if len(iturns) >= 2:
                extra = len(iturns) - 1
                cost = extra * sliced
                total_reread_cost += cost
                rereads.append({
                    "path": p, "turns": iturns,
                    "distinct_turns": len(iturns),
                    "extra_reads": extra,
                    "sliced_tokens_each": sliced,
                    "estimated_reread_tokens": cost,
                    "direct_read_turns": sorted(set(direct_reads[p])),
                })
            if entry["mode"] != "full" and direct_reads[p]:
                friction_files.append({
                    "path": p, "mode": entry["mode"],
                    "direct_read_turns": sorted(set(direct_reads[p])),
                    "count": len(set(direct_reads[p])),
                    "sliced_tokens": sliced,
                    "original_tokens": entry["original_tokens"],
                })
                symbols = entry["symbols_included"] or \
                    _symbol_outline(project_path, p)
                outlines[p] = symbols
                for sym in symbols:
                    hit_turns = [t for t in direct_reads[p]
                                 if sym in turn_texts.get(t, "")]
                    if hit_turns:
                        friction_symbols.append({
                            "path": p, "symbol": sym,
                            "mode": entry["mode"],
                            "turns": sorted(set(hit_turns)),
                            "count": len(set(hit_turns)),
                        })
        rereads.sort(key=lambda r: (-r["estimated_reread_tokens"],
                                    r["path"]))
        unreferenced.sort(key=lambda r: (-r["sliced_tokens"], r["path"]))
        friction_files.sort(key=lambda r: (-r["count"], r["path"]))
        friction_symbols.sort(key=lambda r: (-r["count"], r["path"],
                                             r["symbol"]))

    # Turn timeline: a turn spends re-read tokens for each bundle
    # file it names as a tool input that an EARLIER turn already
    # named as a tool input (once per file per turn, however many
    # times the turn repeats it). Summed over all turns this is
    # exactly total_reread_cost above.
    turn_timeline: list[dict] = []
    seen_inputs: set[str] = set()
    cumulative_reread = 0
    for tno in sorted(timeline_map):
        slot = timeline_map[tno]
        inputs_here = sorted(set(slot["tool_inputs"]))
        reread_here = [p for p in inputs_here if p in seen_inputs]
        cost_here = sum(bundle_files[p]["sliced_tokens"]
                        for p in reread_here) if bundle else 0
        cumulative_reread += cost_here
        turn_timeline.append({
            "turn": tno,
            "referenced_files": sorted(slot["referenced"]),
            "direct_read_files": sorted(set(slot["direct_reads"])),
            "edited_files": sorted(set(slot["edits"])),
            "reread_files": reread_here,
            "reread_estimated_tokens": cost_here,
            "cumulative_reread_estimated_tokens": cumulative_reread,
        })
        seen_inputs.update(inputs_here)

    repetitions = repetition_clusters(blocks)
    waste = total_unreferenced + total_reread_cost
    report = {
        "format": "ghostreplay-report/1",
        "tool": "ghostreplay",
        "version": "0.1.0",
        "session_id": session["session_id"],
        "transcript_sha256": session.get("transcript_sha256"),
        "entry_count": session.get("entry_count"),
        "turn_count": session.get("turn_count"),
        "models": session.get("models", []),
        "started_at": session.get("started_at"),
        "ended_at": session.get("ended_at"),
        "token_method": "estimates (BPE-like split v2, per-language "
                        "calibrated, not exact tokenizer counts)",
        "reported_input_tokens": session.get("reported_input_tokens", 0),
        "reported_output_tokens": session.get("reported_output_tokens", 0),
        "reported_note": "provider-reported usage carried from the "
                         "transcript; never blended with estimates",
        "session_text_estimated_tokens": session_text_tokens,
        "bundle": None if not bundle else {
            "manifest_path": bundle["manifest_path"],
            "manifest_sha256": bundle["manifest_sha256"],
            "tool_version": bundle["tool_version"],
            "total_original_tokens": bundle["total_original_tokens"],
            "total_sliced_tokens": bundle["total_sliced_tokens"],
            "file_count": len(bundle_paths),
        },
        "secret_findings": session.get("secret_findings", []),
        "referenced_files": referenced_files,
        "not_referenced_in_transcript": unreferenced,
        # Short alias of the same list for machine consumers; the
        # qualified name above is the canonical one (see module
        # docstring for why the qualifier must not be dropped).
        "not_referenced": unreferenced,
        "rereads": rereads,
        "turn_timeline": turn_timeline,
        "mode_friction": {
            "files": friction_files,
            "symbols": friction_symbols,
        },
        "rule_repetition": repetitions,
        "totals": {
            "sent_sliced_estimated_tokens": total_sent_sliced,
            "not_referenced_estimated_tokens": total_unreferenced,
            "reread_waste_estimated_tokens": total_reread_cost,
            "estimated_waste_tokens": waste,
            "estimated_waste_percent_of_sent": (
                round(100.0 * waste / total_sent_sliced, 1)
                if total_sent_sliced else 0.0),
        },
        "qualifiers": [
            "Token counts are estimates, not exact tokenizer counts.",
            "'Not referenced in transcript' does not mean 'not "
            "needed': transcripts can omit silent reads and "
            "provider-side context. Treat findings as evidence for "
            "a human, not auto-truth.",
            "Estimated waste can exceed 100% of the bundle total: "
            "unreferenced tokens are bounded by the bundle, but "
            "each re-read spends its tokens again on a later turn.",
            "No transcript text is quoted in this report; secret-"
            "shaped strings are redacted and findings are recorded "
            "as source + line + type only.",
            "Re-reads are charged only for turns that name the "
            "file as a tool input; a text mention is a reference, "
            "not a re-read, and is never charged the file's tokens.",
        ],
    }
    return secrets.sanitize_obj(report)


def file_token_estimate(project: str | Path, rel: str) -> int:
    """Estimated tokens for one project file on disk (0 if unreadable)."""
    fpath = _inside_project(Path(project), rel)
    if fpath is None:
        return 0
    try:
        text = fpath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return estimate_tokens(text, language_for_path(rel))
