# SignWarden 0.1.0

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![PyPI: pending release](https://img.shields.io/badge/PyPI-pending%20release-lightgrey.svg)](https://pypi.org/project/signwarden/)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/cplj/signwarden-public/badge)](https://scorecard.dev/viewer/?uri=github.com/cplj/signwarden-public)
[![CodeQL](https://github.com/cplj/signwarden-public/actions/workflows/codeql.yml/badge.svg)](https://github.com/cplj/signwarden-public/actions/workflows/codeql.yml)
[![CI](https://github.com/cplj/signwarden-public/actions/workflows/ci.yml/badge.svg)](https://github.com/cplj/signwarden-public/actions/workflows/ci.yml)

**Who is this for:** Developers checking explicit permission and action cases against a trusted local adapter.
**Not for:** Untrusted adapter execution or a deployment safety guarantee.

[Compare honestly](docs/comparison/) · [Contributing](CONTRIBUTING.md)

Run permission and action regression cases locally or in CI. The main command,
`signwarden report`, writes reproducible JSON and Markdown evidence with SHA-256
fingerprints. It uses the existing controlled-tool harness; `signwarden run`
remains available for terminal-only results. No runtime dependencies or model calls.

## For AI agents

SignWarden runs explicit permission and action regression cases against a trusted local adapter and emits PASS, FAIL or UNKNOWN evidence.

Install from the repository root (Python 3.10+): `python3 -m pip install .`

Minimal call from the same root:

```sh
signwarden report --cases cases/sample.json --adapter examples/reference_gateway.py:Adapter --out artifacts/report
```

Input: [suite schema](docs/schemas/suite.schema.json) and [case format](docs/case-format.md).
Output: [report/error schema](docs/schemas/report.schema.json) and [report format](docs/report-format.md).
The command prints a compact result and writes the full JSON and Markdown report.
Inspect the result and exit code; HTTP 200 alone does not mean PASS.
Only recorded controlled-tool effects are checked. Adapters execute trusted Python
code without a sandbox or execution deadline. Expected policy is supplied by the
caller. A PASS applies only to the defined cases and version; it is not a deployment
safety guarantee. A rerun executes the adapter again.

## Quick start

Requires Python 3.10+ and a local copy of this directory. From its root, copy:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install .
signwarden --help
signwarden report --cases cases/sample.json --adapter examples/reference_gateway.py:Adapter --out artifacts/report
python -I -m unittest discover -s tests -v
```

Installation is one command: `pip install .`. Pip may fetch the declared
`setuptools>=79` build dependency from the configured Python package index.
The 12 public synthetic sample cases return PASS with the reference adapter.
The command writes `artifacts/report.json` and `artifacts/report.md`, and prints:

```json
{"status":"PASS","summary":{"PASS":12,"FAIL":0,"UNKNOWN":0},"report_sha256":"<64 hex characters>","json":"artifacts/report.json","markdown":"artifacts/report.md"}
```

Exit codes: `0` PASS, `1` at least one FAIL, `2` UNKNOWN without FAIL (including
an empty suite), `3` setup/input/output ERROR. Use `signwarden report --help`.
An adapter crash, invalid status or unsupported operation is UNKNOWN unless
observed effects establish a failure. Input/setup errors emit JSON with
`status: "ERROR"` and an `error` object. FAIL takes precedence over UNKNOWN.
A tool's valid `unknown` response can satisfy an explicitly expected outcome;
it does not confirm whether the real action completed.

## Input and adapter

Input is a suite JSON object. For example, this minimal case asserts that advancing
the controlled clock produces no tool effects:

```json
{"suite":"clock-smoke","fixtures":{"users":[],"policy":{"version":"v1","requires_approval":[]}},"cases":[{"id":"clock","title":"Advance clock","steps":[{"op":"advance_clock","seconds":1,"expect":{"effects":[]}}]}]}
```

The full sample is `cases/sample.json`; the format is in
[docs/case-format.md](docs/case-format.md). Expected statuses and effects are
supplied by the caller. Empty `expect` objects and duplicate case IDs are rejected; a case with no assertions is UNKNOWN.

To connect your tool-call layer, implement the contract demonstrated in
`examples/reference_gateway.py`:

| Method or attribute | Purpose |
|---|---|
| `Adapter(env)` | Receive controlled `env.tools`, `env.clock`, `env.ToolTimeout`, `env.ToolError` |
| `load_fixtures(fx)` | Load isolated users, tenants, resources and policy |
| `set_policy(version, requires_approval)` | Change policy |
| `delegate(delegator, agent, scope, expires_at)` / `revoke(id)` | Delegation |
| `approve(approver, request)` | Bind approval to a call |
| `handle(call)` | Return a status object; include `pending_id` when paused |
| `resume(pending_id, approver, decision, edited_args)` | Resume a paused call |
| `supports` | Set of supported operations; unsupported operations yield UNKNOWN |

Statuses are `executed`, `denied`, `pending_approval`, `error`, `unknown`.
Use isolated adapters you trust: loading an adapter executes Python code.

## Local HTTP API

Start the server from the same directory, in the activated environment:

```sh
signwarden serve --adapter examples/reference_gateway.py:Adapter --port 8765
```

In another terminal, from the directory containing `cases/`:

```sh
curl --fail-with-body http://127.0.0.1:8765/report -H 'Content-Type: application/json' --data-binary @cases/sample.json
```

`POST /report` accepts the suite object directly and returns the same full JSON
report as the CLI. HTTP `200` includes `status: PASS`, `FAIL` or `UNKNOWN`;
clients must inspect the status. Malformed JSON, invalid input and setup errors
return HTTP `400` with `{"status":"ERROR","error":{"type":"...","message":"..."},"schema":"signwarden.error.v1"}`.
Unknown paths return `404`; GET returns `405`. Requests are limited to 1 MiB
with a 10-second socket read timeout. Stop with Ctrl-C.

The server binds only `127.0.0.1`. It uses a fixed operator-selected adapter,
rejects browser Origin headers and requires Host to be exactly `127.0.0.1:PORT`, has no accounts
or authentication, and is intended for trusted local clients. Do not expose or
proxy it to a network. It processes one request at a time; a hanging adapter
can block it. There is no adapter execution timeout or cancellation sandbox.
Each request/rerun executes adapter code; the service does not deduplicate calls.

## Local Docker image

From this directory, build the single CLI/API image and start its default API:

```sh
docker build -t signwarden:0.1.0 .
docker run -d --name signwarden-local --pull=never --network none signwarden:0.1.0
```

The container has no external network and publishes no host port. The API still
binds to `127.0.0.1:8765` inside the container. Call it using the bundled curl
inside that same container:

```sh
docker exec signwarden-local curl --fail-with-body http://127.0.0.1:8765/report -H 'Content-Type: application/json' --data-binary @/app/cases/sample.json
```

With the bundled sample, the expected JSON response is PASS with 12 passing
cases. CLI commands use the
same image; override the default `serve` arguments with `report` or `--help`:

```sh
docker run --pull=never --network none signwarden:0.1.0 report --cases cases/sample.json --adapter examples/reference_gateway.py:Adapter --out /reports/report
```

To check the already-installed image's quick start and tests without a network:

```sh
docker run --pull=never --network none --entrypoint sh signwarden:0.1.0 -c 'set -e; signwarden --help; signwarden report --cases cases/sample.json --adapter examples/reference_gateway.py:Adapter --out /reports/report; python -I -m unittest discover -s tests -v'
```

Report files remain in the container at `/reports/report.json` and
`/reports/report.md`. To retain CLI output, add `--name signwarden-report` to
the CLI `docker run` command and use
`docker cp signwarden-report:/reports/. ./docker-artifacts` afterward.
Stop the API with `docker stop signwarden-local`. Container names must be
unused; choose a new name if keeping an earlier container.

The image runs as UID/GID 65532 and contains only the public package, reference
adapter, sample, documentation and tests. The build context uses a file
allowlist; it excludes environment files, credentials, local reports and private
data. No secrets, host directories or Docker socket are mounted by these commands.
The application does not initiate external connections. The required
`--network none` runtime option enforces isolation; a Dockerfile alone cannot
force callers to use it. Do not add a published port or host networking.

Building is a separate bootstrap step: Docker may download the official
`python:3.12-slim` base image, Debian curl packages and the declared setuptools
build dependency. No registry upload, login, cloud deployment or paid service
is required. An entirely offline build requires these build inputs to be
available locally; this recipe does not bundle them. The base tag and package
indexes are not locked, so builds are not claimed to be bit-for-bit reproducible.

## Report integrity and rerunning

The JSON includes case results, expected/observed checks, side-effect ledgers,
not-executed steps, input snapshot (`input_suite`), Python runtime, version,
case-file hash, adapter hash, harness hash and package source hashes.
Markdown summarizes the same result and carries the report hash and rerun command.
For API input, `case_file` is `<inline>` and its hash is the canonical suite hash.
For CLI input, the case-file hash covers the original file bytes.

`report_sha256` hashes UTF-8 JSON with sorted keys, no extra whitespace,
`ensure_ascii=False`, `allow_nan=False`, omitting only `report_sha256` itself.
Verify a saved report independently:

```sh
python - <<'PY'
import hashlib, json
with open('artifacts/report.json', encoding='utf-8') as f:
    report = json.load(f)
expected = report.pop('report_sha256')
raw = json.dumps(report, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
assert hashlib.sha256(raw).hexdigest() == expected
print('Report hash verified')
with open('replay.json', 'w', encoding='utf-8') as f:
    json.dump(report['input_suite'], f, ensure_ascii=False)
PY
signwarden report --cases replay.json --adapter examples/reference_gateway.py:Adapter --out artifacts/replay
```

Keep the adapter, dependencies, Python runtime and inputs unchanged. Paths and
raw-file formatting affect report hashes; compare case outcomes and canonical
input hashes when replaying an extracted snapshot. Hashes detect changes;
they are not signatures, external timestamps or independent verification.
Transitive adapter dependencies and external state are not captured or locked.
The report does not install or restore an environment. Output prefixes overwrite
existing `.json` and `.md` files; partial files may remain after a write error.

## Tests and CI

`python -I -m unittest discover -s tests -v` checks normal outcomes, failures,
setup errors, UNKNOWN, replay hashes and API boundaries using only public
synthetic input. The release workflow tests the package before publication. The image workflow
builds on version tags. These workflows have not been executed on GitHub as part
of this local preparation.

## What it does not do

- It observes only effects recorded by injected controlled tools, not arbitrary
  database or HTTP side effects outside them.
- It is a regression harness for trusted code, not a sandbox, production
  authorization gateway, security certification or guarantee of deployment safety.
- It does not infer correct policy or prove that a customer's case coverage is complete.
- It makes no claim to outperform handwritten tests. It contains only the public
  12-case sample, with no private coverage corpus.
- It does not deploy services, manage accounts, call paid models or upload data.

See [comparison availability](docs/comparison/index.html). Comparison research is exploratory; no independently validated comparison is currently available for publication.

Apache-2.0. Adapter and verification enquiries: security@signwarden.com
