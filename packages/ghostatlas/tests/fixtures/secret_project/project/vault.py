"""Vault module. Its body holds a planted, fake secret-shaped value.

The GhostAtlas offline test plants the literal below on purpose and
then asserts it never appears in generated Atlas HTML. Atlas output
is names, paths, graph facts and extracted first docstring lines, so
a value from a module body must never leak into the artifact.
This is a test fixture value, not a real credential.
"""

_API_TOKEN = "ATLASPLANTEDSECRET9f3c7d2e51aa"


def load_setting():
    return "fixture-setting"
