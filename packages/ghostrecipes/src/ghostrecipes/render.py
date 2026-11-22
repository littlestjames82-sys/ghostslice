"""Render a recipe to a human checklist / prompt file.

Rendering is text substitution only. Values come from input defaults
overridden by --var pairs. Command hints are printed inside fenced
blocks labelled as manual steps: rendering never runs them, and this
module contains no code path that could.
"""
from __future__ import annotations

import re

from .recipe import PLACEHOLDER_RE, Recipe

MANUAL_NOTE = "run manually - GhostRecipes does not run this"


def resolve_values(recipe: Recipe, overrides: dict) -> dict:
    """Values used for substitution: input defaults, overridden by
    the caller's ``--var name=value`` pairs (overrides win)."""
    values = {}
    for item in recipe.inputs:
        if "default" in item:
            values[item["name"]] = item["default"]
    values.update(overrides)
    return values


def _cell(text: str) -> str:
    """One Markdown table cell: pipes escaped, newlines flattened,
    so a value like ``a|b`` cannot split the row into extra columns."""
    return str(text).replace("|", "\\|").replace("\n", " ")


def _emit(lines: list, prefix: str, text: str) -> None:
    """Append text under a bullet prefix, indenting continuation
    lines to the prefix width so multi-line text stays inside the
    checklist item instead of falling back to column zero."""
    parts = str(text).splitlines() or [""]
    lines.append(prefix + parts[0])
    for extra in parts[1:]:
        lines.append(" " * len(prefix) + extra)


def substitute(text: str, values: dict, unresolved: set) -> str:
    """Replace each ``{{name}}`` with ``values[name]`` when known.
    Unknown names stay visible in the text and are collected in
    ``unresolved`` so the caller can list them, never guess them."""
    def repl(match):
        name = match.group(1)
        if name in values:
            return values[name]
        unresolved.add(name)
        return match.group(0)
    return PLACEHOLDER_RE.sub(repl, text)


def render_recipe(recipe: Recipe, overrides: dict | None = None) -> str:
    """Render ``recipe`` as a Markdown checklist string.

    Layout: title and recipe identity (id, version, file sha256),
    the never-executes notice, description, an inputs table, the
    numbered steps as ``- [ ]`` items (detail, gate, and command
    hints labelled as manual steps), notes, and, if any placeholder
    could not be filled, an Unresolved placeholders section.
    """
    overrides = overrides or {}
    values = resolve_values(recipe, overrides)
    unresolved: set[str] = set()
    data = recipe.data
    lines: list[str] = []
    lines.append(f"# {data.get('name', recipe.id)}")
    lines.append("")
    lines.append(f"Recipe: {recipe.id} v{recipe.version}"
                 + (f" | file sha256: {recipe.file_hash()}"
                    if recipe.file_hash() else ""))
    lines.append("Rendered by GhostRecipes. This is a checklist to "
                 "follow, not a program: GhostRecipes never runs any "
                 "step or command hint in a recipe.")
    lines.append("")
    lines.append(substitute(str(data.get("description", "")), values,
                            unresolved))
    lines.append("")
    if recipe.inputs:
        lines.append("## Inputs")
        lines.append("")
        lines.append("| Name | Required | Value used | Description |")
        lines.append("|------|----------|------------|-------------|")
        for item in recipe.inputs:
            nm = item["name"]
            if item.get("required") and nm not in values:
                unresolved.add(nm)
                used = "(not provided)"
            else:
                used = values.get(nm, "")
            lines.append(f"| {_cell(nm)} | "
                         f"{'yes' if item.get('required') else 'no'} | "
                         f"{_cell(used)} | "
                         f"{_cell(item.get('description', ''))} |")
        lines.append("")
    lines.append("## Steps")
    lines.append("")
    for i, step in enumerate(recipe.steps, start=1):
        title = substitute(str(step.get("title", "")), values, unresolved)
        lines.append(f"- [ ] **{i}. {title}** "
                     f"({step.get('kind', '')}, id: {step.get('id', '')})")
        if step.get("detail"):
            _emit(lines, "  - ",
                  substitute(step['detail'], values, unresolved))
        if step.get("repeat"):
            lines.append(f"  - Repeat: {step['repeat']}")
        if step.get("tools"):
            lines.append(f"  - Tools: {', '.join(step['tools'])}")
        if step.get("gate"):
            _emit(lines, "  - Gate: ",
                  substitute(step['gate'], values, unresolved))
        if step.get("command_hint"):
            hint = substitute(step["command_hint"], values, unresolved)
            # Fence one backtick longer than the longest backtick
            # run inside the hint, so a hint containing ``` cannot
            # close the fence early and spill into the document.
            longest = max((len(run) for run in
                           re.findall(r"`+", hint)), default=0)
            fence = "`" * max(3, longest + 1)
            lines.append(f"  - Command hint ({MANUAL_NOTE}):")
            lines.append("")
            lines.append(f"    {fence}text")
            for hline in hint.splitlines() or [hint]:
                lines.append(f"    {hline}")
            lines.append(f"    {fence}")
        lines.append("")
    if recipe.outputs:
        lines.append("## Outputs")
        lines.append("")
        lines.append("Declared outputs are expectations to check "
                     "against, not files this tool creates.")
        lines.append("")
        lines.append("| Name | Required | From step | Description |")
        lines.append("|------|----------|-----------|-------------|")
        for item in recipe.outputs:
            desc = substitute(str(item.get("description", "")), values,
                              unresolved)
            lines.append(f"| {_cell(item.get('name', ''))} | "
                         f"{'yes' if item.get('required') else 'no'} | "
                         f"{_cell(item.get('from_step') or '-')} | "
                         f"{_cell(desc)} |")
        lines.append("")
    if data.get("notes"):
        lines.append("## Notes")
        lines.append("")
        lines.append(substitute(str(data["notes"]), values, unresolved))
        lines.append("")
    if unresolved:
        lines.append("## Unresolved placeholders")
        lines.append("")
        lines.append("Left visible, never guessed: "
                     + ", ".join("{{" + n + "}}" for n in sorted(unresolved)))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
