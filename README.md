# AgentTrafficCop SDK

[![PyPI version](https://img.shields.io/pypi/v/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)
[![Python versions](https://img.shields.io/pypi/pyversions/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)

**Detect repeated agent behavior. Inspect the evidence. Decide when to stop.**

The official Python SDK for **[AgentTrafficCop](https://agenttrafficcop.com)** — a runtime circuit breaker for multi-agent workflows.

Place a guard check before an agent handoff, tool invocation, or other protected action. AgentTrafficCop evaluates the submitted action against loop, step, usage, and configured spending policies.

Start in **shadow mode** to observe detector decisions without blocking for those detections. Switch to **enforcement mode** when rejected checks should prevent the protected action.

> Your integration must honor the decision. AgentTrafficCop does not execute or forward actions, automatically intercept every LLM call, or cancel work already in progress.

## Features

- **Shadow mode** — observe which loop and step checks would reject an action while allowing it to continue.
- **Repeated-payload detection** — detect consecutive identical payloads using canonical JSON and SHA-256.
- **Cycle detection** — detect repeating payload sequences within configured cycle bounds.
- **Step limits** — limit approved actions in an enforcement session.
- **Strict message validation** — validate submitted handoff fields against the server-side request contract.
- **Schema-change detection — Pro/Team** — flag three consecutive different submitted tool-schema hashes.
- **Rolling spend protection** — evaluate reported costs over a 60-second window.
- **Per-run budgets — Pro/Team** — reject subsequent protected actions when reported cumulative run spending reaches its budget.
- **Incident timelines** — inspect recorded decisions, hashes, explanations, and bounded diagnostics.
- **Webhook alerts** — configure supported Slack or Discord destinations for enforcement notifications.
- **Sync and async clients** — use `GuardSync` or `Guard`.
- **LangGraph integration** — guard selected workflow nodes.
- **Legacy AutoGen integration** — protect supported reply pipelines for `pyautogen==0.2.35`.

Detection is deterministic, not semantic. Similar meaning alone does not make differently worded payloads identical.

## Installation

Python **3.11+** is required.

Install SDK **1.1.0**:

```bash
python -m pip install --upgrade 'agenttrafficcop==1.1.0'
```

Version 1.1.0 includes explicit shadow-mode support, typed shadow-decision fields, per-run budget helpers, and the legacy AutoGen adapter.

It supports:

```text
httpx>=0.27.0,<0.29.0
```

This allows `httpx 0.28.1` without forcing a downgrade to 0.27.x. Other installed packages may have their own dependency requirements.

Check your installed SDK version:

```bash
python -c "from importlib.metadata import version; print(version('agenttrafficcop'))"
```

### Optional Framework Dependencies

For LangGraph:

```bash
python -m pip install 'agenttrafficcop[langgraph]==1.1.0'
```

For legacy AutoGen:

```bash
python -m pip install 'agenttrafficcop[autogen]==1.1.0'
```

The AutoGen extra pins `pyautogen==0.2.35`. It is not intended for modern AutoGen or AG2 applications.

Use a virtual environment to isolate dependencies.

> Installing the SDK does not automatically instrument your application or connect provider cost reporting.

## Quick Start

1. Verify your email and create an account at the [dashboard](https://agenttrafficcop.com/dashboard.html).
2. Generate an API key.
3. Store it in your environment:

```bash
export ATC_API_KEY="your-api-key"
```

4. Check an action before executing it:

```python
import asyncio
import os
import uuid

from agenttrafficcop import AgentTrafficCopError, Guard


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

from agenttrafficcop import AgentTrafficCopError, GuardSync


run_id = uuid.uuid4().hex

with GuardSync(
    url="https://api.agenttrafficcop.com",
    api_key=os.environ["ATC_API_KEY"],
    dry_run=False,
) as guard:
    try:
        result = guard.check(
            session_id=run_id,
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

Creating a client alone does not hook into a framework. Call it at the execution boundary or use a supported adapter.

## Shadow Mode

Evaluate detector behavior before allowing it to interrupt a workflow.

Pass `mode="shadow"` to a normal SDK check:

```python
import asyncio
import os
import uuid

from agenttrafficcop import AgentTrafficCopError, Guard


async def main():
    run_id = uuid.uuid4().hex

    async with Guard(
        url="https://api.agenttrafficcop.com",
        api_key=os.environ["ATC_API_KEY"],
        dry_run=False,
    ) as guard:
        for attempt in range(1, 4):
            try:
                result = await guard.check(
                    session_id=run_id,
                    sender="planner",
                    recipient="worker",
                    payload={"task": "same-action"},
                    mode="shadow",
                )
            except AgentTrafficCopError as exc:
                # Non-shadowed policies can still reject the check.
                print("Action not executed:", exc.error_code)
                break

            print(
                "Attempt:",
                attempt,
                "Approved:",
                result.approved,
                "Would block:",
                result.would_block,
            )

            if result.would_block and result.shadow_decision:
                print("Detector:", result.shadow_decision["error"])

            if result.approved:
                # Your application may execute the protected action here.
                pass


if __name__ == "__main__":
    asyncio.run(main())
```

`GuardSync.check(...)` supports the same arguments without `await`.

With the default repeat threshold and no other blocking policy:

- Attempts 1–2 are approved with `would_block: false`.
- Attempt 3 is approved with `would_block: true`.
- The detector reason is `REPEATED_PAYLOAD_LOOP`.

### Shadow Response

When a loop or step rule triggers, the API returns HTTP **200**, approval, and a separate warning:

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

### Try Shadow Mode Through HTTP

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

### What Shadow Mode Changes

Shadow mode observes the tier-appropriate:

- Repeated-payload rule
- Cycle rule
- Step-limit rule
- Schema-change rule

It does **not** bypass:

- Authentication
- Input validation
- Rate limits
- Message quotas
- Agent limits
- Rolling spend blocks
- Exhausted run budgets

Shadow requests consume normal quota. Detector warnings do not send alerts claiming that a workflow was halted.

Shadow and enforcement use separate loop histories for the same API key and session ID. Switching to enforcement does not transfer shadow history.

Run budgets and spend protection remain shared according to their existing key/run scope.

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

Inside an open `Guard` context:

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

Available through SDK **1.1.0** or the REST API.

```python
import os
import uuid

import httpx

from agenttrafficcop import GuardSync


run_id = uuid.uuid4().hex

with GuardSync(
    url="https://api.agenttrafficcop.com",
    api_key=os.environ["ATC_API_KEY"],
    dry_run=False,
) as guard:
    try:
        budget = guard.set_run_budget(
            session_id=run_id,
            budget_usd="2.00",
        )
    except httpx.HTTPError as exc:
        print("Could not configure run budget:", exc)
        raise
    else:
        print(budget)

    # Use run_id in route checks and trusted cost reports.
```

The asynchronous equivalent, inside an open `Guard` context, is:

```python
budget = await guard.set_run_budget(
    session_id=run_id,
    budget_usd="2.00",
)
```

The budget helper currently exposes HTTPX errors for HTTP or transport failures. Its error handling differs from `guard.check(...)`.

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

For the hosted service, arrange an authorized reporting integration. An ordinary SDK API key does not grant access to the service's ingestion-signing secret.

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

Install the optional dependency:

```bash
python -m pip install 'agenttrafficcop[langgraph]==1.1.0'
```

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

This is an integration fragment. It assumes an existing graph, an open compatible guard client, and a `reviewer_fn`.

Only wrapped nodes are protected. Preserve exception propagation so rejected checks prevent execution.

Existing adapters do not automatically enable shadow mode. Use direct guard calls when you need explicit `mode="shadow"` behavior.

### Legacy AutoGen

Install the optional integration:

```bash
python -m pip install 'agenttrafficcop[autogen]==1.1.0'
```

Supported framework version:

```text
pyautogen==0.2.35
```

Example agent setup:

```python
import os
import uuid

from agenttrafficcop import GuardSync
from agenttrafficcop.autogen import GuardedConversableAgent


with GuardSync(
    url="https://api.agenttrafficcop.com",
    api_key=os.environ["ATC_API_KEY"],
    dry_run=False,
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

    # Run the supported reply pipeline while the guard is open.
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

Use a new session ID for each independent run.

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

In shadow mode, loop and step detector codes appear inside `shadow_decision` on an HTTP 200 response instead of rejecting the action.

Catch `AgentTrafficCopError` around `guard.check(...)` when a workflow should stop on SDK check failures—not only loop errors.

The current budget helper uses HTTPX exceptions for HTTP and transport failures.

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

Production configuration can override defaults. See the [website](https://agenttrafficcop.com) for current commercial terms.

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

| Candidate capability | Goal |
|---|---|
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

SDK 1.1.0 release preparation included:

- **479 passing regression tests, with 1 skipped**, using the original dependency set.
- **43 passing SDK and shadow-mode tests** with `httpx 0.28.1`.
- **Five isolated installed-wheel smoke tests** on each of `httpx 0.27.2` and `0.28.1`.
- Wheel and source-distribution metadata validation.
- Archive-content checks to exclude private backend files.
- An independent wheel rebuild from the source distribution.

The repeated-payload shadow path was also exercised against the hosted API: the detector returned a would-block warning while subsequent checks continued.

These are scoped validation results—not a claim that every customer integration, payment flow, framework version, or provider connection has been verified.

## Links

- [Website](https://agenttrafficcop.com)
- [Dashboard](https://agenttrafficcop.com/dashboard.html)
- [Public SDK repository](https://github.com/belalshafeq/AgentTrafficCop-sdk)
- [Issues and feature requests](https://github.com/belalshafeq/AgentTrafficCop-sdk/issues)
- [PyPI](https://pypi.org/project/agenttrafficcop/)

## License

The SDK is licensed under the MIT License. See [LICENSE](LICENSE).
- [Website](https://agenttrafficcop.com)
- [Dashboard](https://agenttrafficcop.com/dashboard.html)
- [Public SDK repository](https://github.com/belalshafeq/AgentTrafficCop-sdk)
- [Issues and feature requests](https://github.com/belalshafeq/AgentTrafficCop-sdk/issues)
- [PyPI](https://pypi.org/project/agenttrafficcop/)
