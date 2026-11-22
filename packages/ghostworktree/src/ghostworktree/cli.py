"""GhostWorktree CLI: create / list / status / doctor / cleanup.

Thin argparse layer over :mod:`ghostworktree.core`: it parses flags,
prints the human or ``--json`` form of the result, and maps
:class:`~ghostworktree.errors.WorktreeError` to its exit code
(1 = refused or failed, 2 = could not run). All safety rules --
notably the dirty-cleanup refusal and the example-only env rule --
live in core, not here.
"""
from __future__ import annotations
import argparse, json, sys
from . import core
from .errors import WorktreeError

def _p_create(a):
    rec = core.create(a.repo, a.name, branch=a.branch, base=a.base, port=a.port,
                      port_range=a.port_range, path=a.path, no_env=a.no_env, root=a.root)
    if a.json: print(json.dumps(rec, indent=2))
    else:
        print(f"created {rec['name']}: {rec['path']}")
        print(f"  branch: {rec['branch']}  base: {rec['base']}  port: {rec['port']}")
        print(f"  env: {rec['env_source'] or 'no .env.example found'}"
              + (" (example only, .env not seeded)" if a.no_env and rec['env_source'] else ""))
    return 0

def _p_list(a):
    recs = core.list_worktrees(a.repo, root=a.root)
    if a.json: print(json.dumps(recs, indent=2))
    elif not recs: print("no registered worktrees")
    else:
        for r in recs:
            # Registry validation guarantees name/path/branch only;
            # port and created_at may be absent in a hand-written or
            # older registry, and listing must not die with a KeyError
            # traceback on a record load() accepted.
            print(f"{r['name']}: {r['path']}  branch={r['branch']} port={r.get('port')} state={r.get('state')} created={r.get('created_at', 'unknown')}")
    return 0

def _p_status(a):
    rows = core.status(a.repo, name=a.name, root=a.root)
    if a.json: print(json.dumps(rows, indent=2))
    elif not rows: print("no registered worktrees")
    else:
        for r in rows:
            if r["status"] == "missing":
                print(f"{r['name']}: missing  path={r['path']} port={r['port']}")
            else:
                print(f"{r['name']}: {r['status']}  changed={r['changed']} "
                      f"(staged={r['staged']} unstaged={r['unstaged']} untracked={r['untracked']}) "
                      f"branch={r.get('current_branch') or r['branch']} port={r['port']} path={r['path']}")
    return 0

def _p_doctor(a):
    report = core.doctor(a.repo, root=a.root)
    if a.json: print(json.dumps(report, indent=2))
    else:
        s = report["summary"]
        print(f"doctor: {'ok' if report['ok'] else 'problems found'}  "
              f"registered={s['registered']} present={s['present']} missing={s['missing']} "
              f"unregistered={s['unregistered']} orphan_directories={s['orphan_directories']}")
        for p in report["problems"]:
            where = p.get("name") or p.get("path") or ""
            print(f"  problem [{p['kind']}] {where}: {p['detail']}")
        for n in report["notes"]:
            where = n.get("name") or n.get("path") or ""
            print(f"  note [{n['kind']}] {where}: {n['detail']}")
        print("  doctor is read-only: nothing was pruned, removed, or unregistered")
    return 0 if report["ok"] else 1

def _p_cleanup(a):
    res = core.cleanup(a.repo, a.name, force=a.force, delete_branch=a.delete_branch, root=a.root)
    if a.json: print(json.dumps(res, indent=2))
    else:
        if a.force: print("warning: --force used; any uncommitted work in the tree was discarded")
        print(f"cleaned up {res['name']}: removed_tree={res['removed_tree']} "
              f"branch_deleted={res['branch_deleted']} freed_port={res['freed_port']}")
        if res.get("branch_delete_error"):
            print(f"warning: branch {res['branch']} was kept: {res['branch_delete_error']}")
    return 0

_NAME_HELP = ("task name: a single safe path component (letters, digits, "
              "'-', '_', '.'; no slashes, no '..'); it also names the "
              "default branch worktree/<name> and the tree directory")

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ghostworktree",
        description="Isolated git worktree + port + env-copy manager per agent task. Local git only, no network. Never reads or logs a real .env.",
        epilog="examples:\n"
               "  ghostworktree create ~/repo fix-parser\n"
               "  ghostworktree create ~/repo fix-parser --port 4200 --json\n"
               "  ghostworktree list ~/repo\n"
               "  ghostworktree status ~/repo fix-parser\n"
               "  ghostworktree doctor ~/repo\n"
               "  ghostworktree cleanup ~/repo fix-parser   # refuses if dirty\n"
               "\n"
               "exit codes: 0 = ok, 1 = refused or failed, 2 = could not run\n"
               "(for example, not a git repo).",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    def common(sp, repo_required=True):
        sp.add_argument("repo", help="path to the main git repository (must be a git working tree)")
        sp.add_argument("--root", default=None, help="worktrees root holding registry.json (default: sibling <repo-parent>/<repo-name>-worktrees)")
        sp.add_argument("--json", action="store_true", help="machine-readable JSON output instead of the human summary")
    c = sub.add_parser("create", help="create an isolated worktree with a unique port and an env seeded only from .env.example",
        description="Create one isolated worktree per agent task: its own checkout and branch, a port no other registered worktree shares, and a throwaway .env seeded only from .env.example (the real .env is never read). Nothing is created or registered if the create is refused.",
        epilog="example: ghostworktree create ~/repo fix-parser --base main --port-range 4200-4299",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    common(c); c.add_argument("name", help=_NAME_HELP)
    c.add_argument("--branch", default=None, help="branch to check out; created from --base if it does not exist yet (default: worktree/<name>)")
    c.add_argument("--base", default="HEAD", help="base ref for a new branch (default: HEAD)")
    c.add_argument("--port", type=int, default=None, help="explicit port; must be free in the registry and unbound on localhost, otherwise the create is refused (default: lowest free port in --port-range)")
    c.add_argument("--port-range", default=None, help="allocation range START-END (default: 4100-4999)")
    c.add_argument("--path", default=None, help="explicit worktree path (default: <root>/<name>)")
    c.add_argument("--no-env", action="store_true", help="copy .env.example into the tree but do not seed a throwaway .env from it")
    c.set_defaults(fn=_p_create)
    l = sub.add_parser("list", help="list registered worktrees",
        description="List the registered worktrees for a repo: name, path, branch, port, state (present or missing), and creation time. A tree git no longer knows about is shown as missing, never silently dropped.")
    common(l); l.set_defaults(fn=_p_list)
    s = sub.add_parser("status", help="show clean/dirty status per worktree",
        description="Show clean/dirty status for one named worktree, or for every registered worktree when no name is given. Dirty counts staged, unstaged, and untracked entries individually; a missing tree is reported as missing, never as clean.")
    common(s)
    s.add_argument("name", nargs="?", default=None, help="only show this worktree (default: all registered worktrees)"); s.set_defaults(fn=_p_status)
    d = sub.add_parser("doctor", help="read-only audit: reconcile registry, git, disk, and ports; reports unregistered worktrees, orphan directories, duplicate names/ports, and branch drift; changes nothing",
        description="Read-only audit reconciling the registry, git worktree list, the disk, and the managed root. Reports registered trees that are missing or prunable, git worktrees that are not registered, orphan directories, duplicate names or ports, and recorded branches that vanished or drifted. Changes nothing: it never prunes, removes, or unregisters. Exit 0 when healthy, 1 when problems are found.")
    common(d); d.set_defaults(fn=_p_doctor)
    cl = sub.add_parser("cleanup", help="remove a worktree; refuses dirty trees unless --force discards uncommitted work",
        description="Remove a registered worktree and free its port. REFUSES a dirty tree by default: uncommitted work is never deleted silently. The branch is kept unless --delete-branch is given. A missing tree is simply unregistered and needs no --force.",
        epilog="example: ghostworktree cleanup ~/repo fix-parser --delete-branch",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    common(cl); cl.add_argument("name", help=_NAME_HELP)
    cl.add_argument("--force", action="store_true", help="DISCARD uncommitted work and remove a dirty tree; without this flag a dirty tree is refused and left untouched")
    cl.add_argument("--delete-branch", action="store_true", help="also safe-delete the branch (git branch -d, never -D) after removal; if git refuses, the branch is kept and a warning is shown, the cleanup itself still succeeds")
    cl.set_defaults(fn=_p_cleanup)
    return p

def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    try:
        return a.fn(a)
    except WorktreeError as e:
        print(f"error: {e}", file=sys.stderr)
        return e.exit_code
    except BrokenPipeError:
        return 0

if __name__ == "__main__":
    sys.exit(main())
