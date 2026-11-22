"""Shared helpers for the GhostApprove behavioural tests.

CONTRACT (aligned to Agent A's landed PLAN.md + cli.py, read-only).
GhostApprove v0.1 is a local approval queue only:

    ghostapprove [--store <dir>] ingest  <request.json>
    ghostapprove [--store <dir>] list    [--status pending] [--source X] [--json]
    ghostapprove [--store <dir>] show    <id> [--json]
    ghostapprove [--store <dir>] approve <id> --hash <sha256> [--by NAME] [--note TEXT]
    ghostapprove [--store <dir>] deny    <id> --hash <sha256> [--by NAME] [--note TEXT]
    ghostapprove [--store <dir>] history [--id ID] [--json]

Store layout: <store>/requests/<id>.json + <store>/ledger.jsonl
(append-only). Default store: $GHOSTAPPROVE_DIR or ./.ghostapprove.
Request shape: source, action (required), summary (required;
title/description are producer fallbacks), risk (low|medium|high|
critical, default medium), optional diff, payload, requested_by, id.
Canonical hash: sha256 over canonical JSON of the normalised content
(sorted keys, compact separators), computed at ingest.

Rules the tests enforce:
  * a freshly ingested request is PENDING (no auto-approval, ever)
  * approve/deny require the exact hash shown for the request;
    a mismatched or tampered hash refuses and records no decision
  * a decided request cannot be decided again (double decision refuses)
  * history is append-only: earlier records never change
  * approving NEVER executes the action (queue only in v0.1)

Entrypoint discovery, in order:
  1. a ``ghostapprove`` console script on PATH
  2. ``python -m ghostapprove`` with ``src/`` on PYTHONPATH
  3. ``python -m ghostapprove`` as an installed package

If no entrypoint exists the behavioural tests FAIL with a clear
"core not ready" message - they do not skip, so a green run can never
be faked by a missing build. Fixture-sanity tests in
``test_fixtures_sanity.py`` do not need the core and pass on their own.

Verb/flag fallbacks (add/submit for ingest, reject for deny,
queue-via-env) exist so the suite stays robust to small CLI spelling
differences; every fallback is listed in REPORT_B.md. The primary
forms below are exactly Agent A's landed CLI.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
EXAMPLES = REPO / "examples"
HEX64 = re.compile(r"\b[0-9a-fA-F]{64}\b")


def find_entrypoint():
    script = shutil.which("ghostapprove")
    if script:
        return [script]
    src = REPO / "src"
    if (src / "ghostapprove" / "__main__.py").exists() or (
        src / "ghostapprove" / "__init__.py"
    ).exists():
        return [sys.executable, "-m", "ghostapprove"]
    try:
        import ghostapprove  # noqa: F401

        return [sys.executable, "-m", "ghostapprove"]
    except Exception:
        return None


ENTRYPOINT = find_entrypoint()


def _base_env(queue):
    env = dict(os.environ)
    src = REPO / "src"
    if src.is_dir():
        env["PYTHONPATH"] = str(src) + os.pathsep + env.get("PYTHONPATH", "")
    env["NO_COLOR"] = "1"
    if queue is not None:
        env["GHOSTAPPROVE_DIR"] = str(queue)
        env["GHOSTAPPROVE_QUEUE"] = str(queue)
        env["GHOSTAPPROVE_HOME"] = str(queue)
        env["GHOSTAPPROVE_DB"] = str(Path(queue) / "queue.json")
    return env


def _run_raw(argv, queue):
    return subprocess.run(
        ENTRYPOINT + [str(a) for a in argv],
        capture_output=True,
        text=True,
        timeout=120,
        env=_base_env(queue),
    )


def run_ga(queue, args):
    """Run ghostapprove against ``queue`` (a store directory Path).

    Tries, in order: global ``--store <dir>`` before the verb (Agent
    A's landed form), the verb with ``--store <dir>`` appended, no
    store flag at all (store passed only via GHOSTAPPROVE_DIR env),
    then legacy ``--queue`` spellings. The first form that does not die
    on an argparse flag complaint wins.
    """
    if ENTRYPOINT is None:
        pytest.fail(
            "GhostApprove core not ready: no entrypoint found (no "
            "`ghostapprove` script on PATH, no src/ghostapprove package, "
            "package not installed). This test needs Agent A's core - "
            "see REPORT_B.md."
        )
    forms = []
    if queue is not None:
        forms.append(["--store", queue, *args])
        forms.append([*args, "--store", queue])
        forms.append(list(args))
        forms.append(["--queue", queue, *args])
        forms.append([*args, "--queue", queue])
    else:
        forms.append(list(args))
    last = None
    for form in forms:
        proc = _run_raw(form, queue)
        last = proc
        text = out_text(proc).lower()
        if proc.returncode == 0:
            return proc
        if "unrecognized arguments" not in text and "no such option" not in text \
                and "invalid choice" not in text and "unknown command" not in text:
            return proc
    return last


def run_verb(queue, verbs, rest):
    """Run the first verb in ``verbs`` the CLI accepts (not argparse-dead)."""
    last = None
    for verb in verbs:
        proc = run_ga(queue, [verb, *rest])
        last = proc
        text = out_text(proc).lower()
        if "invalid choice" in text or "unknown command" in text or \
                "no such command" in text:
            continue
        return proc
    return last


def out_text(proc):
    return (proc.stdout or "") + "\n" + (proc.stderr or "")


def parse_json_maybe(text):
    """Best-effort JSON extraction: whole text, else last {...} / [...] block."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if 0 <= start < end:
            try:
                return json.loads(text[start:end + 1])
            except Exception:
                continue
    return None


def walk_values(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v
            yield from walk_values(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from walk_values(item)


def find_field(obj, *names):
    """First value whose key contains any of ``names`` (case-insensitive)."""
    if obj is None:
        return None
    for key, value in walk_values(obj):
        low = str(key).lower()
        if any(n in low for n in names) and isinstance(value, (str, int)):
            return value
    return None


def records_matching(obj, req_id):
    """All dict records in a parsed structure that mention ``req_id``."""
    found = []

    def visit(node):
        if isinstance(node, dict):
            if req_id in json.dumps(node):
                found.append(node)
            for v in node.values():
                visit(v)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(obj)
    # Prefer the smallest (most specific) record.
    return sorted(found, key=lambda d: len(json.dumps(d)))


def get_hash(record_or_text, req_id=None):
    """Extract a request's sha256 hash from parsed output or raw text."""
    if isinstance(record_or_text, (dict, list)):
        recs = records_matching(record_or_text, req_id) if req_id else []
        for rec in recs:
            h = find_field(rec, "hash", "sha256", "digest")
            if h and HEX64.search(str(h)):
                return HEX64.search(str(h)).group(0).lower()
        h = find_field(record_or_text, "hash", "sha256", "digest")
        if h and HEX64.search(str(h)):
            return HEX64.search(str(h)).group(0).lower()
        text = json.dumps(record_or_text)
    else:
        text = str(record_or_text or "")
    m = HEX64.search(text)
    return m.group(0).lower() if m else None


def get_status(record_or_text, req_id=None):
    if isinstance(record_or_text, (dict, list)):
        recs = records_matching(record_or_text, req_id) if req_id else []
        for rec in recs:
            s = find_field(rec, "status", "state", "decision")
            if s:
                return str(s).lower()
        s = find_field(record_or_text, "status", "state", "decision")
        if s:
            return str(s).lower()
    return None


# ---------------------------------------------------------------- queue IO

def make_queue(tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir(parents=True, exist_ok=True)
    return queue


def queue_files(queue):
    return [p for p in sorted(Path(queue).rglob("*")) if p.is_file()]


def queue_text(queue):
    parts = []
    for p in queue_files(queue):
        try:
            parts.append(p.read_text(errors="replace"))
        except Exception:
            pass
    return "\n".join(parts)


def snapshot_queue(queue):
    """{relative path: text} for every file under the queue dir."""
    snap = {}
    for p in queue_files(queue):
        try:
            snap[str(p.relative_to(queue))] = p.read_text(errors="replace")
        except Exception:
            pass
    return snap


# ------------------------------------------------------------------- verbs

def ingest(queue, request_path):
    return run_verb(queue, ["ingest", "add", "submit", "new"],
                    [request_path])


def list_requests(queue, status=None):
    extra = ["--json"]
    if status:
        extra += ["--status", status]
    proc = run_verb(queue, ["list", "ls"], extra)
    if proc.returncode != 0:
        proc = run_verb(queue, ["list", "ls"],
                        ["--status", status] if status else [])
    return proc


def show_request(queue, req_id):
    proc = run_verb(queue, ["show", "get", "describe"], [req_id, "--json"])
    if proc.returncode != 0:
        proc = run_verb(queue, ["show", "get", "describe"], [req_id])
    return proc


def decide(queue, verb_family, req_id, hash_value, by="ryan", note=None):
    verbs = {"approve": ["approve"], "deny": ["deny", "reject"]}[verb_family]
    forms = []
    if hash_value is not None:
        forms.append(["--hash", hash_value, "--by", by])
        forms.append(["--hash", hash_value])
        forms.append([hash_value])
    else:
        forms.append(["--by", by])
        forms.append([])
    extra_note = ["--note", note] if note else []
    last = None
    for form in forms:
        proc = run_verb(queue, verbs, [req_id, *form, *extra_note])
        last = proc
        text = out_text(proc).lower()
        if proc.returncode == 0:
            return proc
        if "unrecognized arguments" in text or "no such option" in text:
            continue
        return proc
    return last


def history(queue):
    proc = run_verb(queue, ["history", "log", "audit"], ["--json"])
    if proc.returncode != 0:
        proc = run_verb(queue, ["history", "log", "audit"], [])
    return proc


def history_events(queue):
    """Parsed history events (list of dicts) via `history --json`."""
    proc = history(queue)
    assert proc.returncode == 0, out_text(proc)
    parsed = parse_json_maybe(proc.stdout)
    assert isinstance(parsed, list), (
        f"history --json did not return a list: {proc.stdout[:400]}")
    return parsed


def ledger_text(queue):
    path = Path(queue) / "ledger.jsonl"
    return path.read_text(errors="replace") if path.is_file() else ""


# ---------------------------------------------------------------- fixtures

def load_example(name):
    path = EXAMPLES / name
    return path, json.loads(path.read_text())


def ingest_example(queue, name):
    """Ingest an example file; return (proc, req_id, req_hash)."""
    path, data = load_example(name)
    req_id = data["id"]
    proc = ingest(queue, path)
    assert proc.returncode == 0, (
        f"ingest of {name} failed: {out_text(proc)}")
    req_hash = None
    show = show_request(queue, req_id)
    if show.returncode == 0:
        parsed = parse_json_maybe(show.stdout)
        req_hash = get_hash(parsed if parsed is not None else show.stdout,
                            req_id)
    if not req_hash:
        lst = list_requests(queue)
        parsed = parse_json_maybe(lst.stdout)
        req_hash = get_hash(parsed if parsed is not None else lst.stdout,
                            req_id)
    if not req_hash:
        req_hash = get_hash(queue_text(queue), req_id)
    assert req_hash, (
        f"could not find a sha256 hash for {req_id} in show/list/queue "
        f"output - the queue must display the hash a decision binds to")
    return proc, req_id, req_hash


def status_of(queue, req_id):
    show = show_request(queue, req_id)
    parsed = parse_json_maybe(show.stdout)
    status = get_status(parsed if parsed is not None else show.stdout,
                        req_id)
    if status:
        return status
    text = out_text(show).lower()
    for word in ("pending", "approved", "denied", "rejected"):
        if word in text:
            return word
    return None
