"""GhostShard: planner-only task sharder for GhostSlice / GhostBus.

Boundary (PLAN.md): Shard plans packets. It does not run agents,
dispatch work, contact any GhostBus relay, approve actions, or merge
results. Its only outputs are files.
"""
__version__ = "0.1.0"
__all__ = ["__version__"]
