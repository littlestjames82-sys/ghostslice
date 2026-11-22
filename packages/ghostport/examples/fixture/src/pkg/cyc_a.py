"""Fixture cycle member A."""
import inspect

from pkg import cyc_b


def check(fn):
    return inspect.getargspec(fn), cyc_b.other()
