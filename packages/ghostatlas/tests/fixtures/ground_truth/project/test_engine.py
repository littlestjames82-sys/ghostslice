"""Tests for the ground-truth fixture engine."""

from engine import run


def test_run():
    assert run() == "fixture-ok"
