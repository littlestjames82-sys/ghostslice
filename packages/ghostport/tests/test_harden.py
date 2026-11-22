"""Hardening regression tests (improve wave 2026-10-18, lane: harden).

Each test pins a real bug found by probing the pre-fix code; the class
docstrings name the original failure. Stdlib unittest only, same style
as the rest of the suite. Layer-2 style: imports src/ directly.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from ghostport.bundle import build_unit_bundle, signatures_slice  # noqa: E402
from ghostport.graph import form_units, imports_of  # noqa: E402
from ghostport.ledger import record_verified, unit_states, validate_verify_report  # noqa: E402
from ghostport.patterns import PackError, load_pack, validate_pack  # noqa: E402
from ghostport.profile import ProfileError, load_port_profile  # noqa: E402
from ghostport.scanner import scan_file, scan_project  # noqa: E402
from ghostport.status import build_status  # noqa: E402


def _write(path: pathlib.Path, text: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _plan(units):
    return {"units": units, "profile": {}}


class TestForgedVerifiedDowngraded(unittest.TestCase):
    """A hand-edited ledger line {"state": "verified"} with no GhostVerify
    report used to make status report the unit as verified, breaking the
    hard rule on the read path (record_state refusing it was not enough)."""

    def test_forged_verified_counts_as_claim_not_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = pathlib.Path(tmp)
            _write(proj / "port-plan.json", json.dumps(
                {"units": [{"id": "unit-a", "order": 1, "estimated_tokens": 10}]}))
            _write(proj / ".ghostport-history.jsonl",
                   json.dumps({"unit": "unit-a", "state": "verified"}) + "\n")
            status = build_status(proj)
            self.assertEqual(status["verified_units"], 0)
            self.assertEqual(status["counts"].get("verified", 0), 0)
            self.assertEqual(status["estimated_tokens_remaining"], 10)

    def test_real_verified_record_still_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = pathlib.Path(tmp)
            report = _write(proj / "report.json", json.dumps(
                {"tool": "ghostverify", "kind": "post", "verdict": "ok",
                 "project": str(proj), "bundle": "b"}))
            record_verified(proj, "unit-a", report)
            self.assertEqual(unit_states(proj)["unit-a"], "verified")


class TestVerifyReportValidation(unittest.TestCase):
    """validate_verify_report documented an identity requirement it did not
    enforce, rejected the real GhostVerify post verdict "ok", and accepted
    contradictory ok/verdict combinations."""

    def _report(self, tmp, data):
        return _write(pathlib.Path(tmp) / "r.json", json.dumps(data))

    def test_real_post_shape_verdict_ok_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._report(tmp, {"tool": "ghostverify", "kind": "post",
                                      "verdict": "ok", "exit_code": 0,
                                      "project": "/p", "bundle": "/b"})
            self.assertEqual(validate_verify_report(path)["verdict"], "ok")

    def test_bare_ok_true_without_identity_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._report(tmp, {"ok": True})
            with self.assertRaises(ValueError):
                validate_verify_report(path)

    def test_contradictory_reports_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            for data in ({"ok": True, "verdict": "failed", "project": "/p"},
                         {"ok": False, "verdict": "pass", "project": "/p"}):
                path = self._report(tmp, data)
                with self.assertRaises(ValueError, msg=str(data)):
                    validate_verify_report(path)


class TestLedgerRobustness(unittest.TestCase):
    """Non-object JSON lines crashed unit_states with TypeError; invalid
    UTF-8 crashed read_records with UnicodeDecodeError; unknown states
    flowed into status counts."""

    def test_corrupt_lines_are_skipped_valid_lines_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = pathlib.Path(tmp)
            _write(proj / "port-plan.json", json.dumps(
                {"units": [{"id": "unit-a", "order": 1, "estimated_tokens": 3}]}))
            ledger = proj / ".ghostport-history.jsonl"
            ledger.write_bytes(
                b"123\n\"just a string\"\n\xff\xfe garbage\n"
                + json.dumps({"unit": "unit-a", "state": "bogus-state"}).encode()
                + b"\n" + json.dumps({"unit": "unit-a", "state": "bundled"}).encode() + b"\n")
            status = build_status(proj)
            self.assertEqual(status["units"][0]["state"], "bundled")
            self.assertNotIn("bogus-state", status["counts"])


class TestStatusMalformedPlan(unittest.TestCase):
    """A non-object port-plan.json crashed with AttributeError and a unit
    missing estimated_tokens crashed with KeyError; neither is caught as a
    clean CLI error (exit 2) by main()."""

    def test_non_object_plan_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = pathlib.Path(tmp)
            _write(proj / "port-plan.json", "123")
            with self.assertRaises(ValueError):
                build_status(proj)

    def test_unit_missing_tokens_defaults_to_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = pathlib.Path(tmp)
            _write(proj / "port-plan.json", json.dumps({"units": [{"id": "unit-a"}]}))
            status = build_status(proj)
            self.assertEqual(status["units"][0]["estimated_tokens"], 0)


class TestScannerRecursion(unittest.TestCase):
    """ast.parse on a deeply chained expression raises RecursionError,
    which escaped scan_file and killed the whole scan."""

    def test_deep_expression_is_a_parse_error_not_a_crash(self):
        pack = load_pack("python-upgrade")
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(pathlib.Path(tmp) / "deep.py", "x = " + "1 + " * 100000 + "1\n")
            hits, err = scan_file(path, pack)
            self.assertEqual(hits, [])
            self.assertIsNotNone(err)
            result = scan_project(pathlib.Path(tmp), pack)
            self.assertEqual(len(result["parse_errors"]), 1)

    def test_signatures_slice_survives_deep_expression(self):
        text = "x = " + "1 + " * 100000 + "1\n"
        self.assertEqual(signatures_slice(text), text)


class TestGraphHardening(unittest.TestCase):
    """form_units raised StopIteration when two files collapsed to one
    module name (foo.py and src/foo.py); imports_of never filtered a
    nested file's self-import (it compared a relative path to a basename)."""

    def test_duplicate_module_names_do_not_crash_form_units(self):
        pack = load_pack("python-upgrade")
        with tempfile.TemporaryDirectory() as tmp:
            proj = pathlib.Path(tmp)
            _write(proj / "foo.py", "import imp\n")
            _write(proj / "src" / "foo.py", "import imp\n")
            scan = scan_project(proj, pack)
            self.assertEqual(len(scan["hits"]), 2)
            formed = form_units(proj, scan, {})
            self.assertEqual(sum(u["hit_count"] for u in formed["units"]), 2)

    def test_self_import_is_not_a_dependency(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = pathlib.Path(tmp)
            _write(proj / "pkg" / "__init__.py", "")
            mod = _write(proj / "pkg" / "mod.py", "import pkg.mod\n")
            module_map = {"pkg": "pkg/__init__.py", "pkg.mod": "pkg/mod.py"}
            self.assertNotIn("pkg/mod.py", imports_of(mod, "pkg.mod", module_map))


class TestBundleContainment(unittest.TestCase):
    """A plan entry "../evil.py" was read from outside the project, copied
    into PROMPT.md, and written outside the bundle's files/ directory."""

    def test_traversal_entry_is_refused_and_nothing_escapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            proj = root / "proj"
            proj.mkdir()
            _write(proj / "a.py", "import imp\n")
            _write(root / "evil.py", "SECRET = 1\n")
            plan = _plan([{"id": "unit-a", "order": 1, "files": ["../evil.py"],
                           "hits": [], "depends_on_units": [], "caller_units": [],
                           "covering_tests": [], "covering_test_method": "none",
                           "combined_from_cycle": False, "cycle_files": []}])
            out = root / "out"
            with self.assertRaises(ValueError):
                build_unit_bundle(proj, plan, "unit-a", out)
            self.assertFalse((out / "evil.py").exists())
            prompt = out / "PROMPT.md"
            if prompt.is_file():
                self.assertNotIn("SECRET", prompt.read_text(encoding="utf-8"))


class TestPackValidation(unittest.TestCase):
    """Matcher fields were not type-checked: names="getargspec" (a string)
    loaded and then matched by substring in the scanner. Pack ids with
    path traversal walked out of the pack search directories."""

    def _pack_data(self, matcher):
        return {"id": "x", "title": "t", "version": "1", "date": "2026-01-01",
                "language": "python", "target": "t",
                "patterns": [{"id": "P1", "description": "d", "reference": "r",
                              "reference_date": "2026-01-01", "reference_url": "u",
                              "matcher": matcher}]}

    def test_string_names_rejected(self):
        with self.assertRaises(PackError):
            validate_pack(self._pack_data({"kind": "attribute", "names": "getargspec"}))

    def test_missing_modules_rejected(self):
        with self.assertRaises(PackError):
            validate_pack(self._pack_data({"kind": "import_module"}))

    def test_traversal_pack_id_rejected(self):
        with self.assertRaises(PackError):
            load_pack("../../etc/passwd")

    def test_builtin_pack_still_valid(self):
        self.assertEqual(load_pack("python-upgrade").id, "python-upgrade")


class TestProfileValidation(unittest.TestCase):
    """Wrongly typed profile values were accepted and then crashed or
    silently misbehaved in unit formation (a string "merge" iterated
    character by character)."""

    def _profile(self, tmp, section):
        proj = pathlib.Path(tmp)
        _write(proj / ".ghostslice.json", json.dumps({"port": section}))
        return proj

    def test_string_merge_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ProfileError):
                load_port_profile(self._profile(tmp, {"merge": "unit-a"}))

    def test_string_budget_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ProfileError):
                load_port_profile(self._profile(tmp, {"budget_tokens": "20000"}))

    def test_valid_profile_still_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            prof = load_port_profile(self._profile(
                tmp, {"pack": "python-upgrade", "budget_tokens": 20000,
                      "merge": [["unit-a", "unit-b"]], "pin_first": ["unit-a"],
                      "test_command": None}))
            self.assertEqual(prof["budget_tokens"], 20000)


if __name__ == "__main__":
    unittest.main()
