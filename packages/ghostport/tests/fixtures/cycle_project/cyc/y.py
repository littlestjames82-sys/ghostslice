"""Cycle member Y: imports X, one pattern hit (threading camelCase, PYUP007)."""
import threading

from cyc.x import x_value


def y_value():
    current = threading.currentThread()
    return current, x_value
