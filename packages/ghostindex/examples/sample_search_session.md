# Sample GhostIndex session

A real session against the two tiny projects in this folder
(`project_alpha` and `project_beta`), captured from the v0.1 CLI
on the build machine and refreshed Oct 18, 2026 so the output
matches the current CLI exactly. Root paths print absolute there;
on your machine they will show your own paths. The database lives
in a scratch folder for the demo; by default it would live in the
local state dir, and `--db` chooses the file. Match lines are
marked with `>`; every token figure is an estimate.

```console
$ ghostindex index examples/project_alpha examples/project_beta --db <scratch>/demo.db
Indexed /home/hatch/workspace/ghostindex/examples/project_alpha
  added 3, changed 0, removed 0, unchanged 0
  skipped by ignore rules: 1 {'ignored_dirs': 0, 'ignored_files': 1, 'binary_ext': 0, 'default_files': 0, 'symlinks': 0, 'unreadable': 0}
  files in index for this root: 3, ~86 estimated tokens
  estimator: estimates (BPE-like split v2, per-language calibrated, not exact tokenizer counts)
Indexed /home/hatch/workspace/ghostindex/examples/project_beta
  added 2, changed 0, removed 0, unchanged 0
  files in index for this root: 2, ~87 estimated tokens
  estimator: estimates (BPE-like split v2, per-language calibrated, not exact tokenizer counts)
```

One search spans both projects. The header counts every matching
file before any cap applies (`3 of 3` here, so nothing was capped):

```console
$ ghostindex search "sunflower festival" --db <scratch>/demo.db
3 of 3 matching file(s) for 'sunflower festival' (token figures are estimates)

1. src/ledger.py (python, match)
   root: /home/hatch/workspace/ghostindex/examples/project_beta
   excerpt ~49 estimated tokens, whole file ~65
   L2-L6
         2  
         3  
         4  def close_books(month):
   >     5      """Close the books; also mentions the sunflower festival budget."""
   >     6      return {"month": month, "festival": "sunflower festival"}

2. src/greeter.py (python, match)
   root: /home/hatch/workspace/ghostindex/examples/project_alpha
   excerpt ~43 estimated tokens, whole file ~58
   L2-L6
         2  
         3  
         4  def greet(name):
   >     5      """Return a friendly greeting mentioning the sunflower festival."""
   >     6      return f"Hello {name}, see you at the sunflower festival"

3. README.md (markdown, match)
   root: /home/hatch/workspace/ghostindex/examples/project_alpha
   excerpt ~22 estimated tokens, whole file ~22
   L1-L3
         1  # Example Alpha
         2  
   >     3  A tiny example project. Its greeter talks about the sunflower festival.
```

The alpha example project has a `scratch_notes.py` file that its
`.gitignore` lists. Its planted term answers nothing, because the
file was never indexed:

```console
$ ghostindex search scratchterm --db <scratch>/demo.db
no matches for 'scratchterm'
(exit code 1)
```

```console
$ ghostindex stats --db <scratch>/demo.db
index database: /tmp/tmpdypgshwv/demo.db (53248 bytes)
roots: 2, files: 5, source bytes: 604
total content: ~173 estimated tokens
estimator: estimates (BPE-like split v2, per-language calibrated, not exact tokenizer counts)
search defaults: at most 10 hits, ~2000 total excerpt tokens, ~200 per hit (search output states when a cap binds)
languages: python 2, markdown 2, text 1
```
