"""GhostRecipes command line.

Usage (installed entry point, or ``python3 -m ghostrecipes`` from a
source checkout with ``PYTHONPATH=src``):

    ghostrecipes create --id ID --name NAME -o FILE [--description TEXT]
                        [--tags a,b] [--steps "Title; Title"] [--force]
    ghostrecipes list [--library DIR] [--json]
    ghostrecipes show <id-or-path> [--library DIR] [--json]
    ghostrecipes validate <path-or-id-or-folder> [--library DIR]
    ghostrecipes export <id-or-path> -o DIR [--library DIR] [--force]
    ghostrecipes import <pack-folder> [--library DIR] [--force]
    ghostrecipes render <id-or-path> [-o FILE] [--library DIR]
                        [--var name=value ...]

Run ``ghostrecipes <command> --help`` for one command's flags.

Exit codes: 0 ok, 1 validation failure, 2 usage or config errors.
Local folders only. Recipes are data: no command in this CLI runs a
recipe step or a command hint, ever.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .authoring import create_recipe
from .packio import export_pack, import_pack
from .recipe import (GhostRecipesError, default_library_dirs,
                     find_recipe_files, load_recipe, resolve_recipe,
                     validate_recipe)
from .render import render_recipe


def cmd_create(args) -> int:
    """`create`: scaffold a recipe file and print the next step."""
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else []
    # Empty segments are dropped, exactly like empty tags above:
    # --steps "Setup;; Verify" used to fail the whole create on a
    # phantom empty step title. An all-empty list falls back to the
    # default steps in create_recipe.
    titles = [t.strip() for t in args.steps.split(";") if t.strip()] \
        if args.steps else None
    result = create_recipe(
        args.out, args.id, args.name,
        args.description or f"Workflow recipe: {args.name}",
        tags=[t for t in tags if t], step_titles=titles,
        author=args.author, force=args.force)
    print(f"recipe {args.id} v0.1.0 written to {result['path']}")
    print("next: edit the steps, then run: ghostrecipes validate "
          + result["path"])
    return 0


def cmd_list(args) -> int:
    """`list`: print every recipe in the library (or JSON rows)."""
    dirs = default_library_dirs(args.library)
    # In --json mode stdout must be JSON and nothing else, so the
    # library header goes to stderr there.
    print("library: " + ", ".join(str(d) for d in dirs),
          file=sys.stderr if args.json else sys.stdout)
    files = find_recipe_files(dirs)
    if not files:
        print("(no recipes found in the local library)")
        return 0
    if args.json:
        rows = []
        for f in files:
            try:
                r = load_recipe(f)
                rows.append({"id": r.id, "version": r.version,
                             "name": r.name, "steps": len(r.steps),
                             "tags": r.data.get("tags") or [],
                             "sha256": r.file_hash(), "path": str(f)})
            except GhostRecipesError as exc:
                rows.append({"path": str(f), "error": str(exc)})
        print(json.dumps(rows, indent=2))
        return 0
    for f in files:
        try:
            r = load_recipe(f)
            print(f"{r.summary_line()}  {f}")
        except GhostRecipesError as exc:
            print(f"INVALID RECIPE at {f}: {exc}")
    return 0


def cmd_show(args) -> int:
    """`show`: print one recipe in full; exit 1 if it has errors."""
    path = resolve_recipe(args.recipe, default_library_dirs(args.library))
    r = load_recipe(path)
    errors, warnings = validate_recipe(path)
    if args.json:
        print(json.dumps({"recipe": r.data, "path": str(path),
                          "sha256": r.file_hash(),
                          "errors": errors, "warnings": warnings},
                         indent=2))
        return 0
    print(r.summary_line())
    print(f"path: {path}")
    print(f"sha256: {r.file_hash()}")
    print(f"description: {r.data.get('description', '')}")
    if r.data.get("author"):
        print(f"author: {r.data['author']}")
    if r.data.get("date"):
        print(f"date: {r.data['date']}")
    if r.data.get("category"):
        print(f"category: {r.data['category']}")
    if r.data.get("tools"):
        raw_tools = r.data["tools"]
        if isinstance(raw_tools, list):
            print(f"tools: {', '.join(str(t) for t in raw_tools)}")
        else:
            print(f"tools: {raw_tools}")
    if r.data.get("notes"):
        print(f"notes: {r.data['notes']}")
    # The detail sections below print BEFORE the validation errors
    # are reported, so they must survive malformed shapes (non-dict
    # inputs/steps, missing names) and let the error list at the end
    # do the talking, instead of crashing with a traceback.
    if r.inputs:
        print("inputs:")
        for item in r.inputs:
            if not isinstance(item, dict):
                print(f"  - (malformed input: {item!r})")
                continue
            req = "required" if item.get("required") else "optional"
            default = item.get("default", "")
            print(f"  - {item.get('name', '<missing>')} ({req}"
                  + (f", default: {default}" if default else "")
                  + f") {item.get('description', '')}")
    if r.outputs:
        print("outputs:")
        for item in r.outputs:
            req = "required" if item.get("required") else "optional"
            from_step = item.get("from_step", "")
            print(f"  - {item.get('name', '')} ({req}"
                  + (f", from step: {from_step}" if from_step else "")
                  + f") {item.get('description', '')}")
    print("steps:")
    steps_seq = r.steps if isinstance(r.steps, list) else []
    if not isinstance(r.steps, list) and r.data.get("steps") is not None:
        print(f"  (malformed steps: {r.data.get('steps')!r})")
    for i, step in enumerate(steps_seq, start=1):
        if not isinstance(step, dict):
            print(f"  {i}. (malformed step: {step!r})")
            continue
        print(f"  {i}. [{step.get('kind')}] {step.get('title')} "
              f"(id: {step.get('id')})")
        if step.get("gate"):
            print(f"     gate: {step['gate']}")
    for w in warnings:
        print(f"warning: {w}")
    if errors:
        for e in errors:
            print(f"error: {e}")
        return 1
    return 0


def cmd_validate(args) -> int:
    """`validate`: check a file, folder, pack, or id; exit 1 on any error."""
    target = Path(args.target)
    files: list[Path] = []
    if target.is_dir() and (target / "manifest.json").is_file():
        files = [p for p in sorted(target.glob("*.recipe.*"))
                 if p.is_file()]
        if not files:
            print(f"error: no recipe files in pack folder {target}",
                  file=sys.stderr)
            return 2
    elif target.is_dir():
        files = [p for p in sorted(target.rglob("*"))
                 if p.is_file() and (p.name.endswith(".recipe.json")
                                     or p.name.endswith(".recipe.md"))]
        if not files:
            print(f"error: no recipe files under folder {target}",
                  file=sys.stderr)
            return 2
    else:
        files = [resolve_recipe(args.target,
                                default_library_dirs(args.library))]
    bad = 0
    for f in files:
        errors, warnings = validate_recipe(f)
        for w in warnings:
            print(f"warning: {w}")
        if errors:
            bad += 1
            for e in errors:
                print(f"error: {e}")
            print(f"validate: FAIL {f}")
        else:
            r = load_recipe(f)
            print(f"validate: OK - {r.summary_line()}  {f}")
    return 1 if bad else 0


def cmd_export(args) -> int:
    """`export`: write a data-only pack; refuse an invalid recipe."""
    path = resolve_recipe(args.recipe, default_library_dirs(args.library))
    errors, _ = validate_recipe(path)
    if errors:
        for e in errors:
            print(f"error: {e}")
        print("export: refusing to export an invalid recipe")
        return 1
    result = export_pack(path, args.out, force=args.force)
    m = result["manifest"]
    print(f"exported {m['recipes'][0]} v{m['files'][0]['version']} "
          f"to {result['out_dir']} (sha256 {m['files'][0]['sha256']})")
    print("data-only pack: recipe files plus manifest.json, nothing "
          "in it runs")
    return 0


def cmd_import(args) -> int:
    """`import`: verify a pack, then copy its recipes into the library."""
    library = Path(args.library) if args.library else Path.home() / ".ghostrecipes"
    result = import_pack(args.pack, library, force=args.force)
    for f in result["imported"]:
        print(f"imported: {f}")
    print(f"recipes now in library: {result['library']}")
    return 0


def cmd_render(args) -> int:
    """`render`: print or write the checklist; refuse an invalid recipe."""
    path = resolve_recipe(args.recipe, default_library_dirs(args.library))
    errors, _ = validate_recipe(path)
    if errors:
        for e in errors:
            print(f"error: {e}")
        print("render: refusing to render an invalid recipe")
        return 1
    overrides = {}
    for pair in args.var or []:
        if "=" not in pair:
            raise GhostRecipesError(f"--var needs name=value, got {pair!r}")
        k, v = pair.split("=", 1)
        overrides[k.strip()] = v
    text = render_recipe(load_recipe(path), overrides)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"rendered checklist written to {out}")
    else:
        print(text, end="")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser: one subcommand per command above."""
    p = argparse.ArgumentParser(
        prog="ghostrecipes",
        description="Versioned, data-only workflow recipes: create, "
                    "list, show, validate, export, import, render. "
                    "Local only; a recipe is never run by this tool.",
        epilog="Hard rule: recipes are data only. No command runs a "
               "recipe step or a command hint, ever. "
               "Exit codes: 0 ok, 1 validation failed, "
               "2 usage or config error. "
               "Example: ghostrecipes render "
               "examples/audit-improve-verify.recipe.json "
               "--var target=myfile.py")
    p.add_argument("--version", action="version",
                   version=f"ghostrecipes {__version__}")
    sub = p.add_subparsers(dest="command", required=True,
                           metavar="<command>")

    sp = sub.add_parser(
        "create", help="scaffold a new recipe file",
        description="Scaffold a new, valid recipe file at version "
                    "0.1.0. Edit its steps afterwards, then validate.")
    sp.add_argument("--id", required=True, metavar="ID",
                    help="recipe id: a lowercase slug, e.g. my-new-loop")
    sp.add_argument("--name", required=True, metavar="NAME",
                    help='human title, e.g. "My New Loop"')
    sp.add_argument("--description", metavar="TEXT",
                    help="what the workflow is for "
                         "(default: 'Workflow recipe: <name>')")
    sp.add_argument("--tags", metavar="A,B",
                    help="comma-separated tags, e.g. build,audit")
    sp.add_argument("--steps", metavar='"Title; Title"',
                    help="semicolon-separated step titles to scaffold "
                         "(default: three starter steps)")
    sp.add_argument("--author", metavar="NAME",
                    help="author name to record in the recipe")
    sp.add_argument("-o", "--out", required=True, metavar="FILE",
                    help="output file, or a folder to write <id>.recipe.json into")
    sp.add_argument("--force", action="store_true",
                    help="overwrite the output file if it already exists")
    sp.set_defaults(fn=cmd_create)

    sp = sub.add_parser(
        "list", help="list recipes in the local library",
        description="List every recipe found in the library folders "
                    "(--library, $GHOSTRECIPES_LIBRARY, "
                    "~/.ghostrecipes, ./recipes, bundled recipes/). "
                    "Invalid recipes are shown as INVALID, never skipped.")
    sp.add_argument("--library", metavar="DIR",
                    help="extra library folder to search first")
    sp.add_argument("--json", action="store_true",
                    help="print a JSON array on stdout "
                         "(the library header goes to stderr)")
    sp.set_defaults(fn=cmd_list)

    sp = sub.add_parser(
        "show", help="show one recipe (id or file)",
        description="Print one recipe in full: description, inputs, "
                    "numbered steps with gates, and the file sha256.")
    sp.add_argument("recipe", metavar="RECIPE",
                    help="recipe id, or path to a .recipe.json / .recipe.md file")
    sp.add_argument("--library", metavar="DIR",
                    help="extra library folder to search first")
    sp.add_argument("--json", action="store_true",
                    help="print the recipe, hash, errors, and warnings as JSON")
    sp.set_defaults(fn=cmd_show)

    sp = sub.add_parser(
        "validate", help="validate a recipe file, folder, or id",
        description="Validate a recipe file, a folder of recipes, a "
                    "pack folder, or a recipe id. Exit 0 means valid; "
                    "placeholder problems are warnings, not errors.")
    sp.add_argument("target", metavar="TARGET",
                    help="file path, folder, pack folder, or recipe id")
    sp.add_argument("--library", metavar="DIR",
                    help="extra library folder to search first (for ids)")
    sp.set_defaults(fn=cmd_validate)

    sp = sub.add_parser(
        "export", help="export a recipe as a data-only pack folder",
        description="Export a valid recipe as a data-only pack: the "
                    "recipe file plus manifest.json with a sha256 per "
                    "file. Nothing in a pack runs.")
    sp.add_argument("recipe", metavar="RECIPE",
                    help="recipe id, or path to a .recipe.json / .recipe.md file")
    sp.add_argument("-o", "--out", required=True, metavar="DIR",
                    help="pack folder to write")
    sp.add_argument("--library", metavar="DIR",
                    help="extra library folder to search first (for ids)")
    sp.add_argument("--force", action="store_true",
                    help="reuse the output folder even if it is not empty")
    sp.set_defaults(fn=cmd_export)

    sp = sub.add_parser(
        "import", help="import a data-only pack into a library",
        description="Verify a pack (manifest, hashes, recipes, "
                    "data-only rules) and only then copy its recipes "
                    "into one library folder. Writes nothing on failure.")
    sp.add_argument("pack", metavar="PACK",
                    help="pack folder created by 'export'")
    sp.add_argument("--library", metavar="DIR",
                    help="target library folder (default ~/.ghostrecipes)")
    sp.add_argument("--force", action="store_true",
                    help="overwrite a recipe in the library on a name collision")
    sp.set_defaults(fn=cmd_import)

    sp = sub.add_parser(
        "render", help="render a recipe to a checklist / prompt file",
        description="Render a valid recipe as a Markdown checklist. "
                    "{{placeholders}} are filled from input defaults, "
                    "then --var overrides; anything left unfilled is "
                    "listed, never guessed. Rendering never runs a step.")
    sp.add_argument("recipe", metavar="RECIPE",
                    help="recipe id, or path to a .recipe.json / .recipe.md file")
    sp.add_argument("-o", "--out", metavar="FILE",
                    help="write the checklist to this file "
                         "(default: print to stdout)")
    sp.add_argument("--library", metavar="DIR",
                    help="extra library folder to search first (for ids)")
    sp.add_argument("--var", action="append", metavar="NAME=VALUE",
                    help="input override, name=value (repeatable)")
    sp.set_defaults(fn=cmd_render)
    return p


def main(argv=None) -> int:
    """CLI entry point. Returns the exit code (0, 1, or 2)."""
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except GhostRecipesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0
    except OSError as exc:
        # Filesystem failures that escape a command (an output path
        # under an existing file, a permission error, a full disk)
        # are usage/config errors, not crashes: exit 2, no traceback.
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
