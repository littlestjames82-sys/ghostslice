"""GhostPort: migration slicer paired with GhostSlice. Planner only.

Scans a project for pattern-pack hits, groups them into units, orders
the units leaves-first, and exports one bundle per unit. It never
rewrites project code. See README.md for the full workflow.
"""
__version__ = "0.1.0"
__all__ = ["__version__"]
