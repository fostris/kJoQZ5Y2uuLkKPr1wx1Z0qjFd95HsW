import math
import unittest

from formatters import format_nullable, format_percent, format_rub


class FormatterTests(unittest.TestCase):
    def test_format_rub_positive_and_negative(self):
        self.assertEqual(format_rub(1234.5), "1 234,50")
        self.assertEqual(format_rub(-1234.5), "-1 234,50")

    def test_format_percent_positive_and_negative(self):
        self.assertEqual(format_percent(12.345, decimals=2), "12.35%")
        self.assertEqual(format_percent(-3.2, decimals=1), "-3.2%")

    def test_none_and_nan_to_dash(self):
        self.assertEqual(format_rub(None), "—")
        self.assertEqual(format_rub(math.nan), "—")
        self.assertEqual(format_percent(None), "—")
        self.assertEqual(format_percent(math.nan), "—")
        self.assertEqual(format_nullable(None), "—")
        self.assertEqual(format_nullable(math.nan), "—")


if __name__ == "__main__":
    unittest.main()
