#!/bin/sh
# Render the demo board from the fixture report set.
# No install needed: it runs the module straight from ../src.
# Expected result (see README.md): one project each in Verified,
# Attention, and Stale (stale-proj and empty-proj), written to
# board.html next to this script.
set -e
cd "$(dirname "$0")"
PYTHONPATH=../src python3 -m ghostconsole build --root fixture_reports -o board.html
echo "Demo board written to board.html (open it in any browser, offline)."
