"""Public synthetic tests for the report contract and loopback API."""
import copy
import hashlib
import http.client
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import threading
import unittest

from signwarden.api import MAX_BODY, make_server
from signwarden.reporting import create_report, markdown, report_file

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = str(ROOT / "examples/reference_gateway.py") + ":Adapter"
SAMPLE = ROOT / "cases/sample.json"


class ProductTests(unittest.TestCase):
    def setUp(self):
        self.suite = json.loads(SAMPLE.read_text())
        self.work = Path(tempfile.mkdtemp(prefix="signwarden-test-"))

    def cli(self, *args):
        return subprocess.run([sys.executable, "-I", "-m", "signwarden", *args],
                              cwd=self.work, capture_output=True, text=True)

    def test_sample_and_deterministic_hash(self):
        a = report_file(SAMPLE, ADAPTER)
        b = report_file(SAMPLE, ADAPTER)
        self.assertEqual(a, b)
        self.assertEqual((a["status"], a["summary"]), ("PASS", {"PASS": 12, "FAIL": 0, "UNKNOWN": 0}))
        digest = a.pop("report_sha256")
        encoded = json.dumps(a, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        self.assertEqual(digest, hashlib.sha256(encoded).hexdigest())
        self.assertEqual(a["case_file_sha256"], hashlib.sha256(SAMPLE.read_bytes()).hexdigest())
        self.assertEqual(a["adapter_sha256"], hashlib.sha256(Path(ADAPTER.rpartition(":")[0]).read_bytes()).hexdigest())
        for name, value in a["source_sha256"].items():
            import signwarden
            self.assertEqual(value, hashlib.sha256((Path(signwarden.__file__).parent / name).read_bytes()).hexdigest())

    def test_input_snapshot_and_replay(self):
        a = create_report(self.suite, ADAPTER)
        b = create_report(json.loads(json.dumps(a["input_suite"])), ADAPTER)
        self.assertEqual(a, b)
        self.suite["suite"] = "changed"
        self.assertNotEqual(a["input_suite"], self.suite)
        self.assertNotEqual(a["input_suite_sha256"], create_report(self.suite, ADAPTER)["input_suite_sha256"])

    def test_cli_writes_both_and_quotes_paths(self):
        cases = self.work / "case file.json"
        cases.write_text(json.dumps(self.suite))
        result = self.cli("report", "--cases", str(cases), "--adapter", ADAPTER, "--out", "output/result")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads((self.work / "output/result.json").read_text())
        md = (self.work / "output/result.md").read_text()
        self.assertIn(report["report_sha256"], md)
        self.assertIn("**PASS**", md)
        self.assertIn(str(cases), shlex.split(report["reproduce"]))
        replay = self.cli(*shlex.split(report["reproduce"])[1:])
        self.assertEqual(replay.returncode, 0, replay.stdout + replay.stderr)

    def test_fail_and_exit_one(self):
        self.suite["cases"][0]["expect_total_effects"] = 999
        path = self.work / "fail.json"
        path.write_text(json.dumps(self.suite))
        result = self.cli("report", "--cases", str(path), "--adapter", ADAPTER)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "FAIL")

    def test_empty_suite_is_unknown(self):
        self.suite["cases"] = []
        result = create_report(self.suite, ADAPTER)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertIn("No cases were executed", markdown(result))

    def test_no_assertions_is_unknown(self):
        self.suite["cases"] = [{"id": "empty", "title": "No assertions", "steps": []}]
        self.assertEqual(create_report(self.suite, ADAPTER)["status"], "UNKNOWN")

    def test_unsupported_operation_is_unknown(self):
        adapter = self.work / "unsupported.py"
        adapter.write_text('class Adapter:\n    supports = set()\n    def __init__(self, env): pass\n    def load_fixtures(self, fx): pass\n')
        report = create_report(self.suite, str(adapter) + ":Adapter")
        self.assertEqual(report["status"], "UNKNOWN")
        self.assertTrue(report["cases"][0]["not_executed_steps"])
        self.assertIn("does not support", markdown(report))

    def test_crash_is_unknown_and_exit_two(self):
        adapter = self.work / "crash.py"
        adapter.write_text('class Adapter:\n    def __init__(self, env): raise RuntimeError("synthetic crash")\n')
        result = self.cli("report", "--cases", str(SAMPLE), "--adapter", str(adapter) + ":Adapter")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        report = json.loads((self.work / "report.json").read_text())
        self.assertEqual(report["summary"]["UNKNOWN"], 12)
        self.assertIn("synthetic crash", markdown(report))

    def test_malformed_adapter_status_is_unknown(self):
        self.suite["cases"] = [{"id": "bad-status", "title": "Invalid status", "steps": [
            {"op": "call", "call": {}, "expect": {"status": ["denied"], "effects": []}}]}]
        for output in ['None', '{"status": []}', '{"status": "typo"}']:
            adapter = self.work / "malformed.py"
            adapter.write_text('class Adapter:\n    def __init__(self, env): pass\n    def load_fixtures(self, fx): pass\n    def handle(self, call): return ' + output + '\n')
            with self.subTest(output=output):
                result = create_report(self.suite, str(adapter) + ":Adapter")
                self.assertEqual(result["status"], "UNKNOWN")

    def test_unexpected_effect_overrides_unknown(self):
        self.suite["cases"] = [{"id": "effects", "title": "Effect despite invalid answer", "steps": [
            {"op": "call", "call": {}, "expect": {"status": ["denied"], "effects": []}}]}]
        adapter = self.work / "effect.py"
        adapter.write_text('class Adapter:\n    def __init__(self, env): self.env = env\n    def load_fixtures(self, fx): pass\n    def handle(self, call):\n        self.env.tools["docs.read"](tenant="t", doc="d")\n        return None\n')
        result = create_report(self.suite, str(adapter) + ":Adapter")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(len(result["cases"][0]["ledger"]), 1)

    def test_readme_minimal_input_and_legacy_command(self):
        suite = {"suite": "clock-smoke", "fixtures": {"users": [], "policy": {"version": "v1", "requires_approval": []}},
                 "cases": [{"id": "clock", "title": "Advance clock", "steps": [
                     {"op": "advance_clock", "seconds": 1, "expect": {"effects": []}}]}]}
        self.assertEqual(create_report(suite, ADAPTER)["status"], "PASS")
        result = self.cli("run", "--cases", str(SAMPLE), "--adapter", ADAPTER, "--quiet")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_bad_case_shapes_rejected(self):
        bad = [None, [], {}, {"fixtures": {}, "cases": "wrong"}]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                create_report(value, ADAPTER)
        for expectation in [{}, {"status": "denied"}, {"status": []}, {"status": ["typo"]},
                            {"effects": "none"}, {"unexpected": []}]:
            suite = copy.deepcopy(self.suite)
            suite["cases"][0]["steps"][0]["expect"] = expectation
            with self.subTest(expectation=expectation), self.assertRaises(ValueError):
                create_report(suite, ADAPTER)

    def test_duplicate_id_and_negative_count_rejected(self):
        self.suite["cases"].append(copy.deepcopy(self.suite["cases"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            create_report(self.suite, ADAPTER)
        self.suite["cases"].pop()
        self.suite["cases"][0]["expect_total_effects"] = -1
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            create_report(self.suite, ADAPTER)

    def test_setup_and_output_errors_exit_three(self):
        invalid = self.work / "bad.json"
        invalid.write_text("{")
        for path, adapter, out in [(str(invalid), ADAPTER, "result"),
                                   (str(SAMPLE), "missing.py:Adapter", "result"),
                                   (str(SAMPLE), ADAPTER, "/dev/null/result")]:
            result = self.cli("report", "--cases", path, "--adapter", adapter, "--out", out)
            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "ERROR")

    def test_version_and_help(self):
        self.assertEqual(self.cli("--version").stdout.strip(), "0.1.0")
        result = self.cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("report", result.stdout)


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(ADAPTER, 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, body, path="/report", headers=None, method="POST"):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        try:
            connection.request(method, path, body, headers or {"Content-Type": "application/json"})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_api_matches_cli_core(self):
        code, report = self.request(SAMPLE.read_bytes())
        self.assertEqual(code, 200)
        self.assertEqual(report, create_report(json.loads(SAMPLE.read_bytes()), ADAPTER))

    def test_unknown_and_fail_are_results_not_http_errors(self):
        suite = json.loads(SAMPLE.read_bytes())
        suite["cases"] = []
        code, report = self.request(json.dumps(suite))
        self.assertEqual((code, report["status"]), (200, "UNKNOWN"))
        suite = json.loads(SAMPLE.read_bytes())
        suite["cases"][0]["expect_total_effects"] = 999
        code, report = self.request(json.dumps(suite))
        self.assertEqual((code, report["status"]), (200, "FAIL"))

    def test_invalid_json_shape_and_media_type(self):
        for body in [b"{", b"null", b"[]", b"{}"]:
            code, report = self.request(body)
            self.assertEqual((code, report["status"]), (400, "ERROR"))
        self.assertEqual(self.request(b"{}", headers={"Content-Type": "text/plain"})[0], 400)

    def test_body_size_boundaries(self):
        for length in ["0", str(MAX_BODY + 1), "-1", "invalid"]:
            code, report = self.request(b"", headers={"Content-Type": "application/json", "Content-Length": length})
            self.assertEqual((code, report["status"]), (400, "ERROR"))

    def test_routes_and_browser_origin(self):
        self.assertEqual(self.request(b"{}", path="/other")[0], 404)
        self.assertEqual(self.request(None, method="GET")[0], 405)
        self.assertEqual(self.request(b"{}", headers={"Content-Type": "application/json", "Origin": "https://example.org"})[0], 403)
        self.assertEqual(self.request(b"{}", headers={"Content-Type": "application/json", "Host": "example.org"})[0], 403)


if __name__ == "__main__":
    unittest.main()
