"""Fixture ground truth. These tests need no core: they pin the exact
shape of fixtures/noisy.log so the behavioural tests can assert exact
counts against it. If the fixture changes, these counts must change in
the same edit, deliberately."""
from pathlib import Path

from conftest import (
    AWS_CANARY,
    CACHE_WARN,
    CACHE_WARN_COUNT,
    CANARY,
    ERROR_COUNT,
    ERROR_LINE,
    FIXTURES,
    HEARTBEAT,
    HEARTBEAT_COUNT,
    TOTAL_LINES,
)


def _lines():
    text = (FIXTURES / "noisy.log").read_text()
    assert text.endswith("\n")
    return text.splitlines()


def test_fixture_total_lines():
    assert len(_lines()) == TOTAL_LINES == 70


def test_fixture_first_and_last_lines_are_unique_anchors():
    lines = _lines()
    assert "service boot complete" in lines[0]
    assert "shutdown complete" in lines[-1]
    assert sum(1 for ln in lines if "service boot complete" in ln) == 1
    assert sum(1 for ln in lines if "shutdown complete" in ln) == 1


def test_fixture_repeat_counts_exact():
    lines = _lines()
    assert sum(1 for ln in lines if HEARTBEAT in ln) == HEARTBEAT_COUNT == 40
    assert sum(1 for ln in lines if CACHE_WARN in ln) == CACHE_WARN_COUNT == 12
    assert sum(1 for ln in lines if ln.strip().endswith(ERROR_LINE.split(" ", 1)[1]) or ERROR_LINE in ln) == ERROR_COUNT == 5


def test_fixture_canary_present_once_in_source():
    text = (FIXTURES / "noisy.log").read_text()
    assert text.count(CANARY) == 1
    assert text.count(AWS_CANARY) == 1
    # the AWS canary sits on an ERROR line, so it lands in an error window
    line = next(ln for ln in text.splitlines() if AWS_CANARY in ln)
    assert "ERROR" in line


def test_fixture_error_window_context_present():
    lines = _lines()
    idx = next(i for i, ln in enumerate(lines) if ERROR_LINE in ln)
    # the two lines before the first ERROR are its request context
    assert "request received" in lines[idx - 2]
    assert "handler begin" in lines[idx - 1]
    # stack lines follow
    assert lines[idx + 1].startswith("Traceback")
    assert "OperationalError" in lines[idx + 4]
