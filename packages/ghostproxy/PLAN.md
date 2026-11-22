# GhostProxy - In-Flight Context Proxy for GhostSlice
Working name, prepared Oct 14, 2026. Paired tool #3 for GhostSlice.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostProxy: it is a local proxy. The name says the risky part out loud, which is honest: anything that sits between a developer and a model API must be trusted, inspectable, and easy to bypass.
- Reserve alternative: GhostGate (implies blocking/governing, which is Seatbelt's job and would confuse the stack story).
- Treat as a working name until a name check runs at build gate, same discipline as GhostSlice Oct 12. Note: "proxy" names are crowded in dev tools, so the check matters here more than for the other three companions.

## The problem
GhostSlice works, but it is manual: scan, slice, export, drop the bundle in, repeat when the code changes (watch mode narrows this, it does not remove it). Every developer who agrees slicing saves tokens still has to change how they work to get the saving.

Meanwhile most agent tools already send context the wasteful way on every request: whole files re-sent, stale docs, repeated system context, files the task never touches. The saving GhostSlice proves in a bundle could be applied automatically, at request time, with no workflow change.

That is also exactly why this is companion #3 and not #1: a proxy touches live traffic and credentials. It should only be built on top of verdicts from GhostVerify and proof from GhostBench, not on a demo number alone.

## Position in the Ghost stack
- GhostSlice governs what an agent READS, when a human prepares it.
- GhostProxy applies GhostSlice AUTOMATICALLY, at request time, locally.
- GhostVerify checks the result was sufficient. GhostBench proves the saving held on real tasks.
- Agent Seatbelt governs what an agent DOES. A proxy must never quietly become a second, weaker governor: Proxy transforms context, Seatbelt approves actions. Keep those jobs separate in code and in copy.

## How it pairs with GhostSlice, concretely
Proxy is a runtime for Slice, not a second slicer:
- Slicing engine: calls GhostSlice as a library/CLI (scanner, slicer, fit ladder, call graph, cache). No duplicated parser logic. If Slice cannot slice it, Proxy passes it through and logs that it did.
- Profile: same `.ghostslice.json` per project, plus a `proxy` section (port, upstream, per-project on/off, budget). Unknown keys fail loudly.
- Estimator + prices: same token estimator and local dated `prices.json`, so a Proxy savings report and a Slice export report for the same project agree, estimator version stamped on both.
- Ledger: Proxy appends to a request ledger designed to roll into Slice history analytics (per request: project, files seen, files sliced/dropped, tokens in, tokens out, latency added, fallback used yes/no).
- Verify hook: when GhostVerify is present, Proxy can run its pre check on the transformed context in dry-run mode and record the verdict per request. In v0.1 it records only, it does not block on a soft verdict. Blocking is a separate Ryan gate.
- Secrets guard: Slice secrets scan runs on outbound context. A file flagged by the guard is excluded and logged (path + type only) rather than sent. This is one place Proxy is allowed to drop content even when the client asked for it, and that rule must be in the README in plain words.

## MVP (v0.1) - local-only, one upstream, fail-open
Design rule that outranks every feature: **fail-open, always**. If Proxy errors, times out, or cannot parse a request, the original request goes through untouched and the failure is logged. A context tool must never be the reason an agent run dies.

1. Local proxy server (Python stdlib only, localhost by default)
   - Listens on 127.0.0.1 only. Binding to any other interface is refused in v0.1.
   - One upstream in v0.1: the Anthropic Messages API shape, because Claude Code is Slice's primary target. OpenAI-shaped traffic is v0.2, not a launch claim.
   - Pass-through for everything it does not understand: streaming responses are forwarded as a stream, not buffered and rewritten. Tool calls, images, and unknown fields pass untouched in v0.1.

2. Context transformation (the Slice step)
   - Only transforms the parts of a request that are recognisably project files/context blocks the client included. It does not rewrite the user's prompt text, system instructions, or conversation history in v0.1.
   - Applies, in order: exclude (junk, lockfiles, flagged secrets), mode downgrade via the Slice `--fit` ladder against a per-request token budget from the profile, duplicate drop (Slice exact/near duplicate detection).
   - Keeps a per-request transform map: what was full, what was downgraded, what was dropped, and why. Any transformed request can be replayed in the Slice dashboard as a slice preview.

3. Credentials handling (hard rules, not preferences)
   - Proxy never stores an API key, never logs one, and never writes one to disk, ledger, or report. It forwards the client's auth headers as-is.
   - No Secure Vault integration in v0.1, no key entry UI, nothing to leak.
   - README and startup banner state in plain words: run this only on your own machine, inspect the transform log, bypass any time by pointing the client back at the upstream.
   - Startup refuses to run if the ledger/report path would include request bodies by default. Bodies are logged only with an explicit per-project opt-in flag, off by default, because bodies contain code and prompts.

4. Client setup: one documented path per client
   - v0.1 target: Claude Code via its base-URL environment setting, documented step by step, with an equally documented one-command undo.
   - A `ghostproxy doctor` check in the spirit of `ghostslice doctor`: port free, upstream reachable (a headers-only check, no paid test call by default), profile valid, Slice importable, ledger writable. Any paid or billable connectivity test is opt-in and labelled.

5. Live view + reports
   - Local page on the proxy port: last requests, tokens in/out, saving %, transform map, fallback count. No code bodies on this page by default.
   - `ghostproxy report` rolls the ledger into the same shape GhostBench consumes, so proxy claims are bench-checkable rather than marketing.

## Out of scope for v0.1
- Any hosted / multi-user / team proxy, TLS termination for remote clients, accounts, billing.
- Rewriting prompts, summarising with a model, caching model *responses*, or any response modification.
- Blocking requests on Verify verdicts, Seatbelt-style approvals in the proxy path, or policy enforcement beyond the secrets exclusion stated above.
- OpenAI / Gemini / local-model upstreams, IDE extensions, auto-install into a client's config without the user running a setup command themselves.
- Performance promises. Added latency is measured and reported per request; no "zero latency" copy.

## Build estimate
- Stdlib localhost proxy, streaming pass-through, fail-open wrapper: 4-5 days (highest-risk piece, estimate is honest about it)
- Transform step calling Slice + transform map + ledger: 3-4 days
- Doctor + setup/undo docs for one client + live view: 2-3 days
- Adversarial tests (malformed requests, huge bodies, mid-stream disconnects, key-leak scan of all outputs/logs), README, demo: 3-4 days
Total: roughly 2.5 to 3.5 weeks to a verified v0.1. Longest of the four companions, and the only one where a slip should cut upstream count (already at one) rather than cut the fail-open or credential rules.

## Pricing draft (NOT public, NOT decided)
- MIT core local proxy free, same pattern as Slice. A proxy that phones home or gates the local path would kill the trust it needs.
- Paid candidate later only: hosted team proxy with shared profiles and reporting. That is a separate product decision with its own security review, not a v0.1 upsell path.

## Verification bar
- Fail-open battery: kill the slicer mid-request, feed malformed JSON, oversize body, upstream 500s. Original behaviour in every case: request completes as if Proxy were absent, failure logged.
- Leak scan: run the full test suite with a canary API key and a canary secret in a test file, then scan every file Proxy wrote (ledger, reports, logs) for either canary. Zero hits is the pass bar.
- Parity test: for a fixed project + task, Proxy's transformed totals match a manual GhostSlice export within the estimator's stated tolerance, same estimator version.
- Bypass test: documented undo returns the client to direct upstream behaviour, verified, with Proxy stopped.

## Risks / honest notes
- Trust risk is the product risk: developers are right to be wary of anything between them and their model API. Local-only, stdlib, inspectable transform maps, no key handling, and fail-open are not features, they are the price of admission.
- API shapes change. Pin the supported upstream shape + client version in the README, test against it, and pass through (do not guess) when the shape does not match.
- Streaming + tool-use traffic is where naive proxies break agents. v0.1 transforms only recognisable context blocks for exactly this reason.
- Savings will be lower than bundle savings on chatty sessions where history dominates the request and history is out of scope. Reports must separate "context we could slice" from "total request" so the number stays honest.

## Next gate
Ryan's go on: (1) GhostProxy as working name, (2) local-only + one upstream + one client in v0.1, (3) fail-open and no-key-storage as non-negotiable rules, (4) build order: Proxy is #3, built only after Verify ships and Bench has proven slice quality on real tasks.
