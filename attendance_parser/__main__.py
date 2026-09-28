from __future__ import annotations

import argparse
import json
from pathlib import Path

from .parser import AttendanceWorkbookParser


def main() -> int:
    arguments = argparse.ArgumentParser(description="Analisa formulários de comparecimento XLS/XLSX.")
    arguments.add_argument("source", type=Path)
    arguments.add_argument("--json", dest="json_path", type=Path)
    args = arguments.parse_args()

    result = AttendanceWorkbookParser().parse(args.source)
    print(f"Arquivo: {result.source_file}")
    print(f"Planilhas: {', '.join(result.sheet_names)}")
    print(f"Funcionários identificados: {len(result.employees)}")
    print(f"Com horários: {len(result.included)}")
    print(f"Sem horários: {len(result.excluded)}")
    print()
    print(f"{'FUNCIONÁRIO':<24} {'DEPARTAMENTO':<16} {'HORÁRIOS':>8}  STATUS")
    print("-" * 72)
    for employee in result.employees:
        status = "INCLUÍDO" if employee.included else "EXCLUÍDO_SEM_HORÁRIO"
        print(f"{employee.name or '(SEM NOME)':<24} {employee.department:<16} {employee.valid_time_count:>8}  {status}")

    if args.json_path:
        args.json_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"\nDiagnóstico JSON: {args.json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
