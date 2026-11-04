# ContractGuard

Framework-independent governance and proof-carrying execution for agents.

**Status: working local reference MVP, not a production security boundary.** No LLM, blockchain, ZKP prover, payment provider, PostgreSQL server, or DuckDB installation is required. This repository demonstrates enforceable governance logic when operated by a trusted host. It does not sandbox agents or authenticate network requests.

## What works

- Immutable mandates with principal/agent identity, versioned authority, expiry and bounded delegation.
- Tool allowlists and atomic hierarchical credit reservations, including shared ancestor limits across concurrent workers.
- Durable request fingerprints, cached completed calls, and blocked retries for uncertain outcomes.
- Hash-linked evidence receipts with input/output commitments and policy/tool versions.
- Tickets, execution assignments, deterministic versioned validators, and acceptance/rejection receipts.
- Tested Deep Agents tool-call bridge and DeepSeek Harness Mandate/Ticket/Assignment normalization bridge.
- Fail-closed interfaces for future ZKP and payment providers.

## Quick start

Python 3.11+; standard library runtime and tests. From this repository:

```sh
python3 -m contractguard
python3 -m unittest discover -s tests -v
```

The demo creates a temporary database, runs a **simulated** episode tool, validates 9/10 successes, prints `ACCEPTED` and `receipt_chain_valid: true`, then deletes its temporary data. It performs no external work or payment.

For an installed command:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
contractguard-demo
```

Setuptools is a build dependency; installation may need internet access. Runtime does not.

## Use the core

```python
import time
from contractguard import Guard, Mandate, Tool

guard = Guard('local.db', [
    Tool('metrics.read', 'v1', 2, lambda args: {'count': 42})
])
guard.issue(Mandate(
    id='task-1', principal='tenant-a', agent='worker-a',
    tools=('metrics.read',), limit=10, expires=int(time.time()) + 300,
))
result = guard.execute('task-1', 'worker-a', 'metrics.read', {}, 'stable-call-1')
assert result == {'count': 42}
assert guard.verify_receipts()
```

`Guard` is an **operator API**. An agent must not receive it, database access, tool implementations, or provider credentials. Expose only a trusted identity-bound bridge. Identity strings are not authentication. Tool names are exact matches; argument-specific resource restrictions belong in the trusted tool implementation. Never register a general shell or arbitrary URL fetcher as an unrestricted tool.

Costs are integer **resource credits**, not USD. The trusted tool registry sets a fixed conservative charge. Every ancestor is charged atomically; child limits are caps, not exclusive allocations. A tool's true external resource use must be bounded by its provider implementation. Refunds, metered invoices and reconciliation APIs are deferred.

## Integration status

| Integration | Implemented | Remaining |
|---|---|---|
| Deep Agents | Identity-bound `call` bridge, tested with local fixtures | SDK middleware and full interception, SDK version pinning, live integration tests |
| DeepSeek Harness | Normalized mandate admission, ticket creation, assignment mapping | Native TypeScript transport, authenticated event consumption, atomic import/recovery |
| Deterministic proof | Exact artifact hash + versioned validator result | Independent validator service, signed portable attestations |
| ZKP | Statement protocol + unavailable backend | Circuit, prover, verification key management and adversarial proof tests |
| Payments / x402 | Protocol + explicitly disabled backend | Provider authorization, real ledger, idempotent settlement and reconciliation |
| Blockchain | Design boundary only | Escrow contracts, audits, chain replay protection and settlement integration |
| PostgreSQL | Migration design | Backend implementation and multi-process migration tests |
| DuckDB | Analytics design | Read-only receipt export and query adapter |

The bridge API does not claim automatic interception of built-in filesystem, shell, or delegated framework tools. The host must route **every protected operation** through the gateway and isolate credentials. Events, prompts and issue comments are context, never authority.

## Repository guide

| Path | Purpose |
|---|---|
| `contractguard/core.py` | Authority, storage transactions, gateway, lifecycle and receipts |
| `contractguard/adapters.py` | Explicit framework-neutral bridge implementations |
| `contractguard/validators.py` | Example deterministic acceptance rule |
| `contractguard/extensions.py` | Future proof and settlement contracts |
| `tests/test_guard.py` | Behavioral and adversarial tests |
| `docs/architecture.md` | Trust boundaries, data flow, failure semantics, database plan |
| `docs/PRD.md` | Scope, acceptance criteria, targets and milestones |
| `docs/threat-model.md` | Threats, controls, residual risk |
| `docs/development.md` | Development, integration and recovery instructions |
| `docs/adr/` | Architecture decisions and consequences |

## Safety and evidence limits

A hash chain detects edits relative to the stored chain. A database administrator can rewrite the entire chain or remove a suffix; externally anchored signed checkpoints are required to detect that. Receipts are not signatures or ZK proofs. Passing the example validator proves only that the supplied JSON satisfies a rule, not that a physical simulation ran or that a real-world task succeeded.

Revocation prevents new admissions and cached-result retrieval; it cannot stop an already admitted external operation. The initial MVP does not bind each tool call to an assignment lease: tool authority is mandate-bound, while assignment expiry gates submission. See the threat model before integration.

## Development and CI

Run the tests and demo above. GitHub Actions repeats them on Python 3.11–3.14, then installs the package and invokes the installed command from outside the source directory. CI is configured, not a claim that remote runs have passed. No cloud secrets are needed.

Before production: implement authenticated service boundaries, process isolation, provider-enforced resource limits, PostgreSQL durability/backup operations, external evidence checkpoints, scoped approvals and reconciliation. See the PRD release gates.

## References and attribution

Design references, not copied source or verified SDK compatibility:

- [DeepSeek Superagent prototype](https://github.com/deepseek-ai/dsh-superagent-prototype) — Mandate/Ticket/Assignment vocabulary; upstream explicitly labels itself research code.
- [LangChain Deep Agents documentation](https://docs.langchain.com/oss/python/deepagents/overview) — separate harness, tool and delegation ecosystem.

No upstream runtime is bundled. This is an independent project and is not affiliated with either framework maintainer.
