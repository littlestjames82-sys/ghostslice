# GhostDeps v0.1 - Agent A implementation record
Built Oct 14, 2026. Ownership: PLAN.md, src/**, pyproject.toml, this file.
Agent B owns tests/**, README.md, examples/** (REPORT_B.md).

## What was built
- [PLAN.md](PLAN.md) written first, in the GhostVerify plan format: why this name, problem, position in the Ghost stack, pairing contract, MVP, hard rules, out of scope, build estimate, pricing draft (marked not public, not decided), verification bar, risks, next gate. No em dashes.
- `pyproject.toml`: ghostdeps 0.1.0, zero dependencies, requires-python >=3.11 (tomllib), console script `ghostdeps`.
- `src/ghostdeps/manifests.py`: parsers returning declarations and pins as recorded.
  - pyproject.toml via tomllib: project.dependencies, project.optional-dependencies (kind optional, group named), dependency-groups (kind dev; `{include-group}` entries recorded as a note, not expanded), build-system.requires (kind build), Poetry tables (tool.poetry.dependencies / dev-dependencies, `python` key skipped).
  - requirements*.txt: requirement lines, `#egg=` editables, `-r`/`--requirement` includes noted and not followed, `--hash` and other option lines skipped and counted in a note.
  - package.json: dependencies / devDependencies / peerDependencies / optionalDependencies with specs verbatim.
  - package-lock.json, summary level only: v2/v3 `packages` shape (top-level `node_modules/<name>` pins; nested entries counted as transitive, not listed) and legacy v1 `dependencies` shape. Unrecognised shape degrades to detected-not-parsed with a note.
  - Cargo.toml via tomllib: dependencies / dev-dependencies / build-dependencies, target tables, workspace.dependencies, workspace members noted. String and table forms; `path:` and `git:` specs recorded as such.
  - Detected-not-parsed (listed, never silently skipped): Gemfile, go.mod, composer.json, Pipfile, setup.py, setup.cfg, yarn.lock, pnpm-lock.yaml, Cargo.lock, poetry.lock.
- `src/ghostdeps/imports_scan.py`:
  - Python: real `ast` over every .py file (top-level module per Import/ImportFrom; relative imports are local by construction). Classification: local (file stem, package dir, or any directory name in the tree), stdlib (`sys.stdlib_module_names`), third-party candidate. Syntax-error files recorded in `python_parse_failures`, not fatal.
  - JS/TS: parser-lite regex (import/export-from, side-effect import, require, dynamic import) after a naive comment strip. Scoped names keep both segments; `node:` and bare builtins classified stdlib; relative/absolute/URL specifiers ignored. Labelled parser-lite in the manifest and DEPS.md.
  - Rust: outline level, `use` and `extern crate` first segments; crate/self/super/std classified stdlib, tree names local. Labelled outline.
- `src/ghostdeps/names.py`: PEP 503 style normalisation shared across ecosystems (case folded, `-`/`_`/`.` folded), a built-in Python import-name to distribution-name table (PIL to Pillow, yaml to PyYAML, cv2 to opencv-python, sklearn to scikit-learn, bs4, dateutil, dotenv, jwt, Crypto, and similar; applications are flagged per entry as `name_mapping_applied`), Node builtin set.
- `src/ghostdeps/xref.py`: cross-reference into declared_and_used / declared_not_imported / imported_not_declared / pins, and the DEPS.md renderer. Manifest pins are taken only from Python/JS specs where `==` or a bare version is genuinely exact; Cargo version strings are requirements (caret semantics), so they are never reported as pins (Cargo pins live in Cargo.lock, detected-not-parsed in v0.1). A wording guard scans the rendered DEPS.md for banned strings ("safe to remove", "vulnerable", "vulnerability", "outdated", "latest version", "security risk") and raises rather than write a non-compliant report.
- `src/ghostdeps/cli.py`: `pack` (writes DEPS.md + deps-manifest.json, default output `<project>/deps-pack`, `--json` echoes the manifest) and `doctor` (sources found, parse status, parser confidence per language, counts; `--json`). Exit codes: 0 = built, no imported-not-declared findings; 1 = findings present; 2 = could not build (project missing, or no manifest parsed). Declared-not-imported is information and never affects the exit code.

## Hard rules, enforced in code
- No network: there is no socket/urllib/http code path anywhere in src (audited by grep; the only "requests" string in src is a name-mapping table entry). No registry or advisory lookups, no update checks.
- No vulnerability verdicts, no safety grades, no "outdated" or "latest" language: versions are reported as recorded, and the wording guard makes a violation a build-time error in the renderer.
- Read-only: no command writes anywhere except the pack output directory.

## Smoke results (fixtures built for this record, run, then removed)
- Python fixture (pyproject + requirements.txt; declared requests/Pillow/leftpad-demo/opencv-python/pytest/setuptools/flask; code importing requests, PIL, flask, yaml, stdlib, a relative module): declared 7, used 3 (requests, Pillow via PIL mapping, flask), declared-not-imported 4 (leftpad-demo, opencv-python, pytest, setuptools-build), imported-not-declared 1 (PyYAML, mapping flagged, importing file named), pins 2 (Pillow 10.2.0, flask 3.0.0 as recorded), exit 1. The `-r` include was noted, not followed.
- JS fixture (package.json + lockfileVersion 3 lockfile; code importing lodash, node:fs, chalk via require, a relative export, and one commented-out import): declared 3, used 1 (lodash), declared-not-imported 2 (react, typescript), imported-not-declared 1 (chalk, labelled parser-lite), pins 5 (lockfile top-level: lodash 4.17.21, react 18.2.0, scheduler 0.23.0, typescript 5.4.5; the nested scheduler entry counted as transitive only; manifest pin react 18.2.0). The commented-out import was correctly not extracted. Exit 1.
- Rust fixture (Cargo.toml with serde table form + tokio + criterion dev; main.rs using serde and std): declared 3, used 1 (serde), declared-not-imported 2 (tokio, criterion), imported-not-declared 0, exit 0.
- Clean fixture (declared set exactly matches imports): all gap sections empty, exit 0.
- Empty directory: exit 2 with the reason on stderr. Malformed pyproject.toml: that source recorded as status error with the TOML message, exit 2 (it was the only manifest).
- Real-repo smoke, GhostSlice itself (~/workspace/ghostslice): 75 Python files scanned, 0 parse failures. Declared 1 (setuptools, build-system only, correctly in declared-not-imported). Imported-not-declared 1: pytest, imported by 12 test files and genuinely not declared in GhostSlice's pyproject. Both are true facts about that tree, reported as evidence. Exit 1.
- Fresh-venv `pip install .` verified (with `--no-build-isolation --system-site-packages`, since this sandbox cannot fetch a build backend and a bare 3.12 venv seeds no setuptools): installed CLI reports `ghostdeps 0.1.0` and reproduces the clean-fixture result.
- Stdlib audit: src imports are argparse, ast, datetime, json, os, re, sys, tomllib, pathlib only.
- Wording scan over every generated DEPS.md: no banned strings.
- Agent B's independently written suite, run by me against this core after it landed: 19 passed, 0 failed (`python3 -m pytest tests -q`).

## Bugs caught during my own verification
1. PEP 508 name regex alternation matched a single character first, truncating every declared name ("flask" became "f" with spec "lask==3.0.0"). Fixed by ordering the long alternative first; the Python fixture then matched hand-checked expectations exactly.
2. Parser lookup was case-sensitive, so `Cargo.toml` (capital C) was missed entirely and the Rust fixture reported "no manifest parsed". Fixed with a lowercase fallback lookup.
3. Identity entries in the mapping table (requests to requests) were flagged as "name mapping applied", which would have mislabelled evidence. The flag now compares names.
4. First design reported Cargo version requirements as pins. Corrected: Cargo specs are requirements, excluded from the pins section (see xref notes above).

## Known limits (honest)
- Local-module classification is name-based over the whole tree's directory and file-stem names, so an unrelated directory sharing a third-party name can mask a real imported-not-declared gap, and a local package shadowing a distribution name will be read as local.
- The import-to-distribution table covers common mismatches only. Namespace packages with many providers (the `google.*` family is the known example, deliberately not mapped) will surface as imported-not-declared unless the exact distribution is declared under the import name.
- JS/TS parser-lite: computed specifiers, some re-export chains, and imports inside strings can be missed or falsely caught; the comment strip is naive around `//` inside string literals (URLs in import specifiers are protected, other strings are not guaranteed).
- Rust outline sees `use` statements only: fully-qualified paths (`serde::Serialize` used inline), macro-generated paths, and `pub use` re-exports across crates are partially visible at best.
- package-lock summary trusts the lockfile's own shape; a hand-edited or partial lockfile yields partial pins, noted via the source note, not detected as inconsistent with package.json (no cross-check between manifest specs and lockfile pins in v0.1).
- Nested manifests (examples, fixtures inside a repo) are parsed and attributed by relative path, which is honest evidence but can add noise to a big monorepo pack; there is no ignore-file support in v0.1.
- requirements files under subdirectories are found by the tree walk; `-r` includes pointing outside the walked set are noted, not followed, per plan.

## Gates held
Stdlib only, local only, no network code, no GitHub push, no PyPI/publish, no announcements, no spend. Nothing outside PLAN.md, src/**, pyproject.toml, and this file was written by Agent A (scratch fixtures were built under .smoke/ for verification and deleted).
