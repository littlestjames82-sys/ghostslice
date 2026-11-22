"""Positive: datetime.utcnow / utcfromtimestamp are deprecated in Python 3.12."""
import datetime


def stamps():
    return datetime.datetime.utcnow(), datetime.datetime.utcfromtimestamp(0)
