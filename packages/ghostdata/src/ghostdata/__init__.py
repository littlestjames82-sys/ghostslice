"""GhostData: structured data slicer for GhostSlice.

Reads CSV, TSV, JSON array, JSONL, and top-level JSON object files,
infers a schema, and writes a Slice-style pack: manifest.json,
PROMPT.md, and a bounded sample file (head + tail + evenly spaced
rows). Files are streamed, never loaded whole, except top-level
JSON objects, which are parsed whole under a stated size guard.
Sensitive columns are redacted in samples by default. Source files
are never modified.
"""

__version__ = "0.1.1"
