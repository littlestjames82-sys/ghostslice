"""v0.7 (G2): task selection v2 — symbol matching + graph boosting.

Golden tests for the two signal layers on top of TF-IDF:
(a) a symbol-name match beats more body mentions,
(b) a graph boost pulls in the direct dependency of the top file,
(c) the boost is capped/max-based — a hub imported by everything is
    not dragged in by popularity,
(d) the v0.5 TF-IDF A/B outcome (rare word beats common) is unchanged.
Plus: budget is never exceeded by boosts, determinism, robustness on
unparseable/odd files, and the manifest/CLI score breakdown.
"""
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostslice.cli import main as cli_main
from ghostslice.exporter import build_bundle, validate_bundle
from ghostslice.selection import (
    GRAPH_BOOST_CAP, GRAPH_BOOST_FRACTION, SYMBOL_CAP, SYMBOL_EXACT_BONUS,
    SYMBOL_PART_BONUS, _any_keyword_part_in, _keyword_parts,
    _keyword_parts_in, select_for_task,
    select_for_task_breakdown, split_symbol_name, symbols_for_source)
from ghostslice.slicer import slice_text


def _proj(files: dict[str, str]) -> tempfile.TemporaryDirectory:
    td = tempfile.TemporaryDirectory()
    root = Path(td.name)
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    td.root = root  # type: ignore[attr-defined]
    return td


SYM_PROJ = {
    "sym.py": (
        "def render_invoice(doc):\n"
        "    return render(doc)\n"
        "\n"
        "def render(doc):\n"
        "    return str(doc)\n"
    ),
    "body.py": "# invoice invoice invoice invoice\nVALUE = 1\n",
    "filler.py": "X = 1\n",
}


class TestSymbolMatching(unittest.TestCase):
    def test_symbol_match_beats_body_mentions(self):
        with _proj(SYM_PROJ) as root:
            _r, _s, chosen, bd = select_for_task_breakdown(root, "invoice")
            # sym.py's only relevance is the symbol render_invoice: the
            # body counter tokenises it as one word, so tfidf is 0.
            self.assertEqual(chosen[0], "sym.py")
            self.assertEqual(bd["sym.py"]["tfidf"], 0.0)
            self.assertEqual(bd["sym.py"]["symbol"], SYMBOL_PART_BONUS)
            # body.py has 4 real mentions but no symbol: strictly less.
            self.assertGreater(bd["body.py"]["tfidf"], 0.0)
            self.assertEqual(bd["body.py"]["symbol"], 0.0)
            self.assertLess(bd["body.py"]["total"], bd["sym.py"]["total"])
            self.assertEqual(bd["sym.py"]["graph"], 0.0)

    def test_exact_symbol_name_tier(self):
        with _proj({
            "models.py": "class Invoice:\n    def total(self):\n        return 0\n",
            "filler.py": "X = 1\n",
        }) as root:
            _r, _s, chosen, bd = select_for_task_breakdown(root, "invoice")
            self.assertEqual(chosen[0], "models.py")
            self.assertEqual(bd["models.py"]["symbol"], SYMBOL_EXACT_BONUS)

    def test_full_snake_name_is_exact_not_parts(self):
        with _proj(SYM_PROJ) as root:
            _r, _s, chosen, bd = select_for_task_breakdown(root, "render_invoice")
            self.assertEqual(chosen, ["sym.py"])
            self.assertEqual(bd["sym.py"]["symbol"], SYMBOL_EXACT_BONUS)

    def test_symbol_component_capped(self):
        body = "".join(f"def {w}_thing():\n    return 1\n\n"
                       for w in ("alpha", "beta", "gamma", "delta"))
        with _proj({"cap.py": body, "filler.py": "X = 1\n"}) as root:
            _r, _s, _c, bd = select_for_task_breakdown(
                root, "alpha beta gamma delta")
            # 4 part matches x SYMBOL_PART_BONUS = 40, capped at 25.
            self.assertEqual(bd["cap.py"]["symbol"], SYMBOL_CAP)

    def test_lite_language_symbol_via_slicer_signatures(self):
        src = "export function billingHelper(name: string) {\n  return name;\n}\n"
        self.assertIn("billingHelper", symbols_for_source("typescript", src, "t.ts"))
        with _proj({
            "tsym.ts": src,
            "body.ts": "// billing billing billing billing\nconst x = 1;\n",
            "filler.py": "X = 1\n",
        }) as root:
            _r, _s, chosen, bd = select_for_task_breakdown(root, "billing")
            self.assertEqual(chosen[0], "tsym.ts")
            self.assertEqual(bd["tsym.ts"]["symbol"], SYMBOL_PART_BONUS)
            self.assertEqual(bd["tsym.ts"]["tfidf"], 0.0)

    def test_split_symbol_name(self):
        self.assertEqual(split_symbol_name("render_invoice"),
                         {"render", "invoice", "render_invoice"})
        self.assertEqual(split_symbol_name("HTTPServer"),
                         {"http", "server", "httpserver"})
        self.assertEqual(split_symbol_name("processPayment"),
                         {"process", "payment", "processpayment"})


GRAPH_PROJ = {
    "feat.py": (
        "import util\n"
        "\n"
        "# billing billing billing billing billing\n"
        "def feature():\n"
        "    return util.compute()\n"
    ),
    "util.py": "def compute():\n    return 42\n",
    "caller.py": "import feat\n\ndef run():\n    return feat.feature()\n",
    "other.py": "X = 1\n",
}


class TestGraphBoost(unittest.TestCase):
    def test_boost_pulls_in_dependency_and_importer(self):
        with _proj(GRAPH_PROJ) as root:
            _r, selections, chosen, bd = select_for_task_breakdown(root, "billing")
            self.assertEqual(chosen[0], "feat.py")
            seed_total = bd["feat.py"]["total"]
            expected = min(GRAPH_BOOST_CAP, GRAPH_BOOST_FRACTION * seed_total)
            # Direct dependency (feat imports util): zero text relevance,
            # included purely on the graph component.
            self.assertIn("util.py", chosen)
            self.assertEqual(bd["util.py"]["tfidf"], 0.0)
            self.assertEqual(bd["util.py"]["symbol"], 0.0)
            self.assertAlmostEqual(bd["util.py"]["graph"], expected, places=3)
            # Direct importer (caller imports feat) is boosted the same way.
            self.assertIn("caller.py", chosen)
            self.assertAlmostEqual(bd["caller.py"]["graph"], expected, places=3)
            # Unrelated file stays out.
            self.assertNotIn("other.py", chosen)

    def test_boost_respects_budget_exactly(self):
        with _proj(GRAPH_PROJ) as root:
            _r, selections, _c, _bd = select_for_task_breakdown(root, "billing")
            rootp = Path(root)
            stoks = {}
            for rel, mode in selections.items():
                text = (rootp / rel).read_text()
                stoks[rel] = slice_text(rel, text, mode).sliced_tokens
            full = sum(stoks[r] for r in ("feat.py", "caller.py", "util.py"))
            # Budget for everything: all three in.
            _r, _s, chosen_all, _b = select_for_task_breakdown(
                root, "billing", budget=full)
            self.assertEqual(set(chosen_all), {"feat.py", "caller.py", "util.py"})
            # One token less: the last boosted candidate (util, smaller
            # than caller at equal boost) no longer fits.
            _r, _s, chosen_less, _b = select_for_task_breakdown(
                root, "billing", budget=full - 1)
            self.assertEqual(chosen_less, ["feat.py", "caller.py"])
            spent = sum(stoks[r] for r in chosen_less)
            self.assertLessEqual(spent, full - 1)
            # Budget for the seed alone: no boosted file is added, and
            # the best-file rule still includes the seed itself.
            _r, _s, chosen_seed, _b = select_for_task_breakdown(
                root, "billing", budget=stoks["feat.py"])
            self.assertEqual(chosen_seed, ["feat.py"])


HUB_PROJ = {
    "hub.py": "def shared():\n    return 1\n",
    "s1.py": "import hub\n\n# billing billing billing\ndef a():\n    return hub.shared()\n",
    "s2.py": "import hub\n\n# billing billing\ndef b():\n    return hub.shared()\n",
    "s3.py": "import hub\n\n# billing\ndef c():\n    return hub.shared()\n",
    "noise.py": "Y = 2\n",
}


class TestGraphBoostCap(unittest.TestCase):
    def test_hub_boost_is_max_not_sum(self):
        with _proj(HUB_PROJ) as root:
            _r, _s, chosen, bd = select_for_task_breakdown(root, "billing")
            self.assertIn("hub.py", chosen)
            seed_totals = [bd[s]["total"] for s in ("s1.py", "s2.py", "s3.py")]
            expected = min(GRAPH_BOOST_CAP,
                           GRAPH_BOOST_FRACTION * max(seed_totals))
            sum_based = GRAPH_BOOST_FRACTION * sum(seed_totals)
            self.assertAlmostEqual(bd["hub.py"]["graph"], expected, places=3)
            self.assertLess(bd["hub.py"]["graph"], sum_based - 0.5)

    def test_popularity_alone_does_not_drag_hub_in(self):
        with _proj(HUB_PROJ) as root:
            # Budget 1: only the best seed is taken (best-file rule);
            # the hub's four importers earn it nothing extra.
            _r, _s, chosen, _bd = select_for_task_breakdown(
                root, "billing", budget=1)
            self.assertEqual(chosen, ["s1.py"])


class TestBackwardCompat(unittest.TestCase):
    def test_v05_tfidf_ab_outcome_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "heavy.py").write_text('WORDS = "alpha alpha alpha alpha alpha"\n')
            (root / "rare.py").write_text('WORDS = "alpha omega omega omega"\n')
            for i in range(8):
                (root / f"filler_{i}.py").write_text('WORDS = "alpha"\n')
            _r, _s, chosen, scores = select_for_task(root, "alpha omega")
            self.assertEqual(chosen[0], "rare.py")
            self.assertGreater(scores["rare.py"], scores["heavy.py"])
            self.assertIsInstance(scores["rare.py"], float)
            # Breakdown totals agree with the legacy scores dict.
            _r, _s, chosen2, bd = select_for_task_breakdown(root, "alpha omega")
            self.assertEqual(chosen2, chosen)
            for path, total in scores.items():
                self.assertEqual(bd[path]["total"], total)

    def test_deterministic_across_runs(self):
        with _proj(GRAPH_PROJ) as root:
            a = select_for_task_breakdown(root, "billing")
            b = select_for_task_breakdown(root, "billing")
            self.assertEqual(a[2], b[2])
            self.assertEqual(a[3], b[3])


class TestRobustness(unittest.TestCase):
    def test_unparseable_python_and_weird_files_do_not_crash(self):
        with _proj({
            "broken.py": "def nope(:\n    invoice invoice invoice\n",
            "empty.py": "",
            "odd.py": "x = 'invoice'\n",
            "plain.txt": "invoice invoice\n",
        }) as root:
            _r, _s, chosen, bd = select_for_task_breakdown(root, "invoice")
            self.assertIn("broken.py", chosen)
            # Symbols still extracted from the fallback def lines.
            self.assertIn("nope", symbols_for_source(
                "python", "def nope(:\n    pass\n"))

    def test_symbol_extraction_never_raises(self):
        for lang, src in [
            ("python", "def f(:"),
            ("typescript", "function {"),
            ("go", "func ("),
            ("rust", "fn "),
            ("java", "class {"),
            ("csharp", "namespace {"),
            ("php", "<?php function "),
            ("ruby", "def "),
            ("kotlin", "fun "),
            ("swift", "func "),
        ]:
            symbols_for_source(lang, src, f"x.{lang}")  # must not raise


class TestBreakdownSurfaces(unittest.TestCase):
    def test_manifest_carries_score_components(self):
        with _proj(GRAPH_PROJ) as root:
            _r, selections, chosen, bd = select_for_task_breakdown(root, "billing")
            task_scores = {rel: bd[rel] for rel in chosen}
            out = Path(root) / "bundle"
            m = build_bundle(root, out, selections=selections,
                             include=set(chosen), record_history=False,
                             task_scores=task_scores)
            self.assertTrue(validate_bundle(out)["ok"])
            by_path = {f["path"]: f for f in m["files"]}
            self.assertEqual(by_path["feat.py"]["score"], bd["feat.py"]["total"])
            self.assertEqual(by_path["feat.py"]["score_components"]["symbol"],
                             bd["feat.py"]["symbol"])
            self.assertEqual(by_path["util.py"]["score_components"]["graph"],
                             bd["util.py"]["graph"])
            # Files outside the task selection carry no score fields.
            self.assertNotIn("score", by_path["other.py"])

    def test_manifest_without_task_scores_unchanged(self):
        with _proj(GRAPH_PROJ) as root:
            out = Path(root) / "bundle"
            m = build_bundle(root, out, record_history=False)
            for f in m["files"]:
                self.assertNotIn("score", f)
                self.assertNotIn("score_components", f)

    def test_cli_task_prints_breakdown_and_manifest(self):
        with _proj(GRAPH_PROJ) as root:
            out = Path(root) / "bundle"
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli_main(["task", str(root), "--task", "billing",
                               "-o", str(out)])
            self.assertEqual(rc, 0)
            text = buf.getvalue()
            self.assertIn("tfidf", text)
            self.assertIn("symbol", text)
            self.assertIn("graph", text)
            import json
            manifest = json.loads((out / "manifest.json").read_text())
            by_path = {f["path"]: f for f in manifest["files"]}
            self.assertIn("score_components", by_path["feat.py"])
            self.assertTrue(validate_bundle(out)["ok"])


class TestImproveRound1(unittest.TestCase):
    """G02 Audit #1 fixes: F1 constants are symbols, F2 extract gate."""

    def test_module_and_class_constants_are_symbols(self):
        syms = symbols_for_source(
            "python",
            "INVOICE_LIMIT = 5\n"
            "class Config:\n"
            "    invoice_retries = 3\n"
            "    LIMIT, COUNT = 1, 2\n"
            "other_total: int = 9\n")
        self.assertIn("INVOICE_LIMIT", syms)
        self.assertIn("invoice_retries", syms)
        self.assertIn("LIMIT", syms)
        self.assertIn("COUNT", syms)
        self.assertIn("other_total", syms)

    def test_constant_match_earns_symbol_bonus(self):
        with _proj({
            "consts.py": "INVOICE_LIMIT = 5\n",
            "filler.py": "X = 1\n",
        }) as root:
            _r, _s, chosen, bd = select_for_task_breakdown(root, "invoice")
            self.assertEqual(chosen[0], "consts.py")
            self.assertEqual(bd["consts.py"]["tfidf"], 0.0)
            self.assertEqual(bd["consts.py"]["symbol"], SYMBOL_PART_BONUS)

    def test_function_local_assignment_is_not_a_symbol(self):
        syms = symbols_for_source(
            "python", "def f():\n    invoice = compute()\n    return invoice\n")
        self.assertNotIn("invoice", syms)
        self.assertIn("f", syms)
        with _proj({
            "local.py": "def f():\n    invoice = 1\n    return invoice\n",
            "filler.py": "X = 1\n",
        }) as root:
            _r, _s, _c, bd = select_for_task_breakdown(root, "invoice")
            # The body mentions still earn TF-IDF; the symbol layer
            # stays silent for a mere local variable.
            self.assertEqual(bd["local.py"]["symbol"], 0.0)
            self.assertGreater(bd["local.py"]["tfidf"], 0.0)

    def test_attribute_and_subscript_targets_bind_no_name(self):
        syms = symbols_for_source(
            "python", "obj.invoice = 1\nstore['invoice'] = 2\n")
        self.assertNotIn("obj", syms)
        self.assertNotIn("store", syms)

    def test_symbol_gate_precomputed_parts_agree(self):
        # G02 Audit #2 G1: selection precomputes the keyword parts
        # once; the parts path must agree with the wrapper everywhere.
        parts = _keyword_parts(["render_invoice", "server"])
        for text in ("def render_invoice(doc):", "httpserver",
                     "the invoice module", "completely unrelated"):
            self.assertEqual(
                _keyword_parts_in(parts, text),
                _any_keyword_part_in(["render_invoice", "server"], text),
                msg=text)

    def test_symbol_gate(self):
        self.assertFalse(_any_keyword_part_in(
            ["invoice"], "nothing relevant in this text"))
        self.assertTrue(_any_keyword_part_in(
            ["invoice"], "def render_invoice(doc):"))
        # camelCase part of a keyword can hide inside a longer name.
        self.assertTrue(_any_keyword_part_in(["server"], "httpserver"))
        # snake keyword: any one part appearing is enough to open.
        self.assertTrue(_any_keyword_part_in(
            ["render_invoice"], "the invoice module"))
        self.assertFalse(_any_keyword_part_in(
            ["render_invoice"], "completely unrelated words"))


if __name__ == "__main__":
    unittest.main()
