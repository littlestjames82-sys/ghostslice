"""Corpus format + loader.

A corpus is a single JSON file:

{
  "name": "my-corpus",
  "version": "1",                    // or "corpus_version"
  "projects": [
    {
      "id": "adversarial",
      "path": "projects/adversarial",   // relative to the corpus file
      "commit": "abc123...",            // optional, recorded not fetched
      "tree_hash": "sha256:...",        // optional; computed if absent
      "tasks": [
        {
          "id": "fix-swap",
          "prompt": "Fix Pair.swap",
          "expected_files": ["src/pair.py"],
          "expected_symbols": ["Pair.swap"],        // optional
          "recorded_patch": "patches/fix-swap.diff", // path or null
          "patch_text": "...",                       // inline alternative
          "test_command": "python3 -m pytest -q",    // str or list, opt.
          "budget_tokens": 20000,                    // fit budget, opt.
          "verify_report": "verify/fix-swap.json",   // optional
          "variants": {                              // optional bundles
            "sliced": {"bundle_dir": "bundles/fix-swap"},
            "verified": {"manifest": "bundles/fix-swap-v/manifest.json",
                          "tokens": 1234}
          }
        }
      ]
    }
  ]
}

Bench records repo state by commit hash or tree hash; it never
copies project code into Bench's own tree (PLAN.md, corpus format).
Paths inside a corpus resolve relative to the corpus file.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field

SKIP_DIRS = {".git", "__pycache__", "node_modules", "dist", ".venv", "venv"}


class CorpusError(ValueError):
    """Raised when a corpus file is missing, malformed, or inconsistent.

    The CLI prints this as ``error: ...`` and exits 2.
    """


@dataclass
class Task:
    """One bench task inside a project (see the module docstring)."""

    id: str
    prompt: str = ""
    expected_files: list = field(default_factory=list)
    expected_symbols: list = field(default_factory=list)
    recorded_patch: str | None = None
    patch_text: str | None = None
    test_command: object = None
    budget_tokens: int | None = None
    verify_report: str | None = None
    variants: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


@dataclass
class Project:
    """A recorded project: an id, an absolute path, and its tasks."""

    id: str
    path: str  # absolute
    commit: str | None = None
    tree_hash: str | None = None
    tasks: list = field(default_factory=list)


@dataclass
class Corpus:
    """A loaded corpus file: metadata plus its projects, in file order."""

    name: str
    version: str
    path: str  # corpus file (absolute)
    base_dir: str
    projects: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    def all_tasks(self):
        """Yield ``(project, task)`` pairs for every task in the corpus."""
        for project in self.projects:
            for task in project.tasks:
                yield project, task


def _resolve(base_dir: str, value: str) -> str:
    if os.path.isabs(value):
        return value
    return os.path.normpath(os.path.join(base_dir, value))


def compute_tree_hash(root: str) -> str:
    """Deterministic sha256 over (relpath, content-hash) pairs."""
    h = hashlib.sha256()
    entries = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            try:
                with open(full, "rb") as fh:
                    digest = hashlib.sha256(fh.read()).hexdigest()
            except OSError:
                continue
            entries.append((rel, digest))
    for rel, digest in sorted(entries):
        h.update(rel.encode("utf-8", "replace"))
        h.update(b"\0")
        h.update(digest.encode())
        h.update(b"\n")
    return "sha256:" + h.hexdigest()


def list_project_files(root: str) -> list[str]:
    """Return sorted project-relative file paths under ``root``.

    Skips the directories in ``SKIP_DIRS`` (for example ``.git`` and
    ``__pycache__``).
    """
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            out.append(os.path.relpath(os.path.join(dirpath, name), root))
    return sorted(out)


def _str_list(task_id: str, field_name: str, value) -> list:
    """expected_files / expected_symbols must be a list of strings.
    list('a.py') would silently split a bare string into characters
    and score against nonsense paths, so reject non-lists outright."""
    if value is None:
        return []
    if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value):
        raise CorpusError(
            f"task {task_id}: '{field_name}' must be a list of strings")
    return list(value)


def load_corpus(path: str) -> Corpus:
    """Load and validate a corpus JSON file.

    Resolves project paths relative to the corpus file, stamps a
    ``tree_hash`` for any project that does not carry one, and raises
    :class:`CorpusError` for a missing file, invalid JSON, duplicate
    project or task ids, a missing project directory, or a
    non-positive ``budget_tokens``.
    """
    apath = os.path.abspath(path)
    if not os.path.isfile(apath):
        raise CorpusError(f"corpus file not found: {path}")
    try:
        with open(apath, encoding="utf-8") as fh:
            raw = json.load(fh)
    except json.JSONDecodeError as exc:
        raise CorpusError(f"corpus is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise CorpusError("corpus root must be a JSON object")
    name = raw.get("name")
    if not name or not isinstance(name, str):
        raise CorpusError("corpus requires a string 'name'")
    version = raw.get("version", raw.get("corpus_version"))
    if version is None:
        raise CorpusError("corpus requires 'version' (or 'corpus_version')")
    base = os.path.dirname(apath)
    projects_raw = raw.get("projects")
    if not isinstance(projects_raw, list) or not projects_raw:
        raise CorpusError("corpus requires a non-empty 'projects' list")
    projects = []
    seen_projects = set()
    for praw in projects_raw:
        if not isinstance(praw, dict) or not praw.get("id"):
            raise CorpusError("each project requires an 'id'")
        pid = praw["id"]
        if not isinstance(pid, str):
            raise CorpusError("each project 'id' must be a string")
        if pid in seen_projects:
            raise CorpusError(f"duplicate project id: {pid}")
        seen_projects.add(pid)
        ppath_raw = praw.get("path")
        if not ppath_raw or not isinstance(ppath_raw, str):
            raise CorpusError(f"project {pid}: requires 'path'")
        ppath = _resolve(base, ppath_raw)
        if not os.path.isdir(ppath):
            raise CorpusError(f"project {pid}: path is not a directory: {ppath_raw}")
        tasks_raw = praw.get("tasks") or []
        if not isinstance(tasks_raw, list):
            raise CorpusError(f"project {pid}: 'tasks' must be a list")
        tasks = []
        seen_tasks = set()
        for traw in tasks_raw:
            if not isinstance(traw, dict) or not traw.get("id"):
                raise CorpusError(f"project {pid}: each task requires an 'id'")
            tid = traw["id"]
            if not isinstance(tid, str):
                raise CorpusError(f"project {pid}: each task 'id' must be a string")
            if tid in seen_tasks:
                raise CorpusError(f"project {pid}: duplicate task id: {tid}")
            seen_tasks.add(tid)
            budget = traw.get("budget_tokens")
            if budget is not None and (not isinstance(budget, int)
                                       or isinstance(budget, bool)
                                       or budget <= 0):
                raise CorpusError(f"task {tid}: budget_tokens must be a positive int")
            prompt = traw.get("prompt", "")
            if not isinstance(prompt, str):
                raise CorpusError(f"task {tid}: 'prompt' must be a string")
            for opt in ("recorded_patch", "patch_text", "verify_report"):
                if traw.get(opt) is not None and not isinstance(traw.get(opt), str):
                    raise CorpusError(f"task {tid}: '{opt}' must be a string")
            test_command = traw.get("test_command")
            if test_command is not None and not (
                    isinstance(test_command, str)
                    or (isinstance(test_command, list) and all(
                        isinstance(part, str) for part in test_command))):
                raise CorpusError(
                    f"task {tid}: 'test_command' must be a string "
                    "or a list of strings")
            variants = traw.get("variants") or {}
            if not isinstance(variants, dict) or not all(
                    isinstance(spec, dict) for spec in variants.values()):
                raise CorpusError(
                    f"task {tid}: 'variants' must be an object mapping "
                    "variant names to bundle spec objects")
            tasks.append(Task(
                id=tid,
                prompt=prompt,
                expected_files=_str_list(tid, "expected_files",
                                         traw.get("expected_files")),
                expected_symbols=_str_list(tid, "expected_symbols",
                                           traw.get("expected_symbols")),
                recorded_patch=traw.get("recorded_patch"),
                patch_text=traw.get("patch_text"),
                test_command=test_command,
                budget_tokens=budget,
                verify_report=traw.get("verify_report"),
                variants=dict(variants),
                raw=traw,
            ))
        projects.append(Project(
            id=pid, path=ppath,
            commit=praw.get("commit"),
            tree_hash=praw.get("tree_hash") or compute_tree_hash(ppath),
            tasks=tasks,
        ))
    return Corpus(name=name, version=str(version), path=apath,
                  base_dir=base, projects=projects, raw=raw)


def read_task_patch(corpus: Corpus, project: Project, task: Task) -> str | None:
    """Return a task's recorded patch text, or ``None`` if it has none.

    Inline ``patch_text`` wins; otherwise ``recorded_patch`` is read
    from disk, resolved relative to the corpus file first and then
    relative to the project directory. Raises :class:`CorpusError`
    when a named patch file cannot be found.
    """
    if task.patch_text:
        return task.patch_text
    if not task.recorded_patch:
        return None
    p = _resolve(corpus.base_dir, task.recorded_patch)
    if not os.path.isfile(p):
        # Also try relative to the project dir.
        alt = os.path.join(project.path, task.recorded_patch)
        if os.path.isfile(alt):
            p = alt
        else:
            raise CorpusError(
                f"task {task.id}: recorded_patch not found: {task.recorded_patch}")
    with open(p, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def read_verify_report(corpus: Corpus, project: Project, task: Task):
    """Return ``(report_dict, sha256_hex)`` for a task's Verify report.

    Returns ``(None, None)`` when the task names no report. The hash
    is over the canonical (sorted-keys) JSON, for report traceability.
    Resolution matches :func:`read_task_patch`.
    """
    if not task.verify_report:
        return None, None
    p = _resolve(corpus.base_dir, task.verify_report)
    if not os.path.isfile(p):
        alt = os.path.join(project.path, task.verify_report)
        if os.path.isfile(alt):
            p = alt
        else:
            raise CorpusError(
                f"task {task.id}: verify_report not found: {task.verify_report}")
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusError(
            f"task {task.id}: verify_report is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CorpusError(
            f"task {task.id}: verify_report must be a JSON object")
    return data, hashlib.sha256(json.dumps(
        data, sort_keys=True).encode()).hexdigest()
