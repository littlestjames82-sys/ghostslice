# GhostProxy - Agent B Report (tests / README / examples)

Date: Oct 14, 2026. Scope owned by Agent B: `tests/**`, `README.md`,
`examples/**`, this report. No files under `src/**` or
`pyproject.toml` were edited.

## What was built

- `README.md` - what the proxy is, the trust rules in plain words
  (localhost only on 127.0.0.1; never stores your API key; never
  logs your API key; fail-open always; inspectable transform maps;
  one-command bypass), the secrets rule stated plainly (a file the
  secrets guard flags is excluded and not sent), Claude Code setup
  step by step, the undo, doctor/report usage, transform order,
  ledger shape, and honest limits (estimates, chatty-session
  savings, API shape pinning, latency recorded not promised).
- `tests/` - 31 tests (pytest, stdlib-only harness):
  - `conftest.py` - fake Anthropic-shaped upstream on 127.0.0.1
    (echo / mirror / error500 / streaming / mid-stream-drop modes,
    records every request in memory), a proxy process launcher for
    the documented CLI, a fixture project with one of everything,
    and request builders.
  - `test_fail_open.py` - malformed JSON forwarded byte for byte
    with a fallback logged, ~4 MB oversize body forwarded in full,
    unparseable slicing target fails open, upstream 500 passes
    through and the proxy survives, mid-stream drop (xfail, below).
  - `test_transform.py` - secrets-flagged file excluded, lockfile
    excluded, duplicates sent once, prompt/system/history
    untouched, unknown fields + tool calls + images untouched,
    budget downgrade keeps signatures and drops bodies,
    unrecognised shapes pass byte for byte, streaming forwarded,
    and GhostSlice's exact `# File: <path> (mode: ...)` PROMPT.md
    header recognised.
  - `test_leak_scan.py` - leak scanner unit tests (planted canary
    found, clean tree clean, binary files covered) plus an
    integration run carrying a canary API key header and a canary
    secret in a project file, then a scan of every file the proxy
    wrote (ledger, logs, process log) and of the generated report.
    Zero hits. Hits are reported as file + label only.
  - `tests/leakscan.py` - the scanner as a standalone tool for
    manual re-checks (`python3 tests/leakscan.py <folder> <canary>`).
  - `test_parity_bypass.py` - non-localhost bind refused; bypass
    with the proxy stopped is byte-identical to direct upstream
    traffic; estimator parity against the real GhostSlice checkout
    (below).
  - `test_doctor_report.py` - doctor passes against the fake
    upstream and makes zero billable POSTs; a bad profile fails
    doctor loudly; ledger rows carry `tokens_in` / `tokens_out` /
    `fallback` and contain no request-body markers.
  - `test_docs_examples.py` - pins the README trust phrases and
    the examples contract so a future edit cannot quietly soften
    them; runs without the core.
- `examples/` - fake upstream (localhost, canned replies, smoke
  tested live), a sample project (entry point, padded module,
  exact-duplicate pair, lockfile, labelled-fake secrets file),
  profile / request / expected transform map examples (all valid
  JSON), setup and one-command undo scripts for Claude Code, and
  an examples README with a five-minute no-key demo.

## Honest results

Core status when Agent B started: `src/**` did not exist yet (only
PLAN.md). Agent A's core landed during this build, so the suite
was run against the real core, not just written against the plan.

Command: `PYTHONPATH=src python3 -m pytest tests -q`, run twice in
full at the end:

- **30 passed, 1 xfailed, 0 failed** - both runs identical.
- The 1 xfail is a genuine core gap, pinned on purpose (next
  section), not a harness problem.
- No test contacted a real upstream and nothing was spent: the
  only upstream in any test is the in-process fake on 127.0.0.1.
- Nothing was pushed or published.

Parity, measured on the single-file fixture (only.py):
`ghostslice scan` estimates 19 tokens; the proxy ledger records
`context_tokens_in` 19 and `context_tokens_out` 17; a manual
GhostSlice export of the same project reports
`total_sliced_tokens` 17. Exact match on both sides, and the
ledger row stamps `estimator_version`, as the plan requires.

## Finding for the core owner (Agent A / parent)

**Mid-stream drop leaves the client hanging.** When the upstream
closes mid-stream, the proxy does not close the client stream
promptly; the client read hangs until the proxy's upstream
timeout (observed: client-side timeouts at 20s and 30s). Fail-open
covers the request path, but stream teardown does not yet. The
test `test_mid_stream_drop_does_not_wedge_proxy` is marked xfail
(strict=False) with this reason recorded in the test; when the
core closes the client stream on upstream EOF/error, the test
will xpass and the marker should be removed.

Minor note: the oversize-body test failed once under full-suite
load in an early run, then passed in isolation and in both final
full runs at ~4 MB. Worth knowing it is the slowest test in the
battery; it is not marked flaky, the record here is the whole
story.

## Assumptions made, and how they landed

- Documented CLI contract assumed from the plan, then verified
  against the landed core and aligned where they differed:
  `serve --host --port --upstream --project [--ledger]`,
  `doctor --project --upstream`, and
  `report --ledger <path> --json` (the report test originally
  assumed `--project` / `-o` and was rewritten to the real form).
- Context convention: text blocks whose first line is a
  `# File: <path>` header, with or without GhostSlice's
  `(mode: ...)` annotation. Both forms are recognised by the core;
  an early worry that the annotated form was unsupported came from
  a truncated grep of the header regex and was **wrong** - the
  passing PROMPT.md header test is the evidence.
- Body logging: the plan says opt-in, off by default. The core is
  stricter than the plan text - the profile file cannot enable it
  at all (`log_bodies` is rejected there); only an explicit
  `--log-bodies` CLI flag can, and the v0.1 ledger schema holds no
  bodies regardless. README and the profile example were written
  to the core's stricter behaviour, which is the safer reading of
  the plan.
- Ledger location: the tests discover the ledger under the
  project or work dir rather than assuming a path; in observed
  runs it was written as `.ghostproxy-ledger.jsonl` in the
  project directory.
- Budget for the downgrade test comes from the profile's
  `proxy.budget_tokens` key, which the core accepts.
- Canaries in tests and examples are labelled fakes
  (`CANARY-...`), never real credential shapes, and the leak
  scanner never prints their values.
