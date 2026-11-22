"""Entry point of the repro fixture project.

Referenced by the fixture bundle. Imports two local modules:
app.config (also referenced by the bundle) and app.helper (NOT
referenced by the bundle, so only the import closure can pull it
into a minimal repro project).
"""
from app.config import SETTINGS
from app.helper import compute_total


def main():
    total = compute_total(SETTINGS["prices"])
    print(f"total: {total}")
    return total


if __name__ == "__main__":
    main()
