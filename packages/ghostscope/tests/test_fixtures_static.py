"""Static validation of the fixtures themselves.

These tests do NOT need the GhostScope core. They prove each planted
fixture actually has the property the Verification bar in PLAN.md relies
on, so an integration failure cannot be blamed on a broken fixture.
"""
import ast
import re
import unittest
from pathlib import Path

from tests.helpers import FIXTURES


def callers_of(base: Path, symbol: str):
    hits = []
    for py in sorted(base.rglob("*.py")):
        if py.name.startswith("test_"):
            continue
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
                if name == symbol:
                    hits.append(py.name)
    return hits


class TestHighBlastFixture(unittest.TestCase):
    base = FIXTURES / "high_blast_radius" / "base"
    change = FIXTURES / "high_blast_radius" / "change"

    def test_shared_function_has_many_callers(self):
        self.assertGreaterEqual(len(callers_of(self.base, "compute_total")), 6)

    def test_shared_is_exported(self):
        self.assertIn("compute_total", (self.base / "shared.py").read_text())
        self.assertIn("__all__", (self.base / "shared.py").read_text())

    def test_shared_change_is_one_line(self):
        a = (self.base / "shared.py").read_text().splitlines()
        b = (self.change / "shared.py").read_text().splitlines()
        self.assertEqual(len(a), len(b))
        diff = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        self.assertEqual(len(diff), 1, f"expected a one-line change, got lines {diff}")

    def test_isolated_change_is_200_plus_lines(self):
        lines = (self.change / "isolated.py").read_text().splitlines()
        self.assertGreaterEqual(len(lines), 200)

    def test_isolated_has_no_callers_in_base(self):
        self.assertEqual(callers_of(self.base, "isolated_thing"), [])

    def test_covering_test_exists(self):
        self.assertIn("compute_total", (self.base / "tests" / "test_shared.py").read_text())


class TestSignatureChangeFixture(unittest.TestCase):
    base = FIXTURES / "signature_change_stale_caller" / "base"
    change = FIXTURES / "signature_change_stale_caller" / "change"

    def _arity(self, path):
        tree = ast.parse(Path(path).read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
        return len(fn.args.args)

    def test_signature_gains_a_required_parameter(self):
        self.assertEqual(self._arity(self.base / "api.py"), 2)
        self.assertEqual(self._arity(self.change / "api.py"), 3)

    def test_callers_were_not_updated(self):
        # No caller overlay in change/: the stale state is the fixture.
        self.assertFalse((self.change / "consumer.py").exists())
        self.assertFalse((self.change / "other_caller.py").exists())

    def test_callers_still_call_with_old_arity(self):
        for name in ("consumer.py", "other_caller.py"):
            text = (self.base / name).read_text()
            self.assertRegex(text, re.compile(r"format_name\([^)]*,[^)]*\)"))


class TestDeletedCoveringTestFixture(unittest.TestCase):
    root = FIXTURES / "deleted_covering_test"

    def test_covering_test_exists_in_base(self):
        t = self.root / "base" / "tests" / "test_billing.py"
        self.assertTrue(t.exists())
        self.assertIn("charge", t.read_text())

    def test_deletion_is_declared(self):
        deletions = (self.root / "deletions.txt").read_text()
        self.assertIn("tests/test_billing.py", deletions)

    def test_billing_changed(self):
        self.assertNotEqual(
            (self.root / "base" / "billing.py").read_text(),
            (self.root / "change" / "billing.py").read_text(),
        )


if __name__ == "__main__":
    unittest.main()
