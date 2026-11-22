"""Core forging routines. Imported by almost every other module."""


class Forge:
    """A demo furnace with a temperature and a bellows state."""

    def __init__(self, temperature: int = 900) -> None:
        self.temperature = temperature

    def heat(self, blank: str) -> str:
        """Heat one blank and return its state string."""
        return f"{blank} at {self.temperature}C"


def calibrate_anvil(forge: Forge) -> bool:
    """Check the anvil against the forge temperature."""
    return forge.temperature > 0
