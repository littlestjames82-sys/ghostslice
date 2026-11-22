"""Fixture: matched by the auth glob in the surface pack, AND pinned out
by the user in .ghostslice.json. That is a conflict: the tool must list
it as a conflict requiring a human decision, never resolve it silently.
"""


def authenticate(session_token):
    return bool(session_token)
