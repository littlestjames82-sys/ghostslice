"""Context transformation for Anthropic Messages-shaped requests.

ONLY recognisable project-file context blocks are transformed. The
user's own prompt text, system instructions, images, tool calls/results,
and every unknown field pass untouched (plan MVP rule 2). A context
block is recognisable when a text part carries an explicit file header:

    --- FILE: path/to/file.py ---
    <file content>

or a first line of the form ``# File: path/to/file.py`` (also ``// File:``
and ``<!-- File:``). Text without such a header is not treated as a file
and is never rewritten.

Per block, in order (plan order):
1. exclude junk / lockfiles / vendored & generated paths;
2. exclude blocks whose content trips the secret guard (path+type logged,
   value never recorded);
3. drop duplicates of an earlier kept block: exact duplicates (raw
   content, or GhostSlice's normalized content -- trailing whitespace
   and trailing blank lines ignored) and near duplicates (GhostSlice's
   line-shingle Jaccard similarity >= 0.85, above its 200-character /
   8-line size floors; see slice_adapter.duplicate_fingerprint);
4. if the kept context still exceeds the per-request budget, downgrade
   the largest blocks full -> signatures -> interfaces -> exclude via
   GhostSlice. If GhostSlice is unavailable, no downgrade happens and the
   result is marked fallback (pass-through), never a home-grown rewrite.

The return value always carries a transform map containing paths, modes,
token estimates, and reasons only -- no file content, no secrets, ever.
"""
from __future__ import annotations

import copy
import hashlib
import posixpath
import re
from dataclasses import dataclass, field

from . import slice_adapter
from .tokens import estimate_tokens

JUNK_BASENAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "cargo.lock", "gemfile.lock", "composer.lock", "pipfile.lock",
}
JUNK_PATH_PARTS = {"node_modules", "dist", "build", ".git", "__pycache__",
                   "vendor", ".next", "target"}

_HEADER_DASH = re.compile(r"^---\s*FILE:\s*(?P<path>\S+)\s*---\s*\n", re.IGNORECASE)
# GhostSlice PROMPT.md shape: "# File: <path> (mode: <mode>)" then a blank
# line then the content. The "(mode: ...)" annotation is optional.
_HEADER_HASH = re.compile(
    r"^(?:#|//|<!--)\s*File:\s*(?P<path>\S+?)"
    r"(?:\s*\(mode:\s*(?P<mode>[A-Za-z\-]+)\))?\s*(?:-->)?\s*\n",
    re.IGNORECASE)

_LADDER = ("full", "signatures", "interfaces", "exclude")
# Every mode a block action can carry: the budget ladder plus
# GhostSlice's test-stripping default mode. Pass 3 reports mode_after
# from the action, so an action missing here was misreported as the
# block's original mode (a stripped test file claimed "full").
_KNOWN_MODES = frozenset(_LADDER) | {"strip-tests"}
_CODE_LANGUAGES = {
    "python", "notebook", "typescript", "javascript", "go", "rust",
    "java", "csharp", "php", "ruby", "kotlin", "swift", "c", "cpp", "scala",
}


def _is_test_path(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    base = parts[-1]
    return ("tests" in parts or "test" in parts
            or base.startswith("test_") or base.endswith("_test.py")
            or ".test." in base or ".spec." in base)


def _default_mode(path: str) -> str:
    """GhostSlice export's default mode for a file (code -> signatures,
    test files -> strip-tests, everything else -> full)."""
    if _is_test_path(path):
        return "strip-tests"
    if slice_adapter.language_for(path) in _CODE_LANGUAGES:
        return "signatures"
    return "full"


@dataclass
class BlockResult:
    path: str
    action: str            # full|signatures|interfaces|dropped
    reason: str            # budget|duplicate|secret-guard|junk|lockfile|...
    tokens_in: int
    tokens_out: int
    secret_types: list = field(default_factory=list)  # types only, never values
    mode_before: str = "full"
    mode_after: str = "full"
    duplicate_of: str = ""     # keeper path for duplicate / near-duplicate drops
    similarity: float | None = None  # line-shingle Jaccard for near drops

    def to_dict(self):
        return {"path": self.path, "action": self.action, "reason": self.reason,
                "tokens_in": self.tokens_in, "tokens_out": self.tokens_out,
                "secret_types": list(self.secret_types),
                "mode_before": self.mode_before, "mode_after": self.mode_after,
                "duplicate_of": self.duplicate_of,
                "similarity": self.similarity}


@dataclass
class TransformResult:
    request: dict                       # transformed copy (input never mutated)
    transform_map: list                 # list[BlockResult.to_dict()]
    tokens_in: int                      # whole request, estimated
    tokens_out: int
    context_tokens_in: int              # recognisable context blocks only
    context_tokens_out: int
    files_seen: list = field(default_factory=list)
    files_sliced: list = field(default_factory=list)
    files_dropped: list = field(default_factory=list)
    fallback: bool = False
    fallback_reason: str = ""

    def to_dict(self):
        return {
            "transform_map": self.transform_map,
            "tokens_in": self.tokens_in, "tokens_out": self.tokens_out,
            "context_tokens_in": self.context_tokens_in,
            "context_tokens_out": self.context_tokens_out,
            "files_seen": self.files_seen, "files_sliced": self.files_sliced,
            "files_dropped": self.files_dropped,
            "fallback": self.fallback, "fallback_reason": self.fallback_reason,
        }


def _split_header(text: str):
    """Return (path, header, body, mode_before) for a file block, or None."""
    for pat in (_HEADER_DASH, _HEADER_HASH):
        m = pat.match(text)
        if m:
            mode = m.groupdict().get("mode") if hasattr(m, "groupdict") else None
            return (m.group("path").strip(), text[:m.end()],
                    text[m.end():], mode or "full")
    return None


def _is_junk(path: str) -> str:
    base = posixpath.basename(path)
    if base in JUNK_BASENAMES:
        return "lockfile"
    parts = set(posixpath.normpath(path).split("/"))
    if parts & JUNK_PATH_PARTS:
        return "junk-path"
    return ""


def _placeholder(path: str, reason: str) -> str:
    return f"[ghostproxy: {path} excluded ({reason})]"


def transform_request(request: dict, budget_tokens: int = 60_000) -> TransformResult:
    """Transform an Anthropic Messages request dict. Never raises for
    shape problems: unrecognised shapes come back unchanged. Callers who
    need fail-open semantics should still wrap this (the server does)."""
    if not isinstance(request, dict):
        # A JSON array/string/number is a valid JSON body but not a
        # Messages request: pass it through untouched, marked fallback,
        # exactly as the server's own not-an-object guard does. (This
        # previously raised AttributeError on request.get, breaking the
        # "never raises for shape problems" promise for direct callers
        # such as the transform CLI command.)
        return TransformResult(
            request=copy.deepcopy(request), transform_map=[],
            tokens_in=0, tokens_out=0,
            context_tokens_in=0, context_tokens_out=0,
            fallback=True, fallback_reason="request-not-an-object")
    original_text_total = estimate_tokens(_request_text(request))
    result = TransformResult(
        request=copy.deepcopy(request), transform_map=[],
        tokens_in=original_text_total, tokens_out=original_text_total,
        context_tokens_in=0, context_tokens_out=0)

    messages = result.request.get("messages")
    if not isinstance(messages, list):
        return result

    # Pass 1: locate every recognisable text part.
    # locations: (message_idx, part_kind, part_idx) where part_kind is
    # "text-str" (content is a str) or "text-part" (content list part).
    blocks = []  # dicts describing each block, in order
    for mi, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            hit = _split_header(content)
            if hit:
                blocks.append({"mi": mi, "kind": "str", "idx": None,
                               "path": hit[0], "header": hit[1], "body": hit[2],
                               "mode_before": hit[3]})
        elif isinstance(content, list):
            for pi, part in enumerate(content):
                if (isinstance(part, dict) and part.get("type") == "text"
                        and isinstance(part.get("text"), str)):
                    hit = _split_header(part["text"])
                    if hit:
                        blocks.append({"mi": mi, "kind": "part", "idx": pi,
                                       "path": hit[0], "header": hit[1],
                                       "body": hit[2], "mode_before": hit[3]})
    if not blocks:
        return result

    seen_hashes: dict[str, str] = {}
    seen_normalized: dict[str, str] = {}
    kept_fingerprints: list = []  # (path, fingerprint) of kept blocks, in order
    slicer_ok = slice_adapter.available()
    kept = []
    for b in blocks:
        path, body = b["path"], b["body"]
        result.files_seen.append(path)
        tin = estimate_tokens(body, slice_adapter.language_for(path))
        b["tokens_in"] = tin
        result.context_tokens_in += tin
        junk = _is_junk(path)
        if junk:
            b.update(action="dropped", reason=junk, new_body=None, tokens_out=0)
            result.files_dropped.append(path)
            continue
        findings = slice_adapter.scan_secrets(path, body)
        if findings:
            b.update(action="dropped", reason="secret-guard", new_body=None,
                     tokens_out=0,
                     secret_types=sorted({f["type"] for f in findings}))
            result.files_dropped.append(path)
            continue
        digest = hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()
        fingerprint = slice_adapter.duplicate_fingerprint(body)
        norm_digest = fingerprint["normalized_digest"]
        exact_keeper = None
        if digest in seen_hashes:
            exact_keeper = seen_hashes[digest]
        elif norm_digest is not None and norm_digest in seen_normalized:
            exact_keeper = seen_normalized[norm_digest]
        if exact_keeper is not None:
            b.update(action="dropped", reason="duplicate", new_body=None,
                     tokens_out=0, duplicate_of=exact_keeper, similarity=1.0)
            result.files_dropped.append(path)
            continue
        # Near duplicates (GhostSlice line-shingle Jaccard): only an
        # earlier KEPT block can be the keeper -- a block dropped as
        # junk or by the secrets guard never causes a later, clean
        # block to be dropped as its "duplicate".
        near_keeper, near_sim = None, 0.0
        if fingerprint["near_eligible"]:
            threshold = slice_adapter.near_threshold()
            for kept_path, kept_fp in kept_fingerprints:
                if not kept_fp["near_eligible"]:
                    continue
                sim = slice_adapter.near_similarity(fingerprint, kept_fp)
                if sim > near_sim:
                    near_keeper, near_sim = kept_path, sim
            if near_sim < threshold:
                near_keeper = None
        if near_keeper is not None:
            b.update(action="dropped", reason="near-duplicate",
                     new_body=None, tokens_out=0,
                     duplicate_of=near_keeper,
                     similarity=round(near_sim, 4))
            result.files_dropped.append(path)
            continue
        seen_hashes[digest] = path
        if norm_digest is not None:
            seen_normalized[norm_digest] = path
        kept_fingerprints.append((path, fingerprint))
        b.update(action="full", reason="within-budget", new_body=body,
                 tokens_out=tin)
        kept.append(b)

    # Pass 2a: GhostSlice default modes (what a manual GhostSlice export
    # would do to the same files): code -> signatures, tests -> strip.
    # This is the base transform; the budget ladder below goes further.
    if slicer_ok:
        for b in kept:
            mode = _default_mode(b["path"])
            if mode == "full":
                continue
            sliced = slice_adapter.slice_text(b["path"], b["body"], mode)
            if sliced is None:
                result.fallback = True
                result.fallback_reason = "slicer-failed"
                continue
            tout = estimate_tokens(sliced, slice_adapter.language_for(b["path"]))
            if tout < b["tokens_out"]:
                b.update(action=mode, reason="ghostslice-default-mode",
                         new_body=sliced, tokens_out=tout)
                if b["path"] not in result.files_sliced:
                    result.files_sliced.append(b["path"])
    elif any(_default_mode(b["path"]) != "full" for b in kept):
        result.fallback = True
        result.fallback_reason = "ghostslice-unavailable"

    # Pass 2b: budget downgrade, largest kept blocks first.
    kept_total = sum(b["tokens_out"] for b in kept)
    if kept_total > budget_tokens:
        if not slicer_ok:
            result.fallback = True
            result.fallback_reason = "ghostslice-unavailable-for-budget-downgrade"
        else:
            for b in sorted(kept, key=lambda x: -x["tokens_out"]):
                if kept_total <= budget_tokens:
                    break
                cur = b["action"] if b["action"] in _LADDER else "signatures"
                for mode in _LADDER[_LADDER.index(cur) + 1:]:
                    sliced = slice_adapter.slice_text(b["path"], b["body"], mode)
                    if sliced is None:
                        result.fallback = True
                        result.fallback_reason = "slicer-failed"
                        break
                    tout = estimate_tokens(
                        sliced, slice_adapter.language_for(b["path"]))
                    if tout < b["tokens_out"]:
                        kept_total -= b["tokens_out"] - tout
                        b.update(action=mode, reason="budget",
                                 new_body=(None if mode == "exclude" else sliced),
                                 tokens_out=(0 if mode == "exclude" else tout))
                        if mode == "exclude":
                            if b["path"] not in result.files_dropped:
                                result.files_dropped.append(b["path"])
                            if b["path"] in result.files_sliced:
                                result.files_sliced.remove(b["path"])
                        elif b["path"] not in result.files_sliced:
                            result.files_sliced.append(b["path"])
                    if kept_total <= budget_tokens or mode == "exclude":
                        break

    # Pass 3: write back.
    for b in blocks:
        mode_after = b["action"] if b["action"] in _KNOWN_MODES else (
            "exclude" if b["action"] == "dropped" else b.get("mode_before", "full"))
        header = b["header"]
        if b["new_body"] is not None and "(mode:" in header:
            header = re.sub(r"\(mode:\s*[A-Za-z\-]+\)",
                            f"(mode: {mode_after})", header, count=1)
        new_text = (header + b["new_body"]) if b["new_body"] is not None \
            else _placeholder(b["path"], b["reason"])
        msg = result.request["messages"][b["mi"]]
        if b["kind"] == "str":
            msg["content"] = new_text
        else:
            msg["content"][b["idx"]]["text"] = new_text
        result.context_tokens_out += b["tokens_out"]
        result.transform_map.append(BlockResult(
            path=b["path"], action=b["action"], reason=b["reason"],
            tokens_in=b["tokens_in"], tokens_out=b["tokens_out"],
            secret_types=b.get("secret_types", []),
            mode_before=b.get("mode_before", "full"),
            mode_after=mode_after,
            duplicate_of=b.get("duplicate_of", ""),
            similarity=b.get("similarity")).to_dict())

    result.tokens_out = estimate_tokens(_request_text(result.request))
    return result


def _request_text(request: dict) -> str:
    """All human text in a request, for whole-request token estimates."""
    if not isinstance(request, dict):
        return ""
    out = []
    def walk(obj):
        if isinstance(obj, str):
            out.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
    walk(request.get("messages"))
    walk(request.get("system"))
    return "\n".join(out)
