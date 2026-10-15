"""Shared CLI/API report rendering and content fingerprints."""
import hashlib
import json
from pathlib import Path
import platform
import shlex

from . import harness


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def exit_code(report):
    return {"PASS": 0, "FAIL": 1, "UNKNOWN": 2, "ERROR": 3}[report["status"]]


def create_report(suite, adapter, case_path="<inline>", case_hash=None):
    package = Path(__file__).parent
    sources = {p.name: harness.sha256_file(p) for p in sorted(package.glob("*.py"))}
    snapshot = json.loads(canonical(suite))
    report = harness.run_suite(suite, adapter, case_path, case_hash)
    s = report["summary"]
    report.update({
        "schema": "signwarden.report.v1",
        "status": "FAIL" if s["FAIL"] else "UNKNOWN" if s["UNKNOWN"] or not report["cases"] else "PASS",
        "input_suite": snapshot,
        "input_suite_sha256": hashlib.sha256(canonical(snapshot)).hexdigest(),
        "runtime": {"python": platform.python_version(), "implementation": platform.python_implementation()},
        "source_sha256": sources,
        "reproduce": "signwarden report --cases %s --adapter %s --out rerun" % (
            shlex.quote(case_path if case_path != "<inline>" else "replay.json"), shlex.quote(adapter)),
        "replay_note": "Save input_suite as replay.json and use that path with --cases. Keep the adapter, its dependencies, runtime and inputs unchanged. Rerunning executes the adapter again.",
    })
    if not report["cases"]:
        report["reason"] = "No cases were executed."
    report["report_sha256"] = hashlib.sha256(canonical(report)).hexdigest()
    return report


def report_file(case_path, adapter):
    raw = Path(case_path).read_bytes()
    return create_report(json.loads(raw), adapter, str(case_path), hashlib.sha256(raw).hexdigest())


def error_report(exc):
    return {"schema": "signwarden.error.v1", "status": "ERROR",
            "error": {"type": type(exc).__name__, "message": str(exc)}}


def markdown(report):
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", "<br>").replace("\r", "")
    s = report["summary"]
    lines = ["# SignWarden verification report", "", "Status: **%s**" % report["status"], "",
             "PASS: %d; FAIL: %d; UNKNOWN: %d." % (s["PASS"], s["FAIL"], s["UNKNOWN"]), "",
             report["scope_note"], "", "## Provenance", "",
             "- Version: `%s`" % report["signwarden_version"],
             "- Case file SHA-256: `%s`" % report["case_file_sha256"],
             "- Canonical input SHA-256: `%s`" % report["input_suite_sha256"],
             "- Adapter SHA-256: `%s`" % report["adapter_sha256"],
             "- Harness SHA-256: `%s`" % report["harness_sha256"],
             "- Report SHA-256: `%s`" % report["report_sha256"], "",
             "The report hash covers canonical JSON without report_sha256. It is an integrity fingerprint, not a signature.",
             "", "## Results", "", "| Case | Result | Not executed steps | Reason |",
             "|---|---|---|---|"]
    for c in report["cases"]:
        reasons = [k["reason"] for k in c["checks"] if k["result"] != "PASS"]
        if c["stopped_reason"]:
            reasons.append(c["stopped_reason"])
        lines.append("| %s | %s | %s | %s |" % (cell(c["id"]), c["result"],
                     cell(c["not_executed_steps"]), cell("; ".join(reasons))))
    if not report["cases"]:
        lines.extend(["", report["reason"]])
    lines.extend(["", "## Rerun", "", "```sh", report["reproduce"], "```", "",
                  report["replay_note"], "",
                  "The companion JSON contains the input snapshot, runtime, source hashes, expected/observed checks and side-effect ledgers.", ""])
    return "\n".join(lines)


def write_report(report, prefix):
    base = Path(prefix)
    # Serialize both before writing either output.
    data = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    rendered = markdown(report)
    base.parent.mkdir(parents=True, exist_ok=True)
    Path(str(base) + ".json").write_text(data, encoding="utf-8")
    Path(str(base) + ".md").write_text(rendered, encoding="utf-8")
