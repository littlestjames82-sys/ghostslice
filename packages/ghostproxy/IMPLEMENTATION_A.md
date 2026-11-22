# GhostProxy v0.1 - Implementation Report (Agent A, core)

Built from PLAN.md (read in full first). Ownership honoured: this half is
`src/**`, `pyproject.toml`, and this file only. `tests/**`, `README.md`,
and `examples/**` are Agent B's and were not edited (B's tests were run
read-only to verify the core, and two contract details in them were
matched: the `# File: <path> (mode: <mode>)` block header and the
`report --project <dir> -o <file>` surface).

No push, no publish, no spend, no network calls beyond localhost fakes.

## What was built

Package `src/ghostproxy/` (Python stdlib only, zero dependencies,
Python >= 3.10), version 0.1.0, console script `ghostproxy`:

- `server.py` - ThreadingHTTPServer proxy. Binds 127.0.0.1 only (any
  other host is refused in config and re-checked in `serve()`).
  Responses are streamed chunk-by-chunk via http.client and never
  buffered whole or modified. GET `/` is the local live view (recent
  requests, fallback count, estimated saving, no bodies), `/health` and
  `/api/recent` are local JSON. Server access logging is disabled
  entirely, so no header can reach a log.
- FAIL-OPEN WRAPPER (the plan's top rule): `_try_transform` wraps all
  parsing/transform work; ANY exception, malformed JSON, non-object
  body, or oversize body (> 4 MiB) forwards the ORIGINAL bytes untouched
  and records `fallback: true` plus a reason in the ledger. If the
  upstream itself is unreachable, the client gets a plain 502 (there is
  no honest way to fake a response); upstream 500s pass through as-is.
- `transform.py` - the Slice step, Anthropic Messages shape only
  (`/v1/messages`). See "Transform contract" below.
- `slice_adapter.py` + `tokens.py` - all real slicing/secret scanning is
  delegated to GhostSlice (`ghostslice.slicer.slice_source`,
  `ghostslice.secrets_scan.scan_text`, calibrated estimator, imported
  from an installed package, a sibling `../ghostslice/src` checkout, or
  `$GHOSTPROXY_GHOSTSLICE_SRC`). If GhostSlice is unavailable, blocks
  pass through and the result is marked fallback; a narrow fallback
  secret-shape check still applies (values discarded, type only).
- `config.py` - defaults <- `.ghostslice.json` `proxy` section <-
  explicit CLI overrides. Unknown proxy keys fail loudly; a non-numeric
  port/budget is a clean ConfigError (exit 2), not a traceback.
- `ledger.py` - JSONL ledger, one row per request: project, method,
  path, status, tokens in/out, context tokens in/out, whole-request
  token totals, files seen/sliced/dropped, transform map (paths, modes,
  reasons, secret finding TYPES only), latency, fallback flag/reason,
  estimator name + version stamp. The schema has NO body field, and a
  defensive scrub drops any credential-named key before writing.
  Headline `tokens_in/out` are the context totals so they are directly
  comparable with a manual GhostSlice export (the parity check).
- `doctor.py` - `ghostproxy doctor`: loopback rule, port free, profile
  valid, GhostSlice importable, ledger writable, body-logging state,
  upstream probe only with `--check-upstream` (a bare HEAD, no auth, no
  billable call). Exit 1 on any FAIL.
- `cli.py` - `serve | doctor | report | transform | --version`.
  `report` reads the ledger (`--ledger`, or `--project <dir>` for
  `<project>/.ghostproxy-ledger.jsonl`) and emits the Bench-shaped
  roll-up (Markdown, `--json`, or `-o <file>`). Client setup is the
  documented env-var path (`ANTHROPIC_BASE_URL=http://127.0.0.1:8787`);
  undo is unsetting it. The proxy never edits client config.
  Startup banner states the trust rules in plain words.

## Transform contract

Only recognisable project-file blocks are transformed: a text part
whose first line is `# File: <path> (mode: <mode>)`, `# File: <path>`,
`// File:` / `<!-- File:` variants, or `--- FILE: <path> ---`. Prompt
text, system, history, tool calls/results, images, and unknown fields
pass untouched. Per block, in plan order:

1. lockfiles and junk paths (node_modules/dist/.git/vendor/...) dropped;
2. secret-guard hits dropped (whole block; path + finding type logged);
3. exact duplicates dropped to one copy;
4. GhostSlice default modes applied (code -> signatures, test files ->
   strip-tests, docs/config stay full) - this matches a manual export;
5. if still over the per-request budget, the fit ladder continues on
   the largest blocks: signatures -> interfaces -> exclude.

Dropped blocks are replaced in the request by a short placeholder
naming the path and reason, so the model is not silently misled.
Kept blocks get their `(mode: ...)` header annotation updated.

## Non-negotiables: how each is enforced

- 127.0.0.1 only: ConfigError on any non-loopback host, re-checked in
  `serve()`; B's bind-refusal test passes.
- Never store/log/write an API key: auth headers are forwarded as-is
  in memory only; they are never passed to the ledger, the live view,
  the report, or any log (server logging disabled). Verified by canary
  scan of the ledger in the smoke test and by B's leak-scan suite.
- No request bodies by default: the ledger/report schema has no body
  field at all; `log_bodies` defaults False and even when explicitly
  opted in, v0.1 writes no bodies anywhere.
- Fail-open: see above; verified for malformed JSON and for a forced
  transform crash (monkeypatched), original bytes forwarded both times.

## Smoke test (run locally, fake upstream on 127.0.0.1, recorded here)

In-process harness (fake Anthropic upstream + real proxy server +
canary API key `x-api-key` header + canary secret inside a file block +
a body sentinel string): **18/18 checks passed**, including:

- transform: upstream 200, auth forwarded as-is, request shrank
  6,637 -> 439 bytes under a 200-token budget, secret block excluded,
  lockfile excluded, duplicate excluded;
- fail-open: malformed JSON forwarded byte-for-byte; forced transform
  exception forwarded the original byte-for-byte; both logged fallback;
- streaming: two SSE chunks forwarded intact; upstream 500 passed
  through with its own body; `/health` OK;
- ledger: exists, contains transform + fallback rows, and contains
  NEITHER the canary key, NOR the canary secret, NOR the body sentinel;
- config: non-loopback host refused.

CLI checks also run: `doctor` against the GhostSlice project (all OK,
upstream not probed by default, exit 0), `transform` on a plain request
(pass-through, empty map), `--version`, non-loopback `serve` (exit 2),
unknown profile key (exit 2, key named).

Agent B's test suite, run against this core at the end of the build:
**30 passed, 1 xfailed**. The parity test passes exactly as designed:
proxy context-out 58 estimated tokens vs manual GhostSlice export 108,
difference 50 = the duplicate file (18) + secret-flagged file (32) the
proxy correctly drops and an export keeps, inside the test's tolerance.

## Known gap (honest)

Mid-stream upstream drops: if the upstream dies mid-SSE-stream, the
proxy's read can block until the upstream socket timeout instead of
closing the client stream promptly, so a client with a shorter timeout
sees a timeout on that one stream. The proxy process itself does not
wedge and serves the next request. Agent B pinned this as a non-strict
xfail with the same description. Fixing it properly needs a bounded
stall timeout for streamed reads, which is a policy choice (legitimate
SSE streams idle) left for the next round rather than guessed here.

## Deliberate v0.1 limits (per plan)

One upstream shape (Anthropic Messages), one client setup path, no
response modification or response caching, no Verify blocking (verdicts
are not in the request path), no prompt/system/history rewriting, no
hosted/team anything, no TLS. Savings are reported as context tokens
vs whole-request tokens separately; all counts are estimates stamped
with the estimator version.
