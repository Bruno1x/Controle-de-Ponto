from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

TIME_PAIRS = (
    ("shift1_start", "shift1_end"),
    ("shift2_start", "shift2_end"),
    ("overtime_start", "overtime_end"),
)
CORE_TIME_FIELDS = ("shift1_start", "shift1_end", "shift2_start", "shift2_end")
WEEKLY_TARGET_MINUTES = 44 * 60
PERIOD_TARGET_MINUTES = 220 * 60
LUNCH_BREAK_MINUTES = 90


def _minutes(value: str) -> int:
    hour, minute = map(int, value.split(":"))
    if hour > 23 or minute > 59:
        raise ValueError(f"Horário inválido: {value}")
    return hour * 60 + minute


@dataclass(slots=True)
class AttendanceRecord:
    date: date
    weekday: str = ""
    shift1_start: str | None = None
    shift1_end: str | None = None
    shift2_start: str | None = None
    shift2_end: str | None = None
    overtime_start: str | None = None
    overtime_end: str | None = None

    @property
    def times(self) -> tuple[str, ...]:
        return tuple(
            value
            for value in (
                self.shift1_start,
                self.shift1_end,
                self.shift2_start,
                self.shift2_end,
                self.overtime_start,
                self.overtime_end,
            )
            if value is not None
        )

    @property
    def incomplete_pair_count(self) -> int:
        return sum(bool(getattr(self, start)) != bool(getattr(self, end)) for start, end in TIME_PAIRS)

    @property
    def lunch_minutes(self) -> int | None:
        if not all(getattr(self, field) for field in CORE_TIME_FIELDS):
            return None
        duration = _minutes(self.shift2_start) - _minutes(self.shift1_end)
        return duration if duration >= 0 else duration + 24 * 60

    @property
    def lunch_excess_minutes(self) -> int | None:
        lunch = self.lunch_minutes
        return max(0, lunch - LUNCH_BREAK_MINUTES) if lunch is not None else None

    @property
    def worked_minutes(self) -> int | None:
        if not all(getattr(self, field) for field in CORE_TIME_FIELDS):
            return None
        total = 0
        for start_field, end_field in TIME_PAIRS[:2]:
            start = getattr(self, start_field)
            end = getattr(self, end_field)
            duration = _minutes(end) - _minutes(start)
            total += duration if duration >= 0 else duration + 24 * 60
        lunch = self.lunch_minutes
        if lunch is not None and lunch < LUNCH_BREAK_MINUTES:
            total -= LUNCH_BREAK_MINUTES - lunch
        overtime_start, overtime_end = self.overtime_start, self.overtime_end
        if overtime_start and overtime_end:
            overtime = _minutes(overtime_end) - _minutes(overtime_start)
            total += overtime if overtime >= 0 else overtime + 24 * 60
        return total

    @property
    def worked_label(self) -> str:
        if self.worked_minutes is not None:
            return "Jornada realizada" if self.required_minutes else "Horas extras"
        if not self.times and self.required_minutes == 0:
            return "Sem expediente"
        return "Sem registro de ponto"

    @property
    def required_minutes(self) -> int:
        if self.date.weekday() <= 3:
            return 9 * 60
        if self.date.weekday() == 4:
            return 8 * 60
        return 0

    @property
    def balance_minutes(self) -> int | None:
        worked = self.worked_minutes
        if worked is None or self.required_minutes == 0:
            return None
        return worked - self.required_minutes

    @property
    def has_incomplete_day(self) -> bool:
        return bool(self.times) and self.worked_minutes is None


@dataclass(frozen=True, slots=True)
class WeeklySummary:
    week_start: date
    worked_minutes: int

    @property
    def week_end(self) -> date:
        return self.week_start + timedelta(days=6)

    @property
    def balance_minutes(self) -> int:
        return self.worked_minutes - WEEKLY_TARGET_MINUTES


@dataclass(slots=True)
class Employee:
    employee_number: str
    name: str
    department: str
    period_start: date | None
    period_end: date | None
    records: list[AttendanceRecord] = field(default_factory=list)
    source_sheet: str = ""
    source_start_row: int = 0
    source_end_row: int = 0

    @property
    def valid_time_count(self) -> int:
        return sum(len(record.times) for record in self.records)

    @property
    def days_with_records(self) -> int:
        return sum(bool(record.times) for record in self.records)

    @property
    def worked_minutes(self) -> int:
        return sum(record.worked_minutes or 0 for record in self.records)

    @property
    def incomplete_pair_count(self) -> int:
        return sum(record.incomplete_pair_count for record in self.records)

    @property
    def incomplete_day_count(self) -> int:
        return sum(record.has_incomplete_day for record in self.records)

    @property
    def expected_minutes(self) -> int:
        return PERIOD_TARGET_MINUTES

    @property
    def balance_minutes(self) -> int:
        return self.worked_minutes - self.expected_minutes

    @property
    def weekly_summaries(self) -> list[WeeklySummary]:
        grouped: dict[date, int] = {}
        for record in self.records:
            week_start = record.date - timedelta(days=record.date.weekday())
            grouped[week_start] = grouped.get(week_start, 0) + (record.worked_minutes or 0)
        return [WeeklySummary(week_start, grouped[week_start]) for week_start in sorted(grouped)]

    @property
    def included(self) -> bool:
        return self.valid_time_count > 0


@dataclass(slots=True)
class ImportResult:
    source_file: str
    sheet_names: list[str]
    employees: list[Employee]

    @property
    def included(self) -> list[Employee]:
        return [employee for employee in self.employees if employee.included]

    @property
    def excluded(self) -> list[Employee]:
        return [employee for employee in self.employees if not employee.included]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for item, employee in zip(payload["employees"], self.employees, strict=True):
            item["valid_time_count"] = employee.valid_time_count
            item["days_with_records"] = employee.days_with_records
            item["status"] = "INCLUDED" if employee.included else "EXCLUDED_NO_TIME"
        return payload
