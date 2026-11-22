"""Module entry point, so ``python3 -m ghostschema`` works the same
as the installed ``ghostschema`` command. All behaviour lives in
:mod:`ghostschema.cli`.
"""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
