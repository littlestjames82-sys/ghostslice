# Plugins

Teach GhostSlice a new language, or replace a built-in slicer,
without forking: a plugin is a single Python file you write.

**Trust first: a plugin is your code, run with your full
privileges.** GhostSlice never auto-discovers plugins: no directory
scanning, no entry points, no environment variable. A plugin loads
only when you name it, in one of two places:

- The profile (`.ghostslice.json`): `"plugins": ["./tools/my_slicer.py"]`.
  Paths are relative to the project root and must resolve inside
  it (symlinks are followed before the check); absolute or escaping
  paths are refused with an error.
- The command line: `--plugin PATH` (repeatable) on `export`,
  `slice`, `task`, and `watch`.

The profile route works everywhere, including the dashboard and
the MCP tools. Whenever plugins load, the CLI prints one line per
plugin (name, language, extensions, file) plus a plain warning
that plugins are user code. A plugin set that fails to load fails
the command with exit 2 before anything is written.

## The contract

Attribute style: the module defines

```python
NAME = "My slicer"                    # optional; default: file name
LANGUAGE = "lua"
EXTENSIONS = [".lua"]

def slice_text(path, text, mode):     # -> str
    ...

def outline(path, text):              # optional
    return [{"name": "f", "kind": "function", "start": 3, "end": 9}]
```

Register style: the module defines `register(api)`, and the api
object offers `api.estimate_tokens(text)`, `api.MODES`, and
`api.register_slicer(language, extensions, slicer_fn, outline=None)`.
One file may register several languages.

Rules of the road:

- `slice_text(path, text, mode)` receives RESOLVED modes, the same
  ones built-in slicers get (`signatures`, `interfaces`,
  `strip-tests`, ...). The core handles `full` and `exclude`
  itself; a plugin is never called for them. Return the input
  unchanged for modes you do not implement.
- `outline(path, text)` returns rows of `{name, kind, start, end}`
  (0-based line numbers, inclusive) and joins `ghostslice symbols`
  and `export --symbols`. Without an outline, the language honestly
  reports that it has none.
- Token estimation stays GhostSlice's standard estimator; plugin
  languages are scanned, costed, fitted, and linted like built-ins.
- Overriding a BUILT-IN language (or claiming one of its
  extensions) is refused unless `--allow-plugin-override` is
  passed. When two plugins claim the same NEW language, the last
  one loaded wins, and the load output says so.

## Failure discipline

A plugin that raises on one file does not kill the export: that
file ships its full text, the manifest gains a `plugin_errors`
entry, and the CLI prints a warning line. A slicer returning bytes
is decoded as UTF-8; any other non-string return is treated as a
failure for that file, under the same rule. The content cache keys
on a hash of every loaded plugin's file bytes, so editing a plugin
invalidates its cached slices automatically.

There is no sandbox. A plugin can loop forever or read any file
you can read. Registrations are fixed once loading finishes, and
nothing loads that you did not name. Treat a plugin the way you
would a script a colleague handed you: read it first.

A working example ships in `examples/plugins/lua_slicer.py` (a
parser-lite Lua signatures slicer with an outline), with notes in
`examples/plugins/README.md`.
