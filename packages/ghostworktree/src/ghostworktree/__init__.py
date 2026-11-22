"""GhostWorktree - isolated git worktree, port, and env-copy manager per agent task.

One registered worktree per task: its own checkout and branch, a port
no other registered worktree shares, and a throwaway env seeded only
from ``.env.example``. Local git only; the real ``.env`` is never
read, and cleanup refuses a dirty tree unless ``--force`` is given.
"""
__version__ = "0.1.0"
__all__ = ["__version__"]
