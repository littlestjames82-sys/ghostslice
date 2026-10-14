# Example plugins

Plugins teach GhostSlice a new language (or replace a built-in
slicer) without forking. A plugin is a Python file you name
explicitly — GhostSlice never auto-discovers plugins. Loading a
plugin executes it: plugins are user code with your full
privileges, so only load plugins you have read and trust.

## lua_slicer.py

A parser-lite slicer for Lua: `signatures` collapses each function
to its definition line, a `-- ...` marker, and its `end`;
`interfaces` keeps only non-local functions; it also provides an
`outline()`, so `ghostslice symbols` and `export --symbols` work
on Lua files.

Use it from a profile (`.ghostslice.json` in the project root;
paths are relative to the root and must stay inside it):

```json
{
  "plugins": ["./tools/lua_slicer.py"]
}
```

(copy `lua_slicer.py` into your project's `tools/` directory first)

…or per run, from the command line:

```sh
ghostslice export . -o .claude_context --plugin ./tools/lua_slicer.py
```

(`--plugin` exists on `export`, `slice`, `task`, and `watch`; the
profile route works everywhere, including `scan`, the dashboard,
and MCP.)

Overriding a BUILT-IN language is refused unless you also pass
`--allow-plugin-override`. See the "Plugins" section of the main
README for the full contract: both plugin styles (`register(api)`
and module attributes), the failure rules, and the trust model.
