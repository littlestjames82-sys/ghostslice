# GhostLogs - Log Slicer for GhostSlice
Working name, prepared Oct 14, 2026. Paired tool #31 for GhostSlice, Wave 4.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostLogs: plain job, plain name. It slices logs the way GhostSlice slices code.
- Checked against the family: Waves 1-3 already cover code (Slice, Scope), documents (GhostDocs), and memory (GhostRecall). Logs are the biggest unsliced input an agent gets handed during an incident, and no sibling owns them. GhostWatch owns staleness of reports, not log content. No overlap.
- Treat as a working name until a name check runs at build gate, same as GhostSlice did Oct 12. Alternatives held in reserve: GhostTrace (already the reserve name for GhostReplay, do not reuse), GhostTail (cute, implies live following, which v0.1 does not do).

## The problem
When something breaks, the evidence is a log file, and the log file is enormous. A production service can emit hundreds of megabytes a day, most of it routine heartbeat and retry noise, with the actual failure buried in a few dozen lines plus a stack trace.

Handing that file to an agent raw fails three ways:
- Cost: the full file blows the context budget before the agent reads a line of code.
- Signal: the one error that matters repeats 40,000 times and drowns the three distinct errors around it.
- Safety: logs are where leaked credentials end up. A raw log pasted into a prompt carries any secret-shaped literal it contains straight to the model.

Today the developer greps by hand, guesses at keywords, and pastes fragments with no record of what was left out. There is no tool that turns a log into a small, honest, reproducible incident pack: what errored, how often, in what order, and exactly what was not shown.

## Position in the Ghost stack
- GhostSlice governs what an agent READS from a codebase (scanner, AST slicer, token estimator, .claude_context bundle with manifest + sha256).
- GhostLogs governs what an agent reads from a LOG: the non-code evidence file. It is one of the Wave 4 input slicers alongside GhostDocs (documents), GhostSchema (API specs), and GhostData (structured data), each slicing a file type Slice itself does not parse.
- GhostVerify can check a code slice was sufficient; GhostLogs makes no sufficiency claim about a log, it states exactly what it kept, collapsed, and dropped.
- Agent Seatbelt governs what an agent DOES. GhostLogs runs before any agent is involved and never acts on the system the log came from.

Story: incident happens -> GhostLogs packs the log under a budget -> agent reads INCIDENT.md plus a GhostSlice bundle of the code -> diagnosis starts from evidence, not from grep luck.

## How it pairs with GhostSlice, concretely
Reuses, does not rebuild:
- Token estimator: GhostSlice's calibrated estimator (method v2) is used when a GhostSlice install or sibling checkout is reachable, and the manifest stamps the method either way. A documented fallback estimator is used when Slice is not reachable. All counts are labelled estimates.
- Secret shapes: the redaction shape names follow GhostSlice's secret guard naming (aws-access-key, github-token, openai-or-anthropic-key, slack-token, private-key, and friends) so a redaction reads the same way across the suite.
- Manifest discipline: like a Slice bundle, the pack carries a manifest with hashes and totals that must reconcile. GhostLogs adds its own reconciliation rule (see Verification bar).
- The pack output is a plain folder (INCIDENT.md + manifest.json) that can be handed to an agent directly, or carried into a Slice bundle as an ordinary full file.

Integration contract:
- Input: one local log file, a token budget, optional pattern configuration. Nothing else. No log server, no upload, no account.
- Output: an incident pack folder the caller names. The source log is never modified, never moved, and never copied wholesale into the pack; only selected excerpts are emitted, redacted by default.

## MVP (v0.1) - local CLI first
Rationale: same as Slice v0.1. A CLI proves the slicer on real logs in days.

1. Error and exception windows: `ghostlogs pack <logfile> -o <pack-dir> --budget <tokens>`
   - Finds lines matching error/exception patterns: severity levels (FATAL, CRITICAL, ERROR), exception and traceback markers, panic and crash markers. Default pattern set ships in the box; every pattern has an id and can be replaced or extended.
   - A matched line opens a window: configurable lines of context before and after (`--window-before`, `--window-after`). Overlapping windows merge.
   - Stack traces are absorbed into their window: indented continuation lines, frame lines, and Caused by chains that follow a traceback or exception line belong to the window even past the after-context count, up to a stated per-trace cap.

2. Duplicate collapse
   - Precedence rule: the first burst of an error is windowed in full context. Identical repeats inside a window collapse in place into a counted repeat of the stored line above them, and later bursts of an error that already has a window collapse into duplicate exemplars instead of opening more windows. So a repeated error is always shown once in full and counted exactly, never shown raw thousands of times.
   - Repeated lines collapse into one exemplar with an exact occurrence count and first/last line numbers.
   - Two tiers: exact duplicates (byte-identical lines) and near duplicates (same line after masking timestamps, numbers, hex ids, UUIDs, IPs, and quoted strings). Each exemplar records both its total occurrences and how many were byte-identical to it.
   - Exemplars are ranked by occurrence count, so the loudest repetition is always shown first with its true count, never as 40,000 raw lines.

3. Timeline anchors
   - The first and last lines of the file, and the first and last recognised timestamps (ISO 8601, syslog, and bracketed forms), are always kept, so the pack states when the log starts and ends even when nothing errored.

4. Budgeted emission with reconciled counts
   - Emission priority: anchors first (mandatory), then error windows (highest severity, then file order), then duplicate exemplars (highest count first). Items that do not fit are skipped and counted, never silently truncated mid-window.
   - Token figures use the Slice-style estimator. The pack must land at or under the stated budget; if the mandatory anchors alone exceed it, the pack is still written, marked over budget, and the exit code says so.
   - The manifest states the reconciliation explicitly: total source lines = kept lines + collapsed lines + dropped lines, with dropped split by reason (routine, duplicate exemplar not emitted, window not fitted, window store cap). A pack whose counts do not reconcile does not ship.

5. Redaction by default
   - Secret-shaped literals in emitted excerpts are replaced with a typed placeholder naming the shape, for example [REDACTED:aws-access-key]. The value is never printed in INCIDENT.md, in the manifest, or on stdout.
   - Redaction counts per shape are recorded in the manifest. `--no-redact` exists for local debugging and is loudly recorded in the manifest when used.

6. Streaming reads
   - The source is read line by line in a single pass. The whole file is never loaded into memory at once. Retained state is the kept window lines (capped, with overflow counted), the duplicate signature table, and counters. Multi-hundred-megabyte logs are in scope for v0.1.

7. Doctor: `ghostlogs doctor`
   - Reports the estimator in use (GhostSlice method v2 vs fallback), the pattern set loaded, and the version. Fails loudly on a bad pattern or config file rather than guessing.

## Out of scope for v0.1
- Live tailing, log following, or any daemon mode. v0.1 packs a file that exists.
- Log servers, remote fetch, upload, or any network access of any kind. Local files only.
- Root-cause diagnosis or any claim about why the incident happened. GhostLogs presents evidence (windows, counts, order); it does not explain the failure and never invents a cause.
- Log parsing into structured fields beyond timestamps, levels, and pattern matches. No grok engine, no per-service schemas.
- Multiple input files or glob merging in one pack. One file, one pack.
- Writing back to, rotating, or compressing the source log. The source is read-only to this tool, always.
- MCP server, dashboard panel, cloud, accounts, telemetry, paid layer. (MCP is a v0.2 candidate once the pack format settles.)

## Build estimate
- Streaming analyser (patterns, windows, trace absorption, anchors): 2-3 days
- Duplicate collapse (exact + near signatures, counts): 1-2 days
- Redaction shapes + budget selection + pack writer (INCIDENT.md + manifest): 2 days
- CLI + doctor + config handling: 1 day
- Tests (planted-repeat and planted-secret fixtures, reconciliation checks, large-log streaming check), README, examples: 2 days
Total: roughly 1.5 weeks to a verified v0.1 if built straight through. Near-duplicate signature tuning is the part most likely to need a second pass; the reconciliation rule is the guardrail that keeps tuning honest.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI free, same pattern as Slice / Seatbelt / Ghost Hands.
- Paid candidate later only: team incident-pack profiles (shared pattern packs for a stack) or a hosted pack history. Do not build a paid layer before a free launch validates demand.

## Verification bar
- Planted-repeat fixture: a log with one error line repeated a known number of times plus distinct errors around it. The pack must show the exemplar once with the exact count, and the distinct errors as windows.
- Planted-secret fixture: a log containing a secret-shaped literal inside an error window. The literal value must appear nowhere in the pack outputs; the shape name and a redaction count must appear in the manifest.
- Reconciliation: on every fixture, manifest totals satisfy lines in = kept + collapsed + dropped exactly, with the dropped breakdown summing to the dropped total.
- Budget: with the budget set tight on a fixture, the emitted pack estimates at or under budget, and the lines that did not fit are counted as dropped by reason, not vanished.
- Source untouched: sha256 of the source log is identical before and after the run.
- Streaming: a generated log of at least 200 MB is packed without the file being loaded whole (single streaming pass; retained state limited to capped windows, the signature table, and counters), and the run completes with reconciled counts.
- No-error log: a log with no matching lines still produces a pack (anchors + duplicate summary) and says plainly that no error windows matched.

## Risks / honest notes
- Near-duplicate masking can over-collapse: two genuinely different errors that differ only in a number will share a signature. The exemplar keeps its first occurrence verbatim and reports the byte-identical count alongside the total, so over-collapse is visible, but it is a real limit of signature-based grouping.
- Pattern-based window finding only sees what the patterns name. A failure written in words no pattern matches produces a no-error pack. The pack states the pattern set used, and the no-error wording says "no lines matched the pattern set", never "nothing went wrong".
- Token figures are estimator output, not a vendor tokenizer count. Same labelling rule as GhostSlice: estimates, stamped with the method.
- Stack trace shapes vary by language and runtime. v0.1 absorption covers Python tracebacks, Java-style frame and Caused by lines, and generic indented continuations. Exotic formats may split a trace across windows; the context lines make that survivable, not invisible.
- The duplicate signature table grows with the number of distinct normalised lines. Counts stay exact, but a pathological log of all-unique lines makes the table the memory ceiling. Stated here rather than discovered later.

## Next gate
Ryan's go on: (1) GhostLogs as working name, (2) CLI-first with one file per pack, (3) redaction on by default with the opt-out recorded in the manifest, (4) MCP deferred to v0.2.
