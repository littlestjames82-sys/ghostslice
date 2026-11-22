"""Entry point for ``python3 -m ghostmcpdoctor``; delegates to ``cli.main``."""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
