import unittest

from ghostslice.slicer import slice_source, slice_text

PY = '''"""Module docstring here."""
import os
from typing import Protocol

MAX_SIZE = 42
UserId = int


class Store(Protocol):
    """Storage interface."""

    def get(self, key: str) -> str:
        ...

    def put(self, key: str, value: str) -> None:
        """Store a value."""
        raise NotImplementedError


class Greeter:
    greeting = "hello"

    def __init__(self, name: str):
        self.name = name
        self.secret_body_marker = 12345

    def greet(self, punct: str = "!") -> str:
        """Greet the user."""
        body_marker_should_vanish = "xyz"
        return self.greeting + self.name + punct


def helper(x: int) -> int:
    """Help with x."""
    internal_marker = x * 2
    return internal_marker + 1


def test_helper():
    assert helper(1) == 3


class TestGreeter:
    def test_greet(self):
        assert Greeter("a").greet() == "helloa!"
'''


class TestPythonSlicer(unittest.TestCase):
    def test_full_is_identical(self):
        self.assertEqual(slice_source(PY, "python", "full", "m.py"), PY)

    def test_exclude_is_empty(self):
        self.assertEqual(slice_source(PY, "python", "exclude", "m.py"), "")

    def test_signatures_keep_defs_drop_bodies(self):
        out = slice_source(PY, "python", "signatures", "m.py")
        self.assertIn("def helper(x: int) -> int", out)
        self.assertIn("def greet", out)
        self.assertIn("class Greeter", out)
        self.assertIn("class Store", out)
        self.assertIn("import os", out)
        self.assertIn("MAX_SIZE = 42", out)
        self.assertIn("Help with x.", out)
        self.assertNotIn("internal_marker", out)
        self.assertNotIn("body_marker_should_vanish", out)
        self.assertNotIn("secret_body_marker", out)

    def test_signatures_smaller(self):
        r = slice_text("m.py", PY, "signatures")
        self.assertLess(r.sliced_tokens, r.original_tokens)
        self.assertGreater(r.saved_tokens, 0)

    def test_interfaces_keep_classes_and_aliases_drop_plain_functions(self):
        out = slice_source(PY, "python", "interfaces", "m.py")
        self.assertIn("class Store", out)
        self.assertIn("class Greeter", out)
        self.assertIn("UserId = int", out)
        self.assertIn("def get(self, key: str) -> str", out)
        self.assertNotIn("def helper", out)
        self.assertNotIn("internal_marker", out)

    def test_strip_tests_removes_tests_keeps_rest(self):
        out = slice_source(PY, "python", "strip-tests", "m.py")
        self.assertIn("def helper", out)
        self.assertIn("class Greeter", out)
        self.assertIn("internal_marker", out)  # bodies preserved in strip-tests
        self.assertNotIn("def test_helper", out)
        self.assertNotIn("class TestGreeter", out)
        self.assertNotIn("test_greet", out)

    def test_strip_tests_on_test_file_is_empty(self):
        out = slice_source(PY, "python", "strip-tests", "tests/test_m.py")
        self.assertEqual(out, "")

    def test_syntax_error_fallback_does_not_crash(self):
        broken = "def oops(:\n    pass\nclass Fine:\n    pass\n"
        out = slice_source(broken, "python", "signatures", "bad.py")
        self.assertIn("class Fine", out)


if __name__ == "__main__":
    unittest.main()
