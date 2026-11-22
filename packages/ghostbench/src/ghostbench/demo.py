"""Starter demo corpus generator.

Writes a small adversarial project + corpus file into a target
directory the USER chooses (never into Bench's own tree). The
adversarial fixtures are deliberate:
- a widely-called helper in a file that is easy to exclude,
- near-duplicate modules,
- one task whose recorded patch touches NO expected file and whose
  Verify report predicts a hard gap, so a first run visibly fails
  somewhere (PLAN.md honesty test: a report with zero failures
  everywhere means the corpus is too easy).
"""
from __future__ import annotations

import json
import os

CORE = '''"""Core helpers."""


def helper(x):
    """Return x doubled."""
    return x * 2


def main_value():
    return helper(21)
'''

DUP_A = '''"""Reporting helpers (original)."""


def report_lines(name, total):
    lines = []
    lines.append("report for " + name)
    lines.append("total: " + str(total))
    lines.append("status: ok")
    return lines
'''

DUP_B = '''"""Reporting helpers (edited copy, near-duplicate)."""


def report_lines(name, total):
    lines = []
    lines.append("report for " + name)
    lines.append("total: " + str(total))
    lines.append("status: ok")
    lines.append("copy: b")
    return lines
'''

UNUSED = '''"""Legacy module kept in the tree, referenced by nothing."""


def legacy_a():
    return "a" * 50


def legacy_b():
    return "b" * 50


def legacy_c():
    return "c" * 50
'''

GOOD_PATCH = """--- a/src/core.py
+++ b/src/core.py
@@ -4,7 +4,7 @@
 
 def helper(x):
     \"\"\"Return x doubled.\"\"\"
-    return x * 2
+    return x * 2 + 0
 
 
 def main_value():
"""

BAD_PATCH = """--- a/src/unused.py
+++ b/src/unused.py
@@ -4,7 +4,7 @@
 
 def legacy_a():
-    return "a" * 50
+    return "a" * 51
"""

VERIFY_BAD = {
    "verdict": "insufficient",
    "hard_gaps": [
        {"file": "src/core.py", "symbol": "helper",
         "severity": "hard",
         "reason": "called by the task target but excluded from the slice"}
    ],
    "soft_gaps": [],
}


def make_demo_corpus(target_dir: str) -> str:
    """Write the starter demo corpus into ``target_dir``.

    Creates the adversarial project, two recorded patches, one Verify
    report, and ``corpus.json`` under that directory. Returns the
    corpus file path, ready for ``ghostbench run <path>``. One of the
    two demo tasks is designed to fail visibly (see the module
    docstring).
    """
    root = os.path.abspath(target_dir)
    proj = os.path.join(root, "projects", "adversarial")
    os.makedirs(os.path.join(proj, "src"), exist_ok=True)
    os.makedirs(os.path.join(root, "patches"), exist_ok=True)
    os.makedirs(os.path.join(root, "verify"), exist_ok=True)
    files = {
        os.path.join(proj, "src", "core.py"): CORE,
        os.path.join(proj, "src", "dup_a.py"): DUP_A,
        os.path.join(proj, "src", "dup_b.py"): DUP_B,
        os.path.join(proj, "src", "unused.py"): UNUSED,
        os.path.join(root, "patches", "fix-helper.diff"): GOOD_PATCH,
        os.path.join(root, "patches", "wrong-file.diff"): BAD_PATCH,
    }
    for path, text in files.items():
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(root, "verify", "fix-helper-gap.json"),
              "w", encoding="utf-8") as fh:
        json.dump(VERIFY_BAD, fh, indent=2)
    corpus = {
        "name": "ghostbench-demo",
        "version": "1",
        "projects": [{
            "id": "adversarial",
            "path": "projects/adversarial",
            "tasks": [
                {
                    "id": "fix-helper",
                    "prompt": "Adjust helper in src/core.py",
                    "expected_files": ["src/core.py"],
                    "expected_symbols": ["helper"],
                    "recorded_patch": "patches/fix-helper.diff",
                    "budget_tokens": 500,
                },
                {
                    "id": "fix-helper-missing-context",
                    "prompt": "Fix helper but the slice excluded core.py",
                    "expected_files": ["src/core.py"],
                    "expected_symbols": ["helper"],
                    "recorded_patch": "patches/wrong-file.diff",
                    "verify_report": "verify/fix-helper-gap.json",
                    "budget_tokens": 500,
                },
            ],
        }],
    }
    corpus_path = os.path.join(root, "corpus.json")
    with open(corpus_path, "w", encoding="utf-8") as fh:
        json.dump(corpus, fh, indent=2)
        fh.write("\n")
    return corpus_path
