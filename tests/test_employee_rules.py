from datetime import date
import unittest

from attendance_parser.models import AttendanceRecord, Employee
from attendance_parser.parser import has_real_time_records


def employee(name: str, records: list[AttendanceRecord]) -> Employee:
    return Employee("1", name, "TESTE", date(2026, 8, 25), date(2026, 9, 24), records)


class EmployeeRuleTests(unittest.TestCase):
    def test_employee_with_only_administrative_data_is_excluded(self) -> None:
        item = employee("JENIFER", [AttendanceRecord(date(2026, 8, 25), "Terça-feira")])
        self.assertFalse(has_real_time_records(item))

    def test_employee_with_one_time_is_included(self) -> None:
        item = employee("ANA", [AttendanceRecord(date(2026, 8, 25), shift1_start="07:30")])
        self.assertTrue(has_real_time_records(item))
        self.assertEqual(item.valid_time_count, 1)

    def test_employee_with_times_on_multiple_days_keeps_all_records(self) -> None:
        item = employee(
            "ANA",
            [
                AttendanceRecord(date(2026, 8, 25), shift1_start="07:30", shift1_end="12:00"),
                AttendanceRecord(date(2026, 8, 26), shift1_start="07:31", shift1_end="12:01"),
            ],
        )
        self.assertEqual(item.valid_time_count, 4)
        self.assertEqual(item.days_with_records, 2)

    def test_empty_cells_remain_empty(self) -> None:
        record = AttendanceRecord(date(2026, 8, 25), shift1_start="07:30")
        self.assertIsNone(record.shift1_end)
        self.assertIsNone(record.shift2_start)

    def test_adjacent_employee_without_time_is_not_included(self) -> None:
        with_time = employee("A", [AttendanceRecord(date(2026, 8, 25), shift1_start="07:30")])
        without_time = employee("B", [AttendanceRecord(date(2026, 8, 25))])
        self.assertTrue(with_time.included)
        self.assertFalse(without_time.included)

    def test_weekends_without_time_do_not_create_false_records(self) -> None:
        item = employee(
            "ANA",
            [
                AttendanceRecord(date(2026, 8, 29), "Sábado"),
                AttendanceRecord(date(2026, 8, 30), "Domingo"),
            ],
        )
        self.assertFalse(item.included)


if __name__ == "__main__":
    unittest.main()
