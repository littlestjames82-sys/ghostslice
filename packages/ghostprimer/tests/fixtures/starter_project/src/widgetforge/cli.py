"""Alternate command line front end."""

from widgetforge.core import Forge
from widgetforge.helpers import furnace_name


def run_cli() -> None:
    """Print the furnace label."""
    print(furnace_name(Forge()))
