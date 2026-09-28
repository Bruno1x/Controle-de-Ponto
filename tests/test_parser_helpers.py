from datetime import date
import unittest

from attendance_parser.parser import AttendanceWorkbookParser


class ParserHelperTests(unittest.TestCase):
    def test_month_change_uses_period_boundaries(self) -> None:
        parser = AttendanceWorkbookParser()
        start = date(2026, 8, 25)
        end = date(2026, 9, 24)
        self.assertEqual(parser._date_from_day(25, start, end), date(2026, 8, 25))
        self.assertEqual(parser._date_from_day(1, start, end), date(2026, 9, 1))

    def test_multiline_time_cell_is_split_without_invention(self) -> None:
        parser = AttendanceWorkbookParser()
        self.assertEqual(parser._time_tokens("07:30\n12:00\n13:00\n18:00"), ["07:30", "12:00", "13:00", "18:00"])
        self.assertEqual(parser._time_tokens(""), [])


if __name__ == "__main__":
    unittest.main()
