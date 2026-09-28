import unittest
from datetime import date

from attendance_parser.models import AttendanceRecord, Employee


class WorkedTimeTests(unittest.TestCase):
    def test_sums_two_main_periods_and_complete_overtime(self) -> None:
        record = AttendanceRecord(
            date(2026, 8, 25),
            "Terça-feira",
            "07:30",
            "11:30",
            "13:00",
            "17:30",
            "17:30",
            "18:00",
        )

        self.assertEqual(record.worked_minutes, 540)
        self.assertEqual(record.lunch_minutes, 90)
        self.assertEqual(record.lunch_excess_minutes, 0)
        self.assertEqual(record.incomplete_pair_count, 0)

    def test_lunch_is_deducted_as_a_fixed_ninety_minutes_when_shorter(self) -> None:
        record = AttendanceRecord(
            date(2026, 8, 25), "Terça-feira", "07:26", "11:34", "13:02", "18:02"
        )

        self.assertEqual(record.lunch_minutes, 88)
        self.assertEqual(record.worked_minutes, 546)
        self.assertEqual(record.lunch_excess_minutes, 0)

    def test_lunch_over_ninety_minutes_is_shown_and_not_counted_as_work(self) -> None:
        record = AttendanceRecord(
            date(2026, 8, 25), "Terça-feira", "07:30", "11:30", "13:10", "17:00"
        )

        self.assertEqual(record.lunch_minutes, 100)
        self.assertEqual(record.worked_minutes, 470)
        self.assertEqual(record.lunch_excess_minutes, 10)

    def test_incomplete_main_punches_make_the_daily_total_unavailable(self) -> None:
        record = AttendanceRecord(date(2026, 8, 25), "Terça-feira", "07:30", "11:30", "13:00", None)

        self.assertIsNone(record.worked_minutes)
        self.assertEqual(record.incomplete_pair_count, 1)
        self.assertTrue(record.has_incomplete_day)

    def test_counts_shift_that_crosses_midnight(self) -> None:
        record = AttendanceRecord(date(2026, 8, 25), "Terça-feira", "07:00", "07:00", "22:00", "06:00")

        self.assertEqual(record.worked_minutes, 480)

    def test_expected_workday_is_nine_hours_monday_to_thursday_and_eight_friday(self) -> None:
        self.assertEqual(AttendanceRecord(date(2026, 8, 25)).required_minutes, 540)
        self.assertEqual(AttendanceRecord(date(2026, 8, 28)).required_minutes, 480)
        self.assertEqual(AttendanceRecord(date(2026, 8, 29)).required_minutes, 0)

    def test_employee_total_excludes_incomplete_days_and_compares_with_220_hours(self) -> None:
        employee = Employee(
            "15",
            "Teste",
            "RH",
            date(2026, 8, 25),
            date(2026, 8, 26),
            [
                AttendanceRecord(date(2026, 8, 25), "Terça-feira", "07:30", "11:30", "13:00", "17:30"),
                AttendanceRecord(date(2026, 8, 26), "Quarta-feira", "08:00", "12:00", "13:00", None),
            ],
        )

        self.assertEqual(employee.worked_minutes, 510)
        self.assertEqual(employee.expected_minutes, 13_200)
        self.assertEqual(employee.balance_minutes, -12_690)
        self.assertEqual(employee.incomplete_day_count, 1)
        self.assertEqual(employee.incomplete_pair_count, 1)

    def test_weekly_summary_includes_work_on_the_seventh_day(self) -> None:
        employee = Employee(
            "15", "Teste", "RH", date(2026, 8, 24), date(2026, 8, 30),
            [AttendanceRecord(date(2026, 8, 30), "Domingo", "07:00", "11:00", "12:30", "16:30")],
        )

        self.assertEqual(employee.weekly_summaries[0].worked_minutes, 480)
        self.assertEqual(employee.weekly_summaries[0].balance_minutes, -2_160)


if __name__ == "__main__":
    unittest.main()
