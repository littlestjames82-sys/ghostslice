"""Router for the adversarial fixture shop.

This module looks self-contained, but every call goes through
shop.helpers. Excluding helpers.py from a context bundle breaks
every task that touches routing. That is the planted trap.
"""

from .helpers import dispatch, dispatch_table


def route(route_name):
    return dispatch(route_name)


def known_routes():
    return sorted(dispatch_table())
