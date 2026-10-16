"""Reference tool-call gateway: the application-side layer that executes an agent's tool calls.

This is a stand-in for a customer's system under test, written to the adapter contract:
  load_fixtures, set_policy, delegate, revoke, approve, handle(call) -> {"status": ...}
It is not part of SignWarden's oracle.
"""
import json

RESOURCE_ARG = {"billing.refund": ("account", "account"), "docs.read": ("doc", "doc")}


def _canon(args):
    return json.dumps(args, sort_keys=True)


class Adapter:
    supports = {"set_policy", "delegate", "revoke", "approve", "call", "resume"}

    def __init__(self, env):
        self.env = env
        self.users, self.resources = {}, {}
        self.delegations, self.approvals, self.pending = {}, {}, {}
        self.policy_version, self.requires_approval = None, set()
        self.policy_rev = 0  # bumps on every set_policy, so v1 -> v2 -> v1 still counts as a change
        self._n = 0

    # --- setup -----------------------------------------------------------
    def load_fixtures(self, fx):
        self.users = {u["id"]: u for u in fx["users"]}
        for a in fx.get("accounts", []):
            self.resources[("account", a["id"])] = a["tenant"]
        for d in fx.get("docs", []):
            self.resources[("doc", d["id"])] = d["tenant"]
        self.set_policy(fx["policy"]["version"], fx["policy"]["requires_approval"])

    def set_policy(self, version, requires_approval):
        self.policy_version, self.requires_approval = version, set(requires_approval)
        self.policy_rev += 1

    def _id(self, prefix):
        self._n += 1
        return "%s%d" % (prefix, self._n)

    def delegate(self, delegator, agent, scope, expires_at=None):
        did = self._id("dlg")
        self.delegations[did] = {"delegator": delegator, "agent": agent, "scope": set(scope),
                                 "expires_at": expires_at, "revoked": False}
        return did

    def revoke(self, did):
        self.delegations[did]["revoked"] = True

    def approve(self, approver, request):
        aid = self._id("apr")
        self.approvals[aid] = {"approver": approver, "tool": request["tool"], "tenant": request["tenant"],
                               "args": _canon(request["args"]), "policy_version": self.policy_version,
                               "bound_key": None, "done": False}
        return aid

    # --- checks (split so each can be tested on its own) ------------------
    def _delegation_valid(self, d, call):
        if d["revoked"]:
            return False
        if d["expires_at"] is not None and self.env.clock.now() >= d["expires_at"]:
            return False
        return call["tool"] in d["scope"]

    def _principal(self, call):
        obo = call.get("on_behalf_of")
        if not obo:
            return call["actor"]
        for d in self.delegations.values():
            if d["delegator"] == obo and d["agent"] == call["actor"] and self._delegation_valid(d, call):
                return obo
        return None

    def _permitted(self, user_id, call):
        u = self.users.get(user_id)
        return bool(u) and call["tool"] in u["perms"]

    def _tenant_ok(self, user_id, call):
        kind, arg = RESOURCE_ARG[call["tool"]]
        res_tenant = self.resources.get((kind, call["args"].get(arg)))
        return self.users[user_id]["tenant"] == call["tenant"] and res_tenant == call["tenant"]

    def _approval_ok(self, user_id, call):
        a = self.approvals.get(call.get("approval_id"))
        if not a or a["done"]:
            return False
        if a["bound_key"] is not None and a["bound_key"] != call.get("idempotency_key"):
            return False
        return (a["approver"] == user_id and a["tool"] == call["tool"] and a["tenant"] == call["tenant"]
                and a["args"] == _canon(call["args"]) and a["policy_version"] == self.policy_version)

    def _forward_key(self, call):
        return call.get("idempotency_key")

    def _on_timeout(self):
        return {"status": "unknown", "reason": "tool timed out; side effect not confirmed"}

    def _on_error(self, e):
        return {"status": "error", "reason": str(e)}

    # --- entry point ------------------------------------------------------
    def _authorize(self, call):
        """Returns (user_id, None) when allowed, or (None, response) when not."""
        if call["tool"] not in RESOURCE_ARG:
            return None, {"status": "denied", "reason": "unknown tool"}
        user_id = self._principal(call)
        if user_id is None:
            return None, {"status": "denied", "reason": "no valid delegation"}
        if not self._permitted(user_id, call):
            return None, {"status": "denied", "reason": "principal lacks permission"}
        if not self._tenant_ok(user_id, call):
            return None, {"status": "denied", "reason": "tenant mismatch"}
        return user_id, None

    def _execute(self, call, approval):
        try:
            out = self.env.tools[call["tool"]](tenant=call["tenant"], idempotency_key=self._forward_key(call),
                                               **call["args"])
        except self.env.ToolTimeout:
            if approval is not None and call.get("idempotency_key") is None:
                approval["done"] = True  # cannot retry safely without a key
            return self._on_timeout()
        except self.env.ToolError as e:
            return self._on_error(e)
        if approval is not None:
            approval["done"] = True
        return {"status": "executed", "result": out}

    def handle(self, call):
        user_id, refusal = self._authorize(call)
        if refusal:
            return refusal
        approval = None
        if call["tool"] in self.requires_approval:
            if not self._approval_ok(user_id, call):
                pid = self._id("pnd")
                self.pending[pid] = {"call": dict(call), "user": user_id,
                                     "policy_rev": self.policy_rev, "done": False}
                return {"status": "pending_approval", "pending_id": pid, "reason": "no matching approval"}
            approval = self.approvals[call["approval_id"]]
            approval["bound_key"] = call.get("idempotency_key")
        return self._execute(call, approval)

    def resume(self, pending_id, approver, decision, edited_args=None):
        """Human answers a paused call. Everything is re-checked against the state at resume time."""
        p = self.pending.get(pending_id)
        if not p or p["done"]:
            return {"status": "denied", "reason": "no such pending call or already resumed"}
        p["done"] = True
        if decision != "approve":
            return {"status": "denied", "reason": "rejected by approver"}
        call = dict(p["call"], args=edited_args if edited_args is not None else p["call"]["args"])
        user_id, refusal = self._authorize(call)
        if refusal:
            return refusal
        if approver != user_id:
            return {"status": "denied", "reason": "approver is not the principal"}
        if self.policy_rev != p["policy_rev"]:
            return {"status": "pending_approval", "reason": "policy changed while paused; approve again"}
        return self._execute(call, None)
