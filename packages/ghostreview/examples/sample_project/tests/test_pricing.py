"""Tests for the fixture project."""

from pricing import compute_total


def test_compute_total():
    assert compute_total([10.0]) == 10.8
