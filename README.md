# AgentTrafficCop SDK

[![PyPI version](https://img.shields.io/pypi/v/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)
[![Python versions](https://img.shields.io/pypi/pyversions/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)
[![CI](https://github.com/belalshafeq/AgentTrafficCop-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/belalshafeq/AgentTrafficCop-sdk/actions/workflows/ci.yml)

The official Python SDK for **AgentTrafficCop** — a runtime circuit breaker for multi-agent systems.

Sits between communicating AI agents, validates every handoff against a strict schema, fingerprints the payload with SHA-256, and trips a circuit breaker before an infinite loop burns your budget.

> **Not** an LLM router, **not** an observability platform, **not** a prompt manager. One job: stop runaway agent loops before they burn your budget.

## What It Does

- **Schema shield** — every message validated against a strict Pydantic v2 contract.
- **Smart loop detection** — Canonical JSON serialization + SHA-256 hashing catches repeated payloads and A↔B ping-pong cycles deterministically.
- **Circuit breaker** — step limits, consecutive-repeat limits, cycle limits.
- **Global Rate Limiting** — Redis-backed rate limits across all server instances.
- **Structured errors** — HTTP 422 with stable error codes and diagnostics.
- **Discord / Slack Webhooks** — Instantly alerts your team when a loop is halted.
- **Session Inspector** — Beautiful dashboard UI to view recently tripped loops.
- **LangGraph integration** — wrap any node in one line.
- **240+ automated tests** — the whole stack, verified in CI on every push.

## See It In Action

Two agents get stuck in a loop. Without AgentTrafficCop, nothing stops them. With it, the breaker trips in seconds.

Output:

```text
════════════════════════════════════════════════════════════════
RUN 1: WITHOUT AgentTrafficCop
════════════════════════════════════════════════════════════════
Two agents loop. Nothing stops them. Watch the cost.

  Coder     → Reviewer : {'diff': 'rename foo to bar in app.py', ...}
  Reviewer  → Coder    : {'feedback': 'please add a docstring', ...}
  Coder     → Reviewer : {'diff': 'add null check in handle()', ...}
  Reviewer  → Coder    : {'feedback': 'please handle the empty case', ...}
  ... [repeats for 12 rounds] ...

  No breaker. Loop ran 12 rounds (24 messages).
  Estimated cost: $0.10  (fake model, for illustration)

════════════════════════════════════════════════════════════════
RUN 2: WITH AgentTrafficCop
════════════════════════════════════════════════════════════════
Same agents. Every message goes through the cop at https://api.agenttrafficcop.com.

  Coder    → Reviewer : {...}  [APPROVED step=1]
  Reviewer → Coder    : {...}  [APPROVED step=2]
  Coder    → Reviewer : {...}  [APPROVED step=3]
  Reviewer → Coder    : {...}  [APPROVED step=4]
  Coder    → Reviewer : {...}  [APPROVED step=5]
  Reviewer → Coder    : {...}  [APPROVED step=6]
  Coder    → Reviewer : {...}  [APPROVED step=7]
  Reviewer → Coder    : {...}  [CYCLIC_PAYLOAD_LOOP]

  🛑 CIRCUIT BREAKER TRIPPED
  Error code: CYCLIC_PAYLOAD_LOOP
  Session:    demo-loop
    step: 8
    cycle_length: 2
    cycle_repeats: 3
    max_cycle_repeats: 3

  Session halted after 8 messages. Estimated cost: $0.03
  Saved vs Run 1: $0.07

Demo complete.
```
##  Quick Start

1) Claim a free API key at `agenttrafficcop.com`.
2) Install the SDK:
```bash
 pip install agenttrafficcop ```
```
3) Initialize the Guard client:
```python

from agenttrafficcop import Guard, LoopDetected

guard = Guard(
    url="https://api.agenttrafficcop.com",
    api_key="your-api-key-here"
)
```

## Health check (no auth)
```bash
curl http://localhost:8000/health
```

## Approve a message

```bash
curl -X POST http://localhost:8000/v1/route \
  -H 'content-type: application/json' \
  -H "authorization: Bearer $ATC_KEY" \
  -d '{
    "session_id": "run-42",
    "sender": "coder",
    "recipient": "reviewer",
    "intent": "handoff",
    "payload": {"diff": "fix typo", "file": "app.py"}
  }'
```
Response:

```json
{
  "approved": true,
  "session_id": "run-42",
  "step": 1,
  "payload_hash": "3a7f...",
  "message": "Message approved and forwarded."
}
```

## Trip the breaker

Send the same payload 3 more times in the same session:

```bash
for i in 1 2 3; do
  curl -s -X POST http://localhost:8000/v1/route \
    -H 'content-type: application/json' \
    -H "authorization: Bearer $ATC_KEY" \
    -d '{"session_id":"run-42","sender":"coder","recipient":"reviewer","intent":"handoff","payload":{"diff":"fix typo","file":"app.py"}}'
  echo
done
```

Fourth call returns HTTP 422:

```json
{
  "error": "REPEATED_PAYLOAD_LOOP",
  "message": "Session 'run-42' produced identical payload hash 3 times consecutively.",
  "session_id": "run-42",
  "diagnostics": {
    "step": 4,
    "repeated_hash": "3a7f...",
    "consecutive_repeats": 3,
    "max_repeated_hashes": 3
  }
}
```

## Endpoints


| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/v1/route` | Bearer | Evaluate and approve an inter-agent message |
| `GET` | `/health` | None | Liveness and uptime probe |
| `GET` | `/v1/usage` | Bearer | Return this key's tier and monthly usage |
| `GET` | `/v1/auth/session-logs` | Bearer | Fetch recent session activity (Dashboard) |
| `GET` | `/v1/sessions` | Admin | List active sessions |
| `GET` | `/v1/sessions/{id}` | Admin | Inspect one session |
| `DELETE` | `/v1/sessions/{id}` | Admin | Reset one session |
| `POST` | `/v1/admin/cleanup` | Admin | Expire idle sessions in bulk |
| `GET` | `/metrics` | Bearer | Prometheus metrics endpoint |

Admin endpoints require a key listed in `ATC_ADMIN_API_KEYS`. If that
variable is empty, admin access falls back to the `team` tier.

## LangGraph Support

AgentTrafficCop ships with a first-class
LangGraph adapter. Wrap any
node in your graph and every handoff passes through the cop:

```python
from agenttrafficcop import Guard
from agenttrafficcop.langgraph import guarded_node

guard = Guard(url="http://localhost:8000", api_key="your-key")

graph.add_node(
    "reviewer",
    guarded_node(
        reviewer_fn,
        guard=guard,
        sender="coder",
        recipient="reviewer",
        session_id=lambda s: s["run_id"],
        payload=lambda s: {"draft": s["draft"]},
    ),
)
```
## Tiers & Usage

Every API key is assigned a tier, and every tier has a monthly message
limit. The server counts messages per key and rejects further requests
once a key exceeds its limit.

### Default tiers
| Tier | Monthly message limit | Agent limit |
|---|---|---|
| `free` | 10,000 | 5 |
| `pro` | 250,000 | 25 |
| `team` | 2,000,000 | 100 |

### What counts toward the limit

Only approved messages count. Rejected messages do not increment
the counter (trips, schema failures, auth errors, and rate limits are free).

## Security Notes

- **Auth is fail-closed** — if no API keys are configured, every `/v1/route` call is rejected with 401.
- **Constant-time key comparison** — prevents timing attacks.
- **Auth endpoints are rate-limited** — 10 requests/minute per IP.
- **Global rate limiting** — Redis-backed to share quotas across all replicas.
- **No secrets in logs** — only truncated SHA-256 fingerprints for correlation.
- **Canonical JSON** — hashes are deterministic regardless of key order.
- **No `pickle` / `eval` / `exec`** — hashing uses canonical JSON.
- **Bounded memory** — sessions and hash histories are capped.
- **Body size limit** — enforced on actual bytes, not just `Content-Length`.
- **Proxy trust is opt-in** — `X-Forwarded-For` ignored unless `ATC_TRUST_PROXY=true`.

## Limitations (Honest list)

- **In-memory backend is single-process.** Without Redis, sessions and usage counters do not survive restarts.
- **Exact-match loop detection.** Payloads are compared by exact SHA-256. Semantically equivalent but differently-worded loops (e.g., "fix bug" vs "resolve issue") are not caught. Embeddings are a future feature.
- **No multi-tenancy.** One API key list per deployment; sessions are global. Workspaces are a future feature.
- **SQLite by default.** Fine for up to ~1,000 req/s single-process (thanks to auth caching). Postgres support is on the roadmap for multi-worker deployments.

## License
MIT.
