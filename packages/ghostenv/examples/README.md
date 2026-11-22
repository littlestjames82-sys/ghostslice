# GhostEnv examples

A tiny walkthrough on `mini_project/`. Every value in this folder
is a FAKE placeholder, clearly labelled fake. No real credential
appears in examples, ever.

## The project

`mini_project/app.py` reads three names:

- `DATABASE_URL` - `os.environ["DATABASE_URL"]`
- `DEMO_API_KEY` - `os.getenv("DEMO_API_KEY")`
- `CACHE_TTL_SECONDS` - `os.environ.get(...)` with a default

`mini_project/.env.example` lists exactly those three names with
empty values. `mini_project/.env.fake` shows the *shape* of a
local `.env` with invented, fake-labelled values, so the walkthrough
has something to compare against. It is not a real `.env` and
GhostEnv never prints values from a real one.

## Walkthrough

```bash
# 0. Scan: just the code side (names, file, and line per read)
ghostenv scan examples/mini_project
# Expected shape: DATABASE_URL, DEMO_API_KEY, and
#    CACHE_TTL_SECONDS, each with its read site in app.py.

# 1. Check: code usage vs .env vs .env.example (names only)
ghostenv check examples/mini_project
# Expected shape: exit 1. There is deliberately no real .env in
#    examples (secrets do not ship), so the verdict names
#    DATABASE_URL and DEMO_API_KEY as missing from .env with no
#    default. CACHE_TTL_SECONDS is soft: its read site has one.
# Point check at the fake shape file to see a clean contract:
ghostenv check examples/mini_project \
  --env-file examples/mini_project/.env.fake
# Expected shape: exit 0, "contract complete".

# 2. Break it on purpose in a copy: delete the copy's whole
#    .env.example, then re-check against the fake env file.
# Expected shape: exit 1, the verdict names the missing example
#    file and the undocumented names. (Removing a single line
#    from an example file that exists is listed under
#    missing-in-example; on its own it does not block.) The
#    report names variables. It does not and cannot show any
#    value, because it never reads one out.

# 3. Generate a clean example from code + .env names
ghostenv example examples/mini_project -o /tmp/new.env.example
# Expected shape: the generated file lists DATABASE_URL,
#    DEMO_API_KEY, and CACHE_TTL_SECONDS with empty values.
# Add --stdout instead of -o to preview without writing a file.
```

## What a generated example looks like

Names grouped by the prefix before the first underscore, one
`NAME=` line each, every value empty. This is the whole shape;
there is nothing else in the file to leak:

```text
# --- CACHE ---
CACHE_TTL_SECONDS=

# --- DATABASE ---
DATABASE_URL=

# --- DEMO ---
DEMO_API_KEY=
```

(The real output also carries the GhostEnv header comment
stating that the file contains names only.)

Exact subcommand spelling follows the shipped CLI (`--help` is the
authority); the test suite discovers it from help for the same
reason.

## The rule the examples demonstrate

Names only, never values. A report can say `DEMO_API_KEY is used
in app.py and missing from .env.example`. It must never contain
what `DEMO_API_KEY` is set to, in the project, in a generated
example, or anywhere else.
