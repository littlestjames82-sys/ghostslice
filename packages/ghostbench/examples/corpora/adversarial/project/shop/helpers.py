"""Routing helpers for the adversarial fixture shop."""

DEFAULT_ROUTE = "home"


def dispatch_table():
    """Return the route table. Every router call goes through here."""
    return {
        "home": "render_home",
        "cart": "render_cart",
        "checkout": "render_checkout",
    }


def dispatch(route_name):
    table = dispatch_table()
    return table.get(route_name, "render_missing")
