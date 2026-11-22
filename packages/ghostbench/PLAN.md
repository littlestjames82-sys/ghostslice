# GhostBench - Proof Harness for GhostSlice
Working name, prepared Oct 14, 2026. Paired tool #4 for GhostSlice.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostBench: a bench, in the workshop sense. It measures work, it does not do the work.
- Bench is also the word already in the family: Agent Seatbelt ships a bench corpus (221 cases at v0.3.1, 272 after the Oct 14 Phase 2 remediation) and GhostSlice ships BENCHMARKS.md. GhostBench generalises that habit into one harness for the Slice suite.
- Treat as a working name until a name check runs at build gate. "Bench" names are crowded, so expect the check to matter.

## The problem
GhostSlice's headline number is real but narrow: on the GhostBus tree, the calibrated estimator measures 129,555 tokens full vs 45,770 sliced. That proves a bundle is smaller. It does not prove:
- An agent still completes the task with the slice.
- A team saves that percentage on *their* repo and *their* tasks.
- GhostProxy's in-flight slicing holds up as well as a hand-made bundle.
- A new Slice version did not quietly get worse (the G5 estimator calibration changed the reference numbers honestly, and only a bench makes that kind of change auditable).

Without a bench, every claim for Slice, Verify, Recall, and Proxy rests on one demo tree. With one, every claim can be re-run by a stranger on their own code. That is the difference between a pitch and proof, and it is the asset creator outreach (Supertools submission, sponsorship inquiries sent Oct 13) can actually point to.

## Position in the Ghost stack
- GhostSlice slices. GhostVerify checks a slice. GhostRecall adds memory. GhostProxy applies slicing live.
- GhostBench MEASURES all four: same tasks, same projects, full vs sliced vs verified vs recalled vs proxied, scored the same way every time.
- Bench owns no slicing logic of its own. If Bench and Slice disagree on a token count, that is a bug to surface, not a number to average.

## How it pairs with GhostSlice, concretely
Reuses, does not rebuild:
- Estimator + prices: identical token estimator and local dated `prices.json`, estimator version recorded on every run. Cost figures are estimates from that table and are labelled as such in every report, never presented as billed amounts.
- Bundles + manifests: a bench run consumes ordinary Slice bundles and combined Recall bundles, identified by manifest sha256, so a result can be traced to an exact bundle.
- Verify reports: `verify-report.json` is an input signal (gaps predicted) to compare against what actually failed in the run.
- History: results append to a bench ledger (`.ghostbench-history.jsonl`) with the same stamped-record discipline as Slice's savings ledger, so version-to-version trend is a query, not a memory.
- Test discipline: follows the Seatbelt/GhostSlice house pattern: a fixed corpus, adversarial cases included, results published with failures visible. A bench that only shows wins is marketing, and the reports are designed to make cherry-picking obvious (full corpus results by default, subsets labelled).

Run model - two tiers, kept separate in every report:
- Tier A, static bench (no model, no spend, default): bundle size, Verify verdicts, patch-check outcomes on recorded patches, fit behaviour. Runs anywhere, free, deterministic.
- Tier B, live bench (opt-in, spends the user's own API budget): runs an agent on a task with full context vs sliced context and scores the outcome. Off by default, per-run budget cap required, total estimated cost shown *before* the run starts and confirmed by the user. Bench never spends silently. This is Ryan's standing rule applied to a tool: no paid spend without explicit approval, per run.

## MVP (v0.1) - Tier A complete, Tier B for one agent only
Rationale: Tier A proves the harness and ships free and safe. Tier B is where the persuasive numbers are, and also where cost, flakiness, and scoring arguments live, so it launches narrow.

1. Corpus format
   - A bench project = a repo snapshot + one or more tasks. Each task: prompt, the files/symbols a correct answer is expected to touch (scored loosely, see scoring), an optional recorded patch, an optional test command.
   - Ships with 2 starter projects: GhostBus (the standing Slice demo tree) and one small adversarial project built for Bench (planted duplicates, a called-but-easy-to-exclude file, a superseded decision for Recall runs).
   - Users can add their own project with `ghostbench add`: Bench records repo state by commit hash or tree hash, never by copying code into Bench's repo.

2. Tier A runner: `ghostbench run <corpus> [--suite slice|verify|recall|proxy]`
   - For each task: build full bundle and sliced bundle (and Verify-expanded / Recall-combined variants when that suite is selected), record tokens, modes, Verify verdicts, fit outcome.
   - Score recorded patches with GhostVerify post (static pass) where a patch exists.
   - Output: per-task table + corpus totals: tokens full vs each variant (saving %), hard gaps predicted vs patch failures observed, fit success rate.

3. Tier B runner (one agent, opt-in): `ghostbench live <corpus> --agent claude-code --budget <tokens>`
   - Pre-flight prints tasks, model, estimated full-context cost per task from `prices.json`, and the total cap, then waits for explicit confirmation. No confirmation, no run.
   - Runs each task twice where budget allows (full, sliced), in a temp copy, agent output captured, user test command scored pass/fail in the temp copy only, same guardrails as GhostVerify post.
   - Records wall time, actual tokens reported by the client where available (labelled reported, not estimated, and kept separate from estimator numbers), test outcome, and files touched vs expected.
   - Flakiness is reported, not hidden: a task that passes one arm and fails the other on a re-run is marked flaky in the report.

4. Scoring ( deliberately boring)
   - Task success = user test command passes, or recorded-patch match for Tier A. No LLM judge in v0.1.
   - Files-touched score is informational only (extra files are not auto-failures; real fixes touch unexpected files).
   - Every report shows: corpus version, Slice version, estimator version, price table date, per-task rows, and all failures. A summary percentage with no per-task rows is not a valid Bench report format.

5. Reports
   - `BENCH.md` (human, single file, shareable) + `bench-report.json` (machine) per run, in the run folder.
   - A compare mode: `ghostbench compare <run-a> <run-b>` for version-to-version or Slice-vs-Proxy diffs, token and success deltas per task.
   - Report template includes an honest-scope box by default: corpus size, Tier A vs B, what was not measured. Following Ryan's Oct 6 build-in-public rule, public reports show what was built and measured, with no internal gaps framed as shortcomings, and no claim the run does not support.

## Out of scope for v0.1
- Hosted leaderboards, public rankings, submitting other people's results, telemetry of any kind.
- LLM-as-judge scoring, human-rating workflows, multi-agent Tier B (one agent only until scoring is trusted).
- Running Tier B on a schedule or in CI by default. CI gets Tier A; Tier B in CI is a user's explicit, budgeted choice.
- Comparing commercial products or publishing competitor numbers. Bench measures Ghost tools on stated corpora. Anything broader is a separate editorial decision by Ryan.

## Build estimate
- Corpus format + starter corpora (incl. adversarial project): 3 days
- Tier A runner + scoring + reports + compare: 3-4 days
- Tier B runner for one agent (budget gate, temp-copy runs, capture): 4-5 days
- Tests (deterministic Tier A fixtures, flaky-arm handling, budget-refusal tests, estimator-version stamping), README, first published run on GhostBus: 2-3 days
Total: roughly 2 to 2.5 weeks to a verified v0.1. Tier B could ship one cycle after Tier A if the agent integration fights back, with Tier A alone still meeting the verification bar below except the live-demo item.

## Pricing draft (NOT public, NOT decided)
- MIT core free, corpus format open. A bench people cannot run themselves proves nothing, so the harness itself stays free.
- Paid candidate later only: curated/private corpora packs or hosted report history for teams. Not a v0.1 concern.

## Verification bar
- Reproducibility: a stranger following the README re-runs Tier A on the GhostBus corpus and gets the same per-task token numbers (same Slice + estimator versions), and the report states those versions.
- Honesty test: the shipped adversarial project must produce at least one visible failure or hard gap in the first published report. A first report with zero failures anywhere means the corpus is too easy and v0.1 is not done.
- Budget test: Tier B refuses to start without a cap and a confirmation, and stops at the cap mid-corpus, reporting partial results as partial.
- Traceability: every number in BENCH.md resolves to a bundle manifest hash + a bench-report.json row.

## Risks / honest notes
- Tier B numbers will be noisy: model updates, agent versions, and task flakiness move results more than small Slice changes do. Reports carry versions and re-run counts so noise is visible rather than argued about.
- A public bench invites gaming (tuning Slice to the corpus). Mitigation is procedural: corpus tasks rotate, held-out tasks are kept for release checks in the Seatbelt bench tradition, and reports name the corpus version.
- Cost framing: Bench shows estimator-based costs from a local, dated price table. Real bills differ. Say so on every report, same as Slice does.

## Next gate
Ryan's go on: (1) GhostBench as working name, (2) Tier A free/static by default, Tier B opt-in with a hard budget gate, (3) no LLM judge in v0.1, tests decide, (4) build order: Bench is #4 to *build*, but its corpus format should be sketched while Verify is built so Verify reports land Bench-ready from day one.
