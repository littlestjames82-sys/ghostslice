# The fixture projects under fixtures/ contain their own test_*.py files
# (they are the covering tests GhostScope must find). They are data for
# GhostScope, not tests of GhostScope, so pytest must not collect them.
collect_ignore_glob = ["fixtures/**"]
