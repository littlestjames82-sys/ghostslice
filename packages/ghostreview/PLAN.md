# GhostReview - Plain-English Verdict Layer for GhostSlice Changes
Working name, prepared Oct 14, 2026. Wave 3 tool for GhostSlice.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostReview: plain job, plain name. It reviews a change and says, in plain
  English, what happened and what needs a second look.
- Name note, stated honestly: GhostScope's plan held GhostReview in reserve
  because it sounded generic and close to review bots. Ryan approved the
  Wave 3 list on Oct 14, 2026 with GhostReview on it as the human-readable
  verdict layer, so the name is used as approved. Treat as a working name
  until a name check runs at any release gate, same as GhostSlice did Oct 12.
- Alternatives held in reserve: GhostVerdict (accurate but colder, and a
  verdict must never sound like an approval), GhostRecap (too casual for a
  risk summary).

## The problem
The GhostSlice companions already answer the machine questions about a
change, and none of them answers the human question in human words:

- GhostSlice says what an agent should READ.
- GhostScope builds a change-centred review PACK: the diff in full,
  callers/callees by graph distance, covering tests, risk reasons, a
  ranked reading order. Its output is a bundle to read, not a verdict.
- GhostVerify says whether a slice was ENOUGH and whether a patch HOLDS:
  pass/fail evidence from static, graph, and opt-in test checks in a
  temp copy.

A solo developer running many agents in parallel does not have time to
open a pack, a verify report, and a raw diff for every finished agent and
translate them into "what did it actually do, what does it touch, and is
there anything here I should look at twice before this merges?" That
translation is done by eye, from memory, or not at all, and rubber-stamped
merges are where agent mistakes land.

GhostReview is that translation, and only that translation. It reads the
diff (and, when they exist, the Scope pack and the Verify report for the
same change) and writes one short plain-English review a tired human can
act on in under a minute.

## Position in the Ghost stack
- GhostScope governs review READING (the pack). GhostReview sits on top of
  it and governs the review VERDICT SUMMARY (the words).
- GhostVerify governs sufficiency and patch evidence. Review never re-runs
  Verify's checks; it cites a Verify verdict when one is supplied.
- GhostReview approves nothing, merges nothing, and comments nowhere. The
  verdict is a summary with a risk level, not a merge decision. The human
  decides.
- Agent Seatbelt governs what an agent DOES. Ghost Hands is the governed
  browser body. Review governs nothing but the summary.

Story: Slice -> agent runs under Seatbelt -> Verify (post) + Scope (pack)
-> Review (plain-English verdict summary) -> human accepts or sends back.
No overlap: Scope does not write verdict prose, Verify does not write
plain-English change narration, Review builds no pack and runs no check
of its own beyond a simple import scan for dependents.

## How it pairs with GhostSlice, concretely
Reuses, does not rebuild:
- Diff shape: the same unified diff GhostScope parses (git range output,
  a .diff file, staged or working-tree changes). Review parses it for
  file status, hunks, and added/deleted lines; it does not build Scope's
  graph-distance pack.
- GhostScope pack (OPTIONAL input): if a pack directory or its scope.json
  is supplied, Review reads scope.json only: changed files, risk reasons,
  reading order, token totals. Those facts are cited in the verdict, not
  recomputed. If no pack is supplied, Review says so and works from the
  diff alone.
- GhostVerify report (OPTIONAL input): if a verify-report.json is
  supplied, Review reads its verdict, exit code, gap counts, and post
  patch outcome and cites them. If none is supplied, the review says
  "no Verify report was provided" in plain words; it never implies a
  check ran that did not.
- Symbol outlines: Python symbols exact via ast on the current file,
  other languages parser-lite by line patterns, labelled per file with
  the method used. Same honesty split as Slice: Python complete,
  everything else labelled parser-lite.
- Secrets discipline (Slice v0.4 guard behaviour): a secret-shaped added
  line is reported as path + line + type only. The value is never copied
  into REVIEW.md, review.json, stdout, or any log.

Integration contract:
- Input: project path + a diff source (a .diff file, or the git working
  tree, or staged changes), plus optional --verify-report and
  --scope-pack paths.
- Output: REVIEW.md (plain English) + review.json (same facts,
  machine-readable) in the output directory the user names, or the
  current directory by default. Never inside the project source tree by
  default, and the working tree is never modified.
- Review is a pure function of its inputs: same diff + same optional
  reports + same project tree produce the same review.json except for
  the generated-at timestamp.

## MVP (v0.1) - local CLI first, no dashboard
1. Review a diff: `ghostreview review <project> [--diff <file.diff> | --staged]`
   - Default diff source is the git working tree against HEAD
     (`git diff HEAD`), which covers staged and unstaged tracked changes.
     Untracked files are listed as a note, never silently included.
   - `--diff -` reads the diff from stdin.
   - Per file: status (added / modified / deleted / renamed), lines added
     and deleted, hunks, binary flag.
   - Per file symbols touched: symbols whose definition is added, deleted,
     or whose body range contains an added/deleted line. Python via ast,
     other languages via definition-line patterns matched against the
     added/deleted line texts. Method labelled per file.
   - Totals: files changed by status, total additions and deletions.

2. Dependents affected (simple import scan, deliberately simple)
   - Scans project source files (skipping .git, caches, vendored and
     generated trees) for imports of each changed file: Python module
     imports (ast where parseable, regex otherwise) and JS/TS relative
     imports resolved against the importing file.
   - Reports, per changed file, the project files that import it and are
     NOT themselves in the diff, as "dependents affected". This is a
     one-hop import scan, not Scope's call graph and not transitive
     blast radius; the report says exactly that, with the method named.
   - Files that reference a changed file only by name string are not
     claimed as dependents. No invented edges.

3. Risk flags (explicit rules, every flag cites file + reason)
   - TEST-EDIT: a test file was added, edited, or deleted in the diff.
     A deleted test file is high: a change that removes its own covering
     test needs a human look, stated as a fact, not an accusation.
   - CONFIG: a config-shaped path changed (CI config, package/build
     config, .env-shaped names, editor/tool config). Dependency manifest
     changes (pyproject.toml, package.json, requirements files, lockfiles)
     are flagged separately as DEPENDENCY.
   - SECRET-PATH: a changed path is secret-shaped (.env, credentials,
     key/cert material by extension or name). SECRET-SHAPED-LINE: an added
     line matches a secret shape (labelled key assignment, token prefix,
     private key header). Path + line + type only, value never shown.
   - LARGE-DELETION: a single file loses 100 or more lines, the diff
     deletes 300 or more lines in total, or a whole file is deleted.
     Thresholds are constants in one place (risks.py) and named in the
     report, so a reader can judge them.
   - SYMBOL-REMOVED: a symbol defined in deleted lines has no matching
     definition in added lines of the same file. Dependents may still
     call it; Review states the fact and lists the dependents found.
   - NO-TEST-IN-DIFF (info level): code files changed and no test file
     appears in the diff. An observation, not a failure.
   - BINARY: a changed file is binary; its contents cannot be reviewed
     from the diff, stated plainly.
   - VERIFY-FAILED (high, only when a Verify report is supplied): the
     supplied verify-report.json verdict is not a pass.

4. Verdict summary (the product)
   - Verdict is one of: straightforward / needs-a-look / needs-attention /
     could-not-review. It is derived only from the flags above by a
     stated rule: any high flag means needs-attention, any medium flag
     means needs-a-look, otherwise straightforward. An empty or
     unparseable diff is could-not-review with exit 2, never
     straightforward.
   - The summary paragraph is template-generated from counted facts:
     files by status, lines added/deleted, biggest change by lines,
     dependents count, top risks in flag order, Verify verdict if one
     was supplied, Scope risk reasons if a pack was supplied. No LLM,
     no prose invented beyond the templates, no causes guessed: if the
     evidence does not say why a change was made, Review does not say.
   - REVIEW.md sections: Verdict, What changed (per file, plain words),
     Symbols touched, Dependents affected, Risks, Verify and Scope
     (what was supplied and what each said, or that neither was),
     Honest limits.
   - review.json carries every fact REVIEW.md shows, plus per-flag rule
     names and per-file symbol methods, so Bench or CI can consume the
     verdict without parsing prose.

5. MCP tool (stdio, local only)
   - `review_diff` with capped summary payload, same discipline as the
     Slice and Verify MCP servers (no raw file bodies, no diff text).

## Out of scope for v0.1
- Building a review pack, slicing, or graph-distance analysis. That is
  GhostScope. Review consumes a Scope pack, it never builds one.
- Running Verify checks, applying patches, or running tests. That is
  GhostVerify. Review cites a Verify report, it never produces one.
- Calling any model API or generating prose with an LLM. Every sentence
  in REVIEW.md comes from a template over counted facts.
- Invented causes, intent, or quality judgements ("this looks wrong").
  Review states what changed and what the rules flagged, nothing more.
- Approving, requesting changes, merging, committing, or posting a
  comment anywhere. GitHub/GitLab APIs and any hosting integration.
- Cross-repo diffs. One project, one diff.
- Cloud, accounts, telemetry, paid layer.

## Build estimate
- Diff parser + git diff sources: 1-2 days
- Symbol extraction (Python ast + parser-lite patterns): 1-2 days
- One-hop import scan for dependents: 1-2 days
- Risk rules + verdict derivation: 1 day
- Reports (REVIEW.md templates + review.json), Verify/Scope readers,
  CLI + MCP: 1-2 days
- Tests (planted fixtures per risk rule), README, demo on a real
  GhostSlice-family change: 1-2 days
Total: roughly 1 to 1.5 weeks to a verified v0.1 if built straight through.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI free, same pattern as Slice / Seatbelt / Ghost Hands.
- Paid candidate later only: team verdict history or hosted PR summaries.
  Do not build a paid layer before a free launch validates demand.

## Verification bar
- Known-diff test: a fixture diff with one added file, one modified file,
  and one deleted file must produce the exact per-status counts and a
  REVIEW.md whose numbers match review.json.
- Risk tests, one per rule: a test-file edit flags TEST-EDIT, an .env
  path flags SECRET-PATH, a secret-shaped added line flags
  SECRET-SHAPED-LINE with the value absent from every output, a 100-line
  deletion flags LARGE-DELETION, a deleted test flags high.
- Dependent test: a fixture project where b.py imports a.py, a diff
  touching a.py must list b.py as a dependent; an unrelated diff must
  list none. No invented edges pass.
- Citation test: with a Verify report and a Scope pack supplied, the
  review cites both verdicts verbatim; with neither supplied, it says so
  in plain words and claims no check ran.
- Honesty test: an empty diff exits 2 with could-not-review, never a
  clean verdict.

## Risks / honest notes
- Symbol touch detection for non-Python files is line-pattern level: a
  change inside a long function whose definition line is far away may be
  attributed to no symbol. The per-file method label and the honest-limits
  section say this; counts of symbols are labelled by method, never
  averaged into a false precision.
- The import scan is one hop and import-shaped only. Runtime, dynamic,
  and string-based references are missed by design in v0.1; Scope's graph
  pack is the tool for blast radius. Review must never present its
  dependent list as complete.
- A verdict derived from rules will be argued with. That is why every
  verdict prints its flags and every flag prints its rule. A bare score
  or a bare verdict would kill trust in the tool.
- The verdict is a summary, not a guarantee a change is safe. Copy must
  say "no risks flagged by these rules" not "this change is safe".

## Next gate
Ryan's go on: (1) GhostReview as working name for the verdict layer,
distinct from GhostScope the pack builder, (2) CLI-first, templates only,
no LLM prose in v0.1, (3) Verify and Scope inputs optional and cited,
never required and never faked, (4) build slot: Review is Wave 3, built
alongside the other Wave 3 tools at Ryan's Oct 14, 2026 direction.
