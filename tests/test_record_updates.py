import unittest
from datetime import date
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json
from reportlab.platypus import KeepTogether, Table

from attendance_parser.models import AttendanceRecord, Employee
from server import Handler, SESSION_EMPLOYEES, employee_story, update_record_times


class RecordUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.employee = Employee(
            "15",
            "Bruno",
            "Cadastro",
            date(2026, 8, 25),
            date(2026, 9, 24),
            [AttendanceRecord(date(2026, 8, 25), "Terça-feira", "07:28", "11:33", "13:00", "17:00")],
        )

    def test_updates_valid_and_blank_times(self) -> None:
        update_record_times(self.employee, [{
            "shift1_start": "07:30",
            "shift1_end": "11:40",
            "shift2_start": "",
            "shift2_end": None,
            "overtime_start": "17:05",
            "overtime_end": "18:00",
        }])

        self.assertEqual(self.employee.records[0].shift1_start, "07:30")
        self.assertEqual(self.employee.records[0].shift1_end, "11:40")
        self.assertIsNone(self.employee.records[0].shift2_start)
        self.assertIsNone(self.employee.records[0].shift2_end)
        self.assertEqual(self.employee.records[0].overtime_start, "17:05")
        self.assertEqual(self.employee.valid_time_count, 4)

    def test_invalid_time_does_not_partially_update_records(self) -> None:
        with self.assertRaises(ValueError):
            update_record_times(self.employee, [{"shift1_start": "25:70"}])

        self.assertEqual(self.employee.records[0].shift1_start, "07:28")
        self.assertEqual(self.employee.records[0].shift1_end, "11:33")

    def test_rejects_record_count_mismatch(self) -> None:
        with self.assertRaises(ValueError):
            update_record_times(self.employee, [])

    def test_pdf_story_has_daily_table_and_signature_without_weekly_summary(self) -> None:
        story = employee_story(self.employee)
        tables = [flowable for flowable in story if isinstance(flowable, Table)]

        self.assertEqual(len(tables), 2)  # employee metadata and daily punches
        self.assertIsInstance(story[-1], KeepTogether)


class RecordUpdateApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session_id = "a" * 32
        self.employee = Employee(
            "15",
            "Bruno",
            "Cadastro",
            date(2026, 8, 25),
            date(2026, 9, 24),
            [AttendanceRecord(date(2026, 8, 25), "Terça-feira", "07:28", "11:33", "13:00", "17:00")],
        )
        SESSION_EMPLOYEES[self.session_id] = [self.employee]
        self.http_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.http_server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.http_server.server_port}"

    def tearDown(self) -> None:
        self.http_server.shutdown()
        self.thread.join()
        self.http_server.server_close()
        SESSION_EMPLOYEES.pop(self.session_id, None)

    def test_saved_time_is_returned_by_api_and_used_in_pdf(self) -> None:
        payload = {"records": [{
            "shift1_start": "07:30",
            "shift1_end": "11:40",
            "shift2_start": "13:00",
            "shift2_end": "17:00",
            "overtime_start": None,
            "overtime_end": None,
        }]}
        request = Request(
            f"{self.base_url}/api/session/{self.session_id}/employee/0/records",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            updated = json.loads(response.read())
            self.assertEqual(response.status, 200)
        self.assertEqual(updated["records"][0]["shift1_start"], "07:30")
        self.assertEqual(updated["worked_time"], "8h 00min")
        self.assertEqual(updated["expected_time"], "220h 00min")
        self.assertEqual(updated["records"][0]["worked_time"], "8h 00min")
        self.assertEqual(updated["records"][0]["balance_time"], "-1h 00min")
        self.assertEqual(updated["records"][0]["lunch_minutes"], 80)
        self.assertEqual(updated["records"][0]["lunch_excess_minutes"], 0)
        self.assertEqual(updated["records"][0]["lunch_time"], "1h 20min · ajustado a 1h30")

        with urlopen(f"{self.base_url}/api/session/{self.session_id}/employee/0/pdf") as response:
            pdf = response.read()
            self.assertEqual(response.status, 200)
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_cross_origin_upload_is_rejected(self) -> None:
        request = Request(
            f"{self.base_url}/api/import",
            data=b"file=test",
            headers={"Origin": "https://site-externo.example", "Content-Type": "application/octet-stream"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(request)
        self.assertEqual(context.exception.code, 403)
        context.exception.close()

    def test_responses_include_local_security_headers(self) -> None:
        with urlopen(self.base_url) as response:
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

    def test_invalid_time_is_rejected_without_mutating_employee(self) -> None:
        request = Request(
            f"{self.base_url}/api/session/{self.session_id}/employee/0/records",
            data=json.dumps({"records": [{"shift1_start": "27:91"}]}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(request)
        self.assertEqual(context.exception.code, 400)
        context.exception.close()
        self.assertEqual(self.employee.records[0].shift1_start, "07:28")


if __name__ == "__main__":
    unittest.main()
