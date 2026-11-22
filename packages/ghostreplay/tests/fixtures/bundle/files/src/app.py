"""Sample app: entry point of the fixture project."""

from src.hot import cached_lookup
from src.util import parse_config


def main() -> None:
    config = parse_config("app.toml")
    value = cached_lookup(config["key"])
    print(f"lookup -> {value}")


if __name__ == "__main__":
    main()
