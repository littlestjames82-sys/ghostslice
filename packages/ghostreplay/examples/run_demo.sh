#!/bin/sh
# GhostReplay demo: analyse the planted-waste example transcript.
# Local only, no network. Writes reports to /tmp/replay-demo (never
# into the repo) and appends one record to the sample project's
# trend ledger, like any analyse run.
# Usage: sh examples/run_demo.sh   (from anywhere; it cds to the repo root)
# Then read /tmp/replay-demo/REPLAY.md and compare it with
# examples/EXPECTED_OUTPUT.md.
set -eu
cd "$(dirname "$0")/.."

if [ -x "$(command -v ghostreplay)" ]; then
    GR="ghostreplay"
elif [ -d src/ghostreplay ]; then
    GR="env PYTHONPATH=src python3 -m ghostreplay"
else
    echo "ghostreplay core not found (install it or run from a full checkout)" >&2
    exit 1
fi

$GR analyse examples/sample_project examples/transcripts/planted_waste_1.jsonl \
    --bundle examples/sample_bundle --out /tmp/replay-demo

echo
echo "Reports written to /tmp/replay-demo/:"
ls -l /tmp/replay-demo/
echo
echo "Expected findings: src/hot.py re-read 5x; src/legacy.py not referenced"
echo "in transcript (86 estimated tokens). See examples/EXPECTED_OUTPUT.md."
