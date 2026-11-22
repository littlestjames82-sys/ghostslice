"""GhostRecipes: versioned, data-only workflow recipes.

A recipe describes a repeatable workflow (goal, inputs, ordered
steps, gates, outputs) so a human or an agent can follow it the
same way every time. This tool creates, lists, shows, validates,
exports, imports, and renders recipes as human checklists.

Hard rule: it never runs a step, a command hint, or any other
content found in a recipe file. Recipes are data only.

Entry points: the ``ghostrecipes`` console script, or
``python3 -m ghostrecipes`` (see :mod:`ghostrecipes.cli`).
"""

__version__ = "0.1.0"
