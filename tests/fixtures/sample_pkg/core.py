"""Core module of the sample package."""


class Engine:
    """A pretend engine.

    Args:
        power: How much power.
    """

    def __init__(self, power: int) -> None:
        self.power = power

    def run(self) -> int:
        """Run the engine and return its power."""
        return self.power
