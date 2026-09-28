from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from .models import AttendanceRecord, Employee, ImportResult
from .normalization import compact_label, normalize_text
from .time_parser import normalize_time
from .workbook import Sheet, close_workbook, load_workbook


PERIOD_PATTERN = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4}).*?(\d{1,2})/(\d{1,2})/(\d{4})")
SHORT_DATE_PATTERN = re.compile(r"^\s*(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s*$")
TIME_FIELDS = (
    "shift1_start",
    "shift1_end",
    "shift2_start",
    "shift2_end",
    "overtime_start",
    "overtime_end",
)
WEEKDAYS_PT = ("Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo")


class AttendanceWorkbookParser:
    def parse(self, source: str | Path) -> ImportResult:
        path = Path(source)
        sheets, sheet_names = load_workbook(path)
        try:
            register_sheet = self._find_register_sheet(sheets)
            employees = self._parse_register_blocks(register_sheet)
        finally:
            close_workbook(sheets)
        return ImportResult(path.name, sheet_names, employees)

    def _find_register_sheet(self, sheets: list[Sheet]) -> Sheet:
        ranked: list[tuple[int, Sheet]] = []
        for sheet in sheets:
            score = 0
            normalized_name = normalize_text(sheet.name)
            if "REGIST" in normalized_name and "COMPAREC" in normalized_name:
                score += 100
            sample_rows = min(sheet.nrows, 80)
            for row in range(sample_rows):
                labels = {compact_label(sheet.value(row, col)) for col in range(sheet.ncols)}
                if any(label.startswith("TRANO") for label in labels) and any(
                    label.startswith("NOME") for label in labels
                ):
                    score += 2
            ranked.append((score, sheet))
        score, selected = max(ranked, key=lambda item: item[0])
        if score < 4:
            raise ValueError("Não foi possível localizar a planilha de registros de comparecimento.")
        return selected

    def _parse_register_blocks(self, sheet: Sheet) -> list[Employee]:
        starts = [row for row in range(sheet.nrows) if self._is_employee_start(sheet, row)]
        period_start, period_end = self._find_sheet_period(sheet, starts[0] if starts else sheet.nrows)
        employees: list[Employee] = []
        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else sheet.nrows
            date_row = self._find_register_date_row(sheet, start)
            employee = Employee(
                employee_number=self._label_value(sheet, start, "TRANO"),
                name=self._label_value(sheet, start, "NOME"),
                department=self._label_value(sheet, start, "DEPT"),
                period_start=period_start,
                period_end=period_end,
                records=self._parse_register_records(sheet, date_row, start + 1, end, period_start, period_end),
                source_sheet=sheet.name,
                source_start_row=start + 1,
                source_end_row=end,
            )
            employees.append(employee)
        if not employees:
            raise ValueError("Nenhum bloco de funcionário foi identificado.")
        return employees

    def _find_sheet_period(self, sheet: Sheet, search_end: int) -> tuple[date | None, date | None]:
        for row in range(search_end):
            for column in range(sheet.ncols):
                value = sheet.value(row, column)
                if value is not None:
                    parsed = self._parse_period(str(value))
                    if parsed != (None, None):
                        return parsed
        return None, None

    def _find_register_date_row(self, sheet: Sheet, employee_row: int) -> int:
        candidates = range(max(0, employee_row - 3), employee_row)
        return max(candidates, key=lambda row: sum(self._day_number(sheet.value(row, col)) is not None for col in range(sheet.ncols)))

    def _parse_register_records(
        self,
        sheet: Sheet,
        date_row: int,
        data_start: int,
        data_end: int,
        period_start: date | None,
        period_end: date | None,
    ) -> list[AttendanceRecord]:
        date_columns = [
            column for column in range(sheet.ncols) if self._day_number(sheet.value(date_row, column)) is not None
        ]
        if not date_columns:
            return []
        data_row = max(
            range(data_start, data_end),
            key=lambda row: sum(len(self._time_tokens(sheet.value(row, column))) for column in date_columns),
            default=data_start,
        )
        records: list[AttendanceRecord] = []
        for column in date_columns:
            day = self._day_number(sheet.value(date_row, column))
            record_date = self._date_from_day(day, period_start, period_end)
            if record_date is None:
                continue
            values = self._time_tokens(sheet.value(data_row, column))[:6]
            values.extend([None] * (6 - len(values)))
            records.append(AttendanceRecord(record_date, WEEKDAYS_PT[record_date.weekday()], *values))
        return records

    @staticmethod
    def _day_number(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) and float(value).is_integer() and 1 <= int(value) <= 31:
            return int(value)
        if isinstance(value, str) and value.strip().isdigit() and 1 <= int(value.strip()) <= 31:
            return int(value.strip())
        return None

    @staticmethod
    def _time_tokens(value: object) -> list[str]:
        if isinstance(value, str):
            candidates: list[object] = re.split(r"[\r\n]+", value)
        else:
            candidates = [value]
        return [normalized for candidate in candidates if (normalized := normalize_time(candidate)) is not None]

    @staticmethod
    def _date_from_day(day: int | None, period_start: date | None, period_end: date | None) -> date | None:
        if day is None or period_start is None or period_end is None:
            return None
        if period_start.year == period_end.year:
            month = period_start.month if day >= period_start.day else period_end.month
            return date(period_start.year, month, day)
        if day >= period_start.day:
            return date(period_start.year, period_start.month, day)
        return date(period_end.year, period_end.month, day)

    def _parse_employee_blocks(self, sheet: Sheet) -> list[Employee]:
        starts = [row for row in range(sheet.nrows) if self._is_employee_start(sheet, row)]
        employees: list[Employee] = []
        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else sheet.nrows
            employees.append(self._parse_employee(sheet, start, end))
        if not employees:
            raise ValueError("Nenhum bloco de funcionário foi identificado.")
        return employees

    def _is_employee_start(self, sheet: Sheet, row: int) -> bool:
        labels = [compact_label(sheet.value(row, col)) for col in range(sheet.ncols)]
        return (
            any(label.startswith("TRANO") for label in labels)
            and any(label.startswith("NOME") for label in labels)
            and any(label.startswith("DEPT") for label in labels)
        )

    def _parse_employee(self, sheet: Sheet, start: int, end: int) -> Employee:
        name = self._label_value(sheet, start, "NOME")
        number = self._label_value(sheet, start, "TRANO")
        department = self._label_value(sheet, start, "DEPT")
        period_text = self._label_value(sheet, start, "DATA")
        period_start, period_end = self._parse_period(period_text)
        header_row = self._find_record_header(sheet, start + 1, end)
        records = self._parse_records(sheet, header_row, end, period_start, period_end) if header_row else []
        return Employee(
            employee_number=number,
            name=name,
            department=department,
            period_start=period_start,
            period_end=period_end,
            records=records,
            source_sheet=sheet.name,
            source_start_row=start + 1,
            source_end_row=end,
        )

    def _label_value(self, sheet: Sheet, row: int, expected: str) -> str:
        for column in range(sheet.ncols):
            raw = sheet.value(row, column)
            text = "" if raw is None else str(raw).strip()
            compact = compact_label(text)
            if not compact.startswith(expected):
                continue
            if ":" in text:
                value = text.split(":", 1)[1].strip()
                if value:
                    return value
            for next_column in range(column + 1, min(column + 4, sheet.ncols)):
                candidate = sheet.value(row, next_column)
                if candidate not in (None, ""):
                    return self._clean_scalar(candidate)
        return ""

    @staticmethod
    def _clean_scalar(value: object) -> str:
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip()

    @staticmethod
    def _parse_period(value: str) -> tuple[date | None, date | None]:
        match = PERIOD_PATTERN.search(value)
        if not match:
            return None, None
        sd, sm, sy, ed, em, ey = map(int, match.groups())
        return date(sy, sm, sd), date(ey, em, ed)

    def _find_record_header(self, sheet: Sheet, start: int, end: int) -> int | None:
        for row in range(start, end):
            labels = [compact_label(sheet.value(row, col)) for col in range(sheet.ncols)]
            if labels.count("DATA") >= 1 and "SEMANA" in labels and sum(
                label.startswith("IRPARATRA") or label.startswith("SAIRCEDO") for label in labels
            ) >= 2:
                return row
        return None

    def _parse_records(
        self,
        sheet: Sheet,
        header_row: int,
        end: int,
        period_start: date | None,
        period_end: date | None,
    ) -> list[AttendanceRecord]:
        date_columns = [
            column
            for column in range(sheet.ncols)
            if compact_label(sheet.value(header_row, column)) == "DATA"
        ]
        records: list[AttendanceRecord] = []
        for date_column in date_columns:
            next_date_column = next((col for col in date_columns if col > date_column), sheet.ncols)
            weekday_column = self._find_weekday_column(sheet, header_row, date_column, next_date_column)
            time_columns = self._find_time_columns(sheet, header_row, date_column, next_date_column)
            for row in range(header_row + 1, end):
                parsed_date = self._parse_record_date(sheet.value(row, date_column), period_start, period_end)
                if parsed_date is None:
                    continue
                values = [normalize_time(sheet.value(row, column)) for column in time_columns[:6]]
                values.extend([None] * (6 - len(values)))
                weekday = self._clean_scalar(sheet.value(row, weekday_column)) if weekday_column is not None else ""
                records.append(AttendanceRecord(parsed_date, weekday, *values))
        records.sort(key=lambda record: record.date)
        unique: dict[date, AttendanceRecord] = {}
        for record in records:
            unique[record.date] = record
        return list(unique.values())

    @staticmethod
    def _find_weekday_column(sheet: Sheet, row: int, start: int, end: int) -> int | None:
        return next(
            (column for column in range(start + 1, end) if compact_label(sheet.value(row, column)) == "SEMANA"),
            None,
        )

    @staticmethod
    def _find_time_columns(sheet: Sheet, row: int, start: int, end: int) -> list[int]:
        return [
            column
            for column in range(start + 1, end)
            if compact_label(sheet.value(row, column)).startswith(("IRPARATRA", "SAIRCEDO"))
        ]

    @staticmethod
    def _parse_record_date(value: object, period_start: date | None, period_end: date | None) -> date | None:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if not isinstance(value, str):
            return None
        match = SHORT_DATE_PATTERN.fullmatch(value)
        if not match:
            return None
        day, month = int(match.group(1)), int(match.group(2))
        year_text = match.group(3)
        if year_text:
            year = int(year_text)
            year += 2000 if year < 100 else 0
            return date(year, month, day)
        if period_start is None:
            return None
        year = period_start.year
        candidate = date(year, month, day)
        if candidate < period_start and period_end and period_end.year > year:
            candidate = date(period_end.year, month, day)
        return candidate


def has_real_time_records(employee: Employee) -> bool:
    return employee.included
