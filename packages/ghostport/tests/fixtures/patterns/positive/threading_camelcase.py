"""Positive: threading camelCase aliases were removed in Python 3.10."""
import threading


def worker_state():
    current = threading.currentThread()
    count = threading.activeCount()
    return current, count
