# Report format

[Machine-readable schema](schemas/report.schema.json). This describes the full
JSON written by `report` and returned by `POST /report`, not the CLI's compact
stdout object or the legacy `run` command.

`schema: signwarden.report.v1` contains `status`, `summary`, `cases`,
`input_suite`, runtime/version details, source fingerprints and a rerun command.
Each case contains checks, a controlled-tool ledger, unexecuted step indices and
a stopped reason. Checks contain expected/observed values when available.
Setup/exception checks can omit the expected field; no observation is invented.

Aggregate FAIL takes precedence over UNKNOWN; an empty suite is UNKNOWN.
PASS means the defined adapter version matched the supplied cases only.
An explicitly expected tool `unknown` response can satisfy an assertion without
establishing that an action completed. Cases without assertions are UNKNOWN.

CLI `report` exits 0 for PASS, 1 for FAIL, 2 for UNKNOWN and 3 for ERROR.
HTTP 200 includes PASS, FAIL or UNKNOWN. Invalid input/setup returns HTTP 400;
route, method, Origin and Host restrictions can return 404, 405 or 403.
Errors use `schema: signwarden.error.v1`, `status: ERROR` and an error object.

The report fingerprint hashes canonical sorted UTF-8 JSON without its own
`report_sha256` field. It is not a signature. It does not capture transitive
dependencies or restore external state. Replay requires the same trusted
adapter, dependencies, runtime and inputs and executes the adapter again.

The input schema checks documented structural shapes. Runtime validation also
rejects duplicate case IDs and unsupported faults, and resolves saved references.
It is not a complete validator for custom adapter semantics.
