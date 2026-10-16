"""signwarden run --cases FILE --adapter FILE.py:Class [--out report.json]

Exit codes: 0 all PASS, 1 any FAIL, 2 no FAIL but some UNKNOWN, 3 usage/setup error.
"""
import argparse
import json
import shlex
import sys

from .harness import VERSION, run
from .reporting import error_report, exit_code, report_file, write_report


def main(argv=None):
    p = argparse.ArgumentParser(prog="signwarden")
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a permission/action regression suite against an adapter")
    r.add_argument("--cases", required=True)
    r.add_argument("--adapter", required=True, help="path/to/adapter.py:ClassName")
    r.add_argument("--out", help="write full JSON report here")
    r.add_argument("--quiet", action="store_true")
    r = sub.add_parser("report", help="write a hashed verification report as JSON and Markdown")
    r.add_argument("--cases", required=True, help="suite JSON file")
    r.add_argument("--adapter", required=True, help="trusted path/to/adapter.py:ClassName")
    r.add_argument("--out", default="report", help="output prefix (default: report -> report.json + report.md)")
    r = sub.add_parser("serve", help="serve POST /report on 127.0.0.1 using a fixed trusted adapter")
    r.add_argument("--adapter", required=True, help="trusted path/to/adapter.py:ClassName")
    r.add_argument("--port", type=int, default=8765)
    a = p.parse_args(argv)
    if a.cmd in ("report", "serve"):
        try:
            if a.cmd == "serve":
                from .api import serve
                serve(a.adapter, a.port)
                return 0
            report = report_file(a.cases, a.adapter)
            write_report(report, a.out)
        except Exception as exc:
            print(json.dumps(error_report(exc)), file=sys.stdout)
            return 3
        print(json.dumps({"status": report["status"], "summary": report["summary"],
                          "report_sha256": report["report_sha256"],
                          "json": a.out + ".json", "markdown": a.out + ".md"}))
        return exit_code(report)
    try:
        report = run(a.cases, a.adapter)
    except Exception as e:  # bad case file or adapter path
        print("signwarden: setup error: %s" % e, file=sys.stderr)
        return 3
    report["reproduce"] = "python3 -m signwarden run --cases %s --adapter %s" % (
        shlex.quote(a.cases), shlex.quote(a.adapter))
    if a.out:
        with open(a.out, "w") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    if not a.quiet:
        for c in report["cases"]:
            line = "%-7s %-4s %s" % (c["result"], c["id"], c["title"])
            bad = [k for k in c["checks"] if k["result"] != "PASS"]
            if bad:
                line += "\n        step %s: %s" % (bad[0]["step"], bad[0]["reason"].splitlines()[0])
            elif c["stopped_reason"]:
                line += "\n        %s" % c["stopped_reason"].splitlines()[0]
            print(line)
        s = report["summary"]
        print("summary: PASS %d  FAIL %d  UNKNOWN %d  (adapter sha256 %s)" % (
            s["PASS"], s["FAIL"], s["UNKNOWN"], report["adapter_sha256"][:12]))
    s = report["summary"]
    return 1 if s["FAIL"] else 2 if s["UNKNOWN"] else 0


if __name__ == "__main__":
    sys.exit(main())
