import unittest

from ghostslice.tokens import estimate_tokens


class TestTokens(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(estimate_tokens(""), 0)
        self.assertEqual(estimate_tokens("   \n  "), 0)

    def test_short_words(self):
        self.assertEqual(estimate_tokens("hello"), 2)  # 5 chars -> ceil(5/4)=2
        self.assertEqual(estimate_tokens("a b c"), 3)

    def test_long_word_splits(self):
        self.assertEqual(estimate_tokens("abcdefgh"), 2)
        self.assertEqual(estimate_tokens("abcdefghij"), 3)  # ceil(10/4)

    def test_punctuation_counts(self):
        self.assertEqual(estimate_tokens("x = 1;"), 4)  # x, =, 1, ;

    def test_monotonic_and_positive_for_code(self):
        code = "def foo(x):\n    return x + 1\n"
        self.assertGreater(estimate_tokens(code), 5)
        self.assertGreater(estimate_tokens(code * 3), estimate_tokens(code))


if __name__ == "__main__":
    unittest.main()
