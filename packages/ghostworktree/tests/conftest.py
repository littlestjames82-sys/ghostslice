# Fixture projects under fixtures/ (if any are added later) are data for
# GhostWorktree, not tests of GhostWorktree, so pytest must not collect them.
collect_ignore_glob = ["fixtures/**"]
