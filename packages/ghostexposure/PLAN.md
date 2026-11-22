# GhostExposure - Audit Bundles with Proof of Exclusion, for GhostSlice
Working name, prepared Oct 14, 2026. Paired tool #10 for GhostSlice.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostExposure: an audit is about exposure, what could be reached, touched, or leaked. The tool measures and bounds the exposure surface you hand to a reviewer.
- Naming caution recorded: in the Oct 11 Goliath hunt, Ryan rejected fear/compliance/audit/checker-shaped B2B tools as the lead for Goliath (a non-agent product decision). Exposure is a Slice companion, not a Goliath candidate, and its job is evidence preparation, not fear selling. Copy must stay in that register: facts and manifests, no scare framing.
- Reserve alternative: GhostScope was already used for review packs (#5), GhostAudit is the generic crowded label. Treat Exposure as a working name until a name check runs at build gate, same discipline as GhostSlice Oct 12.

## The problem
Bringing an outside reviewer, human or agent, into a codebase has an unresolved tension:
- Give them the whole repo and you have shared customer data paths, unrelated proprietary code, and files nobody needed to see.
- Give them a hand-picked folder and neither side can prove later what was and was not shared. The reviewer also works half-blind, missing the callers of the code they are meant to judge.

Studios like Ryan's hit this with client code, security reviewers, and contractor agents. What is needed is a scoped bundle of only the sensitive surface (auth, payments, secrets handling, personal-data paths), with its necessary context, plus a manifest that lets either side verify afterward exactly what the bundle contained and that the rest of the tree was not in it.

## Position in the Ghost stack
- GhostSlice: bundles built to minimise tokens for a task.
- GhostExposure: bundles built to bound disclosure for a review. Token cost is secondary, inclusion/exclusion evidence is primary.
- GhostScope builds review packs centred on a *change*. Exposure builds review packs centred on a *sensitive surface*, change or no change.
- Agent Seatbelt governs live agent actions. Exposure governs a one-time hand-off artifact. GhostGuard is the governance family for actions and policy, Exposure does not evaluate policy and the two must not be described as the same layer.

## How it pairs with GhostSlice, concretely
Reuses, does not rebuild:
- Secrets guard as a sensor: files containing secret-shaped material, env/config handling code, and files the guard flags are inputs to surface detection, findings always redacted (path + line + type only).
- Scanner + workspaces + profile: the full tree inventory is the denominator. Exposure's core artifact is a partition of that inventory into IN BUNDLE and NOT IN BUNDLE, every file accounted for, no file in neither list.
- Call graph + import graph: sensitive files pull their direct context (callers/callees at signatures) so a reviewer can judge the surface without receiving the whole tree. Graph distance rules are the same ladder as Scope.
- Manifest + check + sha256: the bundle is a normal Slice bundle (validates with `ghostslice check`) plus an `exposure.json` sidecar: tree inventory hash, per-file in/out decision + reason code, surface definition used, tool versions.
- Surface definitions are data, not vibes: a surface pack lists path globs, symbol/name patterns, import patterns (for example a payments SDK import), and data-shape patterns (for example fields named like personal identifiers), each with an id and a plain-words reason. The user can read, edit, and pin a surface pack in `.ghostslice.json` (`exposure` section). No hidden built-in list decides what counts as sensitive.

## MVP (v0.1) - local bundle builder, evidence first, no verdicts
1. Inventory + surface scan: `ghostexposure scan <project> --surface <pack>`
   - Full inventory with in/out proposal per file and the reason codes that fired (glob / symbol / import / data-shape / graph-neighbour / user-pinned-in / user-pinned-out).
   - Conflict rule: a file matched by both a sensitive pattern and a user pin-out is listed as a conflict requiring a human decision, never resolved silently. A file matched as graph context is marked context, distinct from surface.
   - Scan prints what the pack does NOT cover in plain words (for example: it does not detect sensitive logic in files with no matching signals). This statement is also written into every export.

2. Bundle export: `ghostexposure export <project> --surface <pack> -o <folder>`
   - Surface files full, graph context at signatures, everything else absent. Follows Slice presets for the receiving party (generic default).
   - Writes `EXPOSURE.md`: surface definition (pack id + version + the full pattern list, readable), counts (files in tree, in bundle, surface vs context), token totals as estimates, the coverage limits statement, and verification instructions a receiver can run without trusting the sender.
   - Secret handling inside the bundle: if a surface file itself contains a secret-shaped literal, the export warns and, by default, applies Slice redaction to that value in the exported copy and records the redaction in the manifest. Exporting the literal unredacted requires an explicit flag whose use is also recorded. There is no quiet path that ships a live-looking key.

3. Verify a received bundle: `ghostexposure verify <bundle-folder>`
   - Re-runs Slice check, confirms the inventory hash + in/out partition in `exposure.json` matches the bundle contents, and confirms every tree file is accounted for in the partition.
   - States its limit in the output: this proves the bundle matches its manifest. It cannot prove a sender did not share other files by another channel, and the report says exactly that. The tool proves what is in the artifact, not what happened in the world.

4. Receiver mode note
   - The same `verify` command is the receiver's tool (no separate product). README is written for both sides of the hand-off.

## Out of scope for v0.1
- Security verdicts, vulnerability findings, compliance certifications, or pass/fail grades. Exposure prepares and proves a bundle, reviewers review. Any feature that starts scoring code quality is out.
- Scanning for vulnerabilities (SAST), dependency CVE lookups, or network calls of any kind.
- Legal advice, retention/deletion workflows, DLP across an organisation, monitoring, or ongoing surveillance of a repo.
- Redacting or altering the source project. All transforms happen in the exported copy only.

## Build estimate
- Inventory partition + reason-code engine over Slice scanner: 3 days
- Surface pack format + first pack (auth/payments/secrets/data starter pack, patterns cited and dated) + conflict handling: 3-4 days
- Export + EXPOSURE.md + redaction recording + verify command: 3 days
- Tests (partition completeness fixture where every file must be accounted for, conflict fixture, planted-key export fixture, tampered-bundle verify fixture): 2 days
Total: roughly 1.5 to 2 weeks to a verified v0.1 if built straight through.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI free, same pattern as Slice. A disclosure-evidence tool that is not inspectable loses its point.
- Paid candidate later only: studio-delivered audit-prep engagements for client codebases, a Ryan services decision, not a software gate in v0.1.

## Verification bar
- Partition test: on a fixture tree, in + out lists equal the inventory exactly, zero unaccounted, zero double-counted.
- Tamper test: adding one file to the exported bundle, or removing one surface file, makes `verify` fail and name the discrepancy.
- Key test: exporting a fixture with a planted secret-shaped literal produces a bundle with zero occurrences of that literal on the default path, and a manifest redaction record.
- Limit-statement test: EXPOSURE.md and verify output both contain the coverage-limits and cannot-prove-other-channels statements. Missing statement fails the build.

## Risks / honest notes
- Surface detection is pattern-bound and will miss novel sensitive code. The coverage statement is not legal boilerplate, it is the product being honest about its main failure mode. Never market a bundle as "everything sensitive".
- Overclaiming is the existential risk for this tool. Names, README, and reports must stay in evidence language (contained, accounted for, verified against manifest) and out of assurance language (safe, compliant, certified).
- Surface packs encode judgement calls. Versioning them, dating patterns, and letting the receiving side read the exact pack used are what make an Exposure bundle arguable-with rather than trust-me.

## Next gate
Ryan's go on: (1) GhostExposure as working name, with the no-fear-framing rule, (2) evidence only, no security verdicts or grades in v0.1, (3) default-redact rule for secret-shaped literals in exports, (4) build slot: Exposure is #10 in the suite, demand-driven (client or reviewer hand-off on the table).
