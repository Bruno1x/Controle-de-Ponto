from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Protocol


class Sheet(Protocol):
    name: str
    nrows: int
    ncols: int

    def value(self, row: int, column: int) -> object: ...


@dataclass(slots=True)
class XlrdSheet:
    source: object
    datemode: int

    @property
    def name(self) -> str:
        return self.source.name

    @property
    def nrows(self) -> int:
        return self.source.nrows

    @property
    def ncols(self) -> int:
        return self.source.ncols

    def value(self, row: int, column: int) -> object:
        import xlrd

        cell = self.source.cell(row, column)
        if cell.ctype == xlrd.XL_CELL_EMPTY:
            return None
        if cell.ctype == xlrd.XL_CELL_DATE:
            parts = xlrd.xldate_as_tuple(cell.value, self.datemode)
            if parts[:3] == (0, 0, 0):
                return time(parts[3], parts[4], parts[5])
            return datetime(*parts)
        return cell.value


@dataclass(slots=True)
class OpenpyxlSheet:
    source: object

    @property
    def name(self) -> str:
        return self.source.title

    @property
    def nrows(self) -> int:
        return self.source.max_row

    @property
    def ncols(self) -> int:
        return self.source.max_column

    def value(self, row: int, column: int) -> object:
        return self.source.cell(row=row + 1, column=column + 1).value


def load_workbook(path: Path) -> tuple[list[Sheet], list[str]]:
    suffix = path.suffix.lower()
    if suffix == ".xls":
        import xlrd

        book = xlrd.open_workbook(path, on_demand=True)
        return [XlrdSheet(sheet, book.datemode) for sheet in book.sheets()], book.sheet_names()
    if suffix == ".xlsx":
        from openpyxl import load_workbook as open_xlsx

        book = open_xlsx(path, read_only=True, data_only=True)
        return [OpenpyxlSheet(sheet) for sheet in book.worksheets], book.sheetnames
    raise ValueError(f"Formato não suportado: {suffix or '(sem extensão)'}")


def close_workbook(sheets: list[Sheet]) -> None:
    if not sheets:
        return
    source = sheets[0].source
    parent = getattr(source, "parent", None)
    if parent is not None and callable(getattr(parent, "close", None)):
        parent.close()
        return
    book = getattr(source, "book", None)
    if book is not None and callable(getattr(book, "release_resources", None)):
        book.release_resources()
