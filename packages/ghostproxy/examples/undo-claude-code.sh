#!/bin/sh
# The undo: point Claude Code straight back at the Anthropic API.
# Source this file (do not just run it) so the unset reaches your
# current shell:
#
#     . examples/undo-claude-code.sh
#
# After this, Claude Code talks to the API directly again, exactly
# as if GhostProxy had never been in the path. You can also stop the
# proxy itself with Ctrl-C in its terminal; with the variable unset,
# nothing routes through it either way.

unset ANTHROPIC_BASE_URL
echo "ANTHROPIC_BASE_URL unset: Claude Code now uses the default Anthropic API address."
