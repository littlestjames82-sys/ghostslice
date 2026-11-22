#!/bin/sh
# Point Claude Code at your local GhostProxy instead of the Anthropic
# API directly. Run this in the shell you launch Claude Code from.
# The proxy must already be running (see README: Quickstart).
#
# Undo any time with examples/undo-claude-code.sh, or by opening a
# fresh shell: this only sets a variable in the current shell.

export ANTHROPIC_BASE_URL="http://127.0.0.1:8765"
echo "Claude Code in this shell now talks to GhostProxy at http://127.0.0.1:8765"
echo "Undo: sh examples/undo-claude-code.sh  (or close this shell)"
