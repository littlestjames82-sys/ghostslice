"""Console entry point for widgetforge."""

from widgetforge.core import Forge, calibrate_anvil
from widgetforge.helpers import describe


def main() -> int:
    """Run one demo forging pass and print the result."""
    forge = Forge()
    ok = calibrate_anvil(forge)
    print(describe(forge.heat("blank-1"), ok))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
