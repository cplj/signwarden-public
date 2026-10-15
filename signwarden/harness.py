"""SignWarden harness: controlled test tools, side-effect ledger, case runner, oracle.

The oracle judges two things per step and does not take the system under test (SUT) at its word:
  1. the status the SUT reports, against the statuses the case allows;
  2. the side effects the controlled tools actually recorded, against the case's expected effects.
A SUT that says "denied" but committed a refund, or says "executed" after a timeout, fails.

Limitation: the SUT runs in the same Python process as the ledger. A SUT that deliberately
tampers with the ledger (e.g. via introspection) can hide its effects. This tool tests for
regressions in honest code; it is not a sandbox against hostile code.
"""
import copy
import hashlib
import importlib.util
import json
import traceback

VERSION = "0.1.0"
STATUSES = {"executed", "denied", "pending_approval", "error", "unknown"}
HARNESS_OPS = {"advance_clock"}
ADAPTER_OPS = {"set_policy", "delegate", "revoke", "approve", "call", "resume"}
FAULT_MODES = {"error", "timeout_after_commit"}


class ToolTimeout(Exception):
    """Tool did not answer in time. The side effect may or may not have happened."""


class ToolError(Exception):
    """Tool rejected the request. No side effect happened."""


class Clock:
    def __init__(self, t=0):
        self.t = t

    def now(self):
        return self.t


class ControlledTools:
    """Two isolated test tools. They trust the caller on purpose: authorization is the SUT's job."""

    def __init__(self, fixtures, faults):
        self.docs = {d["id"]: d for d in fixtures.get("docs", [])}
        self.ledger = []
        self.faults = {k: dict(v) for k, v in (faults or {}).items()}
        for tool, f in self.faults.items():  # a typo must not silently disable the fault
            if tool not in ("billing.refund", "docs.read") or f.get("mode") not in FAULT_MODES:
                raise ValueError("unsupported fault %r: %r (modes: %s)" % (tool, f, sorted(FAULT_MODES)))
        self._idem = {}

    def _fault(self, name):
        f = self.faults.get(name)
        if f and f.get("times", 1) > 0:
            f["times"] = f.get("times", 1) - 1
            return f["mode"]
        return None

    def refund(self, tenant, account, amount, idempotency_key=None):
        mode = self._fault("billing.refund")
        if mode == "error":
            raise ToolError("refund backend rejected request")
        if idempotency_key is not None and (tenant, idempotency_key) in self._idem:
            return self._idem[(tenant, idempotency_key)]
        self.ledger.append({"tool": "billing.refund", "tenant": tenant,
                            "args": {"account": account, "amount": amount}})
        result = {"refund_id": "r%d" % len(self.ledger)}
        if idempotency_key is not None:
            self._idem[(tenant, idempotency_key)] = result
        if mode == "timeout_after_commit":
            raise ToolTimeout("refund timed out after commit")
        return result

    def read(self, tenant, doc, idempotency_key=None):
        mode = self._fault("docs.read")
        if mode == "error":
            raise ToolError("docs backend rejected request")
        self.ledger.append({"tool": "docs.read", "tenant": tenant, "args": {"doc": doc}})
        if mode == "timeout_after_commit":
            raise ToolTimeout("read timed out after access")
        d = self.docs.get(doc)
        return {"content": d["content"] if d else None}

    def as_dict(self):
        return {"billing.refund": self.refund, "docs.read": self.read}


class Env:
    """What the adapter receives: tools to call, a clock, and the tool exception types."""

    ToolTimeout = ToolTimeout
    ToolError = ToolError

    def __init__(self, tools, clock):
        self.tools = tools
        self.clock = clock


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def load_adapter(spec):
    """spec is 'path/to/file.py:ClassName'."""
    path, _, name = spec.rpartition(":")
    if not path or not name:
        raise ValueError("adapter must be 'file.py:ClassName', got %r" % spec)
    mod_spec = importlib.util.spec_from_file_location("sw_adapter_%s" % name, path)
    mod = importlib.util.module_from_spec(mod_spec)
    mod_spec.loader.exec_module(mod)
    return getattr(mod, name), path


def _resolve(obj, refs):
    if isinstance(obj, str) and obj.startswith("$"):
        if obj[1:] not in refs:
            raise KeyError("unresolved reference %s" % obj)
        return refs[obj[1:]]
    if isinstance(obj, dict):
        return {k: _resolve(v, refs) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve(v, refs) for v in obj]
    return obj


def _canon(effects):
    return sorted(json.dumps(e, sort_keys=True) for e in effects)


def _extra(observed, expected):
    """Observed effects not accounted for by expected (multiset difference)."""
    left = _canon(expected)
    extra = []
    for e in _canon(observed):
        if e in left:
            left.remove(e)
        else:
            extra.append(e)
    return extra


def run_case(case, defaults, adapter_cls):
    fixtures = copy.deepcopy(case.get("fixtures", defaults))
    tools = ControlledTools(fixtures, case.get("faults"))
    clock = Clock(case.get("clock", 0))
    supports = set(getattr(adapter_cls, "supports", ADAPTER_OPS))
    checks, refs, not_executed = [], {}, []
    stopped = None

    try:
        adapter = adapter_cls(Env(tools.as_dict(), clock))
        adapter.load_fixtures(copy.deepcopy(fixtures))
    except Exception:
        why = "adapter setup raised:\n" + traceback.format_exc(limit=3)
        setup = [{"step": "setup", "op": "load_fixtures", "result": "FAIL", "observed": {"effects": tools.ledger},
                  "reason": "setup touched tools; " + why}] if tools.ledger else []
        return _case_result(case, setup, [i for i in range(len(case["steps"]))], why, tools)
    if tools.ledger:  # setup must never touch tools
        checks.append({"step": "setup", "op": "load_fixtures", "result": "FAIL",
                       "observed": {"effects": list(tools.ledger)}, "reason": "setup touched tools"})

    for i, step in enumerate(case["steps"]):
        if stopped:
            not_executed.append(i)
            continue
        op = step["op"]
        if op not in HARNESS_OPS and op not in supports:
            stopped = "adapter does not support op %r" % op
            not_executed.append(i)
            continue
        before = len(tools.ledger)
        out = None
        try:
            if op == "advance_clock":
                clock.t += step["seconds"]
            elif op == "set_policy":
                adapter.set_policy(step["version"], step["requires_approval"])
            elif op == "delegate":
                refs[step["save_as"]] = adapter.delegate(
                    step["delegator"], step["agent"], step["scope"], step.get("expires_at"))
            elif op == "revoke":
                adapter.revoke(_resolve(step["ref"], refs))
            elif op == "approve":
                refs[step["save_as"]] = adapter.approve(step["approver"], _resolve(step["request"], refs))
            elif op == "call":
                out = adapter.handle(_resolve(step["call"], refs))
                if step.get("save_pending_as") and isinstance(out, dict):
                    refs[step["save_pending_as"]] = out.get("pending_id")
            elif op == "resume":
                out = adapter.resume(_resolve(step["pending"], refs), step["approver"], step["decision"],
                                     step.get("edited_args"))
        except Exception:
            stopped = "step %d (%s) raised:\n%s" % (i, op, traceback.format_exc(limit=3))
            new_effects = tools.ledger[before:]
            exp = step.get("expect") or {}
            # An exception does not excuse an unexpected side effect that already happened.
            # A missing expected effect plus a crash stays UNKNOWN.
            if "effects" in exp:
                extra = _extra(new_effects, exp["effects"])
            elif op == "call":  # at most the call's own effect is explainable
                c = _resolve(step["call"], refs)
                extra = _extra(new_effects, [{"tool": c.get("tool"), "tenant": c.get("tenant"), "args": c.get("args")}])
            elif op == "resume":
                extra = []  # the paused call's effect is unknown here; covered by expect_total_effects
            else:
                extra = new_effects  # setup steps must never touch tools
            if extra:
                res, why = "FAIL", "%d unexpected side effect(s) before exception" % len(extra)
            else:
                res, why = "UNKNOWN", ""
            checks.append({"step": i, "op": op, "result": res, "observed": {"effects": new_effects},
                           "reason": (why + "; " if why else "") + stopped})
            continue
        new_effects = tools.ledger[before:]
        exp = step.get("expect")
        if exp is None:
            continue
        check = {"step": i, "op": op, "expected": exp,
                 "observed": {"status": out.get("status") if isinstance(out, dict) else out,
                              "effects": new_effects},
                 "result": "PASS", "reason": ""}
        reasons = []
        if "status" in exp:
            st = out.get("status") if isinstance(out, dict) else None
            if not isinstance(st, str) or st not in STATUSES:
                check["result"] = "UNKNOWN"
                reasons.append("SUT returned no valid status (got %r); allowed: %s" % (out, sorted(STATUSES)))
            elif st not in exp["status"]:
                reasons.append("status %r not in expected %s" % (st, exp["status"]))
        if "effects" in exp and _canon(new_effects) != _canon(exp["effects"]):
            reasons.append("side effects differ: expected %d, observed %d" % (len(exp["effects"]), len(new_effects)))
        if reasons:
            if any(not r.startswith("SUT returned no valid status") for r in reasons):
                check["result"] = "FAIL"
            check["reason"] = "; ".join(reasons)
        checks.append(check)

    if "expect_total_effects" in case:
        total = case["expect_total_effects"]
        # After a stop the remaining steps never ran, so only exceeding the total is decidable.
        ok = len(tools.ledger) <= total if stopped else len(tools.ledger) == total
        checks.append({"step": "end", "op": "total_effects", "expected": total,
                       "observed": len(tools.ledger), "result": "PASS" if ok else "FAIL",
                       "reason": "" if ok else "total side effects %d != %d" % (len(tools.ledger), total)})
    return _case_result(case, checks, not_executed, stopped, tools)


def _case_result(case, checks, not_executed, stopped, tools):
    results = {c["result"] for c in checks}
    if "FAIL" in results:
        res = "FAIL"
    elif "UNKNOWN" in results or stopped or not_executed or not checks:
        res = "UNKNOWN"
    else:
        res = "PASS"
    return {"id": case["id"], "title": case["title"], "behavior": case.get("behavior"),
            "result": res, "checks": checks, "not_executed_steps": not_executed,
            "stopped_reason": stopped, "ledger": tools.ledger}


def validate_suite(suite):
    """Reject malformed expectations before executing any adapter code."""
    if not isinstance(suite, dict) or not isinstance(suite.get("fixtures"), dict) or not isinstance(suite.get("cases"), list):
        raise ValueError("suite must contain fixtures (object) and cases (array)")
    ids = set()
    for case in suite["cases"]:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"] or not isinstance(case.get("title"), str) or not isinstance(case.get("steps"), list):
            raise ValueError("each case needs a nonempty id, title and steps array")
        if case["id"] in ids:
            raise ValueError("duplicate case id: %s" % case["id"])
        ids.add(case["id"])
        if "expect_total_effects" in case and (type(case["expect_total_effects"]) is not int or case["expect_total_effects"] < 0):
            raise ValueError("expect_total_effects must be a nonnegative integer")
        for step in case["steps"]:
            if not isinstance(step, dict) or step.get("op") not in HARNESS_OPS | ADAPTER_OPS:
                raise ValueError("step has an unsupported or missing op")
            if "expect" not in step:
                continue
            exp = step["expect"]
            if not isinstance(exp, dict) or not exp or set(exp) - {"status", "effects"}:
                raise ValueError("expect must contain status and/or effects")
            if "status" in exp and (not isinstance(exp["status"], list) or not exp["status"] or any(not isinstance(v, str) or v not in STATUSES for v in exp["status"])):
                raise ValueError("expect.status must be a nonempty array of supported statuses")
            if "effects" in exp and (not isinstance(exp["effects"], list) or any(not isinstance(e, dict) for e in exp["effects"])):
                raise ValueError("expect.effects must be an array of objects")


def run(case_path, adapter_spec):
    with open(case_path, "rb") as f:
        raw = f.read()
    return run_suite(json.loads(raw), adapter_spec, case_path, hashlib.sha256(raw).hexdigest())


def run_suite(suite, adapter_spec, case_path="<inline>", case_hash=None):
    validate_suite(suite)
    adapter_path, _, _ = adapter_spec.rpartition(":")
    # Capture provenance before importing or executing the adapter.
    adapter_hash = sha256_file(adapter_path)
    harness_hash = sha256_file(__file__)
    if case_hash is None:
        case_hash = hashlib.sha256(json.dumps(suite, sort_keys=True, ensure_ascii=False,
                                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    adapter_cls, _ = load_adapter(adapter_spec)
    cases = [run_case(c, suite["fixtures"], adapter_cls) for c in suite["cases"]]
    summary = {k: sum(1 for c in cases if c["result"] == k) for k in ("PASS", "FAIL", "UNKNOWN")}
    return {
        "schema": "signwarden.report.v0",
        "signwarden_version": VERSION,
        "suite": suite.get("suite"),
        "case_file": case_path,
        "case_file_sha256": case_hash,
        "adapter": adapter_spec,
        "adapter_sha256": adapter_hash,
        "harness_sha256": harness_hash,
        "summary": summary,
        "scope_note": "PASS means this adapter version matched these cases only. It is not a security certification of a deployment.",
        "cases": cases,
    }
