#!/bin/sh
# GhostScope demo: pack the high-blast-radius fixture as a git range.
#
# Builds a throwaway git repo from tests/fixtures/high_blast_radius
# (base commit, then a one-line change to a 6-caller function plus a
# 220-line isolated change), packs HEAD~1..HEAD, and prints the
# pack's REVIEW.md. Expected: the 6-caller change ranks first.
# Local only. The temp directory is removed on exit.
# Exits 3 with the expected outcome if no core can be found.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
FIX="$HERE/../tests/fixtures/high_blast_radius"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

cp -R "$FIX/base/." "$WORK/proj" 2>/dev/null || { mkdir -p "$WORK/proj"; cp -R "$FIX/base/." "$WORK/proj/"; }
cd "$WORK/proj"
git init -q .
git config user.email demo@example.com
git config user.name "GhostScope Demo"
git add -A && git commit -qm base
cp "$FIX/change/shared.py" shared.py
cp "$FIX/change/isolated.py" isolated.py
git add -A && git commit -qm change

if PYTHONPATH="$HERE/../src" python3 -c "import ghostscope" 2>/dev/null || command -v ghostscope >/dev/null 2>&1; then
  if command -v ghostscope >/dev/null 2>&1; then
    ghostscope pack . --base HEAD~1 --head HEAD -o "$WORK/pack"
  else
    PYTHONPATH="$HERE/../src" python3 -m ghostscope pack . --base HEAD~1 --head HEAD -o "$WORK/pack"
  fi
  echo "Pack written to $WORK/pack (temporary: removed when this script exits)"
  cat "$WORK/pack/REVIEW.md" 2>/dev/null || find "$WORK/pack" -name REVIEW.md -exec cat {} \;
else
  echo "GhostScope core not installed yet: nothing to run."
  echo "The fixture repo was built at $WORK/proj and the expected outcome is:"
  echo "compute_total (1-line change, 6 callers) ranks above isolated.py (220-line change, 0 callers)."
  exit 3
fi
