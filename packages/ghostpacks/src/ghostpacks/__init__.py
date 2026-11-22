"""GhostPacks: shareable, data-only context packs for GhostSlice.

A pack is a human-readable folder containing a ``pack.json`` manifest
(``kind: context``) and a ``profile.json`` fragment in the GhostSlice
``.ghostslice.json`` schema. GhostPacks validates packs, and merges /
removes them in a local project profile with a previewed diff, an
explicit confirmation, a lockfile, and a kept backup so a merge can be
reversed. It contains no network or download code and never installs
or executes pack content: packs are data only.
"""
from .pack import (
    KIND, MODES, PRESETS, GhostPacksError, Pack, lint_pack, load_pack,
    validate_profile_fragment,
)
from .manager import merge_pack, remove_pack

__version__ = "0.1.0"
__all__ = [
    "KIND", "MODES", "PRESETS", "GhostPacksError", "Pack",
    "lint_pack", "load_pack", "validate_profile_fragment",
    "merge_pack", "remove_pack", "__version__",
]
