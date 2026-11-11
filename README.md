# AgentTrafficCop SDK

[![PyPI version](https://img.shields.io/pypi/v/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)
[![Python versions](https://img.shields.io/pypi/pyversions/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)
[![CI](https://github.com/belalshafeq/AgentTrafficCop-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/belalshafeq/AgentTrafficCop-sdk/actions/workflows/ci.yml)

The official Python SDK for **AgentTrafficCop** — a runtime circuit breaker for multi-agent systems.

Sits between communicating AI agents, validates every handoff against a strict schema, fingerprints the payload with SHA-256, and trips a circuit breaker before an infinite loop burns your budget.

> **Not** an LLM router, **not** an observability platform, **not** a prompt manager. One job: stop runaway agent loops before they burn your budget.

## What It Does

- **Schema shield** — every message validated against a strict Pydantic v2 contract.
- **Deterministic loop detection** — Canonical JSON serialization + SHA-256 hashing catches repeated payloads and A↔B ping-pong cycles.
- **Quiet Loop Detection (NEW)** — Hashes your `tools` schema independently. If an agent mutates its schema 3 times in a row, the breaker trips to save your LLM cache.
- **Rolling Spend Limits (NEW)** — Ingest token costs from your LLM router (e.g., CloudPulse, OpenRouter) via webhook. The server tracks a 60-second rolling window and trips the breaker if spend crosses your tier limit.
- **Circuit breaker** — step limits, consecutive-repeat limits, cycle limits.
- **Global Rate Limiting** — Redis-backed rate limits across all server instances.
- **Structured errors** — HTTP 422 with stable error codes and diagnostics.
- **Multiple Webhooks** — Fires alerts to Slack or Discord (1 for Free, 5 for Pro, Unlimited for Team).
- **Session Inspector** — Beautiful dashboard UI to view recently tripped loops.
- **LangGraph integration** — wrap any node in one line.
- **240+ automated tests** — the whole stack, verified in CI on every push.

## Quick Start

1) Claim a free API key at `agenttrafficcop.com`.
2) Install the SDK:
```bash
pip install agenttrafficcop
```
3) Initialize the Guard client and protect your agents:
```python
import asyncio
from agenttrafficcop import Guard, LoopDetected

async def main():
    async with Guard(url="https://api.agenttrafficcop.com", api_key="atc_live_...") as guard:
        try:
            result = await guard.check(
                session_id="run-42",
                sender="coder",
                recipient="reviewer",
                payload={"diff": "fix typo", "file": "app.py"},
                # Pass your tools schema to catch quiet loops (cache-breaking)
                schema={"tools": [{"name": "read_file"}]} 
            )
            print(f"Approved at step {result.step}")
        except LoopDetected as e:
            print(f"Loop caught: {e.error_code}")

if __name__ == "__main__":
    asyncio.run(main())
```


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
## REST API Usage

While the Python SDK is the easiest way to integrate, AgentTrafficCop is built as a language-agnostic REST API. You can call it from Node.js, Go, Ruby, or raw `curl`.

*(Set your API key as an environment variable first: `export ATC_KEY="atc_live_..."`)*

### Health check (no auth required)
```bash
curl https://api.agenttrafficcop.com/health
```
## Approve a message

```bash
curl -X POST https://api.agenttrafficcop.com/v1/route \
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
### Response (HTTP 200 OK):
```json
{
  "approved": true,
  "session_id": "run-42",
  "step": 1,
  "payload_hash": "3a7f...",
  "message": "Message approved and forwarded."
}
```
### Trip the breaker (Loop Detection)
If an agent gets stuck, it will keep sending the exact same payload. Send the same payload 3 more times in the same session:

```bash
for i in 1 2 3; do
  curl -s -X POST https://api.agenttrafficcop.com/v1/route \
    -H 'content-type: application/json' \
    -H "authorization: Bearer $ATC_KEY" \
    -d '{"session_id":"run-42","sender":"coder","recipient":"reviewer","intent":"handoff","payload":{"diff":"fix typo","file":"app.py"}}'
  echo
done
```
### Response on the 4th call (HTTP 422 Unprocessable Entity):

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

The SDK interacts with these core API endpoints:

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/v1/route` | Bearer | Evaluate and approve an inter-agent message |
| `POST` | `/v1/ingest/usage` | Bearer | Ingest rolling token spend from an external router |
| `GET` | `/health` | None | Liveness and uptime probe |
| `GET` | `/v1/usage` | Bearer | Return this key's tier and monthly usage |

> **Note:** The AgentTrafficCop server also exposes endpoints for user authentication, Polar billing, and admin session management (e.g., `/v1/sessions`, `/v1/admin/cleanup`, `/metrics`) to power the hosted dashboard. Those are not part of the SDK and are not meant to be called directly by your agents. You can view the full interactive API map at `https://api.agenttrafficcop.com/docs`.

## LangGraph Support

AgentTrafficCop ships with a first-class LangGraph adapter. Wrap any node in your graph and every handoff passes through the cop. It automatically handles both async and sync nodes.

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
## Synchronous Frameworks (CrewAI, AutoGen)
If you are using a synchronous framework like CrewAI or AutoGen, use the ```GuardSync``` client. It doesn't require ```async``` or ```await```.

```python
from agenttrafficcop import GuardSync, LoopDetected

guard = GuardSync(
    url="https://api.agenttrafficcop.com",
    api_key="your-api-key-here"
)

try:
    result = guard.check(
        session_id="task-1",
        sender="researcher",
        recipient="writer",
        payload={"topic": "AI safety"}
    )
    print("Approved at step", result.step)
except LoopDetected as e:
    print("Loop caught:", e.error_code)
finally:
    guard.close()
```
## Tiers & Usage

Every API key belongs to a user account, and every account is assigned a tier. The server tracks usage in real-time and enforces limits across all API keys belonging to the same account (so creating a new key won't reset your quota).

### Plan Limits
| Feature | Free ($0) | Pro ($49/mo) | Team ($199/mo) |
|---|---|---|---|
| **Monthly messages** | 10,000 | 250,000 | 2,000,000 |
| **Protected agents** | 5 | 25 | 100 |
| **Quiet Loop (Schema)** | ❌ | ✅ | ✅ |
| **Custom Spend Limits** | ❌ | ✅ | ✅ |
| **Custom Loop Thresholds** | ❌ | ❌ | ✅ |
| **Webhooks** | 1 | 5 | Unlimited |
| **Log retention** | 7 days | 30 days | 1 year |

### What counts toward the limit
Only **approved** messages count. Rejected messages do not increment the counter. Trips, schema failures, auth errors, and rate-limited requests are completely free and will not drain your monthly quota.

### Rate Limits
To ensure fair usage and protect the platform from abuse, API calls are rate-limited per minute based on your tier:
- **Free:** 60 requests / minute
- **Pro:** 120 requests / minute
- **Team:** 300 requests / minute

## Security Notes

- **Auth is fail-closed** — If no API keys are configured on the server, every `/v1/route` call is rejected with 401.
- **Constant-time key comparison** — Uses `secrets.compare_digest` to prevent timing attacks on API keys and cron secrets.
- **Strict rate limiting** — Global Redis-backed rate limits to share quotas across all replicas, with dedicated limiters for auth routes to prevent brute-forcing.
- **Billing HMAC verification** — Incoming webhooks from our payment processor (Polar) are cryptographically verified using HMAC-SHA256 signatures.
- **SSRF protection** — Outbound webhooks are validated at send-time against a deny-list of private IP ranges (loopback, RFC 1918, AWS metadata) and redirects are disabled.
- **Database integrity** — SQLite enforces strict Foreign Keys (`PRAGMA foreign_keys=ON`) and uses Write-Ahead Logging (WAL) with a 5-second `busy_timeout` to prevent data corruption and lock crashes.
- **GDPR compliant** — Deleting a user account cascades and permanently destroys all associated API keys, webhooks, and session logs.
- **No secrets in logs** — Only truncated SHA-256 fingerprints are logged for correlation, never raw keys or passwords.
- **Safe JSON parsing** — No `pickle`, `eval`, or `exec`. Payload hashing uses strict canonical JSON to prevent RCE or hash collisions.
- **Bounded memory** — Sessions, hash histories, rate-limit dictionaries, and webhook caches are strictly capped to prevent OOM attacks.
- **Payload limits** — HTTP body size is enforced on actual stream bytes (not just `Content-Length`), and deeply nested JSON is rejected.
- **Proxy trust is opt-in** — `X-Forwarded-For` headers are ignored for rate limiting unless `ATC_TRUST_PROXY=true` is explicitly set.

## Limitations (Honest list)

- **SQLite by default.** We use SQLite for zero-config setup and speed. It's fine for up to ~1,000 req/s single-process (thanks to WAL mode, `busy_timeout`, and auth caching), but multi-worker deployments require Postgres, which is on the roadmap.
- **Redis is required for multi-worker.** Without `ATC_REDIS_URL` set, sessions, usage counters, and rate limits are stored in local memory. This means they won't survive restarts, and they won't sync across multiple Uvicorn workers.
- **Exact-match loop detection.** Payloads are compared by exact SHA-256. Semantically equivalent but differently-worded loops (e.g., "fix bug" vs "resolve issue") are not caught. Embeddings are a future feature.
- **LangChain native callbacks.** We natively support LangGraph via `guarded_node()`. For standard LangChain, you must wrap your calls manually using `Guard` or `GuardSync`. A native `AgentTrafficCopCallback` handler is on the roadmap.
- **Dashboard UI for Custom Limits.** The backend enforces tier-based spend limits and custom loop thresholds. However, the frontend dashboard UI to let users configure their own limits is not live yet.
- **Webhook Cache Eviction.** When the webhook cache hits 10,000 entries, the oldest 10% are evicted. This prevents OOM, but means a few URLs will require a quick DB re-fetch.

## License
MIT.
