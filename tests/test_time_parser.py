from datetime import datetime, time
import unittest

from attendance_parser.time_parser import normalize_time


class NormalizeTimeTests(unittest.TestCase):
    def test_supported_time_formats(self) -> None:
        self.assertEqual(normalize_time(time(8, 5)), "08:05")
        self.assertEqual(normalize_time(datetime(2026, 9, 1, 8, 5)), "08:05")
        self.assertEqual(normalize_time(8 / 24 + 5 / 1440), "08:05")
        self.assertEqual(normalize_time("8:5"), "08:05")
        self.assertEqual(normalize_time("08:05:00"), "08:05")
        self.assertEqual(normalize_time("17:02*"), "17:02")

    def test_blank_and_administrative_values_are_not_times(self) -> None:
        for value in (None, "", "--", "NaN", "23", 23, float("nan")):
            self.assertIsNone(normalize_time(value))

    def test_explicit_numeric_midnight_is_preserved(self) -> None:
        self.assertEqual(normalize_time(0), "00:00")


if __name__ == "__main__":
    unittest.main()
