"""Run GhostReview as ``python3 -m ghostreview`` (same CLI as ``ghostreview``)."""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
