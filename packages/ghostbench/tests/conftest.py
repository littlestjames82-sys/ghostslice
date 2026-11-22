import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
EXAMPLES = REPO / "examples"

CORE_AVAILABLE = (SRC / "ghostbench" / "__init__.py").exists()

import pytest

requires_core = pytest.mark.skipif(
    not CORE_AVAILABLE,
    reason="ghostbench core (src/ghostbench) not present yet: Agent A build pending. "
    "See REPORT_B.md assumptions. Fixture/format tests still run.",
)


def run_cli(args, *, stdin=None, timeout=120, env_remove=(), env_extra=None):
    """Run the GhostBench CLI as a black box: python -m ghostbench ..."""
    env = dict(os.environ)
    for key in env_remove:
        env.pop(key, None)
    for key, value in (env_extra or {}).items():
        env[key] = value
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "ghostbench", *[str(a) for a in args]],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=REPO,
        env=env,
        timeout=timeout,
    )


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def copy_corpus(src_dir, dst_dir):
    import shutil

    shutil.copytree(src_dir, dst_dir)
    return Path(dst_dir)
