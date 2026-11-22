"""Allow `python3 -m ghostlogs ...` as an alternative to the
`ghostlogs` console script. Accepts exactly the same arguments;
see `ghostlogs --help` or the cli module docstring for exit codes.
"""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
