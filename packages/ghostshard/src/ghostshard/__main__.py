"""Entry point for ``python3 -m ghostshard ...``.

Delegates to :func:`ghostshard.cli.main`; see that module (or run
``python3 -m ghostshard --help``) for the three commands: ``plan``,
``check``, and ``export-bus``.
"""
from .cli import main
if __name__ == "__main__":
    raise SystemExit(main())
