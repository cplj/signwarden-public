# Case format (`signwarden.cases.v0`)

A suite is a JSON object with `fixtures`, `expectation_strategy` (the rules the expectations follow, in plain words) and `cases`.

Each case has `id`, `title`, `steps`, optional `faults` and `expect_total_effects`.

Steps:

| `op` | Fields |
|---|---|
| `delegate` | `delegator`, `agent`, `scope`, optional `expires_at`, `save_as` |
| `revoke` | `ref` (e.g. `"$d"`) |
| `approve` | `approver`, `request` (`tool`, `tenant`, `args`), `save_as` |
| `set_policy` | `version`, `requires_approval` |
| `advance_clock` | `seconds` |
| `call` | `call` (`actor`, `on_behalf_of`, `tool`, `tenant`, `args`, optional `approval_id`, `idempotency_key`, `context`), optional `save_pending_as` |
| `resume` | `pending`, `approver`, `decision` (`approve`/`reject`), optional `edited_args` |

Any step may carry `expect`: `status` (list of allowed statuses) and/or `effects` (the exact side effects this step must produce). `"$name"` refers to an id saved earlier.

Faults: `{"billing.refund": {"mode": "timeout_after_commit", "times": 1}}`. Modes are `error` and `timeout_after_commit`; anything else is a setup error.

[Input schema](schemas/suite.schema.json) · [Output schema](schemas/report.schema.json).

`expectation_strategy` documents the caller's policy; it is not inferred or enforced as policy by the harness. Empty `expect` objects are rejected; a case without assertions is UNKNOWN. Step-specific fields listed above are needed at execution time.
