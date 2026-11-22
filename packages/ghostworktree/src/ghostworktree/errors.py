"""Error types; the CLI prints ``error: <message>`` and returns ``exit_code``."""

class WorktreeError(Exception):
    """Refusal or failure (exit 1): the command ran but did not do the work.

    Examples: a dirty cleanup without ``--force``, a duplicate name or
    port, or an unknown worktree name. Nothing is changed on a refusal
    unless the message says otherwise.
    """
    exit_code = 1

class CannotRunError(WorktreeError):
    """Environment cannot run the command at all (exit 2).

    Examples: the repo argument is not a git working tree, or the
    ``git`` executable is not on ``PATH``.
    """
    exit_code = 2

class RegistryError(WorktreeError):
    """The registry is corrupt, malformed, or unwritable (exit 1).

    Raised with a named message (path, record, and field where known)
    instead of a traceback, and never treated as an empty registry.
    """
    exit_code = 1
