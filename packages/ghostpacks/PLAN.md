# GhostPacks - Shareable Profile and Slicer Packs for GhostSlice
Working name, prepared Oct 14, 2026. Paired tool #11 for GhostSlice.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostPacks: a pack is a bundle of tuned Slice settings (and optionally a slicer plugin) for a stack, ready to drop in. The word already does honest work in the family: GhostLang ships policy packs, GhostGuard ships policy packs. A Slice pack is the same idea for context.
- That family reuse is also the caution: packs here are *context* packs, never policy or permission packs, and the format carries a `kind: context` field so no tool can mistake one for the other.
- Treat as a working name until a name check runs at build gate, same discipline as GhostSlice Oct 12.

## The problem
A good `.ghostslice.json` profile is earned knowledge: which folders in a Next.js app are generated, which Django paths are migrations, how a monorepo's packages should be moded, which files are entry points. Today every user re-earns it per project, or runs `ghostslice init` and gets a decent generic start that knows nothing about their stack.

`init` is static analysis of one project. It cannot know the stack's conventions. The people who do know them (framework communities, experienced users, Ryan across his own repos) have no format to share that knowledge in, and no way to keep it updated as stacks change.

Packs are that format: stack knowledge as data, versioned, inspectable, scored by GhostBench on reference projects.

## Position in the Ghost stack
- GhostSlice core stays pack-free and fully usable alone. Packs are an accelerator, never a requirement.
- GhostPacks is a format + a local manager CLI + a starter library. It is not a store, a registry service, or a marketplace in v0.1.
- GhostBench supplies the scoring method (savings + task-fit on stated reference projects, Tier A). A pack without a Bench result is labelled unscored, in the manager and in any listing.
- Plugins (Slice v0.23 plugin system, G18) are the code extension point. A pack may *reference* a compatible plugin, but the manager never installs executable code in v0.1, see the safety rules. That line is deliberate.

## How it pairs with GhostSlice, concretely
Reuses, does not rebuild:
- Profile format is the payload: a pack's core is a profile fragment (ignores, per-glob modes, entry-point hints, budget defaults, workspace hints) in the exact `.ghostslice.json` schema, plus a `pack.json` manifest (id, version, kind: context, stack tags, compatible Slice version range, reference projects, Bench report reference, author, date).
- Slice profile loader rules apply unchanged: merging a pack into a project profile produces a normal profile file the user owns and can read, diff, and edit. Unknown keys fail loudly at merge time, not at some later run.
- Plugin contract knowledge: the manager can verify a referenced plugin exists locally and satisfies the Slice plugin contract checks Slice itself performs. It does not fetch or run it as part of installing a pack.
- Doctor pattern: `ghostpacks doctor` mirrors `ghostslice doctor` (pack validity, compatibility, stale Bench results, profile merge preview).
- History: merges are recorded in the project profile itself (a comment-style provenance block is not possible in JSON, so provenance lives in a sibling `.ghostslice-packs.json` lockfile: pack id, version, source, date merged, profile hash after merge). Reproducing a project setup means sharing the profile + the lockfile.

## MVP (v0.1) - format, local manager, three starter packs, no network
1. Pack format + validation: `ghostpacks lint <pack-folder>`
   - Validates manifest + profile fragment against the live Slice schema, checks the kind field, checks referenced Bench report exists if a score is claimed, checks no absolute paths, no executable files in the pack folder (data only, enforced).
   - A pack is a folder a human can read top to bottom in minutes. If it cannot be eyeballed, it is not a valid v0.1 pack.

2. Local manager: `ghostpacks list / show / merge / remove`
   - Packs live in a local library folder (`~/.ghostpacks/` by default, path in output). `merge` previews a full profile diff and requires an explicit yes, then writes the merged profile + lockfile entry. `remove` reverses a merge using the recorded pre-merge profile hash + a kept backup, or reports exactly why it cannot reverse cleanly (user edited since) instead of guessing.
   - Sources in v0.1: a local folder, or a git clone the *user* already made. The manager contains no download code, no registry client, no update checker. Getting a pack onto the machine is the user's existing git/file habits.

3. Starter library (ships in the repo, Bench-scored)
   - Three packs only, chosen for Slice's actual strengths and Ryan's real work: a Python library pack, a Next.js / TypeScript app pack, a monorepo pack built on Slice workspace detection.
   - Each ships with its Bench Tier A report on a stated reference project (a fixture or a real open repo state recorded by hash), savings and mode choices visible. A pack whose Bench result is embarrassing ships anyway with the number shown, or does not ship. No silent cherry-pick.

4. Authoring helper: `ghostpacks init-pack <project>`
   - Turns a tuned project profile into a draft pack (manifest skeleton, profile fragment, provenance stripped of absolute paths), for Ryan to publish his own project knowledge as packs. Draft only, still needs lint + Bench before it can claim a score.

## Out of scope for v0.1
- Any hosted registry, marketplace, ratings, accounts, payments, auto-updates, or telemetry about installed packs.
- Installing, downloading, or executing plugin code or any executable content.
- Pack signing infrastructure. v0.1 trust model is stated plainly: read the pack, it is data, merges are previewed and reversible. Signing is a v0.2 candidate if a public library actually forms.
- Merging packs automatically into a project (agent-initiated merges included). A human runs merge.

## Build estimate
- Format + lint + lockfile + manager (list/show/merge/remove with preview + backup): 4-5 days
- Three starter packs, each tuned + Bench Tier A scored on a reference project: 3-4 days
- Authoring helper + doctor: 1-2 days
- Tests (tampered pack with an executable file must fail lint, merge/remove round-trip, conflicted merge preview, unscored pack labelling): 2 days
Total: roughly 1.5 to 2 weeks to a verified v0.1 if built straight through. Smallest build in the second wave.

## Pricing draft (NOT public, NOT decided)
- Format + manager + starter packs free under the Slice MIT pattern.
- Paid candidate later only: maintained premium packs for fast-moving stacks, or a studio pack library for client stacks. Nothing priced, no store built, until a free library shows real adoption.

## Verification bar
- Round-trip test: merge a starter pack into a fixture project, run Slice export, remove the pack, export again, second export matches the pre-merge totals exactly.
- Safety test: a pack folder containing any executable or script file fails lint, and a profile fragment with an unknown key fails merge with the key named.
- Score honesty test: `ghostpacks show` on an unscored pack prints unscored in the summary line, and a pack claiming a score without a Bench report file fails lint.
- Real demo: the Next.js pack merged into a real reference project beats the generic `init` profile on estimated bundle tokens for the same task selection, with both numbers in the build report, whatever they turn out to be.

## Risks / honest notes
- A bad pack silently worsens context for everyone who trusts it. Bench scoring + diff preview + reversibility are the mitigations, and the manager copy must point at them instead of at convenience.
- Stack packs rot as frameworks release majors. Packs carry stack version ranges and dates, `doctor` flags out-of-range use as a warning with the range printed, never as a silent pass.
- Ecosystem plays fail quietly if nobody authors packs. The authoring helper + Ryan's own repos as pack sources are the seeding plan; if three months of use produces no third-party pack, that is evidence about demand, recorded honestly, not a prompt to build a marketplace to force it.

## Next gate
Ryan's go on: (1) GhostPacks as working name, with the kind: context guard, (2) data-only packs, no code install, no network in the manager in v0.1, (3) three starter packs as scoped, Bench-scored or labelled unscored, (4) build slot: Packs is #11 in the suite, cheap enough to pull earlier if an ecosystem push is wanted.
