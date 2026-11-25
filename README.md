# AgentTrafficCop SDK

[![PyPI version](https://img.shields.io/pypi/v/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)
[![Python versions](https://img.shields.io/pypi/pyversions/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)

**Check the next agent action before it runs.**

AgentTrafficCop helps detect repeated actions, repeating cycles, and excessive steps in agent workflows. Use local checks without a network connection, or hosted checks for coordinated decisions, incident timelines, and reported-spending controls.

Your application must honor the result. Installing the SDK does not automatically protect every model or tool call.

## Installation

Requires **Python 3.11+**.

```bash
python -m pip install --upgrade 'agenttrafficcop==1.6.0'
```

Check the installed version:

```bash
python -c "from importlib.metadata import version; print(version('agenttrafficcop'))"
```

Base dependency: `httpx>=0.27.0,<0.29.0`. Optional framework integrations have additional dependencies.

## Choose Your Integration

| Option | Best for | Important boundary |
|---|---|---|
| `LocalGuard` | Offline repeat, cycle, and step checks | History stays in one guard instance |
| `GuardRuntime` | Unified sync/async checks, optional policies, and execution helpers | Requires the hosted API |
| `Guard` / `GuardSync` | Direct async/sync hosted clients | You manage the client lifecycle |

### Main Capabilities

- **Deterministic checks:** exact repeats, repeating sequences, and approved-step limits.
- **Payload normalization:** explicit field exclusions; optional scoped metadata normalization through `GuardRuntime`.
- **Semantic policies:** experimental warnings or opt-in blocking using your embedding encoder.
- **Hosted controls:** shadow mode, bounded timelines, threshold comparisons, and owner-reviewed one-action continuation.
- **Spending controls:** report-driven limits and Pro/Team estimated-cost reservations.
- **Usage accounting:** configured-price adapters for supported non-streaming OpenAI and Anthropic token usage.
- **Integration hooks:** supported LangGraph, CrewAI, current AutoGen, and MCP tool-call paths.

These features are not all enabled automatically. See the examples and boundaries below.

## Quick Start: Local Checks

No account, API key, or network connection is required.

```python
from agenttrafficcop import LocalGuard

guard = LocalGuard(max_repeats=3, max_steps=50)

action = {
    "tool": "search_docs",
    "arguments": {"query": "refund policy"},
}

for _ in range(3):
    result = guard.check(session_id="run-1", payload=action)

    if not result.approved:
        print("Action not executed:", result.reason)
        break

    # Execute your protected action here.
    print("Approved step", result.step)
```

Output:

```text
Approved step 1
Approved step 2
Action not executed: REPEATED_PAYLOAD_LOOP
```

Reuse the **same guard instance and session ID** throughout a run. Creating a new guard or changing the session ID starts independent history.

### Local Configuration

| Option | Default |
|---|---:|
| `max_repeats` | `3` |
| `max_steps` | `50` |
| `max_cycle_length` | `2` |
| `max_cycle_repeats` | `3` |
| `max_sessions` | `1000` |
| `session_ttl` | `3600` seconds |
| `ignore_paths` | No exclusions |

`check()` returns a `LocalResult` containing `approved`, `session_id`, `step`, `payload_hash`, and `reason`.

Rejection reasons:

- `REPEATED_PAYLOAD_LOOP`
- `CYCLIC_PAYLOAD_LOOP`
- `STEP_LIMIT_EXCEEDED`
- `LOCAL_CAPACITY_EXCEEDED`

Invalid inputs raise `ValueError`. Do not execute after a rejected or failed check.

**Local boundaries:**

- History is thread-safe within one instance, but not shared across instances or processes.
- Restart, inactivity expiry, or `guard.reset(session_id)` removes history.
- New sessions are rejected at capacity rather than evicting active protection.
- Local checks do not enforce hosted quotas or spending controls.
- An approved step records a check—not proof that an action executed.

## Quick Start: Hosted Checks

1. Create an account and generate a key at the [dashboard](https://agenttrafficcop.com/dashboard.html).
2. Store the key in your environment:

```bash
export ATC_API_KEY="your-api-key"
```

3. Check immediately before execution:

```python
import os
import uuid

from agenttrafficcop import AgentTrafficCopError, GuardRuntime

runtime = GuardRuntime(
    url="https://api.agenttrafficcop.com",
    api_key=os.environ["ATC_API_KEY"],
)

run_id = uuid.uuid4().hex

try:
    decision = runtime.check(
        session_id=run_id,
        sender="planner",
        recipient="search",
        payload={"tool": "search", "arguments": {"query": "refund policy"}},
    )
except AgentTrafficCopError as exc:
    print("Action not executed:", exc.error_code)
else:
    if decision.execution_allowed:
        # Execute your protected action here.
        print("Approved")
```

Reuse `run_id` for subsequent checks in that run.

For async applications, use the same runtime:

```python
decision = await runtime.acheck(
    session_id=run_id,
    sender="planner",
    recipient="search",
    payload={"tool": "search", "arguments": {"query": "refund policy"}},
)
```

`GuardRuntime` manages short-lived HTTP clients for each call. Use `acheck()` inside an event loop.

### Direct Hosted Clients

For explicit lifecycle management and connection reuse:

```python
from agenttrafficcop import GuardSync

with GuardSync(
    url="https://api.agenttrafficcop.com",
    api_key="YOUR_API_KEY",
    dry_run=False,
) as guard:
    result = guard.check(
        session_id="run-1",
        sender="planner",
        recipient="worker",
        payload={"task": "review patch"},
        hash_only=True,
    )

    if result.approved:
        # Execute your protected action here.
        pass
```

The async equivalent is `async with Guard(...)` and `await guard.check(...)`.

## Payload Identity and Privacy

Exact-repeat checks depend on the fields included in the action hash. Changing timestamps or request IDs can hide repeats; removing meaningful arguments can merge different actions.

### Explicit Field Exclusions

```python
guard = LocalGuard(ignore_paths=["/timestamp", "/request/id"])
```

For direct hosted clients:

```python
result = await guard.check(
    session_id=run_id,
    sender="planner",
    recipient="worker",
    payload=action,
    hash_only=True,
    ignore_paths=["/timestamp"],
)
```

Paths are explicit JSON pointers through objects—not array selectors or wildcards. The original action is not modified.

### Optional Runtime Metadata Preset

```python
runtime = GuardRuntime(
    url="https://api.agenttrafficcop.com",
    api_key="YOUR_API_KEY",
    normalize_volatile_metadata=True,
)
```

This removes `timestamp`, `request_id`, and `trace_id` at the payload root and directly inside its root `metadata` object.

It is **off by default**, requires hash-only mode, and does not recursively strip tool arguments or arrays. Review your schema before enabling it.

### Hash-Only Mode

- `GuardRuntime` defaults to hash-only checks.
- Direct `Guard` and `GuardSync` checks default to raw payload transmission.
- Hash-only requests omit raw payloads and reject request metadata.
- Hashes, session IDs, routing fields, and agent names still reach the server.
- Hashes reveal equality and are not encryption or guaranteed anonymization.
- The server cannot prove that a submitted hash matches the action eventually executed.

## Experimental Semantic Policies

Deterministic checks compare hashes—not meaning. To detect potentially similar or paraphrased actions, supply an embedding encoder:

```python
from agenttrafficcop import GuardRuntime, SemanticMonitor

# encode_text is your synchronous text -> list[float] embedding function.
monitor = SemanticMonitor(
    encode_text,
    model_id="your-model-and-version",
)

runtime = GuardRuntime(
    url="https://api.agenttrafficcop.com",
    api_key="YOUR_API_KEY",
    semantic_monitor=monitor,
    semantic_mode="block",  # Default: "warn"
)

decision = runtime.check(
    session_id="run-1",
    sender="planner",
    recipient="search",
    payload={"query": "refund policy"},
    semantic_text="Find the refund rules",
)
```

**Important:**

- No embedding model is bundled or downloaded automatically.
- Your encoder may transmit text externally.
- Semantic history is bounded, process-local, and tracks attempted checks—not confirmed executions.
- False positives and missed loops are possible.
- Block mode stops on a semantic warning or unavailable monitoring.
- Optional hosted evidence is labelled **client-reported**, not a verified hosted decision.

Evaluate your encoder and thresholds against your own workflows before enabling blocking.

## Outage Behavior

Hosted checks **fail closed by default**.

`OutagePolicy` supports up to two connection-establishment retries and an optional redacted synchronous event callback. Ambiguous read/write failures and HTTP errors are not automatically retried.

`GuardRuntime` also supports explicit connection-only fail-open:

```python
runtime = GuardRuntime(
    url="https://api.agenttrafficcop.com",
    api_key="YOUR_API_KEY",
    failure_mode="fail_open",
)
```

During eligible connection failures, the result has:

```text
execution_allowed=True
approved=False
degraded=True
```

This is **not a hosted approval**. Hosted spending, quota, and history protections are unavailable during that continuation.

Fail-open does not bypass HTTP rejections, ambiguous delivery errors, semantic blocks, or authentication failures. Reserved execution helpers require an actual hosted approval.

## Spending Controls

Hosted spending protection uses **trusted reported costs**. Setting a budget does not connect provider billing.

| Control | Scope | Availability |
|---|---|---|
| Rolling reported-spend threshold | API key | All hosted tiers |
| Cumulative run budget | API key + session | Pro/Team |
| Estimated-cost reservations | API key + session | Pro/Team |

### Set a Run Budget

Inside an open `GuardSync` context:

```python
budget = guard.set_run_budget(
    session_id=run_id,
    budget_usd="2.00",
)
```

Async clients support `await guard.set_run_budget(...)`.

Updating a budget preserves reported spending. Budgets do not reset monthly; use a new session ID for an independent run.

### Reservations and Usage Accounting

SDK 1.6.0 adds helpers to:

1. Check the action.
2. Reserve estimated spending before execution.
3. Refuse duplicate reservations as execution permission.
4. Execute the supplied callable once.
5. Extract supported usage and submit trusted final-cost settlement.

Unused estimated budget is released through settlement. Unknown execution outcomes, cancellation, missing usage, or failed reports leave holds unresolved.

Usage adapters support configured-price, **non-streaming text-token usage** from OpenAI and Anthropic. They do not automatically cover every provider charge, streaming response, audio charge, discount, or service tier.

> Reservations are not guaranteed hard spending caps. Underestimated costs and unreserved calls can exceed a budget.

### Trusted Reporting

Cost ingestion requires timestamped HMAC authentication. An ordinary API key does not grant the operator signing secret.

Keep signing secrets on a trusted reporting backend—never in browser code or an untrusted agent.

If reporting fails after execution, retry the **same cost report**, not the provider action. Keep stable operation and event IDs in a durable application ledger.

## Framework and MCP Hooks

Installing the SDK does not instrument your application automatically. Register the tools or nodes you want protected.

| Integration | SDK helper | Tested version |
|---|---|---|
| LangGraph | `guard_langgraph` | `1.2.24` |
| CrewAI | `guard_crewai_tools` | `1.15.45` |
| AutoGen AgentChat | `guard_autogen_tools` | AgentChat/core `0.7.5` |
| MCP | `runtime.mcp_client(...)` | `1.30.0` |
| Generic callables | `runtime.wrap(...)` / `guard_functions` | Sync/async, non-streaming |

Optional installation examples:

```bash
python -m pip install 'agenttrafficcop[langgraph]==1.6.0'
python -m pip install 'agenttrafficcop[crewai]==1.6.0'
python -m pip install 'agenttrafficcop[autogen-agentchat]==1.6.0'
python -m pip install 'agenttrafficcop[mcp]==1.6.0'
```

Only registered paths are protected. Unsupported node types, streaming paths, existing unwrapped nodes, and direct calls outside the hooks are not automatically covered.

The separate legacy AutoGen adapter supports `pyautogen==0.2.35`; it is not interchangeable with current AgentChat or AG2.

## Shadow Mode, Review, and Evidence

### Shadow Mode

Direct hosted clients accept `mode="shadow"` to return supported detector warnings without blocking those actions.

- Approved shadow checks consume message quota.
- Authentication, budgets, quotas, and coordination failures still reject.
- Shadow and enforcement histories are separate.
- Legacy `dry_run=True` is not equivalent to server-side shadow evaluation.

Use shadow mode only when continuing past detector warnings is acceptable.

### Human Review

Account owners can review eligible repeat, cycle, or step-limit blocks in the dashboard and approve one retry of the exact action.

Approvals expire, require unchanged detector history, preserve that history, and do not bypass other rules, budgets, quotas, or authentication. Review does not execute the action.

### Timelines and Replay

Open **Dashboard → Recent Sessions → Inspect run** to inspect recorded decisions, rule explanations, hashes, and bounded diagnostics.

Threshold comparison evaluates the retained deterministic sequence without rerunning tools or changing live settings. Optional semantic evidence is shown for reference—it is not recomputed semantic replay.

Evidence is bounded to the latest **200 records per run**, up to **10,000 per key**, within plan retention. It is not a complete execution trace or proof of savings.

## History and Deployment

- **LocalGuard:** in-memory history within one instance.
- **Memory-backed hosted state:** process-local and lost on restart.
- **Redis-backed hosted state:** shared across compatible workers, subject to Redis persistence and expiry configuration.
- **Timelines and spending records:** require their own persistent database storage.
- **SemanticMonitor:** local embedding memory, not shared by hosted Redis.

Persistent timelines do not restore active detector history.

The server supports `ATC_REQUIRE_SHARED_STATE=true` to refuse startup without reachable Redis. This checks connectivity—not disk durability or backups. Production Redis must still be configured and verified by the operator.

## Hosted Plans

Local checks require no account and consume no hosted quota.

| Capability | Free | Pro | Team |
|---|---:|---:|---:|
| Monthly price | $0 | $49 | $199 |
| Approved messages per usage period | 10,000 | 250,000 | 2,000,000 |
| Tracked agents | 5 | 25 | 100 |
| Tier rate limit | 60/min | 120/min | 300/min |
| Shadow mode and timelines | Yes | Yes | Yes |
| Schema-change detection | — | Yes | Yes |
| Run budgets and reservations | — | Yes | Yes |
| Custom hosted step/repeat limits | — | — | Yes |
| Listed retention | 7 days | 30 days | 1 year |

Account-issued keys share an account-anchored **30-day usage period** and tracked-agent allowance. Creating another key does not create fresh account quota.

Run budgets, reservations, and timelines are **API key + session scoped**.

Configuration can override defaults. See the [website](https://agenttrafficcop.com) for current commercial terms.

## Failure Handling

- Inspect local results; invalid local inputs raise `ValueError`.
- Catch `AgentTrafficCopError` for direct hosted checks.
- Direct budget and reservation helpers expose HTTPX failures.
- Runtime callbacks, accounting, and validation can raise additional errors.
- Unless deliberately using the documented degraded policy, stop after any failed check.
- Never assume a timeout means the server recorded nothing.
- Never retry an executed action because its response or cost report failed.

No guard can protect execution paths that bypass it. Keep session IDs, policy selection, reset operations, and reporting authority under trusted application control.

## Validation

SDK 1.6.0 release validation included:

- **739 passing Python tests**, with **3 expected skips**.
- **6 framework/MCP integration tests**.
- Real Redis restart and independent-process coordination tests.
- Dashboard and landing behavior/security checks.
- Strict wheel/source-distribution checks.
- **20 clean-installed-package checks** and fresh PyPI installation verification.
- Passing final PR, post-merge CI, and release verification runs.

These results do not establish semantic-model accuracy, production Redis configuration, every customer integration, or actual provider billing accuracy.

## Links

- [Website](https://agenttrafficcop.com)
- [Dashboard](https://agenttrafficcop.com/dashboard.html)
- [PyPI](https://pypi.org/project/agenttrafficcop/)
- [SDK repository](https://github.com/belalshafeq/AgentTrafficCop-sdk)
- [Issues](https://github.com/belalshafeq/AgentTrafficCop-sdk/issues)

## License

MIT. See [LICENSE](LICENSE).
