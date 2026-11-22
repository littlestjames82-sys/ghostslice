"""Recipe scaffolding for the ``create`` command.

:func:`create_recipe` writes a minimal, already-valid recipe at
version 0.1.0 so a new workflow starts from a file that passes
``validate``. It only writes data: nothing here runs recipe content.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .recipe import GhostRecipesError, validate_data


def slugify(text: str) -> str:
    """Turn a step title into a step id slug, e.g. 'Check the result'
    becomes 'check-the-result'. Falls back to 'step' if nothing
    slug-like survives."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-._")
    return slug or "step"


def create_recipe(out_path, recipe_id: str, name: str, description: str,
                  tags=None, step_titles=None, author=None,
                  force: bool = False) -> dict:
    """Write a new recipe file and return ``{"path", "recipe"}``.

    ``out_path`` may be a file path, or a folder, in which case the
    file is written inside it as ``<recipe_id>.recipe.json``.
    ``step_titles`` defaults to three starter steps when not given;
    duplicate titles get suffixed ids so step ids stay unique.
    Raises :class:`GhostRecipesError` if the file already exists
    without ``force``, or if the scaffolded recipe would not
    validate (in which case nothing is written).
    """
    out = Path(out_path)
    if out.is_dir():
        out = out / f"{recipe_id}.recipe.json"
    if out.exists() and not force:
        raise GhostRecipesError(f"{out} already exists; use --force")
    titles = step_titles or ["Describe the goal", "Do the work",
                             "Check the result"]
    steps, seen = [], set()
    for title in titles:
        base = slugify(title)
        sid, n = base, 2
        while sid in seen:
            sid = f"{base}-{n}"
            n += 1
        seen.add(sid)
        steps.append({"id": sid, "title": title, "kind": "manual"})
    data = {
        "id": recipe_id,
        "name": name,
        "version": "0.1.0",
        "description": description,
        "steps": steps,
    }
    if tags:
        data["tags"] = tags
    if author:
        data["author"] = author
    errors, _ = validate_data(data, source="create")
    if errors:
        raise GhostRecipesError("refusing to write an invalid recipe: "
                                + "; ".join(errors))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return {"path": str(out), "recipe": data}
