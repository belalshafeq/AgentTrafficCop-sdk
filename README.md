# AgentTrafficCop SDK

[![PyPI version](https://img.shields.io/pypi/v/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)
[![Python versions](https://img.shields.io/pypi/pyversions/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)
[![CI](https://github.com/belalshafeq/AgentTrafficCop-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/belalshafeq/AgentTrafficCop-sdk/actions/workflows/ci.yml)

The official Python SDK for **[AgentTrafficCop](https://agenttrafficcop.com)** — a runtime circuit breaker for multi-agent workflows.

Check agent handoffs and protected actions before they execute. AgentTrafficCop validates the message, fingerprints its payload, and rejects actions that violate loop, step, usage, or configured spending policies.

> **Your integration must stop on rejection.** AgentTrafficCop does not automatically intercept every LLM call, forward messages, execute tools, or cancel actions already in progress.

## What It Does

- **Schema shield** — validates handoff fields against a strict server-side Pydantic contract.
- **Repeated-payload detection** — uses canonical JSON and SHA-256 to detect consecutive identical payloads.
- **Cycle detection** — detects repeating payload sequences within configured cycle bounds.
- **Step limits** — rejects further actions after a session reaches its configured limit.
- **Schema-change detection — Pro/Team** — flags three consecutive different submitted tool-schema hashes.
- **Rolling spend protection** — evaluates reported costs over a 60-second window.
- **Per-run budgets — Pro/Team** — rejects subsequent protected actions when reported cumulative run spending reaches its budget.
- **Incident timelines** — inspect recorded decisions, hashes, and rule diagnostics without storing raw payloads in the timeline.
- **Webhook alerts** — configure Slack or Discord destinations for circuit-breaker notifications.
- **Sync and async clients** — use `GuardSync` or `Guard`.
- **LangGraph integration** — protect selected nodes with `guarded_node`.
- **Legacy AutoGen integration** — protect the reply pipeline of supported `pyautogen==0.2.35` agents.

Detection is deterministic, not semantic. Differently worded messages with similar meaning are not treated as identical payloads.

## Installation

Python **3.11+** is required.

### Published SDK

```bash
pip install agenttrafficcop
```

### SDK Source Version 1.1.0

The per-run budget helper and legacy AutoGen adapter were added in SDK source version **1.1.0**. That version has not yet been published to PyPI.

Until publication, install the merged source:

```bash
pip install 'agenttrafficcop @ git+https://github.com/belalshafeq/AgentTrafficCop.git@8674b4fb96b0fb9aa76e6a08e3995c6dcfbba9b2#subdirectory=sdk'
```

For the legacy AutoGen adapter:

```bash
pip install 'agenttrafficcop[autogen] @ git+https://github.com/belalshafeq/AgentTrafficCop.git@8674b4fb96b0fb9aa76e6a08e3995c6dcfbba9b2#subdirectory=sdk'
```

These commands require Git and are pinned to the feature merge commit for reproducibility.

## Quick Start

1. Create an account and verify your email at [agenttrafficcop.com/dashboard](https://agenttrafficcop.com/dashboard).
2. Obtain your API key.
3. Set it in your environment:

```bash
export ATC_API_KEY="your-api-key"
```

4. Check each protected action **before** executing it:

```python
import asyncio
import os
import uuid

from agenttrafficcop import Guard, AgentTrafficCopError


async def main():
    run_id = uuid.uuid4().hex

    async with Guard(
        url="https://api.agenttrafficcop.com",
        api_key=os.environ["ATC_API_KEY"],
        dry_run=False,
    ) as guard:
        try:
            result = await guard.check(
                session_id=run_id,
                sender="coder",
                recipient="reviewer",
                intent="handoff",
                payload={"diff": "fix typo", "file": "app.py"},
            )
        except AgentTrafficCopError as exc:
            print(f"Check failed: {exc.error_code}")
            return  # Do not execute the protected action.

        if not result.approved:
            return

        # Execute the actual handoff, tool, or LLM action here.
        print(f"Approved at step {result.step}")


if __name__ == "__main__":
    asyncio.run(main())
```

Use one stable `session_id` throughout a run and a new ID for each independent run.

Choose a payload that meaningfully represents the action. Adding a changing timestamp or random ID to every payload can prevent exact-repeat detection.

> **Dry-run mode is not enforcement.** It suppresses certain rejection errors so execution can continue. Keep it disabled when you need blocking behavior.

## Synchronous Usage

Use `GuardSync` in synchronous Python workflows:

```python
import os
import uuid

from agenttrafficcop import GuardSync, AgentTrafficCopError


with GuardSync(
    url="https://api.agenttrafficcop.com",
    api_key=os.environ["ATC_API_KEY"],
    dry_run=False,
) as guard:
    try:
        result = guard.check(
            session_id=uuid.uuid4().hex,
            sender="researcher",
            recipient="writer",
            payload={"topic": "AI safety"},
        )
    except AgentTrafficCopError as exc:
        print("Check failed:", exc.error_code)
    else:
        if result.approved:
            # Execute the protected action here.
            print("Approved at step", result.step)
```

Using `GuardSync` alone does not automatically hook into a framework. Call it at the appropriate execution boundary or use a supported adapter.

## How Loop Detection Works

### Repeated Payloads

Payloads are serialized deterministically and hashed with SHA-256.

With the default consecutive-repeat threshold of **3**:

1. First identical payload: approved.
2. Second identical payload: approved.
3. Third identical consecutive attempt: rejected.

### Repeating Cycles

The server checks for repeating payload sequences within its configured maximum cycle length.

The default maximum cycle length is **2**, supporting patterns such as:

```text
payload A → payload B → payload A → payload B → …
```

This compares payload sequences, not simply whether two agents exchange messages. Longer cycles require appropriate server configuration.

### Step Limits

The default maximum is **25 approved steps per session**. Further attempts are rejected by the step-limit policy.

### Schema-Change Detection — Pro/Team

Pass your tool schema when checking an action:

```python
result = await guard.check(
    session_id=run_id,
    sender="coder",
    recipient="reviewer",
    payload={"task": "review patch"},
    schema={"tools": [{"name": "read_file"}]},
)
```

The SDK hashes the schema independently. On Pro and Team, three consecutive different submitted schema hashes trigger the schema-mutation rule.

This is a **heuristic for repeated schema changes**. It does not prove a semantic loop, measure cache misses, or guarantee cache savings.

## Spending Protection

AgentTrafficCop provides two separate controls:

| Control | Scope | Behavior |
|---|---|---|
| Rolling spend threshold | API key | Evaluates reported spending over a 60-second window |
| Per-run budget | API key + session ID | Evaluates cumulative reported spending for that run |

### Rolling Spend Thresholds

Default server thresholds are:

| Free | Pro | Team |
|---:|---:|---:|
| $0.50 / 60 seconds | $5 / 60 seconds | $50 / 60 seconds |

Production configuration can override these defaults. Pro and Team users can configure custom spend thresholds.

### Per-Run Budgets — Pro/Team

Requires SDK source version **1.1.0** or a published release containing this feature.

Set a budget before starting the run:

```python
import os
import uuid

from agenttrafficcop import GuardSync


run_id = uuid.uuid4().hex

with GuardSync(
    "https://api.agenttrafficcop.com",
    os.environ["ATC_API_KEY"],
) as guard:
    budget = guard.set_run_budget(
        session_id=run_id,
        budget_usd="2.00",
    )

    print(budget)

    # Use run_id in every protected check
    # and in your trusted router's cost reports.
```

The async client supports:

```python
budget = await guard.set_run_budget(
    session_id=run_id,
    budget_usd="2.00",
)
```

Once reported cumulative spending reaches the budget, subsequent route checks return:

```text
HTTP 402
RUN_BUDGET_EXCEEDED
```

Updating a budget preserves accumulated spending. Raising the budget above reported spending can permit further checks, provided no other policy blocks them.

Run budgets do not reset monthly. Use a new session ID for a new run.

### Cost Reporting Is Required

**Setting a budget does not automatically connect provider billing.**

A trusted backend or router must report incremental costs through:

```text
POST /v1/ingest/usage
```

Example body:

```json
{
  "api_key": "YOUR_ATC_KEY",
  "event_id": "provider-request-123",
  "cost": "0.30",
  "session_id": "task-123"
}
```

Requirements:

- Send each action's **incremental cost**, not a running total.
- Use stable, unique event IDs for retries and deduplication.
- Use the same session ID as the protected route checks.
- Sign the exact body using the configured ingestion secret.
- Do not report the same spending through multiple ingestion sources.

The endpoint requires:

```text
X-ATC-Timestamp
X-ATC-Signature
```

The signature is the hexadecimal SHA-256 HMAC of:

```text
timestamp + "." + exact_request_body
```

Keep `ATC_INGEST_WEBHOOK_SECRET` on the trusted reporting backend. **Never expose it in browser code.** A bearer token alone does not authenticate this endpoint.

The server also implements a CloudPulse webhook handler with explicit external-key mapping. CloudPulse key-level window reports do not currently attribute spending to individual runs.

Other routers require an integration that produces the supported reports.

### Spending Limitations

These controls are **not provider-side hard caps**:

- Missing reports mean spending is not known to AgentTrafficCop.
- Delayed reports, parallel actions, and in-flight calls can cause overshoot.
- Completed spending cannot be reversed.
- Actions that bypass AgentTrafficCop are not blocked.
- A run without a configured budget does not inherit another run's budget.
- Run budgets are key-scoped; another key does not share the same run budget.

## Incident Timeline

In the hosted dashboard:

**Overview → Recent Sessions → Inspect run**

Inspect recorded checks including:

- Approved or rejected outcome.
- Step number, when available.
- Sender and recipient.
- Triggered rule.
- Payload hash.
- Rule explanation and bounded diagnostics.

Pro and Team users can set or update the selected run's budget from the inspector.

### Privacy and Retention

The timeline does **not** store raw payloads or request metadata. It stores identifiers, timestamps, hashes, and diagnostics.

Hashes reveal equality and are not anonymization. Keep secrets out of agent names and session IDs.

Evidence is bounded to:

- The latest **200 recorded checks per run**.
- Up to **10,000 recorded checks per API key**.
- The applicable plan's time-based retention.

Older sessions are not backfilled.

This is not a complete execution trace. Malformed requests, authentication failures, rate-limited requests, and actions outside AgentTrafficCop are not all represented.

Timeline storage does not restore the active loop detector's in-memory history after a restart.

## LangGraph Integration

Wrap selected nodes with `guarded_node`:

```python
import os

from langgraph.graph import StateGraph, START, END
from agenttrafficcop import Guard
from agenttrafficcop.langgraph import guarded_node


async def reviewer_fn(state):
    return {"draft": state["draft"]}


async def run_workflow(initial_state):
    async with Guard(
        url="https://api.agenttrafficcop.com",
        api_key=os.environ["ATC_API_KEY"],
        dry_run=False,
    ) as guard:
        graph = StateGraph(dict)

        graph.add_node(
            "reviewer",
            guarded_node(
                reviewer_fn,
                guard=guard,
                sender="coder",
                recipient="reviewer",
                session_id=lambda state: state["run_id"],
                payload=lambda state: {"draft": state["draft"]},
                raise_on_trip=True,
            ),
        )

        graph.add_edge(START, "reviewer")
        graph.add_edge("reviewer", END)

        app = graph.compile()
        return await app.ainvoke(initial_state)
```

Install a compatible LangGraph version separately or use the SDK's `langgraph` extra.

The wrapper supports synchronous and asynchronous node functions.

Provide a stable, run-specific session ID and a meaningful payload extractor. Only wrapped nodes are protected. Preserve exception propagation so a rejected check prevents the wrapped node from executing.

## Legacy AutoGen Integration

Requires SDK source version **1.1.0** and its `autogen` extra.

**Supported framework: `pyautogen==0.2.35` only.**

This adapter does not support AutoGen 0.4+, modern AgentChat, AG2, or arbitrary versions of similarly named packages.

```python
import os
import uuid

from autogen import ConversableAgent
from agenttrafficcop import GuardSync, AgentTrafficCopError
from agenttrafficcop.autogen import GuardedConversableAgent


with GuardSync(
    "https://api.agenttrafficcop.com",
    os.environ["ATC_API_KEY"],
) as guard:
    worker = GuardedConversableAgent(
        "worker",
        atc_guard=guard,
        atc_session_id=uuid.uuid4().hex,
        llm_config=False,
        human_input_mode="NEVER",
        code_execution_config=False,
        default_auto_reply="Acknowledged.",
    )

    caller = ConversableAgent(
        "caller",
        llm_config=False,
        human_input_mode="NEVER",
        code_execution_config=False,
    )

    try:
        reply = worker.generate_reply(
            messages=[
                {"role": "user", "content": "Review this task"}
            ],
            sender=caller,
        )
        print(reply)
    except AgentTrafficCopError as exc:
        print("Check failed:", exc.error_code)
        # Stop the enclosing workflow; do not retry indefinitely.
```

The adapter checks before running the agent's reply pipeline, including registered tool/code reply handlers.

It supports both:

```python
worker.generate_reply(...)
await worker.a_generate_reply(...)
```

The asynchronous path offloads the synchronous AgentTrafficCop check to a thread. Keep the `GuardSync` client open for the agent's lifetime.

### AutoGen Boundaries

- Protect every agent that executes relevant actions.
- Direct tool calls, direct sends, and execution outside the guarded reply methods are not intercepted.
- One reply may execute a batch of tools; the adapter performs one pre-reply check, not a reservation for each tool.
- Rejections propagate as exceptions. A `TERMINATE` string is not treated as a universal cancellation mechanism.
- The adapter does not automatically report LLM spending or provide a code-execution sandbox.
- Dry-run guards are rejected by this adapter.

## REST API Usage

Use the HTTP API from any language.

```bash
export ATC_API_KEY="your-api-key"
```

### Health Check

```bash
curl https://api.agenttrafficcop.com/health
```

### Evaluate an Action

```bash
curl -X POST https://api.agenttrafficcop.com/v1/route \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $ATC_API_KEY" \
  -d '{
    "session_id": "example-run",
    "sender": "coder",
    "recipient": "reviewer",
    "intent": "handoff",
    "payload": {
      "diff": "fix typo",
      "file": "app.py"
    }
  }'
```

A successful response includes:

```json
{
  "approved": true,
  "session_id": "example-run",
  "step": 1,
  "payload_hash": "..."
}
```

**Approval does not execute or forward the action.** Your application performs it after receiving approval.

### Try Repeated-Payload Detection

Use a fresh session ID, then submit three identical consecutive attempts:

```bash
RUN_ID="repeat-test-$(python -c 'import uuid; print(uuid.uuid4().hex)')"

for i in 1 2 3; do
  curl -sS -X POST https://api.agenttrafficcop.com/v1/route \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $ATC_API_KEY" \
    -d "{
      \"session_id\": \"$RUN_ID\",
      \"sender\": \"coder\",
      \"recipient\": \"reviewer\",
      \"intent\": \"handoff\",
      \"payload\": {\"action\": \"same-action\"}
    }"
  echo
done
```

With default settings and no other blocking policy, the first two are approved. The third returns HTTP 422 with:

```text
REPEATED_PAYLOAD_LOOP
```

### Core Endpoints

| Method | Path | Authentication | Purpose |
|---|---|---|---|
| `POST` | `/v1/route` | Bearer API key | Evaluate a protected action |
| `GET` | `/v1/usage` | Bearer API key | Return usage and tier information |
| `PUT` | `/v1/runs/{session_id}/budget` | Bearer API key; Pro/Team | Set or update a run budget |
| `GET` | `/v1/runs/{session_id}/budget` | Bearer API key | Read the run's budget and reported spending |
| `GET` | `/v1/runs/{session_id}/timeline` | Bearer API key | Read recorded run evidence |
| `POST` | `/v1/ingest/usage` | Timestamped HMAC; ATC key in body | Report incremental costs |
| `GET` | `/health` | None | Check service health |

Timeline requests support `after` and `limit` pagination parameters. Use the response's `next_after` value for the next page.

The hosted service also exposes account, billing, and administrative endpoints. Agent API keys are not automatically administrator credentials.

## Errors and Enforcement

Errors include stable codes where supported:

| Code | Meaning |
|---|---|
| `REPEATED_PAYLOAD_LOOP` | Consecutive identical payload threshold reached |
| `CYCLIC_PAYLOAD_LOOP` | Repeating payload cycle threshold reached |
| `STEP_LIMIT_EXCEEDED` | Session step limit reached |
| `SCHEMA_MUTATION_LOOP` | Schema-change heuristic triggered |
| `RUN_BUDGET_EXCEEDED` | Reported cumulative run budget reached |
| `SPEND_LIMIT_EXCEEDED` | Rolling spend block active |
| `TOKEN_LIMIT_EXCEEDED` | Cost integration reported a token-limit violation |
| `TIER_LIMIT_EXCEEDED` | Monthly message allowance reached |
| `AGENT_LIMIT_EXCEEDED` | Tracked-agent allowance reached |

Not every rejection uses HTTP 422. Depending on the policy, responses can include HTTP **401, 402, 403, 422, or 429**.

Catch `AgentTrafficCopError` when the workflow should stop on any SDK check failure, rather than catching only loop errors.

## Tiers & Usage

Listed hosted plans:

| Feature | Free — $0 | Pro — $49/month | Team — $199/month |
|---|---:|---:|---:|
| Monthly approved messages | 10,000 | 250,000 | 2,000,000 |
| Tracked agents | 5 | 25 | 100 |
| Tier rate limit | 60/min | 120/min | 300/min |
| Active API keys | 2 | 5 | Effectively unlimited |
| Repeated-payload detection | Yes | Yes | Yes |
| Cycle and step-limit protection | Yes | Yes | Yes |
| Schema-change detection | — | Yes | Yes |
| Custom rolling spend threshold | — | Yes | Yes |
| Per-run budgets | — | Yes | Yes |
| Custom maximum-step threshold | — | — | Yes |
| Incident timeline | Yes | Yes | Yes |
| Webhook destinations | 1 | 5 | Effectively unlimited |
| Listed log-retention period | 7 days | 30 days | 1 year |

“Effectively unlimited” uses a high implementation cap rather than literal infinity. Production settings may override default limits.

### Usage Accounting

For account-issued keys, monthly message usage and tracked-agent membership are shared across the account's keys. Creating another key does not provide a fresh account quota.

Only approved route checks increment the monthly message counter. Rejected checks do not consume the monthly approved-message allowance, but remain subject to relevant rate limits.

Per-run budgets and incident timelines are **API key + session scoped**, unlike account-wide monthly usage.

### Retention

Incident evidence has both time-based and count-based bounds described above.

Session-log pruning is implemented through an administrative operation. Operating a self-hosted server requires scheduling that operation. A retention policy is not a guarantee of an unlimited archive.

## Storage and Deployment

### Monthly Usage

Without Redis, monthly message counters and tracked-agent membership use SQLite.

They survive application restarts **when the SQLite database is on persistent storage**. Container-local ephemeral storage does not provide that guarantee.

### Loop History

Without Redis, active loop-detection history is process-local and is lost on restart. Separate workers do not share that in-memory history.

Redis support is available for shared session state.

### Rate Limits

Rate limiting can use Redis when configured. The implementation can fall back to process-local limiting during Redis failures, so do not assume a globally enforced limit in that condition.

### Run Records

Per-run budgets, cumulative cost totals, run cost receipts, and incident evidence are stored in SQLite.

Configure persistent storage, monitor disk usage, and maintain tested backups.

Budget totals and cost receipts are not erased by short-lived incident-timeline pruning.

### Scaling

SQLite supports multiple processes, subject to write contention and filesystem constraints. Redis does not replace the SQLite account and run-record database.

Multiple hosts, independent disks, high write rates, and stronger availability requirements need an explicit storage and deployment design. No universal throughput figure is claimed.

## Security Notes

The implementation includes:

- Hashed API-key storage.
- Authenticated API and account endpoints.
- Account-scoped authorization for dashboard access.
- Timestamped HMAC verification for generic cost ingestion.
- Signature verification for billing webhooks.
- Webhook URL checks and disabled redirects.
- Request-body size enforcement.
- Bounded session histories and caches.
- Opt-in proxy-header trust.
- Account deletion support for associated application records, including the new run records.

These controls are not a blanket compliance certification or a guarantee against every attack.

Operators must also manage secrets, dependencies, backups, monitoring, and infrastructure access.

## Limitations

- **Not semantic detection.** Differently worded but equivalent actions may evade exact-payload checks.
- **No automatic interception.** Unguarded actions are outside AgentTrafficCop's control.
- **No retroactive cancellation.** Approval checks cannot undo completed calls.
- **Cost reporting is external.** Budgets cannot enforce spending AgentTrafficCop has not received.
- **No absolute spending guarantee.** Delayed reporting and concurrent actions can overshoot.
- **Adapters are scoped.** LangGraph protects wrapped nodes; the AutoGen adapter supports the pinned legacy version and guarded reply methods.
- **Timeline evidence is bounded.** It is not a full execution recording or proof of money saved.
- **Restart durability depends on storage.** SQLite requires a persistent filesystem; active in-memory loop history remains separate.
- **Webhooks are best-effort alerts.** They are not a durable, guaranteed-delivery incident queue.

## Testing

The combined backend and SDK feature branch passed **413 tests, with 1 skipped**, before merge.

Coverage includes:

- Loop and policy enforcement.
- Persistent usage and run budgets.
- Concurrent cost-report deduplication.
- Tenant isolation and dashboard authorization.
- Timeline privacy and bounded retention.
- Real legacy AutoGen sync/async tool execution paths.

Separate browser regressions cover signup, safe dashboard rendering, and the run inspector. Container smoke tests check non-root startup and persisted account login.

These results describe tested behavior, not a claim that every customer integration or live provider connection has been verified.

## License

MIT.
