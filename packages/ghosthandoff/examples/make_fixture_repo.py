#!/usr/bin/env python3
"""Build the demo fixture repo used by the examples walkthrough.

Creates a small git repository in a known mid-session state:

- branch ``feature/handoff-fixture``
- an old commit (dated 3 days before the demo repo is built,
  outside the default window)
- two recent commits (inside the window)
- one staged change, one unstaged change, one untracked file
- one stash entry
- three markers (TODO / FIXME / TODO)
- a verify-report.json + VERIFY.md recording a failing verdict

Usage: python3 make_fixture_repo.py [target-dir]
Default target: ./demo-project next to this script.

Stdlib only; shells out to the git CLI, which you need anyway.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Fixture Dev",
    "GIT_AUTHOR_EMAIL": "fixture@example.com",
    "GIT_COMMITTER_NAME": "Fixture Dev",
    "GIT_COMMITTER_EMAIL": "fixture@example.com",
}


def git(repo: Path, *args: str, env_extra: dict | None = None) -> None:
    env = dict(ENV)
    if env_extra:
        env.update(env_extra)
    subprocess.run(["git", "-C", str(repo), *args],
                   check=True, env=env, capture_output=True, text=True)


def write(repo: Path, rel: str, text: str) -> None:
    (repo / rel).write_text(text, encoding="utf-8")


def commit(repo: Path, subject: str, when: str | None = None) -> None:
    env = None
    if when:
        env = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", subject, env_extra=env)


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        Path(__file__).resolve().parent / "demo-project"
    if (target / ".git").exists():
        print(f"{target} already looks like the demo repo; "
              "delete it first if you want a fresh one.")
        return 1
    target.mkdir(parents=True, exist_ok=True)

    git(target, "init", "-q", "-b", "feature/handoff-fixture")
    git(target, "config", "commit.gpgsign", "false")

    write(target, "README.md",
          "# Fixture Project\n\nA small project used to test handoff packs.\n")
    write(target, "app.py",
          '"""Entry point for the fixture project."""\n\n\n'
          "def main():\n"
          '    print("fixture app")\n\n\n'
          'if __name__ == "__main__":\n'
          "    main()\n")
    write(target, "config.txt", "mode=fixture\n")
    # Relative to build time, never a fixed date: a hard-coded "old"
    # date ages out of every window the walkthrough demonstrates.
    old_when = (datetime.now() - timedelta(days=3)).strftime(
        "%Y-%m-%dT%H:%M:%S")
    commit(target, "Initial import", when=old_when)

    write(target, "pricing.py",
          '"""Pricing helpers."""\n\n'
          "# TODO: handle tax rounding at checkout\n\n\n"
          "def total(items):\n"
          "    return sum(items)\n")
    commit(target, "Add pricing module")

    write(target, "app.py",
          '"""Entry point for the fixture project."""\n\n'
          "from pricing import total\n\n"
          "# FIXME: retry the pricing call on failure\n\n\n"
          "def main():\n"
          '    print("fixture app", total([1, 2, 3]))\n\n\n'
          'if __name__ == "__main__":\n'
          "    main()\n")
    write(target, "CHANGELOG.md",
          "# Changelog\n\n## 0.2.0\n- Pricing wired into the entry point.\n")
    commit(target, "Wire pricing into the app entry point")

    write(target, "config.txt", "mode=fixture-experimental\n")
    git(target, "stash", "push", "-q", "-m",
        "experiment: alternate config mode")

    with open(target / "CHANGELOG.md", "a", encoding="utf-8") as fh:
        fh.write("- Pending release notes.\n")
    git(target, "add", "CHANGELOG.md")

    with open(target / "README.md", "a", encoding="utf-8") as fh:
        fh.write("\nLocal note: not committed yet.\n")

    write(target, "scratch.py",
          "# TODO: decide whether this scratch file ships\n\n"
          "SCRATCH = True\n")

    (target / "verify-report.json").write_text(json.dumps({
        "tool": "ghostverify",
        "verdict": "failed",
        "exit_code": 1,
        "gaps": [{"kind": "missing-hard", "symbol": "helper",
                  "file": "pricing.py"}],
    }, indent=2), encoding="utf-8")
    write(target, "VERIFY.md",
          "# Verify report\n\nVerdict: failed\n"
          "One hard gap was found; see verify-report.json.\n")

    print(f"Demo repo ready at {target}")
    print("Next: ghosthandoff pack", target, "-o ./pack-out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
