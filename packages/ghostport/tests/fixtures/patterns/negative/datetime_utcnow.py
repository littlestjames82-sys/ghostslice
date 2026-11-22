"""Look-alike negative: timezone-aware now() is the supported call."""
import datetime


def stamps():
    return datetime.datetime.now(datetime.timezone.utc)
