#!/bin/sh
# Build an onboarding GhostAtlas for the ground-truth fixture project.
# Local only, no network, and the fixture project is never modified:
# output goes to a fresh temp folder. Usage: ./demo.sh
#
# What to look for: the reading order starts with main.py, the map
# shows main.py -> engine.py -> util.py, and dead.py appears only
# under dead zones. See README.md in this directory for details.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO=$(dirname "$HERE")
OUT=$(mktemp -d)
export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"
python3 -m ghostatlas build "$REPO/tests/fixtures/ground_truth/project" -o "$OUT/atlas.html"
echo "HTML map:  $OUT/atlas.html"
echo "Brief:     $OUT/ATLAS.md  (or next to the HTML output)"
echo "Open the HTML map in any browser; it is self-contained and works offline."
