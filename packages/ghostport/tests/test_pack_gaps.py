"""Former known-gap tests against the v1.0.0 pack, now regression tests.

These two tests encode behaviour the PLAN's verification bar implies
(a pattern must hit the real-world form of the deprecated API). They
were written against two real gaps found by Agent B while reconciling
the fixtures to Agent A's pack on Oct 14, 2026 (see REPORT_B.md):

1. PYUP005 (distutils) uses an ``import_module`` matcher. The scanner
   originally matched ``from X import ...`` only when the module equalled
   the listed name exactly, so the idiomatic
   ``from distutils.core import setup`` produced NO hit.
2. PYUP007 (threading camelCase) listed currentThread / activeCount /
   isDaemon / setDaemon, but not ``isAlive`` - ``Thread.isAlive()`` was
   removed in Python 3.10 on the same cleanup the pattern cites.

Both gaps were fixed by the core owner (see FIX_REPORT.md: the scanner
now matches a listed module or any submodule of it, and ``isAlive`` was
added to PYUP007). Both tests now PASS and are kept in the suite,
unskipped, as regression tests so the gaps cannot silently return.
"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _helpers import CORE_AVAILABLE, PACK_ID, SKIP_CORE, run_cli  # noqa: E402


@unittest.skipUnless(CORE_AVAILABLE, SKIP_CORE)
class TestKnownPackGaps(unittest.TestCase):
    def _scan_single_file(self, source: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            proj = pathlib.Path(tmp)
            (proj / "only.py").write_text(source, encoding="utf-8")
            proc = run_cli(["scan", str(proj), "--pack", PACK_ID])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return proc.stdout + proc.stderr

    def test_distutils_from_import_form_is_hit(self):
        out = self._scan_single_file(
            "from distutils.core import setup\n\nsetup(name='x')\n"
        )
        self.assertIn("PYUP005", out)

    def test_threading_isalive_is_hit(self):
        out = self._scan_single_file(
            "import threading\n\n\ndef f(t):\n    return t.isAlive()\n"
        )
        self.assertIn("PYUP007", out)


if __name__ == "__main__":
    unittest.main()
