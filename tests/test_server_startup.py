import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from server import create_http_server


class ServerStartupTests(unittest.TestCase):
    def test_uses_an_available_local_port_when_default_is_taken(self) -> None:
        occupied = ThreadingHTTPServer(("127.0.0.1", 0), lambda *_: None)
        try:
            occupied_port = occupied.server_port
            with patch("server.PORT", occupied_port):
                server = create_http_server()
            try:
                self.assertNotEqual(server.server_port, occupied_port)
                self.assertEqual(server.server_address[0], "127.0.0.1")
            finally:
                server.server_close()
        finally:
            occupied.server_close()


if __name__ == "__main__":
    unittest.main()
