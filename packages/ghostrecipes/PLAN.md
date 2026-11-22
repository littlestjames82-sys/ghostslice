# GhostRecipes - Versioned Workflow Recipes for the Ghost Stack
Working name, prepared Oct 14, 2026. Wave 3 tool #21 for GhostSlice / Ghost Developer Studio.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostRecipes: plain job, plain name. A recipe is a repeatable workflow written down once, followed the same way every time.
- Checked against the family: GhostPacks shares *context profiles*, GhostRecipes shares *process*. No overlap in the name or the job.
- Alternatives held in reserve: GhostPlaybooks (longer, implies enterprise runbooks), GhostLoops (implies the tool runs the loop itself, which v0.1 must never do).

## The problem
Ryan's best workflows live in chat history and habit, not in files:

- The GhostSlice 20-goal marathon loop: build, audit, improve twice, parent-verify, push, release, with gates held at PyPI and announcements.
- The companion build pattern used Oct 14, 2026: Agent A owns core, Agent B owns tests/README/examples, no file collisions, parent verification per tool.
- The draft-first outreach loop: draft, Ryan approves verbatim text, send, verify in-thread, watch for replies, never send a follow-up unapproved.

Every time one of these runs, it is re-explained from scratch. Steps get skipped, order drifts, gates get re-decided, and a new agent (or a tired human at 1 AM) has no checklist to follow. There is no versioned, shareable, machine-validatable format for "how we do this here."

## Position in the Ghost stack
- GhostSlice governs what an agent READS.
- GhostPacks governs shareable context PROFILES (data-only packs for Slice).
- GhostRecipes governs repeatable PROCESS: the ordered steps, gates, inputs, and checks of a workflow, as data.
- Agent Seatbelt governs what an agent DOES. GhostRecipes never does anything: it describes, validates, and renders. Execution, if any ever happens, belongs to a human or to a separately gated tool, never to Recipes in v0.1.

Story: Packs share the setup -> Recipes share the method -> a human or agent follows the rendered checklist under Seatbelt -> Verify checks the result.
No overlap: Packs fragments are Slice profiles. Recipe files are workflow descriptions. A recipe may *name* a pack, a Slice profile, or a tool in a step; it never embeds or installs one.

## How it pairs with the Ghost stack, concretely
Reuses, does not rebuild:
- Data-only pack discipline from GhostPacks: only .json/.md/.txt files, no executable bit, no shebang, unknown keys fail loudly, hashes in a manifest, import verifies hashes before copying anything.
- Slice format conventions: same PLAN shape, same exit-code discipline (0 ok, 1 validation failure, 2 usage/config error), same local library pattern (--library flag, environment variable, per-user folder, bundled folder).
- The marathon loop itself is the reference recipe: Ryan's build/audit/improve-twice/verify/push loop is the workflow the format was designed to capture exactly, step for step, gates included.

Integration contract:
- Input: recipe files on local disk. A recipe is one file: `<id>.recipe.json` (canonical) or `<id>.recipe.md` (a Markdown file whose recipe is the single fenced json block it contains, so a recipe can live inside human notes without a second format to learn).
- Output: validation verdicts, library listings, rendered Markdown checklists / prompt files, and data-only export packs (folder + manifest.json with sha256 per file).
- A rendered checklist is a *document for a human or an agent to follow*. Command hints inside steps are printed text labelled "run manually". GhostRecipes contains no code path that runs them.

## The recipe format (v0.1)
Top-level object, unknown keys rejected by name:
- `id` (required): slug, lowercase letters/digits plus `._-`, starting with a letter or digit.
- `name` (required): human title.
- `version` (required): `MAJOR.MINOR.PATCH` numbers. Recipes are versioned; changing steps means bumping the version, so two people following "the same recipe" can prove it by id + version + file hash.
- `description` (required): what the workflow achieves and when to use it.
- `steps` (required, non-empty): ordered list, see below.
- Optional: `tags`, `author`, `date` (YYYY-MM-DD), `category`, `tools` (names of tools the workflow uses, informational only), `inputs`, `notes`.

Each step object, unknown keys rejected by name:
- `id` (required, unique in the recipe): slug.
- `title` (required): one line, checklist wording.
- `kind` (required): one of `manual`, `check`, `run`, `review`, `approve`, `note`. `run` means "the follower runs this"; it is a label, not an instruction to this tool.
- Optional: `detail` (longer instructions), `command_hint` (a command shown as text for manual use only), `tools`, `gate` (what must be true / who must approve before continuing), `repeat` (e.g. "twice" for the improve-twice step).

Each input object, unknown keys rejected by name:
- `name` (required, unique): used in `{{name}}` placeholders inside description/detail/command_hint text.
- Optional: `description`, `required` (bool), `default` (string).
Placeholders naming an undeclared input are a validation warning, not an error, so a draft recipe still validates while it is being written.

Data-only enforcement, all checked by `validate`:
- Files only .json/.md/.txt in recipes and packs; executable permission bit or a shebang anywhere fails.
- No key anywhere in a recipe may claim an execution hook: keys outside the allowlists above fail by name, which is what keeps fields like an auto-run command, a script path, or an on-load hook out of the format entirely.

## MVP (v0.1) - local CLI first
1. Create: `ghostrecipes create --id <id> --name "..." -o <file>` (plus --description, --tags, --steps "Title; Title; ..." scaffolding steps). Writes a valid, versioned 0.1.0 recipe; refuses to overwrite without --force.
2. List: `ghostrecipes list [--library DIR] [--json]` over the local library (explicit --library, $GHOSTRECIPES_LIBRARY, ~/.ghostrecipes, ./recipes, bundled recipes/ next to the checkout). Invalid recipes are listed as INVALID with the reason, never silently skipped.
3. Show: `ghostrecipes show <id-or-path> [--json]` prints the recipe, its version, step count, inputs, and file hash.
4. Validate: `ghostrecipes validate <path-or-id-or-folder>` checks format, version shape, unique step/input ids, kind values, placeholder warnings, and the data-only rules. Exit 1 on any error.
5. Export / import as a data-only pack, same shape as GhostPacks:
   - `ghostrecipes export <id-or-path> -o <folder>`: writes the recipe file(s) plus `manifest.json` (format stamp, tool version, per-file sha256, recipe id + version). Refuses to overwrite a non-empty folder without --force.
   - `ghostrecipes import <pack-folder> [--library DIR] [--force]`: verifies the manifest and every hash, validates every recipe, rejects executable files, symlinks, and path-traversal entries, then copies recipe files into the library. A name collision without --force writes nothing.
6. Render: `ghostrecipes render <id-or-path> [-o <file.md>] [--var name=value ...]`
   - Produces a human checklist / prompt file: title, description, inputs table (defaults applied, --var overrides), then numbered steps as `- [ ]` checklist items with detail, gate lines, and command hints in fenced blocks labelled as manual steps.
   - Unresolved placeholders are left visible in the output and listed at the end, never guessed.
   - Without -o, prints to stdout. Render never modifies the recipe.

## Out of scope for v0.1
- Running any step, command, script, or tool named in a recipe. No exceptions, no opt-in flag. This is the tool's central rule.
- Calling a model, dispatching an agent, scheduling, or watching files (GhostWatch's job).
- A recipe marketplace, downloads, accounts, telemetry, or any network use.
- Editing Slice profiles or Packs packs. A recipe names them; Packs and Slice own them.
- Judging whether a followed recipe *succeeded*. That is GhostVerify / GhostBench evidence, not a recipe concern.

## Build estimate
- Format + validator + library discovery: 2-3 days
- create/list/show: 1 day
- Export/import pack with hashes and traversal guards: 1-2 days
- Render with inputs and placeholder handling: 1-2 days
- Tests (valid/invalid fixtures, traversal and data-only adversarial packs, render golden files), README, starter recipes (marathon loop, companion A/B build, draft-first outreach): 2 days
Total: roughly 1 to 1.5 weeks to a verified v0.1 if built straight through.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI free, same pattern as Slice / Seatbelt / Ghost Hands.
- Paid candidate later only: team recipe libraries / hosted sharing. Do not build a paid layer before a free launch validates demand.

## Verification bar
- Round trip: create a recipe, validate it, export it, import it into a fresh library, and the imported file hash equals the original.
- Marathon fidelity: the starter marathon-loop recipe renders to a checklist containing every real step in order (build, audit, improve twice, verify, push, release) with the PyPI/announcement gates shown as approve steps.
- Data-only adversarial tests: a pack containing an executable file, a shebang, a path-traversal manifest entry, or a recipe with an unknown execution-style key each fails with the reason named, and import writes nothing.
- No-execution proof: source scan of src/ finds no process-spawning, network, or dynamic-code tokens at all; a recipe whose command hint would be destructive renders as inert text and nothing runs.

## Risks / honest notes
- The format is the product. If the step schema is too loose, recipes drift into prose nobody can validate; too strict, and real workflows do not fit. v0.1 chooses strict keys with free-text detail fields as the pressure valve.
- Command hints are the risky surface: they look executable. Every render labels them manual, the validator rejects execution-hook keys, and the tool ships with no runner at all, so a future runner would be a new tool with its own gate, not a flag here.
- A recipe records a workflow; it does not prove the workflow is good. Bench/Verify evidence decides that, and recipe copy must not claim otherwise.

## Next gate
Ryan's go on: (1) GhostRecipes as working name, (2) data-only forever in the core tool, any future runner as a separate gated tool, (3) JSON canonical with the Markdown json-block variant, (4) starter recipe set: marathon loop, companion A/B build, draft-first outreach.
