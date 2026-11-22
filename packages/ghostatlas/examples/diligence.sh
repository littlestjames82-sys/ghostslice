#!/bin/sh
# Build a diligence-audience GhostAtlas for the ground-truth fixture.
# Local only, no network, and the fixture project is never modified:
# output goes to a fresh temp folder. Usage: ./diligence.sh
#
# Same map as demo.sh; the difference is the brief: ATLAS.md leads
# with size, test presence, secrets counts/types, dependencies,
# licences, and git history, plus the checked / not-checked box.
# It is an orientation aid, not an audit opinion.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO=$(dirname "$HERE")
OUT=$(mktemp -d)
export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"
python3 -m ghostatlas build "$REPO/tests/fixtures/ground_truth/project" -o "$OUT/atlas.html" --audience diligence
echo "HTML map:  $OUT/atlas.html"
echo "Brief:     $OUT/ATLAS.md  (diligence ordering, checked / not-checked box)"
echo "Start with the brief: its first sections are the diligence summary."
