"""Look-alike negative: snake_case threading API is current."""
import threading


def worker_state(thread):
    alive = thread.is_alive()
    current = threading.current_thread()
    return alive, current
