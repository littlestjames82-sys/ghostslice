"""GhostSchema: API spec slicer, a GhostSlice companion.

Slices large API specifications down to what a task touches:
- OpenAPI 3.x JSON and standalone JSON Schema get the full treatment
  (selection + local $ref reachability + a reduced spec and manifest).
- GraphQL SDL gets an outline only, labelled outline everywhere.

Static parsing only. Remote $refs are never fetched. YAML is refused.
Input files are never modified. Python stdlib only.

Command line: ``ghostschema inspect <spec>`` lists what a spec
contains; ``ghostschema slice <spec> --select <ids>`` (or ``--task``
or ``--all``) writes a bundle; ``ghostschema mcp`` runs the stdio
MCP server. See README.md for the full guide.
"""

__version__ = "0.1.0"
