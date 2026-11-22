import os
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ghostconsole_app import store  # noqa: E402
from ghostconsole_app.runner import Runner  # noqa: E402
from ghostconsole_app.server import make_server  # noqa: E402


@pytest.fixture
def app_home(tmp_path, monkeypatch):
    """Isolated app home so the registry never touches the real one."""
    home = tmp_path / "apphome"
    monkeypatch.setenv(store.APP_HOME_ENV, str(home))
    return home


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    (p / "app.py").write_text("x = 1\n", encoding="utf-8")
    return p


@pytest.fixture
def live_server(app_home):
    """A real server on an ephemeral port, in a thread."""
    server = make_server("127.0.0.1", 0, Runner(), quiet=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
