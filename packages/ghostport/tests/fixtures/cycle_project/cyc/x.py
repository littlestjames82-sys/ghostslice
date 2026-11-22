"""Cycle member X: imports Y, one pattern hit (datetime.utcnow, PYUP012)."""
import datetime

from cyc.y import y_value


def x_value():
    return datetime.datetime.utcnow(), y_value()
