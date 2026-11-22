"""Reporting helpers."""

from widgetforge.core import Forge, calibrate_anvil


def report(forge: Forge) -> str:
    """Summarise the forge state for a report."""
    return f"temp={forge.temperature} calibrated={calibrate_anvil(forge)}"
