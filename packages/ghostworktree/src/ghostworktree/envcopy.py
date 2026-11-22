"""Env seeding: ONLY .env.example / .env.sample / .env.template are ever read or copied.

The real .env is never opened, copied, parsed, or logged. Contents are copied
byte-for-byte and never printed.
"""
from __future__ import annotations
import os
import shutil
from pathlib import Path

EXAMPLE_NAMES = (".env.example", ".env.sample", ".env.template")

def find_example(repo: Path) -> Path | None:
    """Return the first env example present in ``repo``, or ``None``.

    Checks ``EXAMPLE_NAMES`` in order (``.env.example``, then
    ``.env.sample``, then ``.env.template``). The real ``.env`` is
    deliberately not in that list and is never probed here.
    Symlinked candidates are skipped, never followed (see below).
    """
    for n in EXAMPLE_NAMES:
        p = Path(repo) / n
        # Never follow a symlink: a planted `.env.example` symlink to the
        # real `.env` (or to any other file) would otherwise smuggle that
        # file's contents into every worktree, breaking the env rule.
        # A symlinked candidate is skipped, as if it were not there.
        if p.is_symlink():
            continue
        if p.is_file(): return p
    return None

def seed_env(repo: Path, dest: Path, seed_dotenv: bool = True) -> str | None:
    """Copy the example into ``dest`` under its own name; optionally seed ``dest/.env``.

    Existing files in ``dest`` are left alone. Returns the example
    file NAME only (never its contents), or ``None`` when the repo
    has no example file, in which case nothing is copied.
    """
    src = find_example(repo)
    if src is None: return None
    target = Path(dest) / src.name
    # lexists, not exists: exists() is False for a broken symlink, and
    # copyfile would then write *through* that symlink to its target,
    # an arbitrary file outside the worktree. Any existing entry at
    # all (file, directory, or symlink, broken or not) is left alone.
    if not os.path.lexists(target):
        shutil.copyfile(src, target)
    if seed_dotenv:
        dotenv = Path(dest) / ".env"
        if not os.path.lexists(dotenv):
            shutil.copyfile(src, dotenv)
    return src.name
