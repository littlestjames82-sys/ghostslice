"""Project-local source walkers.

Hard boundary (PLAN.md): sources live INSIDE the project root the user
pointed at. Muse private memory is never a source: any path resolving
to ~/MEMORY.md, ~/memory/**, or ~/.MEMORY* is excluded, and a project
root that IS one of those locations is refused. Symlinks escaping the
root are never followed. No network, no hosting API; git history comes
from the local `git log` only.
"""
from __future__ import annotations
import re, subprocess
from pathlib import Path

from .model import Item, Provenance
from .secrets import scan_text

IGNORE_DIRS = {".git", "node_modules", "dist", "build", "__pycache__",
               ".ghost_memory", ".claude_context", ".venv", "venv",
               ".ghostslice-cache"}
TEXT_EXTS = {".md", ".txt", ".rst"}
MAX_FILE_BYTES = 2_000_000

def _forbidden_roots() -> list[Path]:
    home = Path.home()
    return [(home / "MEMORY.md").resolve(), (home / "memory").resolve(),
            (home / ".MEMORY.md").resolve()]

def assert_project_root(project) -> Path:
    """Resolve *project* and enforce the project-local boundary.

    Raises ValueError when the path is not a directory, is the user's
    home directory, or is (inside) the assistant's private memory.
    """
    root = Path(project).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"project not a directory: {project}")
    for forb in _forbidden_roots():
        # Refuse a root that IS a forbidden location, sits INSIDE one
        # (forb in root.parents), or CONTAINS one (root in
        # forb.parents): the last case covers the home dir itself,
        # which would sweep private memory in.
        if root == forb or forb in root.parents or root in forb.parents:
            raise ValueError(f"refusing private assistant memory as a project source: {root}")
        if root == Path.home().resolve():
            raise ValueError("refusing home directory as a project source (private memory boundary)")
    return root

def _is_forbidden(path: Path) -> bool:
    try:
        rp = path.resolve()
    except OSError:
        return True
    for forb in _forbidden_roots():
        if rp == forb or forb in rp.parents:
            return True
    return False

def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root)
        return True
    except (ValueError, OSError):
        return False

def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:60] or "item"

_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_FIELD_RE = re.compile(r"^\s*(?:[-*]\s*)?\**([A-Za-z][A-Za-z \-]*)\**\s*:\s*(.+?)\s*$")

_NONE_REFS = {"", "none", "no", "n/a", "na", "null", "nil", "-", "nothing"}

def _clean_ref(value) -> str | None:
    """Normalise a Supersedes / Superseded-by reference.

    'none' (and friends) means NO reference: it must come back as
    None, never as a truthy string, or it will spawn spurious
    supersession links and conflict lines (REPORT_B F1b).
    """
    if value is None:
        return None
    v = str(value).strip().strip('"').strip()
    if v.lower() in _NONE_REFS:
        return None
    return v

def _parse_decision_block(block: str, start_line: int, rel: str, heading: str) -> Item:
    fields: dict[str, str] = {}
    body_lines = []
    for ln in block.splitlines():
        m = _FIELD_RE.match(ln)
        if m and m.group(1).strip().lower() in (
                "date", "decision", "reason", "supersedes", "superseded by",
                "tags", "status", "rule"):
            fields[m.group(1).strip().lower()] = m.group(2).strip()
        else:
            body_lines.append(ln)
    date_m = _DATE_RE.search(heading) or _DATE_RE.search(fields.get("date", "")) or _DATE_RE.search(block)
    title = re.sub(r"^\d{4}-\d{2}-\d{2}\s*[-:]*\s*", "", heading).strip() or heading
    decision = fields.get("decision") or title
    tags = [t.strip().lower() for t in re.split(r"[,;]", fields.get("tags", "")) if t.strip()]
    if fields.get("rule", "").lower() in ("true", "yes", "standing", "pinned"):
        tags.append("rule")
    status = fields.get("status", "active").lower().strip().strip(".;")
    # Anything that is plainly no longer in force must not be served
    # as current: common lifecycle words (and a trailing-punctuation
    # typo like "superseded.") all map to superseded. "current" is
    # the documented synonym for active; unknown words stay active
    # for back-compat rather than silently dropping a live rule.
    if status in ("superseded", "replaced", "archived", "withdrawn",
                  "deprecated", "revoked", "obsolete", "retired", "inactive"):
        status = "superseded"
    elif status not in ("active", "current"):
        status = "active"
    if status == "current":
        status = "active"
    item = Item(
        id="decision-" + _slug(title),
        title=title,
        text=block.strip(),
        source_type="decision",
        provenance=Provenance(path=rel, line=start_line, date=fields.get("date") or (date_m.group(1) if date_m else None)),
        tags=tags,
        status=status,
        supersedes=_clean_ref(fields.get("supersedes")),
    )
    declared_by = _clean_ref(fields.get("superseded by"))
    if declared_by:
        # A record that declares what superseded it IS superseded,
        # even before the link is resolved to a title.
        item.superseded_by = declared_by
        item.status = "superseded"
    item.decision_text = decision  # type: ignore[attr-defined]
    item.reason_text = fields.get("reason", "")  # type: ignore[attr-defined]
    return item

def parse_decisions(text: str, rel: str) -> list[Item]:
    """Parse DECISIONS.md into individual decision records.

    Documented format: one decision per '## ' heading block. Fields are
    'Key: value' lines: Date, Decision, Reason, Supersedes, Tags,
    Status, Rule. Freeform body text is kept as part of the record.
    """
    items: list[Item] = []
    lines = text.splitlines()
    cur_start = None
    cur_heading = ""
    cur: list[str] = []
    def flush():
        if cur_start is not None and cur:
            items.append(_parse_decision_block("\n".join(cur), cur_start, rel, cur_heading))
    for i, ln in enumerate(lines, 1):
        if ln.startswith("## "):
            flush()
            cur_start, cur_heading, cur = i, ln[3:].strip(), [ln]
        elif cur_start is not None:
            cur.append(ln)
    flush()
    if not items:
        # Single-decision file with fields but no ## heading.
        if _FIELD_RE.search(text) and ("decision" in text.lower()):
            items.append(_parse_decision_block(text, 1, rel, rel))
    # Identical headings would produce identical item ids, which
    # breaks id-keyed bookkeeping downstream (selection sets,
    # explain lookups, manifest audits). Disambiguate with the
    # record's start line, which is unique within the file.
    seen_ids: dict[str, int] = {}
    for it in items:
        if it.id in seen_ids:
            seen_ids[it.id] += 1
            suffix = it.provenance.line or seen_ids[it.id]
            it.id = f"{it.id}-{suffix}"
            if seen_ids.get(it.id):
                it.id = f"{it.id}-{seen_ids[it.id]}"
            seen_ids[it.id] = 1
        else:
            seen_ids[it.id] = 1
    # A record with no date still has file+line provenance, which the
    # plan requires; date stays None rather than being invented.
    return items

def _split_sections(text: str) -> list[tuple[str, int, str]]:
    """Split markdown/text into (title, start_line, section_text)."""
    sections: list[tuple[str, int, str]] = []
    lines = text.splitlines()
    cur_title, cur_start, cur = None, 1, []
    for i, ln in enumerate(lines, 1):
        if ln.startswith("#"):
            if cur is not None and cur_title is not None:
                sections.append((cur_title, cur_start, "\n".join(cur)))
            cur_title, cur_start, cur = ln.lstrip("# ").strip() or f"section-{i}", i, [ln]
        else:
            if cur_title is None:
                cur_title, cur_start, cur = "intro", 1, []
            cur.append(ln)
    if cur_title is not None:
        sections.append((cur_title, cur_start, "\n".join(cur)))
    return [(t, s, b) for (t, s, b) in sections if b.strip()]

def _classify(rel_path: Path) -> str:
    name = rel_path.name.upper()
    parts = [p.lower() for p in rel_path.parts]
    if name == "DECISIONS.MD":
        return "decision-file"
    if "audits" in parts or name.endswith("REPORT.MD") or name.startswith("ROADMAP") or name.startswith("BUILD"):
        return "session_note"
    if "docs" in parts or "adr" in parts or name.startswith("ADR"):
        return "doc"
    return "note"

def collect_items(project, include_git: bool = True, git_limit: int = 200) -> list[Item]:
    """Collect every recallable item inside *project*.

    Walks Markdown/text sources (DECISIONS.md parsed into records,
    other files split into sections), skips ignored and oversized
    files, never follows a path outside the root, scans each item
    with the secrets guard, optionally appends local git history,
    and resolves superseded links between decisions before returning.
    """
    root = assert_project_root(project)
    items: list[Item] = []
    for path in sorted(root.rglob("*")):
        try:
            rel_parts = path.relative_to(root).parts
        except ValueError:
            continue
        # Ignore dirs are matched on the PROJECT-RELATIVE path only:
        # matching the absolute path would silently empty any project
        # that happens to live under an ancestor named e.g. "build".
        if any(part in IGNORE_DIRS for part in rel_parts):
            continue
        if not path.is_file() or path.suffix.lower() not in TEXT_EXTS:
            continue
        if not _inside(root, path) or _is_forbidden(path):
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(path.relative_to(root))
        kind = _classify(path.relative_to(root))
        if kind == "decision-file":
            new_items = parse_decisions(text, rel)
        else:
            new_items = []
            for title, start, body in _split_sections(text):
                date_m = _DATE_RE.search(body)
                new_items.append(Item(
                    id=_slug(rel) + "-" + _slug(title) + f"-{start}",
                    title=title, text=body.strip(),
                    source_type=kind if kind in ("doc", "session_note") else "note",
                    provenance=Provenance(path=rel, line=start, date=date_m.group(1) if date_m else None),
                ))
        for it in new_items:
            if not it.provenance.is_valid():
                continue  # anti-hallucination rule: no provenance, no item
            it.secret_findings = [f.to_dict() for f in scan_text(it.text, rel)]
            items.append(it)
    if include_git:
        items.extend(_git_items(root, git_limit))
    _resolve_superseded(items)
    return items

def _git_items(root: Path, limit: int) -> list[Item]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "log", f"-n{int(limit)}",
             "--pretty=format:%H%x1f%aI%x1f%s%x1f%b%x1e"],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    out: list[Item] = []
    for rec in proc.stdout.split("\x1e"):
        rec = rec.strip("\n")
        if not rec.strip():
            continue
        parts = rec.split("\x1f")
        if len(parts) < 3:
            continue
        commit, date, subject = parts[0].strip(), parts[1][:10], parts[2].strip()
        body = parts[3].strip() if len(parts) > 3 else ""
        text = subject + (("\n\n" + body) if body else "")
        it = Item(
            id="commit-" + commit[:10], title=subject or commit[:10], text=text,
            source_type="commit",
            provenance=Provenance(path=f"git:{commit[:10]}", commit=commit, date=date),
        )
        it.secret_findings = [f.to_dict() for f in scan_text(text, f"git:{commit[:10]}")]
        out.append(it)
    return out

_ID_TOKEN_RE = re.compile(r"\b[A-Za-z]{1,10}-\d+\b")

def _ref_keys(decision) -> set[str]:
    """All normalised keys a decision can be referenced by.

    Decisions are cited by short id ('D-010') while their titles and
    item ids carry more ('D-010 (2026-02-01)' / 'decision-d-010-...'),
    so a bare exact-match index never resolves the citation. Register
    the title/id slugs, every id-shaped token inside them, and the
    slug prefixes, so 'D-010' finds the D-010 record.
    """
    keys: set[str] = set()
    for raw in (decision.title, decision.id):
        if not raw:
            continue
        keys.add(str(raw).lower())
        slug = _slug(str(raw))
        keys.add(slug)
        for tok in _ID_TOKEN_RE.findall(str(raw)):
            keys.add(_slug(tok))
        parts = slug.split("-")
        for k in range(2, len(parts) + 1):
            keys.add("-".join(parts[:k]))
    return keys

def _find_ref(by_key: dict, ref: str, self_item=None):
    candidates = [_slug(ref), str(ref).lower()]
    candidates += [_slug(tok) for tok in _ID_TOKEN_RE.findall(str(ref))]
    for cand in candidates:
        hit = by_key.get(cand)
        if hit is not None and hit is not self_item:
            return hit
    return None

def _resolve_superseded(items: list[Item]) -> None:
    decisions = [i for i in items if i.source_type == "decision"]
    by_key = {}
    for d in decisions:
        for key in _ref_keys(d):
            by_key.setdefault(key, d)
    for d in decisions:
        ref = _clean_ref(d.supersedes)
        d.supersedes = ref
        if ref:
            old = _find_ref(by_key, ref, self_item=d)
            if old is not None:
                old.status = "superseded"
                old.superseded_by = d.title
        # Reverse declarations: 'Superseded by: X' marks this record.
        declared_by = _clean_ref(getattr(d, "superseded_by", None))
        if declared_by:
            d.status = "superseded"
            newer = _find_ref(by_key, declared_by, self_item=d)
            d.superseded_by = newer.title if newer is not None else declared_by
