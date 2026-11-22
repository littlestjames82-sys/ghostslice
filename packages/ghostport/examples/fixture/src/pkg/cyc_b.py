"""Fixture cycle member B."""
import locale

from pkg import cyc_a


def other():
    return locale.getdefaultlocale(), cyc_a.check
