"""Recipe format, loading, validation, and library discovery.

Canonical form: one JSON object per file, named ``<id>.recipe.json``.
Markdown form: a ``.recipe.md`` file whose recipe is the single fenced
json block it contains, so a recipe can live inside human notes.

Data-only rules enforced here:
- Only .json / .md / .txt recipe files.
- No file with an executable permission bit, no shebang line.
- Unknown keys at any level fail validation by name. That allowlist
  design is what keeps execution-hook fields (an auto-run command, a
  script path, an on-load hook) out of the format entirely.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
from pathlib import Path

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
DATA_SUFFIXES = {".json", ".md", ".txt"}
STEP_KINDS = {"manual", "check", "run", "review", "approve", "note"}

TOP_KEYS = {"id", "name", "version", "description", "steps", "tags",
            "author", "date", "category", "tools", "inputs", "notes",
            "outputs"}
STEP_KEYS = {"id", "title", "kind", "detail", "command_hint", "tools",
             "gate", "repeat"}
INPUT_KEYS = {"name", "description", "required", "default"}
OUTPUT_KEYS = {"name", "description", "required", "from_step"}


class GhostRecipesError(Exception):
    """Usage or config error; the CLI maps this to exit code 2."""


def strict_json_loads(text: str):
    """json.loads with the gaps in Python's default parser closed.

    Python's json accepts three things a versioned data format must
    not: duplicate object keys (the last one silently wins, so two
    readers can disagree about which recipe a file is), and the
    non-JSON constants NaN / Infinity / -Infinity. Both fail here as
    a ValueError, like any other malformed JSON.
    """
    def _no_duplicate_keys(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError(f"duplicate key {key!r}")
            obj[key] = value
        return obj

    def _no_nonstandard_constant(name):
        raise ValueError(f"invalid JSON constant {name!r}")

    return json.loads(text, object_pairs_hook=_no_duplicate_keys,
                      parse_constant=_no_nonstandard_constant)


class Recipe:
    """A parsed recipe: the raw ``data`` dict plus its source ``path``.

    Convenience properties expose ``id``, ``name``, ``version``,
    ``steps``, and ``inputs``; :meth:`file_hash` and
    :meth:`summary_line` are what the CLI prints for identity.
    """

    def __init__(self, data: dict, path: Path | None = None):
        self.data = data
        self.path = path

    @property
    def id(self) -> str:
        return self.data.get("id", "")

    @property
    def name(self) -> str:
        return self.data.get("name", "")

    @property
    def version(self) -> str:
        return self.data.get("version", "")

    @property
    def steps(self) -> list:
        return self.data.get("steps") or []

    @property
    def inputs(self) -> list:
        return self.data.get("inputs") or []

    @property
    def outputs(self) -> list:
        return self.data.get("outputs") or []

    def file_hash(self) -> str | None:
        if self.path is None or not self.path.is_file():
            return None
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def summary_line(self) -> str:
        # Defensive: this line is printed for INVALID recipes too
        # (list, show), where tags may be any JSON value at all.
        # Joining a non-list or non-string tags value used to crash
        # the listing with a TypeError instead of reporting errors.
        raw_tags = self.data.get("tags")
        if isinstance(raw_tags, list):
            tags = ",".join(str(t) for t in raw_tags) or "-"
        else:
            tags = "-"
        steps = self.data.get("steps")
        return (f"{self.id} v{self.version} - {self.name} "
                f"({len(steps) if isinstance(steps, list) else 0} "
                f"steps, tags: {tags})")


def _is_executable(path: Path) -> bool:
    return bool(path.stat().st_mode & 0o111)


def _has_shebang(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(2) == b"#!"
    except OSError:
        return False


def check_data_only_file(path: Path) -> list[str]:
    """Errors for a single file under the data-only rules."""
    errors = []
    path = Path(path)
    if path.suffix.lower() not in DATA_SUFFIXES and not (
            path.name.endswith(".recipe.json")):
        errors.append(f"{path}: suffix {path.suffix!r} is not a data "
                      f"suffix (allowed: .json, .md, .txt)")
    if path.is_file():
        if _is_executable(path):
            errors.append(f"{path}: executable permission bit set; "
                          f"recipes are data only")
        if _has_shebang(path):
            errors.append(f"{path}: shebang line found; recipes are "
                          f"data only")
    return errors


def extract_recipe_data(path: Path) -> dict:
    """Parse a .recipe.json file, a plain .json file, or a .recipe.md
    file (single fenced json block) into the recipe dict."""
    path = Path(path)
    try:
        # utf-8-sig decodes plain UTF-8 identically and strips a
        # byte-order mark, so a recipe saved by a Windows editor is
        # not rejected for an invisible prefix. Every read failure
        # (missing file, directory, unreadable, invalid UTF-8) is a
        # GhostRecipesError, never a raw traceback.
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise GhostRecipesError(
            f"{path}: cannot read recipe file: {exc}") from exc
    if path.suffix.lower() == ".md":
        blocks = re.findall(r"```json\s*\n(.*?)```", text, re.DOTALL)
        if len(blocks) != 1:
            raise GhostRecipesError(
                f"{path}: a Markdown recipe must contain exactly one "
                f"fenced json block, found {len(blocks)}")
        text = blocks[0]
    try:
        data = strict_json_loads(text)
    except (ValueError, RecursionError) as exc:
        # ValueError covers JSONDecodeError plus the strict-loader
        # rejections; RecursionError covers pathologically nested
        # input that exceeds the parser's stack.
        raise GhostRecipesError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise GhostRecipesError(f"{path}: recipe must be a JSON object")
    return data


def load_recipe(path) -> Recipe:
    path = Path(path)
    if not path.is_file():
        raise GhostRecipesError(f"recipe file not found: {path}")
    return Recipe(extract_recipe_data(path), path)


def _check_str_list(value, label, errors):
    if not isinstance(value, list) or not all(
            isinstance(v, str) and v for v in value):
        errors.append(f"{label} must be a list of non-empty strings")


def validate_data(data: dict, source: str = "recipe") -> tuple[list, list]:
    """Return (errors, warnings) for a parsed recipe dict.

    Errors fail validation: unknown keys (named), a bad ``id`` slug,
    a non-semver ``version``, missing required fields, duplicate
    step or input ids, and an unknown step ``kind``. Warnings do not
    fail validation, so drafts still pass: undeclared or unused
    ``{{placeholders}}``, malformed placeholders, and a file name
    that does not match the recipe id.
    """
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, dict):
        return [f"{source}: recipe must be a JSON object"], warnings
    for key in sorted(set(data) - TOP_KEYS):
        errors.append(f"{source}: unknown top-level key {key!r} "
                      f"(allowed: {', '.join(sorted(TOP_KEYS))})")
    rid = data.get("id")
    if not isinstance(rid, str) or not SLUG_RE.match(rid or ""):
        errors.append(f"{source}: id must be a slug matching "
                      f"{SLUG_RE.pattern}, got {rid!r}")
    if not isinstance(data.get("name"), str) or not data.get("name", "").strip():
        errors.append(f"{source}: name is required (non-empty string)")
    version = data.get("version")
    if not isinstance(version, str) or not VERSION_RE.match(version or ""):
        errors.append(f"{source}: version must be MAJOR.MINOR.PATCH, "
                      f"got {version!r}")
    if not isinstance(data.get("description"), str) \
            or not data.get("description", "").strip():
        errors.append(f"{source}: description is required (non-empty string)")
    if "date" in data:
        raw_date = str(data.get("date", ""))
        if not DATE_RE.match(raw_date):
            errors.append(f"{source}: date must be YYYY-MM-DD")
        else:
            try:
                datetime.date(int(raw_date[0:4]), int(raw_date[5:7]),
                              int(raw_date[8:10]))
            except ValueError:
                errors.append(f"{source}: date {raw_date!r} is not a "
                              f"real calendar date")
    if "tags" in data:
        _check_str_list(data["tags"], f"{source}: tags", errors)
    if "tools" in data:
        _check_str_list(data["tools"], f"{source}: tools", errors)
    for opt in ("author", "category", "notes"):
        if opt in data and not isinstance(data[opt], str):
            errors.append(f"{source}: {opt} must be a string")

    inputs = data.get("inputs") or []
    input_names: set[str] = set()
    if not isinstance(inputs, list):
        errors.append(f"{source}: inputs must be a list")
        inputs = []
    for i, item in enumerate(inputs):
        label = f"{source}: inputs[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        for key in sorted(set(item) - INPUT_KEYS):
            errors.append(f"{label}: unknown key {key!r}")
        nm = item.get("name")
        if not isinstance(nm, str) or not re.match(
                r"^[A-Za-z_][A-Za-z0-9_]*$", nm or ""):
            errors.append(f"{label}: name must be an identifier, got {nm!r}")
        elif nm in input_names:
            errors.append(f"{label}: duplicate input name {nm!r}")
        else:
            input_names.add(nm)
        if "required" in item and not isinstance(item["required"], bool):
            errors.append(f"{label}: required must be true or false")
        if "default" in item and not isinstance(item["default"], str):
            errors.append(f"{label}: default must be a string")
        if "description" in item and not isinstance(
                item["description"], str):
            errors.append(f"{label}: description must be a string")

    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append(f"{source}: steps is required (non-empty list)")
        steps = []
    seen_steps: set[str] = set()
    for i, step in enumerate(steps):
        label = f"{source}: steps[{i}]"
        if not isinstance(step, dict):
            errors.append(f"{label} must be an object")
            continue
        for key in sorted(set(step) - STEP_KEYS):
            errors.append(f"{label}: unknown key {key!r}")
        sid = step.get("id")
        if not isinstance(sid, str) or not SLUG_RE.match(sid or ""):
            errors.append(f"{label}: id must be a slug, got {sid!r}")
        elif sid in seen_steps:
            errors.append(f"{label}: duplicate step id {sid!r}")
        else:
            seen_steps.add(sid)
        if not isinstance(step.get("title"), str) \
                or not step.get("title", "").strip():
            errors.append(f"{label}: title is required (non-empty string)")
        if step.get("kind") not in STEP_KINDS:
            errors.append(f"{label}: kind must be one of "
                          f"{', '.join(sorted(STEP_KINDS))}, "
                          f"got {step.get('kind')!r}")
        if "tools" in step:
            _check_str_list(step["tools"], f"{label}: tools", errors)
        for opt in ("detail", "command_hint", "gate", "repeat"):
            if opt in step and not isinstance(step[opt], str):
                errors.append(f"{label}: {opt} must be a string")

    # Declared outputs: what a follower should end up holding.
    # An output is a named expectation only. Declaring one never
    # creates it, and no output field can name anything to run:
    # unknown keys fail by name, like everywhere else in the format.
    outputs = data.get("outputs", [])
    if not isinstance(outputs, list):
        errors.append(f"{source}: outputs must be a list")
        outputs = []
    output_names: set[str] = set()
    for i, item in enumerate(outputs):
        label = f"{source}: outputs[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        for key in sorted(set(item) - OUTPUT_KEYS):
            errors.append(f"{label}: unknown key {key!r}")
        nm = item.get("name")
        if not isinstance(nm, str) or not SLUG_RE.match(nm or ""):
            errors.append(f"{label}: name must be a slug, got {nm!r}")
        elif nm in output_names:
            errors.append(f"{label}: duplicate output name {nm!r}")
        else:
            output_names.add(nm)
        if "description" in item and not isinstance(item["description"], str):
            errors.append(f"{label}: description must be a string")
        if "required" in item and not isinstance(item["required"], bool):
            errors.append(f"{label}: required must be true or false")
        if "from_step" in item:
            fs = item["from_step"]
            if not isinstance(fs, str):
                errors.append(f"{label}: from_step must be a string")
            elif seen_steps and fs not in seen_steps:
                errors.append(f"{label}: from_step {fs!r} does not "
                              f"match any step id")

    # Scan exactly the fields render substitutes: description, notes,
    # output descriptions, and step title/detail/command_hint/gate.
    # Fields render prints verbatim (input descriptions, tools,
    # repeat) are not scanned.
    texts = [str(data.get("description", "")), str(data.get("notes", ""))]
    for step in steps if isinstance(steps, list) else []:
        if isinstance(step, dict):
            texts.extend(str(step.get(k, "")) for k in
                         ("title", "detail", "command_hint", "gate"))
    for item in outputs:
        if isinstance(item, dict):
            texts.append(str(item.get("description", "")))
    used = set()
    malformed: set[str] = set()
    for t in texts:
        used.update(PLACEHOLDER_RE.findall(t))
        valid_spans = {m.group(0) for m in PLACEHOLDER_RE.finditer(t)}
        for seg in re.findall(r"\{\{[^{}]*\}\}", t):
            if seg not in valid_spans:
                malformed.add(seg)
    for seg in sorted(malformed):
        warnings.append(f"{source}: malformed placeholder {seg!r} "
                        f"(want {{{{name}}}} with an identifier name); "
                        f"render leaves it as literal text")
    for name in sorted(used - input_names):
        warnings.append(f"{source}: placeholder {{{{{name}}}}} is used "
                        f"but no input named {name!r} is declared")
    for name in sorted(input_names - used):
        warnings.append(f"{source}: input {name!r} is declared but "
                        f"never used in a placeholder")
    return errors, warnings


def validate_recipe(path) -> tuple[list, list]:
    """Validate a recipe file: data-only rules plus format rules."""
    path = Path(path)
    errors = check_data_only_file(path)
    try:
        data = extract_recipe_data(path)
    except GhostRecipesError as exc:
        return errors + [str(exc)], []
    errs, warns = validate_data(data, source=str(path))
    name_id = data.get("id")
    stem = path.name
    if isinstance(name_id, str):
        for suffix in (".recipe.json", ".recipe.md"):
            if stem.endswith(suffix):
                if stem[: -len(suffix)] != name_id:
                    warns.append(
                        f"{path}: file name does not match recipe id "
                        f"{name_id!r}")
                break
    return errors + errs, warns


def default_library_dirs(explicit=None) -> list[Path]:
    """Library folders to search, in priority order.

    ``explicit`` (--library) first, then ``$GHOSTRECIPES_LIBRARY``,
    ``~/.ghostrecipes``, ``./recipes``, and the bundled ``recipes/``
    folder. Folders are deduped by resolved path, so the same folder
    spelled two ways is scanned only once.
    """
    dirs: list[Path] = []
    if explicit:
        dirs.append(Path(explicit))
    env = os.environ.get("GHOSTRECIPES_LIBRARY")
    if env:
        dirs.append(Path(env))
    dirs.append(Path.home() / ".ghostrecipes")
    dirs.append(Path.cwd() / "recipes")
    # Bundled recipes folder at the checkout root (src layout).
    bundled = Path(__file__).resolve().parents[2] / "recipes"
    if bundled not in dirs:
        dirs.append(bundled)
    # Dedupe by resolved path: an explicit --library spelled
    # differently (relative vs absolute) must not scan the same
    # folder twice and list every recipe in it twice.
    seen, out = set(), []
    for d in dirs:
        try:
            key = str(Path(d).expanduser().resolve())
        except OSError:
            key = str(d)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def find_recipe_files(dirs) -> list[Path]:
    """All recipe files under the given library dirs, sorted.

    The same physical file reached through two dirs (or two links)
    is returned once, keyed by resolved path.
    """
    found: list[Path] = []
    seen: set[str] = set()
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            if p.is_file() and (p.name.endswith(".recipe.json")
                                or p.name.endswith(".recipe.md")):
                try:
                    key = str(p.resolve())
                except OSError:
                    key = str(p)
                if key in seen:
                    continue
                seen.add(key)
                found.append(p)
    return found


def resolve_recipe(arg, dirs) -> Path:
    """Resolve a path argument or a bare recipe id to a file.

    A file path wins as-is; a folder yields its first recipe file;
    otherwise each library dir in ``dirs`` is searched for a recipe
    whose ``id`` equals ``arg``. Raises :class:`GhostRecipesError`
    listing the folders searched when nothing matches.
    """
    p = Path(arg)
    if p.is_file():
        return p
    if p.is_dir():
        for cand in sorted(p.glob("*.recipe.*")):
            if cand.is_file():
                return cand
        raise GhostRecipesError(f"no recipe file inside folder: {p}")
    for f in find_recipe_files(dirs):
        try:
            data = extract_recipe_data(f)
        except GhostRecipesError:
            continue
        if data.get("id") == arg:
            return f
    raise GhostRecipesError(
        f"recipe not found: {arg!r} (looked in: "
        + ", ".join(str(d) for d in dirs) + ")")
