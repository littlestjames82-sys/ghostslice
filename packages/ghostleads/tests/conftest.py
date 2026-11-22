"""Shared helpers for GhostLeads tests.

The core is run as a local subprocess only, exactly as a user would:
``ghostleads`` on PATH if installed, else ``python -m ghostleads``
with ``src/`` on PYTHONPATH. If no entrypoint exists the behavioural
tests FAIL with a clear "core not ready" message. They do not skip,
so a missing build cannot fake a green run.

All behavioural tests work against copies of fixtures in pytest tmp
dirs and a store file inside the tmp dir. Checked-in fixtures and any
real lead list are never written to by a run.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _entrypoint():
    exe = shutil.which("ghostleads")
    if exe:
        return [exe]
    if (SRC / "ghostleads" / "__main__.py").exists() or \
            (SRC / "ghostleads" / "cli.py").exists() or \
            (SRC / "ghostleads" / "__init__.py").exists():
        return [sys.executable, "-m", "ghostleads"]
    return None


def run_cli(args, cwd=None, check=False):
    cmd = _entrypoint()
    assert cmd is not None, (
        "core not ready: no ghostleads entrypoint found "
        "(not on PATH and no src/ghostleads module)")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        cmd + [str(a) for a in args],
        cwd=str(cwd) if cwd else str(ROOT),
        env=env, capture_output=True, text=True, timeout=60)
    if check:
        assert proc.returncode == 0, out_text(proc)
    return proc


def out_text(proc):
    return (proc.stdout or "") + (proc.stderr or "")


def import_leads(tmp_path, fixture_name, store_name="leads.json"):
    """Copy a fixture into tmp_path and import it into a fresh store."""
    src = FIXTURES / fixture_name
    local = Path(tmp_path) / fixture_name
    local.write_bytes(src.read_bytes())
    store = Path(tmp_path) / store_name
    proc = run_cli(["import", local, "--store", store])
    return proc, store


def records_from_json_text(text):
    """Normalise the many plausible JSON shapes to a list of dicts."""
    data = json.loads(text)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("leads", "results", "records", "items", "scored"):
            if isinstance(data.get(key), list):
                return data[key]
        # A single record object.
        if "name" in data:
            return [data]
    raise AssertionError(f"could not find a lead list in JSON: {text[:400]}")


def score_records(store):
    proc = run_cli(["score", "--store", store, "--json"])
    assert proc.returncode == 0, out_text(proc)
    try:
        return records_from_json_text(proc.stdout)
    except Exception:
        # Fall back to the human table plus list --json for structure.
        proc2 = run_cli(["list", "--store", store, "--json"])
        assert proc2.returncode == 0, out_text(proc2)
        return records_from_json_text(proc2.stdout)


def list_records(store, *extra):
    proc = run_cli(["list", "--store", store, "--json", *extra])
    assert proc.returncode == 0, out_text(proc)
    return records_from_json_text(proc.stdout)


def find_record(records, name_part):
    part = name_part.lower()
    for rec in records:
        if part in str(rec.get("name", "")).lower():
            return rec
    raise AssertionError(
        f"no record matching {name_part!r} in "
        f"{[r.get('name') for r in records]}")


def pack(store, out_dir, *extra):
    return run_cli(["pack", "--store", store, "--out", out_dir, *extra])


def pack_texts(out_dir):
    """Return {filename: text} for every markdown pack in out_dir."""
    out = {}
    for p in sorted(Path(out_dir).rglob("*.md")):
        out[p.name] = p.read_text(errors="replace")
    return out


def all_pack_text(out_dir):
    return "\n".join(pack_texts(out_dir).values())
