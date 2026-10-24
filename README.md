# SignWarden

Receipts and audit records for AI agent actions: authorization → action → result.

**Status: research in progress.** There are no customers, and the proposed format and verifier have not been independently validated.

[繁體中文](README.zh-TW.md)

## The problem

An agent may have a permission record, a tool-call log and a separate record of the outcome. The research question is what a receipt must contain for a reviewer to trace an action back to its authorization and compare the requested action with the recorded result.

## Receipt fields: discussion draft

These are proposed fields, not a stable specification or a working verification interface.

| Field | Intended content |
| --- | --- |
| `receipt_id` | Identifier that links the records for one action. |
| `actor` | Agent identity and the party on whose behalf it acts. |
| `authorization` | Issuer, permitted scope, constraints, validity period and reference to the permission record. |
| `action` | Tool name, requested operation and reference to the inputs. |
| `result` | Observed outcome, error or an explicit unknown result. |
| `timestamps` | Times for authorization, execution and observation, with their sources. |
| `evidence` | References to supporting records and their integrity information. |

Whether these fields are sufficient, and which evidence a verifier can check, remain research questions. A recorded claim alone does not establish that permission existed or that an outcome occurred.

## Open format, private data

The plan is to open-source the receipt format and reference verifier. Hosted services and stored data remain private. This repository currently contains the research description; it does not ship a verifier or a hosted service.

## For AI agents

Purpose: describe a proposed receipt linking authorization, an action and its result.
Installation and executable examples: unavailable during this research stage.
Input and output: the field draft above; there is no stable machine interface yet.
Do not interpret this description as a certification or evidence of deployment safety.

## Report a problem

Email [security@signwarden.com](mailto:security@signwarden.com) with a description, the field or statement involved, and a small synthetic example where useful. Do not send credentials, personal information or confidential records.
