# AgentTrafficCop SDK

[![PyPI version](https://img.shields.io/pypi/v/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)
[![Python versions](https://img.shields.io/pypi/pyversions/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)

**Detect repeated agent behavior. Check the next action before it runs.**

The official Python SDK for [AgentTrafficCop](https://agenttrafficcop.com), a runtime circuit breaker for agent workflows.

Choose how to guard your application:

- **Local checks:** detect exact repeats, repeating cycles, and step limits inside your Python process. No API key or network requests.
- **Hosted checks:** evaluate actions through the API, with shadow mode, incident timelines, account quotas, and configured reported-spending controls.

> AgentTrafficCop returns a decision. Your application must honor it. The SDK does not execute or forward actions, automatically intercept every model call, or cancel work already in progress.

## Installation

Requires **Python 3.11+**.

```bash
python -m pip install --upgrade 'agenttrafficcop==1.3.0'
```

Check your installed version:

```bash
python -c "from importlib.metadata import version; print(version('agenttrafficcop'))"
```

SDK 1.3.0 includes:

- `LocalGuard` and `LocalResult` for offline deterministic loop checks.
- Sync and async hosted clients.
- Hash-only payload submission, introduced in 1.2.0.
- Explicit hosted shadow mode and per-run budget helpers.
- LangGraph and legacy AutoGen integrations.

The SDK supports:

```text
httpx>=0.27.0,<0.29.0
```

Other packages in your environment may impose additional dependency requirements. Use a virtual environment when possible.

## Local or Hosted?

| Capability | `LocalGuard` | Hosted `Guard` / `GuardSync` |
|---|---|---|
| API key required | No | Yes |
| Network request for each check | No | Yes |
| Exact-repeat detection | Yes | Yes |
| Repeating-cycle detection | Yes | Yes |
| Step limits | Yes | Yes |
| Detector configuration | Per local instance | Server configuration and eligible plan settings |
| Shadow mode | No | Yes |
| Schema-change detection | No | Pro/Team |
| Dashboard incident timelines | No | Yes |
| Reported-spending controls | No | With authorized cost reporting |
| History storage | In-memory, per instance | Depends on server storage configuration |
| Automatic tool interception | No | No |

**Neither mode provides semantic understanding.** Differently worded actions can mean the same thing without producing the same hash.

## Quick Start: Local Checks

No account, API key, or backend URL is needed.

```python
from agenttrafficcop import LocalGuard


def main():
    guard = LocalGuard(
        max_repeats=3,
        max_steps=50,
    )

    action = {
        "tool": "search_docs",
        "arguments": {"query": "refund policy"},
    }

    for _ in range(3):
        result = guard.check(
            session_id="example-run",
            payload=action,
        )

        if not result.approved:
            print("Action not executed:", result.reason)
            break

        # Replace this print with your protected tool invocation.
        print("Approved step", result.step)


if __name__ == "__main__":
    main()
```

Expected output:

```text
Approved step 1
Approved step 2
Action not executed: REPEATED_PAYLOAD_LOOP
```

With `max_repeats=3`, the third consecutive identical action is rejected.

**Reuse the same guard instance and session ID throughout a run.** Creating a new guard or changing the session ID for every action starts independent history and defeats run-level detection.

### Local Configuration

```python
from agenttrafficcop import LocalGuard

guard = LocalGuard(
    max_repeats=3,
    max_steps=50,
    max_cycle_length=2,
    max_cycle_repeats=3,
    max_sessions=1000,
    session_ttl=3600,
)
```

| Option | Default | Meaning |
|---|---:|---|
| `max_repeats` | `3` | Reject when this many consecutive identical actions would be reached |
| `max_steps` | `50` | Maximum approved checks per session |
| `max_cycle_length` | `2` | Largest repeating sequence length checked |
| `max_cycle_repeats` | `3` | Number of consecutive sequence repetitions that triggers rejection |
| `max_sessions` | `1000` | Maximum retained, unexpired sessions |
| `session_ttl` | `3600` | Inactivity expiry in seconds |

Integer options must be positive integers. `max_cycle_repeats` must be at least two. The inactivity TTL must be positive and finite.

For example, with the default cycle settings:

```text
A → B → A → B → A → B
```

The sixth attempt completes the third repetition of the two-action sequence and is rejected, assuming no earlier rule blocks it.

### Local Results

`LocalGuard.check(...)` returns a `LocalResult`:

| Field | Meaning |
|---|---|
| `approved` | Whether the application may proceed |
| `session_id` | Session checked |
| `step` | Number of approved checks recorded for that session |
| `payload_hash` | Locally calculated SHA-256 digest |
| `reason` | Rejection code, or `None` on approval |

Local rejection codes:

| Code | Meaning |
|---|---|
| `REPEATED_PAYLOAD_LOOP` | Consecutive identical-action threshold reached |
| `CYCLIC_PAYLOAD_LOOP` | Repeating-sequence threshold reached |
| `STEP_LIMIT_EXCEEDED` | Approved-step limit reached |
| `LOCAL_CAPACITY_EXCEEDED` | No room for another unexpired session |

Policy rejections are returned as results—not raised as hosted SDK exceptions.

Invalid inputs raise `ValueError`. Treat these as failed checks; do not execute the protected action afterward.

Rejected checks do not advance approved-step counts or action history. They do refresh an existing session's activity time. A loop rejection does not permanently lock the run: a different subsequent action can be approved if no other rule blocks it.

### Resetting Local History

```python
removed = guard.reset("example-run")
```

Reset explicitly discards that session's history.

Do not expose reset operations or session-ID selection to untrusted callers when guard policies are mandatory.

### Local Boundaries

- Checks and history updates are atomic and thread-safe within one guard instance.
- Separate guard instances and separate processes do not share history.
- History is held in memory and lost on restart, explicit reset, or inactivity expiry.
- Retained history is bounded according to the configured detector thresholds.
- At session capacity, new sessions are rejected instead of evicting active protection.
- There are no network requests, telemetry uploads, dashboard records, or hosted fallback from `LocalGuard`.
- Local checks do not enforce account quotas, schema-change rules, or shared spending limits.
- Local mode has no shadow-mode option or automatic framework instrumentation.

Approval counts checks—not proof that an action actually executed. Put the check immediately before execution and only proceed after approval.

## Quick Start: Hosted Checks

1. Verify your email and create an account at the [dashboard](https://agenttrafficcop.com/dashboard.html).
2. Generate an API key.
3. Store it in your environment:

```bash
export ATC_API_KEY="your-api-key"
```

4. Check each protected action before executing it:

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
            # Execute your protected action here.
            print("Approved at step", result.step)


if __name__ == "__main__":
    asyncio.run(main())
```

Use a stable session ID throughout a run and a new ID for each independent run.

Creating a hosted client alone does not hook it into your framework. Call it at the execution boundary or use a supported adapter.

### Synchronous Hosted Usage

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
            # Execute your protected action here.
            print("Approved at step", result.step)
```

## Choose a Meaningful Payload

Local checks and the hosted hash-only helper calculate SHA-256 over JSON serialized with:

- Sorted object keys
- Compact separators
- Unescaped Unicode
- UTF-8 encoding
- Non-finite numbers rejected

Choose fields that meaningfully represent the action.

A new timestamp or random identifier on every payload can prevent exact-repeat detection. Removing meaningful arguments can make distinct actions appear identical.

Changing values are not automatically removed.

This serialization is not an RFC 8785 canonicalization implementation. Cross-language integrations must match the serialization rules to generate identical digests.

## Hosted Hash-Only Payload Mode

Hash-only mode submits an action's locally calculated SHA-256 digest instead of its raw payload.

The Python helper is available in **SDK 1.2.0 and later**, including 1.3.0, and requires a compatible backend.

### SDK Usage

Inside an open asynchronous `Guard` context:

```python
result = await guard.check(
    session_id=run_id,
    sender="planner",
    recipient="worker",
    payload={
        "task": "review account",
        "private_content": "stays in your application",
    },
    hash_only=True,
)
```

`GuardSync.check(...)` supports the same option without `await`.

The helper omits the raw payload from the outgoing request. It rejects metadata in hash-only mode and does not fall back to transmitting raw contents if the backend rejects the format.

### REST Usage

```python
import getpass
import hashlib
import json
import urllib.request
import uuid

api_key = getpass.getpass("AgentTrafficCop API key: ")
run_id = uuid.uuid4().hex

payload = {
    "task": "review account",
    "private_content": "This stays in your application.",
}

canonical = json.dumps(
    payload,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
    allow_nan=False,
)

digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

body = {
    "session_id": run_id,
    "sender": "planner",
    "recipient": "worker",
    "intent": "handoff",
    "payload_mode": "hash_only",
    "payload_hash": digest,
    "mode": "enforce",
}

request = urllib.request.Request(
    "https://api.agenttrafficcop.com/v1/route",
    data=json.dumps(body).encode("utf-8"),
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    },
    method="POST",
)

# HTTP failures raise HTTPError; transport failures may raise URLError.
# Do not execute after a failed check.
with urllib.request.urlopen(request, timeout=30) as response:
    result = json.load(response)

if result.get("approved") is True:
    # Execute your protected action here.
    print("Approved")
```

Reuse `run_id` in subsequent checks for that run.

### Request Rules

- Set `payload_mode` to `"hash_only"`.
- Supply `payload_hash` as exactly 64 lowercase hexadecimal characters.
- Omit `payload` and `metadata` entirely—even null values are rejected.
- Supply the required session and routing fields.
- Select `mode="shadow"` separately when desired.
- Raw payload submission remains the default for hosted SDK checks.

### Supported Hosted Protections

Hash-only requests retain:

- Exact-repeat and repeating-cycle detection
- Step limits
- Schema-change detection with a separately supplied schema hash on eligible plans
- Authentication and request-envelope validation
- Rate limits and usage quotas
- Reported-spending controls and per-run budgets
- Shadow decisions and incident timelines

Raw and hash-only requests share detector history for the same API key, session, and enforcement/shadow mode when their payload hashes match.

### Privacy Boundaries

**Hash-only is not the same as local-only.**

Hosted hash-only requests still send hashes, session IDs, agent names, intent, and other required routing fields.

Hashes reveal equality. Predictable inputs can be guessed by hashing candidate values. A hash is not encryption or a guarantee of anonymization.

The backend cannot inspect the original action or prove that the submitted digest matches the action actually executed. Use a trusted integration.

Framework adapters do not automatically enable hash-only mode.

## Hosted Shadow Mode

Use shadow mode to observe supported detector decisions before enabling enforcement.

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

With the default repeat threshold, a fresh session, and no other blocking policy:

- Attempts 1–2 are approved without a detector warning.
- Attempt 3 is approved with `would_block=True`.
- The warning code is `REPEATED_PAYLOAD_LOOP`.

### Shadow Response

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

### What Shadow Mode Changes

Shadow mode observes supported, tier-appropriate:

- Repeated-payload checks
- Cycle checks
- Step limits
- Schema-change checks

It does **not** bypass:

- Authentication or input validation
- Rate limits
- Message or agent quotas
- Rolling spend blocks
- Exhausted run budgets
- Session-coordination failures

Approved shadow checks consume normal message quota. Detector warnings do not send alerts claiming that the workflow was halted.

Shadow and enforcement histories are separate. Switching to enforcement does not transfer shadow history.

Run budgets and spend controls retain their existing key/run scope.

> Keep `dry_run=False` for server-side shadow evaluation. Legacy SDK dry-run behavior is not equivalent to shadow mode.

If guard policies are mandatory, prevent untrusted callers from selecting shadow mode.

## Detection Rules

### Consecutive Repeats

With a repeat threshold of three, the first two identical consecutive actions are approved and the third is rejected.

This is exact hash matching—not semantic similarity.

### Repeating Cycles

Cycle detection compares recurring payload sequences.

With a maximum cycle length of two and a repeat threshold of three:

```text
A → B → A → B → A → B
```

The final attempt triggers the cycle rule.

Local cycle bounds are constructor options. Hosted bounds depend on server configuration.

### Step Limits

A step counts an approved check, not a verified execution.

- `LocalGuard` defaults to **50 approved checks per session**.
- Hosted enforcement defaults to **25 approved checks per session**, subject to server configuration and eligible custom settings.

Policy-rejected checks do not increment the approved-step count. Infrastructure failures can leave an ambiguous outcome if recording succeeded but the response did not reach the client.

Hosted shadow mode can continue past the configured step limit while reporting a would-block warning.

### Hosted Schema-Change Detection — Pro/Team

Inside an open asynchronous `Guard` context:

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

## Hosted Spending Protection

Local checks do not measure or enforce spending.

Hosted spending controls evaluate costs supplied by an authorized reporting integration:

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

    print(budget)

    # Use run_id in subsequent checks and trusted cost reports.
```

Inside an open asynchronous `Guard` context:

```python
budget = await guard.set_run_budget(
    session_id=run_id,
    budget_usd="2.00",
)
```

The budget helper exposes HTTPX exceptions for HTTP and transport failures. Its error handling differs from `guard.check(...)`.

Once reported cumulative spending reaches the budget, subsequent guarded checks return:

```text
HTTP 402
RUN_BUDGET_EXCEEDED
```

Updating a budget preserves accumulated spending. Raising it can permit additional actions if no other rule blocks them.

Budgets do not reset monthly. Use a new session ID for a new run.

### Connect Trusted Cost Reporting

Setting a budget does not connect provider billing automatically.

A trusted reporting backend must submit incremental costs to:

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

- Report incremental costs—not cumulative totals.
- Use stable, unique event IDs for retries.
- Match the protected run's session ID.
- Sign the exact request body.
- Avoid reporting the same spending through multiple sources.

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

For the hosted service, arrange an authorized reporting integration. An ordinary SDK API key does not grant access to the ingestion-signing secret.

The CloudPulse handler requires explicit external-key mapping. A threshold response without a mapping does not establish that an ATC key was blocked. CloudPulse key-level reports do not currently attribute costs to individual runs.

> Spending protection is report-driven—not a provider-side hard cap. Missing or delayed reports, parallel work, and in-flight calls can cause overshoot. Your application must honor rejections.

## Hosted Incident Timelines

In the dashboard:

**Overview → Recent Sessions → Inspect run**

Inspect:

- Approved, blocked, and would-block decisions
- Shadow versus enforcement mode
- Step number, when available
- Sender and recipient
- Triggered rule
- Payload hash
- Explanation and bounded diagnostics

Pro and Team users can set or update the selected run's budget from the inspector.

`LocalGuard` does not upload decisions or create hosted timeline records.

### Privacy and Retention

Timeline records omit raw payloads and request metadata. They retain identifiers, timestamps, hashes, and selected diagnostics.

Normal hosted checks still transmit raw payloads for server-side validation and hashing unless hash-only mode is explicitly selected.

Evidence is bounded to:

- The latest **200 recorded checks per run**
- Up to **10,000 recorded checks per API key**
- The applicable plan's time-based retention

Older activity is not backfilled. A timeline is not a full execution trace, historical replay system, or proof of money saved.

## Framework Integrations

The existing adapters target hosted guard clients. Do not assume `LocalGuard` is a drop-in replacement: place explicit local checks before framework actions when using local mode.

### LangGraph

Install the optional dependency:

```bash
python -m pip install 'agenttrafficcop[langgraph]==1.3.0'
```

Wrap selected nodes:

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

This fragment assumes an existing graph, an open compatible hosted guard, and a `reviewer_fn`.

Only wrapped nodes are protected. Preserve exception propagation so rejected checks prevent execution.

Adapters do not automatically enable shadow or hash-only mode. Use direct guard calls when you need options not exposed by an adapter.

### Legacy AutoGen

```bash
python -m pip install 'agenttrafficcop[autogen]==1.3.0'
```

Supported framework version:

```text
pyautogen==0.2.35
```

Example:

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

Direct sends, direct tool calls, and work outside guarded reply methods are not intercepted. One reply can execute multiple tools; the guard does not reserve spending per tool.

The adapter does not automatically report model costs or provide an execution sandbox. Dry-run guards are rejected.

## REST API

Use the hosted API from any language.

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

Approval permits your application to proceed; it does not execute the action.

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

## Hosted Errors

| Code | Meaning |
|---|---|
| `REPEATED_PAYLOAD_LOOP` | Consecutive identical-payload threshold reached |
| `CYCLIC_PAYLOAD_LOOP` | Repeating-sequence threshold reached |
| `STEP_LIMIT_EXCEEDED` | Session step limit reached |
| `SCHEMA_MUTATION_LOOP` | Schema-change rule triggered |
| `RUN_BUDGET_EXCEEDED` | Reported cumulative run budget reached |
| `SPEND_LIMIT_EXCEEDED` | Rolling spend block active |
| `TOKEN_LIMIT_EXCEEDED` | Integration reported a token-limit violation |
| `TIER_LIMIT_EXCEEDED` | Account message allowance reached |
| `AGENT_LIMIT_EXCEEDED` | Tracked-agent allowance reached |

Common hosted failure responses include HTTP **401, 402, 403, 413, 422, 429, and 503**, depending on the failure. Other server or transport failures are also possible.

### Session Coordination Failures — HTTP 503

The backend can return **503 Service Unavailable** when session coordination is unavailable, the session remains busy beyond the acquisition wait, or a coordination lease expires before a protected write.

These are failed checks—not detector approvals. They may use an HTTP error detail rather than one of the detector codes above.

**Do not execute the protected action after a 503 or any other failed check.**

In shadow mode, supported detector codes appear in `shadow_decision` on an HTTP 200 approval rather than rejecting the action. Coordination and infrastructure failures are not converted into shadow approvals.

### SDK Error Handling

Catch `AgentTrafficCopError` around hosted `guard.check(...)` calls when check failures should stop the workflow—not only loop-specific exceptions.

Budget helpers currently use HTTPX exceptions for HTTP and transport failures.

For local checks, inspect `LocalResult.approved` and `LocalResult.reason`; invalid local inputs raise `ValueError`.

A timeout or failed response is not proof that the server recorded nothing. Do not assume retries are idempotent or reset history to work around a failure.

## Hosted Plans and Usage

`LocalGuard` requires no hosted account and does not consume hosted message or tracked-agent quota.

The following limits apply to hosted service usage:

| Feature | Free — $0 | Pro — $49/month | Team — $199/month |
|---|---:|---:|---:|
| Approved messages per account usage period | 10,000 | 250,000 | 2,000,000 |
| Tracked agents | 5 | 25 | 100 |
| Tier rate limit | 60/min | 120/min | 300/min |
| Active API keys | 2 | 5 | High implementation cap |
| Shadow mode | Yes | Yes | Yes |
| Repeated-payload, cycle, and step checks | Yes | Yes | Yes |
| Schema-change detection | — | Yes | Yes |
| Custom rolling spend threshold | — | Yes | Yes |
| Per-run budgets | — | Yes | Yes |
| Custom hosted step and repeat thresholds | — | — | Yes |
| Incident timelines | Yes | Yes | Yes |
| Webhook destinations | 1 | 5 | High implementation cap |
| Listed log retention | 7 days | 30 days | 1 year |

Production configuration can override defaults. See the [website](https://agenttrafficcop.com) for current commercial terms.

For account-issued keys, usage follows a stable account-anchored **30-day period**, not necessarily a calendar month.

Message usage and tracked-agent membership are shared across the account's keys. Creating or rotating a key does not create a fresh account quota.

Approved shadow checks consume message quota. Policy-rejected checks do not consume approved-message quota, but remain subject to relevant rate limits.

Some crash or ambiguous storage-failure cases can retain a conservative message-quota charge even when the client receives no approval. Quota admission and detector-history storage are not one cross-store transaction.

Run budgets and timelines are **API key + session scoped**, unlike account-wide message usage.

## Reliability and Security

### Local Checks

`LocalGuard` makes no network requests and does not upload payloads, hashes, or identifiers.

Its history is process-local and instance-local. It is lost on restart, explicit reset, or inactivity expiry. Thread safety does not make it a distributed guard.

It does not prove that an approved action ran, that a rejected action was stopped, or that the submitted payload matches the eventual operation.

### Hosted Checks

The hosted application includes authenticated endpoints, hashed API-key storage, account-scoped dashboard authorization, signed cost ingestion, billing webhook verification, request-size limits, and bounded evidence storage.

These controls are not a compliance certification or a guarantee against every attack.

Hosted session evaluation, quota admission, and history recording are coordinated to prevent simultaneous requests for the same session from independently approving against stale history.

- **Memory-backed history** remains process-local. Decisions use the backend's shared lock, which also coordinates reset and eviction. This can serialize unrelated sessions.
- **Redis-backed history** uses per-session coordination and token-fenced writes. A worker whose lease expired cannot commit a stale history update.
- Participating workers must use a compatible backend version and shared configuration. Old writers that do not honor coordination must be drained or stopped during rollout.
- Session coordination does not make quota storage, detector history, and incident logging one atomic transaction.

Blocking route work runs through a bounded worker pool. This improves event-loop responsiveness but does not guarantee a particular throughput or eliminate database contention.

Usage and run records require persistent storage to survive restarts. Without Redis, active hosted loop history does not span independent workers and is lost on restart. Persistent timeline records do not restore active detector history.

Webhook alerts are best-effort notifications—not a guaranteed-delivery incident queue.

### Mandatory Enforcement Checklist

- Guard every relevant execution boundary.
- Reuse the intended guard instance and stable run ID.
- Execute only after approval.
- Stop on a rejected or failed check, including timeouts and HTTP 503 responses.
- Keep hosted legacy `dry_run` disabled.
- Prevent untrusted callers from bypassing checks, changing policy modes, or resetting history.
- Connect and monitor trusted cost reporting when using hosted spending controls.
- Account for the documented restart, expiry, and multi-worker boundaries.
- Do not treat a failed response as proof that no history or quota update occurred.

## Roadmap Candidates

These are possible future capabilities—not currently available features or delivery commitments.

| Candidate capability | Goal |
|---|---|
| Historical replay and threshold comparison | Compare detector settings against suitable recorded event sequences |
| Explicit outage policies | Configure availability behavior separately for loop and spend protections |
| Human review and controlled resume | Review a detection and authorize limited continuation |
| Shared spending reservations | Coordinate participating parallel workers before actions start |
| Experimental semantic detection | Explore rephrased repetition, beginning with warning-only evaluation |
| Additional framework integrations | Support frameworks requested by active users |

Local-first deterministic checks shipped in **SDK 1.3.0** and are no longer a roadmap-only feature.

Open an [issue](https://github.com/belalshafeq/AgentTrafficCop-sdk/issues) describing your framework, workflow, and desired behavior.

## Validation

SDK 1.3.0 validation included:

- **549 passing tests, with 1 skipped**, in the local full-suite run.
- **30 local-guard tests**, including concurrency, session isolation, expiry, bounded history, capacity rejection, invalid inputs, and no-network behavior.
- Local-versus-hosted detector comparisons across all binary action sequences of length six under default repeat and cycle settings.
- **10 isolated installed-package smoke tests** on each of `httpx 0.27.2` and `0.28.1`.
- Strict wheel and source-distribution metadata checks.
- Archive-content checks to exclude private backend files.
- An independent wheel rebuild from the source distribution.
- Fresh PyPI installation and installed-package smoke verification.
- Passing PR, post-merge CI, and release workflows.

A separate user-run Colab verification using the published 1.3.0 package also passed repeat, cycle, step-limit, session-isolation, reset, and concurrent-check tests while socket connections were blocked.

These figures describe SDK 1.3.0 release validation, not the current backend test-suite total.

These are scoped validation results—not proof that every customer integration, framework version, payment flow, or provider connection has been verified.

## Links

- [Website and current plans](https://agenttrafficcop.com)
- [Dashboard](https://agenttrafficcop.com/dashboard.html)
- [PyPI package](https://pypi.org/project/agenttrafficcop/)
- [SDK repository](https://github.com/belalshafeq/AgentTrafficCop-sdk)
- [Issues and feature requests](https://github.com/belalshafeq/AgentTrafficCop-sdk/issues)
- - [PyPI](https://pypi.org/project/agenttrafficcop/)

## License

The SDK is licensed under the MIT License. See [LICENSE](LICENSE).
