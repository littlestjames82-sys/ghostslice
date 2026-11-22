"""Console entry point for demoapp."""

from demoapp.greeter import greeting


def main() -> int:
    """Print one greeting and exit cleanly."""
    print(greeting("world"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
