"""GhostDocs: GhostSlice for non-code corpora.

Stdlib only and local-first: GhostDocs scans a folder of business
documents, finds duplicate and superseded pages, holds back pages with
sensitive shapes, and exports a manifest-backed set for an AI
assistant or a RAG pipeline. It never edits the originals, never
calls a model, and never uses the network.
"""

__version__ = "0.1.0"
# Stamp recorded in every manifest so an export can be tied to the
# estimator that produced its (estimated, never exact) token counts.
ESTIMATOR_VERSION = "chars4-v1"
