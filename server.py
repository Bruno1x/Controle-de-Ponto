from __future__ import annotations

import atexit, io, json, mimetypes, re, shutil, tempfile, threading, uuid, webbrowser, zipfile
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from attendance_parser import AttendanceWorkbookParser
from attendance_parser.models import Employee, ImportResult, LUNCH_BREAK_MINUTES, WEEKLY_TARGET_MINUTES

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend" / "dist"
UPLOAD_DIR = Path(tempfile.mkdtemp(prefix="controle_ponto_"))
SESSION_EMPLOYEES: dict[str, list[Employee]] = {}
MAX_UPLOAD = 25 * 1024 * 1024
HOST = "127.0.0.1"
PORT = 8766
TIME_FIELDS = ("shift1_start", "shift1_end", "shift2_start", "shift2_end", "overtime_start", "overtime_end")
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class LocalThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False


@atexit.register
def cleanup_uploads() -> None:
    shutil.rmtree(UPLOAD_DIR, ignore_errors=True)


def employee_payload(employee: Employee, index: int, include_records: bool = False) -> dict:
    payload = {"id": index, "employee_number": employee.employee_number, "name": employee.name,
        "department": employee.department, "period_start": employee.period_start.isoformat() if employee.period_start else None,
        "period_end": employee.period_end.isoformat() if employee.period_end else None,
        "time_count": employee.valid_time_count, "days_with_records": employee.days_with_records,
        "worked_minutes": employee.worked_minutes, "worked_time": format_duration(employee.worked_minutes),
        "expected_minutes": employee.expected_minutes, "expected_time": format_duration(employee.expected_minutes),
        "balance_minutes": employee.balance_minutes, "balance_time": format_signed_duration(employee.balance_minutes),
        "incomplete_pair_count": employee.incomplete_pair_count,
        "incomplete_day_count": employee.incomplete_day_count,
        "lunch_excess_day_count": sum((record.lunch_excess_minutes or 0) > 0 for record in employee.records),
        "weekly_summaries": [{"week_start": item.week_start.isoformat(), "week_end": item.week_end.isoformat(),
            "worked_minutes": item.worked_minutes, "worked_time": format_duration(item.worked_minutes),
            "expected_minutes": WEEKLY_TARGET_MINUTES, "expected_time": format_duration(WEEKLY_TARGET_MINUTES),
            "balance_minutes": item.balance_minutes, "balance_time": format_signed_duration(item.balance_minutes)}
            for item in employee.weekly_summaries],
        "status": "included" if employee.included else "excluded_no_time",
        "source": f"{employee.source_sheet} / linhas {employee.source_start_row}-{employee.source_end_row}"}
    if include_records:
        payload["records"] = [{"date": item.date.isoformat(), "date_label": item.date.strftime("%d/%m/%Y"),
            "weekday": item.weekday, "shift1_start": item.shift1_start, "shift1_end": item.shift1_end,
            "shift2_start": item.shift2_start, "shift2_end": item.shift2_end,
            "overtime_start": item.overtime_start, "overtime_end": item.overtime_end,
            "lunch_minutes": item.lunch_minutes, "lunch_excess_minutes": item.lunch_excess_minutes,
            "lunch_time": format_lunch(item.lunch_minutes, item.lunch_excess_minutes),
            "worked_minutes": item.worked_minutes,
            "worked_time": format_duration(item.worked_minutes) if item.worked_minutes is not None else item.worked_label,
            "required_minutes": item.required_minutes,
            "required_time": format_duration(item.required_minutes) if item.required_minutes else "Hora extra" if item.times else "—",
            "balance_minutes": item.balance_minutes,
            "balance_time": format_signed_duration(item.balance_minutes) if item.balance_minutes is not None else "—",
            "incomplete_pair_count": item.incomplete_pair_count,
            "has_incomplete_day": item.has_incomplete_day} for item in employee.records]
    return payload


def format_duration(minutes: int) -> str:
    hours, remaining_minutes = divmod(minutes, 60)
    return f"{hours}h {remaining_minutes:02d}min"


def format_signed_duration(minutes: int) -> str:
    sign = "-" if minutes < 0 else "+" if minutes > 0 else ""
    return f"{sign}{format_duration(abs(minutes))}"


def format_lunch(minutes: int | None, excess: int | None) -> str:
    if minutes is None:
        return "—"
    hours, remaining = divmod(minutes, 60)
    actual = f"{hours}h {remaining:02d}min"
    if excess:
        extra = f"{excess}min" if excess < 60 else format_duration(excess)
        return f"{actual} · +{extra}"
    if minutes < LUNCH_BREAK_MINUTES:
        return f"{actual} · ajustado a 1h30"
    return actual


def format_pdf_lunch(minutes: int | None, excess: int | None) -> str:
    if minutes is None:
        return "—"
    hours, remaining = divmod(minutes, 60)
    actual = f"{hours}h {remaining:02d}min"
    if excess:
        return f"{actual} (+{excess}m)"
    return actual


def create_http_server() -> ThreadingHTTPServer:
    """Use the standard local port when free, otherwise let Windows choose one."""
    try:
        return LocalThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        return LocalThreadingHTTPServer((HOST, 0), Handler)


def session_payload(session_id: str, result: ImportResult) -> dict:
    start = next((item.period_start for item in result.employees if item.period_start), None)
    end = next((item.period_end for item in result.employees if item.period_end), None)
    return {"session_id": session_id, "filename": result.source_file,
        "period_start": start.isoformat() if start else None, "period_end": end.isoformat() if end else None,
        "identified_count": len(result.employees), "included_count": len(result.included), "excluded_count": len(result.excluded),
        "employees": [employee_payload(item, index) for index, item in enumerate(result.included)],
        "excluded": [employee_payload(item, index) for index, item in enumerate(result.excluded)]}


def update_record_times(employee: Employee, records: object) -> None:
    if not isinstance(records, list) or len(records) != len(employee.records):
        raise ValueError("A quantidade de dias enviada não corresponde à ficha aberta.")
    cleaned: list[dict[str, str | None]] = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Formato de marcação inválido.")
        cleaned_record = {}
        for field in TIME_FIELDS:
            value = record.get(field)
            if value in (None, ""):
                cleaned_record[field] = None
            elif isinstance(value, str) and TIME_PATTERN.fullmatch(value):
                cleaned_record[field] = value
            else:
                raise ValueError("Use horários válidos no formato HH:MM.")
        cleaned.append(cleaned_record)
    for target, values in zip(employee.records, cleaned, strict=True):
        for field, value in values.items():
            setattr(target, field, value)


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value.strip().upper()).strip("_") or "SEM_NOME"


def period_code(employee: Employee) -> str:
    reference = employee.period_end or employee.period_start
    return reference.strftime("%Y-%m") if reference else "SEM_PERIODO"


def pdf_filename(employee: Employee) -> str:
    return f"Ponto_{safe_name(employee.name)}_{period_code(employee)}.pdf"


def pdf_header_footer(canvas, document) -> None:
    canvas.saveState(); canvas.setStrokeColor(colors.HexColor("#d6ded9")); canvas.setLineWidth(0.4)
    canvas.line(14 * mm, 11 * mm, landscape(A4)[0] - 14 * mm, 11 * mm)
    canvas.setFillColor(colors.HexColor("#5f6d65")); canvas.setFont("Helvetica", 7)
    canvas.drawString(14 * mm, 7 * mm, "Controle de Ponto - documento gerado localmente")
    canvas.drawRightString(landscape(A4)[0] - 14 * mm, 7 * mm, f"Página {document.page}"); canvas.restoreState()


def employee_story(employee: Employee) -> list:
    styles = getSampleStyleSheet()
    title = ParagraphStyle("TitleGreen", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=colors.HexColor("#0b5d3b"), spaceAfter=5)
    small = ParagraphStyle("Small", parent=styles["BodyText"], fontName="Helvetica", fontSize=8, leading=10, textColor=colors.HexColor("#26352c"))
    cell = ParagraphStyle("Cell", parent=small, fontSize=6.6, leading=7.4, alignment=TA_CENTER)
    left = ParagraphStyle("LeftCell", parent=cell, alignment=TA_LEFT)
    header_cell = ParagraphStyle("HeaderCell", parent=cell, textColor=colors.white, fontName="Helvetica-Bold")
    period = f"{employee.period_start:%d/%m/%Y} a {employee.period_end:%d/%m/%Y}" if employee.period_start and employee.period_end else ""
    story = [Paragraph("Controle de Ponto", title)]
    metadata = [[Paragraph(f"<b>Tra. No.:</b> {employee.employee_number}", small), Paragraph(f"<b>Nome:</b> {employee.name}", small),
        Paragraph(f"<b>Departamento:</b> {employee.department}", small), Paragraph(f"<b>Período:</b> {period}", small)],
        [Paragraph(f"<b>Dias com registro:</b> {employee.days_with_records}", small),
         Paragraph(f"<b>Total de marcações:</b> {employee.valid_time_count}", small),
         Paragraph(f"<b>Jornada realizada:</b> {format_duration(employee.worked_minutes)}", small),
         Paragraph(f"<b>Meta do período:</b> {format_duration(employee.expected_minutes)}", small)],
        [Paragraph(f"<b>Saldo do período:</b> {format_signed_duration(employee.balance_minutes)}", small),
         Paragraph(f"<b>Dias sem os 4 horários principais:</b> {employee.incomplete_day_count}", small),
         Paragraph(f"<b>Marcações incompletas:</b> {employee.incomplete_pair_count}", small), Paragraph("", small)]]
    meta = Table(metadata, colWidths=[65 * mm, 72 * mm, 72 * mm, 52 * mm], rowHeights=[8 * mm, 8 * mm, 8 * mm])
    meta.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), .6, colors.HexColor("#0b5d3b")),
        ("INNERGRID", (0, 0), (-1, -1), .35, colors.HexColor("#b9c8bf")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f5ee")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story.extend([meta, Spacer(1, 2 * mm)])
    headers = ["Data", "Semana", "Tem. 1<br/>Entrada", "Tem. 1<br/>Saída", "Almoço", "Tem. 2<br/>Entrada", "Tem. 2<br/>Saída", "Hora extra<br/>Entrada", "Hora extra<br/>Saída", "Horas<br/>obrigatórias", "Horas<br/>trabalhadas", "Saldo<br/>do dia"]
    rows = [[Paragraph(label, header_cell) for label in headers]]
    for record in employee.records:
        values = (record.shift1_start, record.shift1_end, record.shift2_start, record.shift2_end, record.overtime_start, record.overtime_end)
        worked = format_duration(record.worked_minutes) if record.worked_minutes is not None else record.worked_label
        required = format_duration(record.required_minutes) if record.required_minutes else "Hora extra" if record.times else "—"
        balance = format_signed_duration(record.balance_minutes) if record.balance_minutes is not None else "—"
        rows.append([Paragraph(record.date.strftime("%d/%m/%Y"), cell), Paragraph(record.weekday, left),
            *[Paragraph(value or "", cell) for value in values[:2]],
            Paragraph(format_pdf_lunch(record.lunch_minutes, record.lunch_excess_minutes), cell),
            *[Paragraph(value or "", cell) for value in values[2:]], Paragraph(required, cell),
            Paragraph(worked, cell), Paragraph(balance, cell)])
    required_total = sum(record.required_minutes for record in employee.records)
    worked_total = sum(record.worked_minutes or 0 for record in employee.records)
    daily_balance_total = worked_total - required_total
    rows.append([Paragraph("TOTAL DO PERÍODO", header_cell), *[""] * 8,
        Paragraph(format_duration(required_total), header_cell),
        Paragraph(format_duration(worked_total), header_cell),
        Paragraph(format_signed_duration(daily_balance_total), header_cell)])
    table = Table(rows, repeatRows=1, colWidths=[20*mm,24*mm,19*mm,19*mm,28*mm,19*mm,19*mm,20*mm,20*mm,27*mm,29*mm,27*mm], rowHeights=[9*mm]+[4*mm]*(len(rows)-1))
    table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0b5d3b")), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("GRID", (0,0), (-1,-1), .35, colors.HexColor("#9eb1a5")), ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,1), (-1,-1), 1.2), ("BOTTOMPADDING", (0,1), (-1,-1), 1.2),
        ("ROWBACKGROUNDS", (0,1), (8,-2), [colors.white, colors.HexColor("#f6faf7")]),
        ("SPAN", (0,-1), (8,-1)), ("BACKGROUND", (0,-1), (-1,-1), colors.HexColor("#e8f5ee")),
        ("ALIGN", (0,-1), (8,-1), "RIGHT"), ("LINEABOVE", (0,-1), (-1,-1), .7, colors.HexColor("#0b5d3b"))]))
    signature = Table([[""], [Paragraph("Assinatura do funcionário", cell)]], colWidths=[95*mm], rowHeights=[6*mm,4*mm], hAlign="RIGHT")
    signature.setStyle(TableStyle([("LINEABOVE", (0,1), (0,1), .7, colors.HexColor("#17211b")), ("ALIGN", (0,1), (0,1), "CENTER")]))
    story.extend([table, Spacer(1, 2*mm), KeepTogether(signature)]); return story


def build_pdf(employees: list[Employee]) -> bytes:
    output = io.BytesIO(); document = SimpleDocTemplate(output, pagesize=landscape(A4), rightMargin=12*mm, leftMargin=12*mm, topMargin=8*mm, bottomMargin=10*mm, title="Controle de Ponto")
    story = []
    for index, employee in enumerate(employees):
        if index: story.append(PageBreak())
        story.extend(employee_story(employee))
    document.build(story, onFirstPage=pdf_header_footer, onLaterPages=pdf_header_footer); return output.getvalue()


class Handler(BaseHTTPRequestHandler):
    server_version = "ControlePonto/1.0"
    def log_message(self, fmt: str, *args) -> None: print(f"[{self.log_date_time_string()}] {fmt % args}")
    def json_response(self, payload: dict, status: int = 200) -> None: self.bytes_response(json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8", status)
    def bytes_response(self, data: bytes, kind: str, status: int = 200, filename: str | None = None) -> None:
        self.send_response(status); self.send_header("Content-Type", kind); self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if filename: self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers(); self.wfile.write(data)
    def trusted_local_request(self) -> bool:
        expected_host = f"{HOST}:{self.server.server_port}"
        if self.headers.get("Host") != expected_host:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin == f"http://{expected_host}"
    def do_POST(self) -> None:
        if not self.trusted_local_request(): return self.json_response({"error":"Requisição local não autorizada."},403)
        update_match = re.fullmatch(r"/api/session/([a-f0-9]+)/employee/(\d+)/records", self.path)
        if update_match:
            return self.update_employee_records(update_match.group(1), int(update_match.group(2)))
        if self.path != "/api/import": return self.json_response({"error":"Rota não encontrada."},404)
        length = int(self.headers.get("Content-Length","0"))
        if length <= 0 or length > MAX_UPLOAD: return self.json_response({"error":"Arquivo ausente ou maior que 25 MB."},413)
        body = self.rfile.read(length); content_type = self.headers.get("Content-Type","")
        message = BytesParser(policy=default).parsebytes(f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode()+body)
        part = next((item for item in message.iter_attachments() if item.get_param("name",header="content-disposition")=="file"),None)
        if part is None: return self.json_response({"error":"Selecione um arquivo XLS ou XLSX."},400)
        filename = Path(part.get_filename() or "arquivo").name; suffix = Path(filename).suffix.lower()
        if suffix not in {".xls",".xlsx"}: return self.json_response({"error":"Formato inválido. Use XLS ou XLSX."},400)
        sid=uuid.uuid4().hex; target=UPLOAD_DIR/f"{sid}{suffix}"; target.write_bytes(part.get_payload(decode=True))
        try: result=AttendanceWorkbookParser().parse(target)
        except Exception as exc: return self.json_response({"error":f"Não foi possível interpretar a planilha: {exc}"},422)
        finally:
            try: target.unlink(missing_ok=True)
            except PermissionError: pass
        result.source_file = filename
        SESSION_EMPLOYEES.clear()
        SESSION_EMPLOYEES[sid]=list(result.included)
        self.json_response(session_payload(sid,result))
    def update_employee_records(self, session_id: str, index: int) -> None:
        employees = SESSION_EMPLOYEES.get(session_id)
        if employees is None or index >= len(employees):
            return self.json_response({"error":"Sessão ou funcionário não encontrado. Importe novamente."},404)
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1_000_000:
            return self.json_response({"error":"Dados de edição ausentes ou inválidos."},400)
        try:
            payload = json.loads(self.rfile.read(length))
            records = payload["records"]
            employee = employees[index]
            update_record_times(employee, records)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            return self.json_response({"error":str(exc) or "Dados de edição inválidos."},400)
        self.json_response(employee_payload(employee, index, True))
    def do_GET(self) -> None:
        if not self.trusted_local_request(): return self.json_response({"error":"Requisição local não autorizada."},403)
        parsed=urlparse(self.path)
        if parsed.path.startswith("/api/"): return self.handle_api(parsed.path,parse_qs(parsed.query))
        relative="index.html" if parsed.path=="/" else parsed.path.lstrip("/"); target=(FRONTEND_DIR/relative).resolve(); root=FRONTEND_DIR.resolve()
        if root not in target.parents and target!=root: return self.json_response({"error":"Acesso inválido."},403)
        if not target.is_file(): target=FRONTEND_DIR/"index.html"
        self.bytes_response(target.read_bytes(),mimetypes.guess_type(target.name)[0] or "application/octet-stream")
    def handle_api(self,path:str,query:dict[str,list[str]])->None:
        employee_match=re.fullmatch(r"/api/session/([a-f0-9]+)/employee/(\d+)(/pdf)?",path)
        bundle_match=re.fullmatch(r"/api/session/([a-f0-9]+)/(combined\.pdf|selected\.zip)",path)
        try:
            if employee_match:
                session_id=employee_match.group(1); index=int(employee_match.group(2)); employee=SESSION_EMPLOYEES[session_id][index]
                if employee_match.group(3): return self.bytes_response(build_pdf([employee]),"application/pdf",filename=pdf_filename(employee))
                return self.json_response(employee_payload(employee,index,True))
            if bundle_match:
                session_id=bundle_match.group(1); employees=SESSION_EMPLOYEES[session_id]; ids=query.get("ids",[""])[0]
                employees=employees if not ids else [employees[int(value)] for value in ids.split(",") if value.isdigit() and int(value)<len(employees)]
                if not employees: return self.json_response({"error":"Selecione pelo menos um funcionário."},400)
                if bundle_match.group(2)=="combined.pdf": return self.bytes_response(build_pdf(employees),"application/pdf",filename=f"Pontos_{period_code(employees[0])}.pdf")
                output=io.BytesIO()
                with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED) as archive:
                    for employee in employees: archive.writestr(f"PDFs/{pdf_filename(employee)}",build_pdf([employee]))
                return self.bytes_response(output.getvalue(),"application/zip",filename=f"Pontos_{period_code(employees[0])}.zip")
        except (KeyError,IndexError,ValueError): return self.json_response({"error":"Sessão ou funcionário não encontrado. Importe novamente."},404)
        self.json_response({"error":"Rota não encontrada."},404)


def main() -> None:
    if not (FRONTEND_DIR/"index.html").exists(): raise SystemExit("Interface não encontrada.")
    server=create_http_server(); address=f"http://{HOST}:{server.server_port}"
    threading.Timer(1,lambda:webbrowser.open(address)).start()
    print(f"Controle de Ponto disponível em {address}")
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
