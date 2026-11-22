"""GhostAtlas: a human codebase map built on GhostSlice data.

Extractive and factual only: module descriptions are docstring first
lines extracted from the source, graph facts, and names/paths. Nothing
here invents prose about what a module does.
"""
from __future__ import annotations

__version__ = "0.1.0"
VERSION = __version__

from .data import AtlasData, build_atlas_data  # noqa: E402

__all__ = ["__version__", "VERSION", "AtlasData", "build_atlas_data"]
