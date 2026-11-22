# Demo project (example fixture)

A tiny legacy Python project used by the GhostPort README walkthrough.
It is deliberately *not* migrated: GhostPort is a planner, it never
rewrites code.

| File | Depends on | Pattern hit |
|---|---|---|
| `legacy/storage.py` | nothing | PYUP006 `configparser.SafeConfigParser` |
| `legacy/plugin_loader.py` | nothing | PYUP004 `import imp` |
| `legacy/report.py` | storage, plugin_loader | PYUP003 `inspect.getargspec` |

Expected plan order (leaves first): `storage` and `plugin_loader` in any
order relative to each other, then `report` last.
