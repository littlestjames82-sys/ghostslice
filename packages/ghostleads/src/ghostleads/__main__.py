"""Entry point for ``python3 -m ghostleads``.

All behaviour lives in :mod:`ghostleads.cli`; this module only
forwards to its ``main()`` so the module form and the installed
``ghostleads`` command behave identically.
"""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
