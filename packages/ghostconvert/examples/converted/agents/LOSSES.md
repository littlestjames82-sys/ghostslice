# Conversion losses: agents

Source bundle: /home/hatch/workspace/ghostconvert/examples/sample_bundle
Project: sample_project
Converted by GhostConvert 0.1.0. This note names everything the agents format could not carry from the GhostSlice manifest, so nothing was dropped silently.

## Excluded files (no body in any target)

1 file(s) were excluded by GhostSlice and appear in the source manifest only: vendor/blob.py. The receiving agent does not see them at all.

## Per-file sha256 hashes

6 hash value(s) from the manifest are not carried by the agents format, so the converted output cannot be verified with `ghostslice check`. Verify the source bundle instead.

## Per-file token estimates

Per-file original/sliced token counts for 6 file(s) are not carried; only the bundle totals appear in the header.

## Files emptied by GhostSlice (no body by design)

GhostSlice shipped no body for these files on purpose; the manifest shows each one as an empty slice, so nothing was lost in conversion: tests/test_app.py (mode: strip-tests). They appear in the source manifest only, and the receiving agent does not see their content because Slice chose to send none.

## Machine-readable per-file metadata

The agents format is a single prose document; beyond the mode label in each section header there is no structured per-file metadata channel, so language and package fields from the manifest are not carried.
