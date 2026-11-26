# AgentTrafficCop SDK

[![PyPI version](https://img.shields.io/pypi/v/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)
[![Python versions](https://img.shields.io/pypi/pyversions/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)

**Check the next agent action before it runs.**

Catch repeated actions, repeating cycles and step-limit overruns. Start locally without an account, or use hosted checks for coordinated decisions, run timelines and reported-spending controls.

**Installing the SDK does not automatically protect every call.** Your application must check or wrap each protected execution boundary and honor rejected or failed checks.

## Install

Requires **Python 3.11+**.

```bash
python -m pip install --upgrade 'agenttrafficcop==1.7.0'
```

This README describes **published SDK 1.7.0**. SDK 2.0 changes—including default root-metadata normalization and additional named accounting adapters—are not included in these installation instructions.

## Choose Your Starting Point

| You want to… | Use |
|---|---|
| Try loop detection without an account or network | `LocalGuard` |
| Check actions through the hosted API | `GuardRuntime.check()` / `acheck()` |
| Check, reserve, execute and settle a participating call | `runtime.run(...).execute()` / `aexecute()` |
| Detect similar meanings across differently worded actions | `SemanticMonitor` with a configured encoder |
| Manage hosted client connections yourself | `Guard` / `GuardSync` |
| Protect framework tools or nodes | Explicit framework registration hooks |

---

## 1. Try Local Loop Protection

This complete example executes a tool twice, then blocks the third identical attempt.

```python
from agenttrafficcop import LocalGuard


def search_docs(query):
    return f"Found documentation for: {query}"


guard = LocalGuard(max_repeats=3, max_steps=50)
run_id = "refund-demo"

for attempt in range(1, 4):
    decision = guard.check(
        session_id=run_id,
        payload={
            "tool": "search_docs",
            "arguments": {"query": "refund policy"},
        },
    )

    if not decision.approved:
        print(f"Attempt {attempt}: blocked ({decision.reason})")
        break

    print(f"Attempt {attempt}: approved")
    print(search_docs("refund policy"))
```

Expected output:

```text
Attempt 1: approved
Found documentation for: refund policy
Attempt 2: approved
Found documentation for: refund policy
Attempt 3: blocked (REPEATED_PAYLOAD_LOOP)
```

### What to remember

- Reuse the **same guard and session ID** throughout the run.
- A new instance or session ID starts independent history.
- Local history is in-memory and is not shared across processes.
- Restart, inactivity expiry or `guard.reset(session_id)` removes history.
- Check immediately before execution; approved checks are not proof that an action ran.
- Stop on rejection or invalid-input errors.

### Local defaults

| Setting | Default |
|---|---:|
| Consecutive identical-action threshold | `3` |
| Maximum approved checks per session | `50` |
| Maximum repeating cycle length | `2` |
| Cycle repetitions before rejection | `3` |
| Retained sessions | `1000` |
| Session inactivity expiry | `3600` seconds |
| Ignored payload fields | None |

Checks are atomic and thread-safe within one instance. At session capacity, new sessions are rejected rather than silently evicting active protection.

Local checks do not enforce hosted spending, quotas or schema-change detection.

---

## 2. Use Hosted Checks

Create an API key in the [dashboard](https://agenttrafficcop.com/dashboard.html), then set:

```bash
export ATC_API_KEY="your-api-key"
```

Check before calling your tool:

```python
import os
import uuid

from agenttrafficcop import AgentTrafficCopError, GuardRuntime


def search_docs(query):
    return f"Found documentation for: {query}"


runtime = GuardRuntime(
    url="https://api.agenttrafficcop.com",
    api_key=os.environ["ATC_API_KEY"],
)

run_id = uuid.uuid4().hex

try:
    decision = runtime.check(
        session_id=run_id,
        sender="planner",
        recipient="search_docs",
        payload={
            "tool": "search_docs",
            "arguments": {"query": "refund policy"},
        },
    )
except AgentTrafficCopError as error:
    print("Action not executed:", error.error_code)
else:
    if decision.execution_allowed:
        print(search_docs("refund policy"))
```

Reuse `run_id` for subsequent actions in the same run. Hosted checks **fail closed by default**.

For async applications, use:

```python
decision = await runtime.acheck(
    session_id=run_id,
    sender="planner",
    recipient="search_docs",
    payload={
        "tool": "search_docs",
        "arguments": {"query": "refund policy"},
    },
)
```

`GuardRuntime` manages short-lived clients for you. For explicit lifecycle management and connection reuse, use `with GuardSync(...)` or `async with Guard(...)`.

---

## 3. Enable Semantic Loop Blocking

Exact hashes do not identify differently worded actions with similar meanings. Semantic monitoring adds an **experimental, opt-in** similarity policy.

**This is semantic loop detection—not semantic caching.** It does not store and reuse model answers.

### One-line OpenAI encoder setup

Set your OpenAI key:

```bash
export OPENAI_API_KEY="your-openai-api-key"
```

Then configure the monitor and runtime:

```python
import os
import uuid

from agenttrafficcop import (
    AgentTrafficCopError,
    GuardRuntime,
    SemanticMonitor,
)

monitor = SemanticMonitor.openai()

runtime = GuardRuntime(
    url="https://api.agenttrafficcop.com",
    api_key=os.environ["ATC_API_KEY"],
    semantic_monitor=monitor,
    semantic_mode="block",
)

run_id = uuid.uuid4().hex

attempts = [
    "Find the refund rules",
    "Look up the policy for getting a refund",
    "Search for the conditions for refund eligibility",
]

for text in attempts:
    try:
        decision = runtime.check(
            session_id=run_id,
            sender="planner",
            recipient="search",
            payload={"tool": "search", "query": text},
            semantic_text=text,
        )
    except AgentTrafficCopError as error:
        print("Action not executed:", error.error_code)
        break

    if not decision.execution_allowed:
        break

    # Execute your search here.
    print("Approved:", text)
```

**The exact outcome is model- and threshold-dependent.** This example does not guarantee that these three phrases will trigger a semantic block.

### Configuration and privacy

- The default helper model is `text-embedding-3-small`.
- Construction makes no request. Observing text sends it to OpenAI and may incur charges.
- Embedding charges are separate from the protected operation’s cost accounting.
- No embedding model is bundled or downloaded automatically.
- `semantic_mode="warn"` observes without enforcing semantic warnings.
- `semantic_mode="block"` blocks on a semantic warning or unavailable monitoring.
- Similarity thresholds and repeat settings can be configured on the monitor.
- History is bounded, process-local and based on attempted checks—not verified executions.
- False positives and missed loops are possible.

Start with representative workloads in warning mode before choosing an enforcement threshold.

### Bring your own encoder

Use a synchronous text-to-vector callable when you need a different provider or local processing:

```python
monitor = SemanticMonitor(
    encoder=encode_text,
    model_id="your-model-and-version",
)
```

`encode_text` is your configured embedding function. Whether text stays local depends on that function.

Optional hosted semantic evidence is labelled **client-reported**; it is not independently verified hosted semantic replay.

---

## 4. Configure Protected Execution Once

For participating calls, the recommended budgeted path is:

```text
check → reserve → execute → report → settle
```

Bind the settings shared by a run once:

```python
run = runtime.run(
    session_id=run_id,
    sender="agent",
    recipient="model",
    accountant=accountant,
)
```

Then execute each operation:

```python
response = run.execute(
    call_provider,
    operation_id="persisted-operation-123",
    estimated_cost_usd="0.02",
    payload={"task": "find refund rules"},
)
```

For async work:

```python
response = await run.aexecute(
    async_call_provider,
    operation_id="persisted-operation-124",
    estimated_cost_usd="0.02",
    payload={"task": "summarize refund rules"},
)
```

These fragments assume:

- A configured `GuardRuntime`.
- A provider callable returning supported final usage.
- A `UsageAccountant` with exact-model prices and an authorized reporter.
- An existing **Pro/Team run budget** for the same key and session.
- Durable application tracking of operation IDs.

The wrapper returns the original provider response. Low-level check, reservation and reporting APIs remain available.

### Configure a run budget

Inside an open `GuardSync` context:

```python
guard.set_run_budget(
    session_id=run_id,
    budget_usd="2.00",
)
```

Async clients support `await guard.set_run_budget(...)`.

Changing the budget does not erase reported spending or outstanding holds.

### Configure accounting

SDK 1.7.0 supports configured-price extraction for supported non-streaming OpenAI and Anthropic text-token usage:

```python
from agenttrafficcop import TokenPrices, UsageAccountant

accountant = UsageAccountant(
    provider="openai",
    model_prices={
        "exact-returned-model-name": TokenPrices(
            input_per_million="2.00",
            output_per_million="10.00",
        ),
    },
    reporter=authorized_reporter,
)
```

The prices above are **illustrative**, not current provider pricing. Replace them with the rates for the exact returned model. Configure cache pricing separately when applicable.

`authorized_reporter` is your trusted reporting integration. Setting a budget or supplying an ordinary API key does not connect provider billing or grant ingestion-signing authority.

### Failure handling matters

| Outcome | Behavior |
|---|---|
| Rejected check | Do not execute |
| Duplicate reservation | Does not authorize another execution |
| Known supported final usage | Report cost and settle the hold |
| Timeout, cancellation or unknown usage | Retain the unresolved hold |
| Reporting failure after execution | Retry the same cost report—not the action |

Persist operation IDs and failed reports in your application ledger or outbox.

**Never assume an exception means no charge.** Streaming, audio, tool fees, discounts and other billing variations may require custom handling. Missing usage or unknown pricing is not silently treated as zero.

> Reported-cost controls and estimated reservations are not guaranteed provider-side hard caps. Delayed reports, underestimates and unreserved calls can exceed a budget.

Keep ingestion-signing secrets on a trusted backend—never in browser code or an untrusted agent.

---

## 5. Protect Framework Tools and Nodes

Install the integration you use:

```bash
python -m pip install 'agenttrafficcop[langgraph]==1.7.0'
python -m pip install 'agenttrafficcop[crewai]==1.7.0'
python -m pip install 'agenttrafficcop[autogen-agentchat]==1.7.0'
python -m pip install 'agenttrafficcop[mcp]==1.7.0'
```

| Integration | Entry point | Tested version |
|---|---|---|
| LangGraph | `guard_langgraph(...)` | `1.2.24` |
| CrewAI | `guard_crewai_tools(...)` | `1.15.45` |
| AutoGen AgentChat | `guard_autogen_tools(...)` | AgentChat/core `0.7.5` |
| MCP client tools | `runtime.mcp_client(...)` | `1.30.0` |
| Generic callables | `runtime.wrap(...)` / `guard_functions(...)` | Supported non-streaming sync/async functions |

Framework hooks require application-specific context describing the run, routing and meaningful action payload.

**Only registered or wrapped paths are protected.** These hooks do not automatically add budget reservations or account for every internal model call.

The legacy AutoGen adapter supports `pyautogen==0.2.35`; it is separate from current AgentChat and does not imply AG2 support.

[Read the framework and runtime guide →](https://github.com/belalshafeq/AgentTrafficCop/blob/main/sdk/RUNTIME_FEATURES.md)

---

## Payload Identity and Privacy

Changing timestamps or request IDs can hide exact repeats. Excluding meaningful arguments can incorrectly merge distinct actions.

### Explicit field exclusions

Local:

```python
guard = LocalGuard(
    ignore_paths=["/timestamp", "/request/id"],
)
```

Hosted runtime:

```python
decision = runtime.check(
    session_id=run_id,
    sender="planner",
    recipient="worker",
    payload=action,
    hash_only=True,
    ignore_paths=["/timestamp"],
)
```

Paths are JSON pointers through objects, not array selectors or wildcards. The SDK normalizes a copy; the original action is not modified.

### SDK 1.7.0 metadata preset

```python
runtime = GuardRuntime(
    url="https://api.agenttrafficcop.com",
    api_key=os.environ["ATC_API_KEY"],
    normalize_volatile_metadata=True,
)
```

In **1.7.0**, this preset:

- Is **off by default**.
- Requires hash-only mode.
- Removes exact-case `timestamp`, `request_id` and `trace_id` at the root and directly inside root `metadata`.
- Does not recursively strip nested tool arguments or arrays.

Keep the normalization policy consistent within a run.

### What leaves the application?

| Mode | Data boundary |
|---|---|
| `LocalGuard` | No network request |
| `GuardRuntime` default | Hash-only hosted request |
| Direct `Guard` / `GuardSync` default | Raw payload transmission |
| Hosted semantic encoder | Explicitly supplied text reaches the encoder provider |

Hash-only requests still send hashes, routing fields, agent names and session IDs. Hashes reveal equality; they are not encryption or guaranteed anonymization.

---

## Outage Behavior

Hosted checks **fail closed by default**.

Connection-establishment retries can be configured through `OutagePolicy`. Ambiguous read/write failures and HTTP errors are not automatically retried.

Explicit connection-only degraded continuation is available:

```python
runtime = GuardRuntime(
    url="https://api.agenttrafficcop.com",
    api_key=os.environ["ATC_API_KEY"],
    failure_mode="fail_open",
)
```

An eligible degraded result has:

```text
execution_allowed=True
approved=False
degraded=True
```

This is **not a hosted approval**. Hosted quotas, spending enforcement and detector history are unavailable during that continuation.

Fail-open does not bypass authentication failures, HTTP rejections, ambiguous delivery or semantic blocks. Reserved execution requires an actual hosted approval.

---

## Inspect Decisions in the Dashboard

Open **Dashboard → Recent Sessions → Inspect run**.

You can inspect recorded decisions, compare deterministic thresholds and review eligible blocked actions.

| Capability | What it does |
|---|---|
| Shadow mode | Records supported detector warnings while allowing those actions |
| Threshold comparison | Simulates repeat, cycle and step policies over retained history |
| One-action review | Authorizes one eligible retry without clearing detector history |
| Semantic evidence | Displays explicitly submitted client-reported observations |

Important boundaries:

- Shadow approvals consume quota; authentication, spending and coordination failures still reject.
- Legacy `dry_run=True` is not server-side shadow evaluation.
- Review does not execute the action or bypass other controls.
- Threshold comparison does not rerun tools or change live policy.
- Retention is bounded to **200 records per run**, **10,000 per key**, and the plan’s retention window.
- Timelines are not complete execution traces or proof of savings.

---

## Plans and Feature Availability

### Hosted allowances

| Allowance | Free | Pro | Team |
|---|---:|---:|---:|
| Monthly price | $0 | $49 | $199 |
| Approved checks / usage period | 10,000 | 250,000 | 2,000,000 |
| Tracked agents | 5 | 25 | 100 |
| Tier rate limit | 60/min | 120/min | 300/min |
| Active API keys | 2 | 5 | Higher configured capacity |
| Webhook destinations | 1 | 5 | Higher configured capacity |
| Default reported-spend threshold / 60s | $0.50 | $5 | $50 |
| Timeline retention* | 7 days | 30 days | 365 days |

Account-issued keys share an account-anchored **30-day usage period** and tracked-agent allowance. Creating another key does not create fresh account quota.

*Retention remains subject to record caps. Configuration and commercial terms can differ; see the [website](https://agenttrafficcop.com).*

### Feature comparison

| Feature | Free | Pro | Team |
|---|:---:|:---:|:---:|
| Exact-repeat, cycle and step checks | ✓ | ✓ | ✓ |
| Shadow mode | ✓ | ✓ | ✓ |
| Timelines and threshold comparison | ✓ | ✓ | ✓ |
| Eligible owner-reviewed one-action continuation | ✓ | ✓ | ✓ |
| Client-reported semantic evidence | ✓ | ✓ | ✓ |
| Default reported-spend protection¹ | ✓ | ✓ | ✓ |
| Custom rolling spend thresholds | — | ✓ | ✓ |
| Run budgets and reservations | — | ✓ | ✓ |
| Schema-change detection | — | ✓ | ✓ |
| Custom hosted step/repeat limits | — | — | ✓ |

¹ Requires authorized cost reporting.

Local checks, normalization helpers, semantic policies, framework hooks, outage policies and configured-price accounting helpers have **no SDK paid-tier gate**. Hosted allowances, paid hosted controls and external provider charges still apply.

**Team adds capacity, retention and custom hosted step/repeat limits—not unimplemented collaboration or workspace features.**

---

## State and Production Deployment

| State | Storage boundary |
|---|---|
| Local detector history | One in-memory guard instance |
| Memory-backed hosted detector history | One process; lost on restart |
| Redis-backed hosted detector history | Shared compatible workers, subject to TTL and persistence |
| Timelines, budgets and reservations | Separate persistent database |
| Semantic embeddings | Process-local monitor memory |

Persistent timelines do not restore active detector history.

Server operators can enable `ATC_REQUIRE_SHARED_STATE=true` to refuse startup without reachable Redis. This verifies connectivity—not backups or disk durability.

Production storage must be configured and verified separately. Installing the SDK does not provision Redis or a persistent ledger.

---

## Safety Checklist

- Check or wrap every execution boundary you intend to protect.
- Reuse a stable run ID and meaningful action identity.
- Stop after rejected or failed checks unless you explicitly accept documented degraded behavior.
- Keep policy changes, resets and reporting authority under trusted application control.
- Persist operation IDs before budgeted execution.
- Never retry an executed action because reporting failed.
- Treat missing usage and ambiguous provider outcomes as unknown cost—not zero.

## Documentation and Links

- [Runtime, accounting and framework guide](https://github.com/belalshafeq/AgentTrafficCop/blob/main/sdk/RUNTIME_FEATURES.md)
- [Changelog](https://github.com/belalshafeq/AgentTrafficCop/blob/main/sdk/CHANGELOG.md)
- [Website](https://agenttrafficcop.com)
- [Dashboard](https://agenttrafficcop.com/dashboard.html)
- [PyPI](https://pypi.org/project/agenttrafficcop/)
- [SDK repository](https://github.com/belalshafeq/AgentTrafficCop-sdk)
- [Report an issue](https://github.com/belalshafeq/AgentTrafficCop-sdk/issues)

## License

MIT. See [LICENSE](LICENSE).
