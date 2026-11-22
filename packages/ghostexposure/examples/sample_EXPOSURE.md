# Exposure bundle: mini_project

Sample output. This is what the `EXPOSURE.md` inside an exported bundle
looks like. Numbers are from the invented mini project in this folder.

## Surface definition used

- Pack: `starter-auth-payments-data` version `0.1.0` (dated 2026-10-14)
- Patterns (id, kind, pattern, reason):
  - `glob-auth`, glob, `auth/**`: Authentication code is part of the sensitive surface.
  - `glob-payments`, glob, `payments/**`: Payment handling code is part of the sensitive surface.
  - `glob-config`, glob, `config/**`: Configuration and secrets handling are part of the sensitive surface.
  - `import-stripe`, import, `stripe`: Files importing a payments SDK handle payment data.
  - `symbol-login`, symbol, `login|authenticate|verify_password`: Authentication entry points are part of the surface even outside auth/.
  - `data-personal`, data, `email|ssn|date_of_birth|password_hash`: Fields shaped like personal identifiers are part of the surface.

## Counts

- Files in tree inventory: 2
- Files in bundle: 1 (surface: 1, context: 0)
- Files accounted for as out: 1
- Estimated tokens in bundle: 42 (estimate, GhostSlice estimator, prices table dated 2026-10-14)

## Decisions

| File | Decision | Reasons |
|---|---|---|
| `auth/login.py` | surface | glob:auth/** |
| `util/format.py` | out | no matching signal |

## Redactions

None in this sample. Any redaction would be listed here by file and
finding type, never by value.

## Coverage limits

This pack does not detect sensitive logic in files with no matching
signals. It covers only the patterns listed above. Files with sensitive
logic but no matching signal are not in this bundle, and this statement
is part of the bundle so the limit travels with it.

## What verification proves, and what it does not

Run `ghostexposure verify <this-bundle-folder>` to check that this
bundle matches its manifest (`manifest.json` + `exposure.json`) and that
every file in the tree inventory is accounted for in the partition.

Verification cannot prove a sender did not share other files by another
channel. It proves what is in this artifact, not what happened in the
world.
