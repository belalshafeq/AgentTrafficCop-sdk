# AgentTrafficCop SDK

[![PyPI version](https://img.shields.io/pypi/v/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)
[![Python versions](https://img.shields.io/pypi/pyversions/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)

**Check the next agent action before it runs.**

Catch repeated actions, repeating cycles and step-limit overruns. Start locally without an account, or use hosted checks for coordinated decisions, run timelines and reported-spending controls.

**Installing the SDK does not automatically protect every call.** Your application must check or wrap each protected execution boundary and honor rejected or failed checks.

[Developer guide](https://agenttrafficcop.com/guide/) · [Dashboard](https://agenttrafficcop.com/dashboard.html) · [API reference](https://agenttrafficcop.com/guide/#api)

## Install

Requires **Python 3.11+**.

```bash
python -m pip install --upgrade 'agenttrafficcop==1.7.0'
```

Check your installed version:

```bash
python -c "from importlib.metadata import version; print(version('agenttrafficcop'))"
```

This README describes **published SDK 1.7.0**. Do not assume APIs or defaults from unreleased source are available in your installed package.

[Version differences and migration →](https://agenttrafficcop.com/guide/#versions)

## Choose Your Integration

| You want to… | Use |
|---|---|
| Try offline loop protection without credentials | `LocalGuard` |
| Check actions through the hosted API | `GuardRuntime.check()` / `acheck()` |
| Configure a budget-protected run once | `runtime.run(...)` |
| Check, reserve, execute, report and settle | `run.execute()` / `aexecute()` |
| Detect similar meanings across differently worded actions | `SemanticMonitor` |
| Manage hosted connections yourself | `Guard` / `GuardSync` |
| Protect framework tools or nodes | Explicit framework registration hooks |

## Quickstart: Local Protection

This complete example executes a tool twice, then blocks the third identical attempt.

No account, API key or network connection is required.

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

### Local behavior

- Reuse the **same guard instance and session ID** throughout the run.
- A new instance or session ID starts independent history.
- Checks are atomic and thread-safe within one instance.
- Separate processes do not share history.
- Restart, inactivity expiry or reset removes history.
- Local checks do not enforce hosted quotas, schema detection or spending controls.
- Approved steps count checks—not verified executions.

Defaults include a repeat threshold of `3`, a step limit of `50`, maximum cycle length of `2`, and session inactivity expiry of `3600` seconds.

Invalid inputs raise `ValueError`. Do not execute after a rejected or failed check.

[Local configuration and return values →](https://agenttrafficcop.com/guide/#local)

## Quickstart: Hosted Protection

Create an API key in the [dashboard](https://agenttrafficcop.com/dashboard.html).

```bash
export ATC_API_KEY="your-api-key"
```

Check immediately before executing your action:

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

Reuse `run_id` for subsequent actions in the same run.

For async applications, use `await runtime.acheck(...)` with the same arguments.

`GuardRuntime` manages short-lived clients. Use `with GuardSync(...)` or `async with Guard(...)` when you need explicit lifecycle management and connection reuse.

**Hosted checks fail closed by default.** Other validation or callback errors should also stop execution; do not catch an error and continue unguarded.

[Hosted checks and async usage →](https://agenttrafficcop.com/guide/#hosted)

## Semantic Loop Blocking

Deterministic detection compares hashes—not meaning. Experimental semantic monitoring can flag similar meanings across differently worded actions.

**This is semantic loop detection, not semantic caching.** It does not store and reuse model answers.

### One-line encoder setup

```bash
export OPENAI_API_KEY="your-openai-api-key"
```

```python
from agenttrafficcop import SemanticMonitor

monitor = SemanticMonitor.openai()
```

Attach it to your hosted runtime:

```python
runtime = GuardRuntime(
    url="https://api.agenttrafficcop.com",
    api_key=os.environ["ATC_API_KEY"],
    semantic_monitor=monitor,
    semantic_mode="block",
)

decision = runtime.check(
    session_id=run_id,
    sender="planner",
    recipient="search_docs",
    payload={"tool": "search_docs", "query": "refund policy"},
    semantic_text="Find the refund rules",
)
```

Handle rejection and failure before executing, as in the hosted quickstart.

### Important boundaries

- Requires an OpenAI key in addition to the hosted ATC key.
- Construction makes no request; observing text sends it to OpenAI and may incur charges.
- Default helper model: `text-embedding-3-small`.
- No model is bundled or downloaded automatically.
- BYO synchronous embedding encoders remain supported.
- Default runtime semantic mode is `warn`; `block` must be selected explicitly.
- Block mode stops on a semantic warning or unavailable monitoring.
- History is bounded, process-local and based on attempted checks.
- False positives and missed loops are possible.

Start with representative workloads in warning mode before selecting a blocking threshold.

[Complete semantic examples, tuning and BYO setup →](https://agenttrafficcop.com/guide/#semantic)

## Budget-Protected Execution

Configure routing and accounting once for a run:

```python
run = runtime.run(
    session_id=run_id,
    sender="agent",
    recipient="model",
    accountant=accountant,
)
```

Then protect each participating operation:

```python
response = run.execute(
    call_provider,
    operation_id="persisted-operation-123",
    estimated_cost_usd="0.02",
    payload={"task": "find refund rules"},
)
```

Use `await run.aexecute(...)` for async work.

The helper handles:

```text
check → reserve → execute → report → settle
```

### Prerequisites

These fragments assume:

- A configured `GuardRuntime`.
- A provider callable returning supported final usage.
- A `UsageAccountant` with exact-model prices.
- An authorized reporting integration.
- An existing **Pro/Team run budget** for the same API key and session.
- Persisted operation IDs and application recovery state.

A budget setting or ordinary API key does not automatically connect provider billing or grant ingestion-signing authority.

### Accounting and recovery

SDK 1.7.0 includes configured-price adapters for supported non-streaming OpenAI and Anthropic text-token usage.

- Duplicate reservations do not authorize another execution.
- Known supported usage can be reported and settled.
- Timeouts, cancellation and unknown usage retain unresolved holds.
- Reporting failure after execution exposes a cost report to retry.
- **Retry the same report—not the provider action.**
- Keep ingestion-signing secrets on a trusted backend.

Streaming, audio, tool fees, discounts and other billing variations may need custom handling. Missing usage or unknown pricing is not silently treated as zero.

> Reported-cost controls and estimated reservations are not guaranteed provider-side hard caps. Underestimates, delayed reports and unreserved calls can exceed a budget.

[Complete budget and accounting setup →](https://agenttrafficcop.com/guide/#budgets)  
[Failure recovery and reporting-only retries →](https://agenttrafficcop.com/guide/#recovery)

## Framework and MCP Integrations

Install the extra you need:

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

Register the execution paths you want protected and provide application-specific context for run identity and meaningful arguments.

**Only wrapped or registered paths are protected.** Framework hooks do not automatically reserve budgets or account for every internal model call.

The legacy AutoGen adapter supports `pyautogen==0.2.35`; it is separate from current AgentChat and does not imply AG2 support.

[Framework registration examples →](https://agenttrafficcop.com/guide/#frameworks)

## Action Identity and Privacy

Include stable tool names and meaningful arguments in each payload.

Changing timestamps can hide exact repeats. Excluding business arguments can make distinct actions appear identical.

### Explicit exclusions

```python
guard = LocalGuard(
    ignore_paths=["/timestamp", "/request/id"],
)
```

Hosted checks accept exclusions with hash-only mode:

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

Paths are JSON pointers through objects, not array selectors or wildcards. Normalization uses a copy and does not modify the executed action.

### SDK 1.7.0 defaults

- LocalGuard excludes no fields unless configured.
- GuardRuntime defaults to hash-only hosted checks.
- Direct Guard/GuardSync checks default to raw payload transmission.
- The runtime metadata preset is **opt-in** through `normalize_volatile_metadata=True`.
- That 1.7.0 preset removes root `timestamp`, `request_id` and `trace_id`, plus those fields directly inside root `metadata`.

Hashes, session IDs, agent names and routing fields still reach the hosted service. Hashes reveal equality; they are not encryption or guaranteed anonymization.

[Normalization rules and data boundaries →](https://agenttrafficcop.com/guide/#identity)

## Dashboard, Shadow Mode and Review

Open **Dashboard → Recent Sessions → Inspect run** to inspect recorded decisions.

| Capability | Purpose |
|---|---|
| Shadow mode | Observe supported detector warnings without enforcing those warnings |
| Run timelines | Inspect recorded approvals, blocks and diagnostics |
| Threshold comparison | Evaluate deterministic policies over retained history |
| One-action review | Authorize one eligible retry without clearing detector history |
| Semantic evidence | Inspect explicitly submitted client-reported observations |

Important boundaries:

- Shadow approvals consume quota; authentication, spending and coordination failures still reject.
- Legacy `dry_run=True` is not server-side shadow evaluation.
- Review does not execute the action or bypass other controls.
- Threshold comparison does not rerun tools or change live policy.
- Semantic observations are client-reported, not verified semantic replay.
- Evidence is bounded to **200 records per run**, **10,000 per key**, and the plan’s retention window.
- Timelines are not complete execution traces or proof of savings.

[Dashboard behavior and limitations →](https://agenttrafficcop.com/guide/#dashboard)

## Plans and Availability

### Hosted allowances

| Allowance | Free | Pro | Team |
|---|---:|---:|---:|
| Monthly price | $0 | $49 | $199 |
| Approved checks / 30-day usage period | 10,000 | 250,000 | 2,000,000 |
| Tracked agents | 5 | 25 | 100 |
| Tier rate limit | 60/min | 120/min | 300/min |
| Active API keys | 2 | 5 | Higher configured capacity |
| Webhook destinations | 1 | 5 | Higher configured capacity |
| Default reported-spend threshold / 60s | $0.50 | $5 | $50 |
| Timeline retention* | 7 days | 30 days | 365 days |

Account-issued keys share an account-anchored 30-day usage period and tracked-agent allowance. Creating another key does not create fresh account quota.

*Retention remains subject to record caps. Configuration and commercial terms may differ.*

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

Local checks, semantic policies, normalization helpers, framework hooks, outage policies and configured-price accounting helpers have **no SDK paid-tier gate**. Hosted allowances, paid hosted controls and external provider charges still apply.

Team adds capacity, retention and custom hosted step/repeat limits—not unimplemented collaboration or shared-workspace features.

[Plans, storage and production requirements →](https://agenttrafficcop.com/guide/#production)

## Production and Failure Boundaries

- Hosted checks fail closed by default.
- Optional fail-open permits degraded continuation only after eligible connection-establishment failures.
- Degraded continuation is not hosted approval and cannot enforce hosted quotas, spending or history.
- Reserved execution requires actual hosted approval.
- Local and semantic histories are process-local.
- Redis-backed hosted detector history depends on deployment persistence and TTL.
- Budgets, reservations and timelines use a separate persistent ledger.
- Persistent timelines do not restore active detector history.
- Installing the SDK does not provision Redis or a database.

Server operators can use `ATC_REQUIRE_SHARED_STATE=true` to refuse startup without reachable Redis. Connectivity checks do not establish durability or backups.

Never assume a timeout means no charge, no execution or no recorded request.

[Failure handling and outage policies →](https://agenttrafficcop.com/guide/#recovery)

## Documentation

The website guide contains setup instructions, examples, API signatures, recovery requirements and version differences.

- [Getting started](https://agenttrafficcop.com/guide/#getting-started)
- [Local protection](https://agenttrafficcop.com/guide/#local)
- [Hosted protection and async](https://agenttrafficcop.com/guide/#hosted)
- [Identity, normalization and privacy](https://agenttrafficcop.com/guide/#identity)
- [Semantic blocking](https://agenttrafficcop.com/guide/#semantic)
- [Budgets and accounting](https://agenttrafficcop.com/guide/#budgets)
- [Framework integrations](https://agenttrafficcop.com/guide/#frameworks)
- [Failure recovery](https://agenttrafficcop.com/guide/#recovery)
- [API reference](https://agenttrafficcop.com/guide/#api)
- [Version differences](https://agenttrafficcop.com/guide/#versions)
- [Troubleshooting](https://agenttrafficcop.com/guide/#troubleshooting)
- [Download the guide as Markdown](https://agenttrafficcop.com/guide.md)

When asking an AI assistant to integrate AgentTrafficCop, provide the guide and specify your installed SDK version. Do not assume that unreleased source APIs exist in the published package.

## Links

[Website](https://agenttrafficcop.com) · [Dashboard](https://agenttrafficcop.com/dashboard.html) · [PyPI](https://pypi.org/project/agenttrafficcop/) · [SDK repository](https://github.com/belalshafeq/AgentTrafficCop-sdk) · [Issues](https://github.com/belalshafeq/AgentTrafficCop-sdk/issues)

## License

MIT. See [LICENSE](LICENSE).
