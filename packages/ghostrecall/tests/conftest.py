"""Shared helpers for GhostRecall tests.

Tests target the PUBLIC CLI and bundle formats described in PLAN.md.
They do not import ghostrecall internals: if the CLI contract changes,
these tests are supposed to fail loudly.

Assumed CLI (see REPORT_B.md, assumptions A1-A8):
  ghostrecall recall  <project> --task "..." [--out <dir>]
  ghostrecall bundle  <project> --task "..." --fit <tokens> -o <dir>
                                        (also accepts --out <dir>)
  ghostrecall check   <bundle>
  ghostrecall explain <project> --task "..."   (the --explain style view)

Assumed bundle layout:
  <bundle>/manifest.json   JSON object; item list under "items"
                            (tolerated: "files" / "entries" / "records")
  <bundle>/PROMPT.md       merged prompt for the combined bundle

Assumed manifest item fields (tolerated aliases in _norm_item):
  source type, mode, original tokens, sliced tokens, sha256, and
  provenance: source path + (line or commit) + date, plus a status
  ("current" / "superseded" / "excluded" / "blocked").
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Synthetic, randomly-shaped test value. Deliberately contains none of
# the placeholder words secret scanners exempt (fake / example / dummy /
# test-key ...), otherwise the guard would wave it through as a labelled
# placeholder - the exact convention GhostSlice used for its own test
# keys. It is not a real credential.
PLANTED_SECRET = "K7f9Q2xLm4Vz8Rp1Wd6Hs3Nj5Yb0TcAa"


def cli_base():
    exe = shutil.which("ghostrecall")
    if exe:
        return [exe]
    return [sys.executable, "-m", "ghostrecall"]


def cli_env():
    env = dict(os.environ)
    parts = [str(REPO_ROOT / "src"), str(REPO_ROOT)]
    if env.get("PYTHONPATH"):
        parts.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def run_cli(*args, cwd=None, timeout=120):
    return subprocess.run(
        cli_base() + [str(a) for a in args],
        capture_output=True, text=True, cwd=cwd, env=cli_env(),
        timeout=timeout,
    )


def core_available():
    """True if `ghostrecall` (console script or module) actually runs."""
    try:
        r = run_cli("--help", timeout=30)
    except Exception:
        return False
    return r.returncode == 0


@pytest.fixture(scope="session", autouse=True)
def require_core():
    if not core_available():
        pytest.fail(
            "ghostrecall core CLI is not available "
            "(`ghostrecall --help` / `python -m ghostrecall --help` failed). "
            "Tests are written against the PLAN.md CLI contract; see "
            "REPORT_B.md assumptions."
        )


def copy_fixture(name, tmp_path):
    src = FIXTURES / name
    assert src.is_dir(), f"missing fixture {name}"
    dst = tmp_path / name
    shutil.copytree(src, dst)
    return dst


@pytest.fixture()
def provenance_project(tmp_path):
    return copy_fixture("provenance_project", tmp_path)


@pytest.fixture()
def superseded_project(tmp_path):
    return copy_fixture("superseded_project", tmp_path)


@pytest.fixture()
def secret_project(tmp_path):
    return copy_fixture("secret_project", tmp_path)


# ---------------------------------------------------------------- manifest

def find_manifest(bundle):
    bundle = Path(bundle)
    for cand in (
        bundle / "manifest.json",
        bundle / "recall_manifest.json",
        bundle / "memory_manifest.json",
        bundle / ".ghost_memory" / "manifest.json",
    ):
        if cand.is_file():
            return cand
    found = sorted(bundle.rglob("manifest.json"))
    assert found, f"no manifest.json found under bundle {bundle}"
    return found[0]


def load_manifest(bundle):
    path = find_manifest(bundle)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "manifest must be a JSON object"
    return data


def manifest_items(bundle):
    data = load_manifest(bundle)
    for key in ("items", "files", "entries", "records"):
        if isinstance(data.get(key), list):
            return [_norm_item(it) for it in data[key]]
    raise AssertionError(
        f"manifest has no item list under items/files/entries/records: "
        f"keys={sorted(data)}"
    )


def _first(item, *names):
    prov = item.get("provenance") if isinstance(item.get("provenance"), dict) else {}
    for name in names:
        if item.get(name) not in (None, ""):
            return item[name]
        if prov.get(name) not in (None, ""):
            return prov[name]
    return None


def _norm_item(item):
    assert isinstance(item, dict), f"manifest item is not an object: {item!r}"
    return {
        "raw": item,
        "source_type": _first(item, "source_type", "type", "kind"),
        "mode": _first(item, "mode"),
        "original_tokens": _first(item, "original_tokens", "tokens_original", "orig_tokens"),
        "sliced_tokens": _first(item, "sliced_tokens", "tokens", "tokens_sliced"),
        "sha256": _first(item, "sha256", "hash"),
        "source": _first(item, "source", "source_path", "path", "file", "rel_path"),
        "line": _first(item, "line", "line_number", "lineno"),
        "commit": _first(item, "commit", "commit_hash", "sha"),
        "date": _first(item, "date", "decided", "decision_date", "timestamp"),
        "status": _first(item, "status", "state"),
        "decision": _first(item, "decision", "title", "text", "summary"),
        "pinned": _first(item, "pinned", "is_pinned", "pin"),
    }


def bundle_prompt(bundle):
    bundle = Path(bundle)
    for cand in (bundle / "PROMPT.md", bundle / "prompt.md"):
        if cand.is_file():
            return cand.read_text(encoding="utf-8", errors="replace")
    return ""


def bundle_all_text(bundle):
    """Every text file inside a bundle, concatenated (leak scanning)."""
    out = []
    for p in sorted(Path(bundle).rglob("*")):
        if p.is_file():
            try:
                out.append(p.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
    return "\n".join(out)


def run_bundle(project, out_dir, task, fit=4000):
    r = run_cli("bundle", project, "--task", task, "--fit", fit, "-o", out_dir)
    if r.returncode != 0 and "unrecognized" in (r.stderr + r.stdout).lower():
        r = run_cli("bundle", project, "--task", task, "--fit", fit,
                    "--out", out_dir)
    return r


def sha256_hex(s):
    return isinstance(s, str) and len(s) == 64 and all(
        c in "0123456789abcdef" for c in s.lower()
    )
