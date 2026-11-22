# The fixture sample project under fixtures/ contains its own
# test_*.py files (they are data the diffs refer to, and the file
# the deleted-test / test-edit fixtures are about). They are data
# for GhostReview, not tests of GhostReview, so pytest must not
# collect them.
collect_ignore_glob = ["fixtures/**"]
