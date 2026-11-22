"""Entry point for ``python3 -m ghostpacks``; see ``ghostpacks --help``."""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
