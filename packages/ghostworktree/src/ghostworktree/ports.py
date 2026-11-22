"""Port allocation: registry uniqueness + localhost bind check. No other network use."""
from __future__ import annotations
import socket
from .errors import WorktreeError

DEFAULT_RANGE = (4100, 4999)

def parse_range(text: str) -> tuple[int, int]:
    """Parse ``"START-END"`` into ``(lo, hi)``; raise on malformed or out-of-range input."""
    try:
        a, b = text.split("-", 1)
        lo, hi = int(a), int(b)
    except Exception as e:
        raise WorktreeError(f"invalid port range {text!r}, expected START-END") from e
    if not (1 <= lo <= hi <= 65535):
        raise WorktreeError(f"invalid port range {text!r}")
    return (lo, hi)

def is_bindable(port: int) -> bool:
    """True if nothing is currently listening/bound on localhost:port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()

def allocate(used: set[int], requested: int | None = None,
             rng: tuple[int, int] = DEFAULT_RANGE) -> int:
    """Return a free port, or raise :class:`WorktreeError` if none can be given.

    A ``requested`` port must be valid, absent from ``used`` (the
    registry), and bindable on localhost; it is never stolen or
    substituted. Without one, the lowest port in ``rng`` meeting the
    same two checks wins. Note: this reserves the port only in the
    registry, not with the OS.
    """
    if requested is not None:
        # bool is a subclass of int (True == 1) and a str/float port
        # otherwise dies with a bare TypeError deep in the comparison.
        if isinstance(requested, bool) or not isinstance(requested, int):
            raise WorktreeError(f"invalid port {requested!r}")
        if not (1 <= requested <= 65535):
            raise WorktreeError(f"invalid port {requested}")
        if requested in used:
            raise WorktreeError(f"port {requested} is already allocated to a registered worktree")
        if not is_bindable(requested):
            raise WorktreeError(f"port {requested} is already in use on localhost")
        return requested
    try:
        lo, hi = rng
    except (TypeError, ValueError) as e:
        raise WorktreeError(f"invalid port range {rng!r}") from e
    if (isinstance(lo, bool) or isinstance(hi, bool)
            or not isinstance(lo, int) or not isinstance(hi, int)
            or not (1 <= lo <= hi <= 65535)):
        raise WorktreeError(f"invalid port range {rng!r}")
    for p in range(lo, hi + 1):
        if p not in used and is_bindable(p):
            return p
    raise WorktreeError(f"no free port in range {lo}-{hi}")
