"""Loopback-only HTTP interface to the shared report command."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

from .harness import load_adapter
from .reporting import create_report, error_report

MAX_BODY = 1024 * 1024


def make_server(adapter, port=8765):
    # Only the operator chooses executable adapter code, never a request.
    load_adapter(adapter)

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def reply(self, code, payload):
            data = (json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            self.wfile.write(data)

        def do_POST(self):
            if self.path != "/report":
                self.reply(404, error_report(ValueError("use POST /report")))
                return
            if self.headers.get("Origin") or self.headers.get("Host") != "127.0.0.1:%d" % self.server.server_port:
                self.reply(403, error_report(ValueError("only direct loopback clients are supported")))
                return
            try:
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("Content-Type must be application/json")
                if self.headers.get("Transfer-Encoding"):
                    raise ValueError("Transfer-Encoding is not supported")
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= MAX_BODY:
                    raise ValueError("body must be between 1 and %d bytes" % MAX_BODY)
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError("incomplete request body")
                suite = json.loads(raw)
                report = create_report(suite, adapter)
            except Exception as exc:
                self.reply(400, error_report(exc))
                return
            self.reply(200, report)

        def do_GET(self):
            self.reply(405, error_report(ValueError("use POST /report")))

        def log_message(self, fmt, *args):
            pass

    return HTTPServer(("127.0.0.1", port), Handler)


def serve(adapter, port=8765):
    with make_server(adapter, port) as server:
        print("SignWarden API: http://127.0.0.1:%d/report (trusted local adapters only)" % server.server_port, flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
