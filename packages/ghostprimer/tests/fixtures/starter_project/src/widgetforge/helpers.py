"""Small formatting helpers."""

from widgetforge.core import Forge


def describe(state: str, ok: bool) -> str:
    """Format a forging result for printing."""
    return f"result: {state} (anvil ok: {ok})"


def furnace_name(forge: Forge) -> str:
    """Return a label for the furnace."""
    return f"furnace-{forge.temperature}"
