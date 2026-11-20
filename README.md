# AgentTrafficCop SDK

[![PyPI version](https://img.shields.io/pypi/v/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)
[![Python versions](https://img.shields.io/pypi/pyversions/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)
[![CI](https://github.com/belalshafeq/AgentTrafficCop-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/belalshafeq/AgentTrafficCop-sdk/actions/workflows/ci.yml)

**Detect repeated agent behavior. Inspect the evidence. Decide when to stop.**

The official Python SDK for **[AgentTrafficCop](https://agenttrafficcop.com)** — a runtime circuit breaker for multi-agent workflows.

Place a guard check before an agent handoff, tool invocation, or other protected action. AgentTrafficCop evaluates the submitted action against loop, step, usage, and configured spending policies.

Start in **shadow mode** to observe loop-policy decisions without blocking for those detections. Use **enforcement mode** when you want a rejected check to stop the protected action.

> Your integration must honor the decision. AgentTrafficCop does not execute or forward actions, automatically intercept every LLM call, or cancel work already in progress.

## Features

- **Shadow mode** — see which loop and step checks would reject an action while allowing it to continue.
- **Repeated-payload detection** — detect consecutive identical payloads using canonical JSON and SHA-256.
- **Cycle detection** — detect repeating payload sequences within configured cycle bounds.
- **Step limits** — limit the number of approved actions in an enforcement session.
- **Strict message validation** — validate handoff fields against a server-side Pydantic contract.
- **Schema-change detection — Pro/Team** — flag three consecutive different submitted tool-schema hashes.
- **Rolling spend protection** — evaluate reported costs over a 60-second window.
- **Per-run budgets — Pro/Team** — reject subsequent protected actions when reported cumulative run spending reaches its budget.
- **Incident timelines** — inspect recorded decisions, hashes, explanations, and bounded diagnostics.
- **Webhook alerts** — configure supported Slack or Discord destinations for enforcement notifications.
- **Sync and async clients** — use `GuardSync` or `Guard`.
- **LangGraph integration** — guard selected workflow nodes.
- **Legacy AutoGen adapter in development source** — protect supported reply pipelines for `pyautogen==0.2.35`.

Detection is deterministic, not semantic. Similar meaning alone does not make two differently worded payloads identical.

## Installation and Release Availability

Python **3.11+** is required.

```bash
pip install agenttrafficcop
```

### Published package versus development source

The PyPI package and development source do not necessarily contain the same features.

The following SDK additions are implemented in development source but have not been published as a new release at the time of this documentation:

- `set_run_budget(...)`
- The legacy AutoGen adapter
- `check(..., mode="shadow")`
- Typed shadow-decision result fields

Do not assume these helpers exist in an older installed package.

Check your installed package version:

```bash
python -c "from importlib.metadata import version; print(version('agenttrafficcop'))"
```

The hosted API supports explicit shadow-mode requests independently of the Python SDK. See [Shadow Mode](#shadow-mode).

Development-source examples below require a source revision containing the relevant feature. The private backend repository is not a customer installation source.

## Quick Start

1. Verify your email and create an account at the [dashboard](https://agenttrafficcop.com/dashboard.html).
2. Generate an API key.
3. Store it in your environment:

```bash
export ATC_API_KEY="your-api-key"
```

4. Check the action before executing it:

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
            print("Action not executed:", exc.error_code)
            return

        if result.approved:
            # Execute the protected action here.
            print("Approved at step", result.step)


if __name__ == "__main__":
    asyncio.run(main())
```

Use one stable `session_id` throughout a run and a new ID for each independent run.

Choose a payload that meaningfully represents the action. Adding a changing timestamp or random identifier to every payload can prevent exact-repeat detection.

### Synchronous Usage

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
        print("Action not executed:", exc.error_code)
    else:
        if result.approved:
            # Execute the protected action here.
            print("Approved at step", result.step)
```

Using a client alone does not hook into a framework. Call it at the execution boundary or use a supported adapter.

## Shadow Mode

Evaluate loop policies before allowing them to interrupt a workflow.

Send:

```json
{
  "mode": "shadow"
}
```

as part of a normal route request.

When a loop or step rule triggers, the API returns HTTP **200** with an approval and a separate warning:

```json
{
  "approved": true,
  "session_id": "shadow-example",
  "step": 3,
  "payload_hash": "...",
  "mode": "shadow",
  "would_block": true,
  "shadow_decision": {
    "error": "REPEATED_PAYLOAD_LOOP",
    "message": "Detector explanation",
    "diagnostics": {}
  }
}
```

The application may continue because the check is approved. The warning explains what enforcement mode would have rejected.

### Try It Without an SDK Update

Use a fresh session ID and submit three identical actions:

```bash
RUN_ID="shadow-test-$(python -c 'import uuid; print(uuid.uuid4().hex)')"

for i in 1 2 3; do
  curl -sS https://api.agenttrafficcop.com/v1/route \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $ATC_API_KEY" \
    -d "{
      \"session_id\": \"$RUN_ID\",
      \"sender\": \"planner\",
      \"recipient\": \"worker\",
      \"intent\": \"handoff\",
      \"payload\": {\"task\": \"same-action\"},
      \"mode\": \"shadow\"
    }"
  echo
done
```

With the default repeat threshold and no other blocking policy:

- Attempts 1–2: HTTP 200, `would_block: false`.
- Attempt 3: HTTP 200, `would_block: true`.
- The reason is `REPEATED_PAYLOAD_LOOP`.
- Further shadow checks may continue, subject to other limits.

### Development SDK Usage

Requires SDK source containing shadow support:

```python
result = await guard.check(
    session_id=run_id,
    sender="planner",
    recipient="worker",
    payload={"task": "review patch"},
    mode="shadow",
)

if result.would_block:
    print(result.shadow_decision["error"])

if result.approved:
    # The application chooses to execute the action.
    pass
```

`GuardSync.check(...)` supports the same arguments without `await`.

### What Shadow Mode Changes

Shadow mode observes the tier-appropriate:

- Repeated-payload rule
- Cycle rule
- Step-limit rule
- Schema-change rule

It does **not** bypass authentication, input validation, rate limits, message quotas, agent limits, rolling spend blocks, or exhausted run budgets.

Shadow requests consume normal quota. Detector warnings do not send alerts claiming that a workflow was halted.

Shadow and enforcement use separate loop histories for the same API key and session ID. Switching to enforcement does not transfer shadow history. Run budgets and spend protection remain shared according to their existing key/run scope.

The timeline labels detections as **[Shadow] Would block**.

> Shadow mode is not the legacy SDK `dry_run` option. Keep `dry_run=False` when evaluating server-side shadow mode. Legacy dry-run suppresses additional errors and is not equivalent.

Shadow mode is explicitly caller-selected. If guard policies are mandatory, do not let untrusted callers choose the mode.

## How Detection Works

### Repeated Payloads

Payloads are serialized deterministically and hashed with SHA-256.

With the default consecutive-repeat threshold of **3**, enforcement mode approves the first two identical consecutive payloads and rejects the third.

### Repeating Cycles

The default maximum cycle length is **2**, supporting repeating sequences such as:

```text
payload A → payload B → payload A → payload B
```

Detection compares payload sequences, not simply whether two agents exchange messages. Longer cycle bounds require appropriate server configuration.

### Step Limits

The default enforcement limit is **25 approved steps per session**.

Shadow mode can continue beyond the configured step limit while reporting that enforcement would block.

### Schema-Change Detection — Pro/Team

```python
result = await guard.check(
    session_id=run_id,
    sender="coder",
    recipient="reviewer",
    payload={"task": "review patch"},
    schema={"tools": [{"name": "read_file"}]},
)
```

The SDK hashes the submitted schema separately. Three consecutive different submitted schema hashes trigger the rule on eligible plans.

This is a schema-change heuristic—not proof of a semantic loop, measured cache misses, or guaranteed savings.

## Spending Protection

| Control | Scope | Behavior |
|---|---|---|
| Rolling spend threshold | API key | Evaluates reported spending over a 60-second window |
| Per-run budget | API key + session ID | Evaluates cumulative reported spending for a run |

Default rolling thresholds:

| Free | Pro | Team |
|---:|---:|---:|
| $0.50 / 60 seconds | $5 / 60 seconds | $50 / 60 seconds |

Production configuration can override defaults. Pro and Team support custom rolling thresholds.

### Per-Run Budgets — Pro/Team

Requires development SDK source containing the budget helper, or direct REST usage.

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

    # Use run_id in route checks and trusted cost reports.
```

The asynchronous equivalent is:

```python
budget = await guard.set_run_budget(
    session_id=run_id,
    budget_usd="2.00",
)
```

Once reported cumulative spending reaches the budget, subsequent protected checks return:

```text
HTTP 402
RUN_BUDGET_EXCEEDED
```

Updating the budget preserves accumulated spending. Raising it can permit further actions if no other rule blocks them.

Budgets do not reset monthly. Use a new session ID for a new run.

### Connect Cost Reporting

Setting a budget does not connect provider billing automatically.

A trusted backend must report incremental costs to:

```text
POST /v1/ingest/usage
```

```json
{
  "api_key": "YOUR_ATC_KEY",
  "event_id": "provider-request-123",
  "cost": "0.30",
  "session_id": "task-123"
}
```

Requirements:

- Report incremental costs, not cumulative totals.
- Use stable, unique event IDs for retries.
- Match the protected run's session ID.
- Sign the exact request body.
- Do not report the same spending through multiple sources.

Required headers:

```text
X-ATC-Timestamp
X-ATC-Signature
```

The signature is the hexadecimal SHA-256 HMAC of:

```text
timestamp + "." + exact_request_body
```

Keep `ATC_INGEST_WEBHOOK_SECRET` on the trusted reporting backend. Never expose it in browser code. A bearer token alone does not authenticate ingestion.

The CloudPulse handler supports explicit external-key mapping. A threshold response without a mapping does not establish that an ATC key was blocked. CloudPulse key-level window reports do not currently attribute costs to individual runs.

> Spend protection is report-driven, not a provider-side hard cap. Missing or delayed reports, parallel work, and in-flight calls can cause overshoot. Your application must honor rejections.

## Incident Timeline

In the hosted dashboard:

**Overview → Recent Sessions → Inspect run**

Inspect:

- Approved, blocked, or would-block decisions
- Shadow versus enforcement mode
- Step number, when available
- Sender and recipient
- Triggered rule
- Payload hash
- Explanation and bounded diagnostics

Pro and Team users can set or update the selected run's budget from the inspector.

### Privacy and Retention

The timeline does not store raw payloads or request metadata. It stores identifiers, timestamps, hashes, and selected diagnostics.

This does not mean the current route API is hash-only: normal checks still submit payloads for server-side validation and hashing.

Hashes reveal equality and are not anonymization. Keep secrets out of agent names and session IDs.

Evidence is bounded to:

- The latest **200 recorded checks per run**
- Up to **10,000 recorded checks per API key**
- The applicable plan's time-based retention

Older activity is not backfilled. The timeline is not a full execution trace, historical replay system, or proof of money saved.

## Framework Integrations

### LangGraph

Wrap selected nodes with `guarded_node`:

```python
from agenttrafficcop.langgraph import guarded_node

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
```

Install a compatible LangGraph version separately or use an available SDK `langgraph` extra.

Only wrapped nodes are protected. Preserve exception propagation so rejected checks prevent execution.

Existing adapters do not automatically enable shadow mode. Explicit adapter wiring or direct guard calls are required.

### Legacy AutoGen — Development Source

Supported version:

```text
pyautogen==0.2.35
```

The adapter is implemented in development SDK source and is not yet included in the previously published package.

```python
import os
import uuid

from agenttrafficcop import GuardSync
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
```

The adapter checks before supported `generate_reply` and `a_generate_reply` pipelines, including registered reply handlers.

It does not support AutoGen 0.4+, modern AgentChat, AG2, or arbitrary similarly named packages.

Direct sends, direct tool calls, and execution outside guarded reply methods are not intercepted. One reply may execute multiple tools; the guard does not reserve spending per tool.

The adapter does not automatically report model costs or provide an execution sandbox. Dry-run guards are rejected.

## REST API

Use the API from any language.

### Health

```bash
curl https://api.agenttrafficcop.com/health
```

### Enforcement Check

```bash
curl https://api.agenttrafficcop.com/v1/route \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $ATC_API_KEY" \
  -d '{
    "session_id": "example-run",
    "sender": "coder",
    "recipient": "reviewer",
    "intent": "handoff",
    "payload": {"task": "review patch"},
    "mode": "enforce"
  }'
```

Omitting `mode` defaults to enforcement.

Approval permits the caller to proceed; it does not execute the action.

### Core Endpoints

| Method | Path | Authentication | Purpose |
|---|---|---|---|
| `POST` | `/v1/route` | Bearer API key | Evaluate an action |
| `GET` | `/v1/usage` | Bearer API key | Read tier and usage |
| `PUT` | `/v1/runs/{session_id}/budget` | Bearer API key; Pro/Team | Set or update a budget |
| `GET` | `/v1/runs/{session_id}/budget` | Bearer API key | Read run spending and budget |
| `GET` | `/v1/runs/{session_id}/timeline` | Bearer API key | Read recorded decisions |
| `POST` | `/v1/ingest/usage` | Timestamped HMAC; ATC key in body | Report incremental costs |
| `GET` | `/health` | None | Check service health |

Timeline pagination supports `after` and `limit`. Use `next_after` for subsequent pages.

Agent API keys are not automatically administrator credentials.

## Errors

| Code | Meaning |
|---|---|
| `REPEATED_PAYLOAD_LOOP` | Consecutive identical-payload threshold reached |
| `CYCLIC_PAYLOAD_LOOP` | Repeating sequence threshold reached |
| `STEP_LIMIT_EXCEEDED` | Session step limit reached |
| `SCHEMA_MUTATION_LOOP` | Schema-change rule triggered |
| `RUN_BUDGET_EXCEEDED` | Reported cumulative run budget reached |
| `SPEND_LIMIT_EXCEEDED` | Rolling spend block active |
| `TOKEN_LIMIT_EXCEEDED` | Integration reported a token-limit violation |
| `TIER_LIMIT_EXCEEDED` | Account message allowance reached |
| `AGENT_LIMIT_EXCEEDED` | Tracked-agent allowance reached |

Rejections can use HTTP **401, 402, 403, 422, or 429**, depending on the failure.

In shadow mode, loop/step detector codes appear inside `shadow_decision` on an HTTP 200 response instead of rejecting the action.

Catch `AgentTrafficCopError` when a workflow should stop on any SDK check failure—not only loop errors.

## Plans and Usage

| Feature | Free — $0 | Pro — $49/month | Team — $199/month |
|---|---:|---:|---:|
| Approved messages per account usage period | 10,000 | 250,000 | 2,000,000 |
| Tracked agents | 5 | 25 | 100 |
| Tier rate limit | 60/min | 120/min | 300/min |
| Active API keys | 2 | 5 | High implementation cap |
| Shadow mode | Yes | Yes | Yes |
| Repeated-payload, cycle and step checks | Yes | Yes | Yes |
| Schema-change detection | — | Yes | Yes |
| Custom rolling spend threshold | — | Yes | Yes |
| Per-run budgets | — | Yes | Yes |
| Custom step and repeat thresholds | — | — | Yes |
| Incident timeline | Yes | Yes | Yes |
| Webhook destinations | 1 | 5 | High implementation cap |
| Listed log retention | 7 days | 30 days | 1 year |

Production configuration can override defaults.

For account-issued keys, usage follows a stable account-anchored **30-day period**, not necessarily a calendar month.

Message usage and tracked-agent membership are shared across the account's keys. Creating or rotating a key does not create a fresh account quota.

Approved shadow checks consume message quota. Rejected checks do not increment the approved-message counter but remain subject to relevant rate limits.

Run budgets and timelines are **API key + session scoped**, unlike account-wide message usage.

## Reliability and Security

The hosted application includes authenticated endpoints, hashed API-key storage, account-scoped dashboard authorization, signed cost ingestion, billing webhook verification, request-size limits, and bounded evidence storage.

These controls are not a compliance certification or a guarantee against every attack.

Usage and run records require persistent storage to survive restarts. Without Redis, active loop history is process-local, does not span independent workers, and is lost on restart. Persistent timeline records do not restore that active history.

Webhook alerts are best-effort notifications, not a guaranteed-delivery incident queue.

For mandatory enforcement:

- Guard every relevant execution boundary.
- Keep legacy `dry_run` disabled.
- Prevent untrusted callers from selecting shadow mode.
- Stop when a protected check fails.
- Connect and monitor trusted cost reporting.

## Coming Soon

The following are roadmap candidates, not currently available features or delivery commitments. Priorities may change based on user feedback.

| Planned capability | Goal |
|---|---|
| Updated SDK release | Publish development-source budget helpers, legacy AutoGen support, and explicit shadow-mode helpers |
| Hash-only privacy mode | Evaluate supported checks without submitting raw action payloads |
| Historical replay and threshold comparison | Compare detector settings against suitable recorded event sequences |
| Local-first SDK checks | Run selected deterministic loop checks locally |
| Explicit outage policies | Configure availability behavior separately for loop and spend protections |
| Human review and controlled resume | Review a detection and authorize limited continuation |
| Shared spending reservations | Coordinate participating parallel workers before actions start |
| Experimental semantic detection | Explore rephrased repetition, beginning with warning-only evaluation |
| Additional framework integrations | Support frameworks requested by active users |

Interested in evaluating one of these capabilities? Open an [issue](https://github.com/belalshafeq/AgentTrafficCop-sdk/issues) describing your framework, workflow, and desired behavior.

## Validation

The private backend's shadow-mode change passed:

- **479 tests, with 1 skipped**
- **11 deployment/content script tests**
- **Three browser regression scripts**

The repeated-payload shadow path was also exercised against the hosted API: the detector returned a would-block warning while subsequent checks continued.

These are scoped validation results—not a claim that every public SDK release, customer integration, payment flow, or provider connection has been verified.

## Links

- [Website](https://agenttrafficcop.com)
- [Dashboard](https://agenttrafficcop.com/dashboard.html)
- [Public SDK repository](https://github.com/belalshafeq/AgentTrafficCop-sdk)
- [Issues and feature requests](https://github.com/belalshafeq/AgentTrafficCop-sdk/issues)
- [PyPI](https://pypi.org/project/agenttrafficcop/)

## License

The SDK is licensed under the MIT License. See [LICENSE](LICENSE).
