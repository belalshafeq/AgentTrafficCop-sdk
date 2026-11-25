# AgentTrafficCop SDK

[![PyPI version](https://img.shields.io/pypi/v/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)
[![Python versions](https://img.shields.io/pypi/pyversions/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)

**Check the next agent action before it runs.**

AgentTrafficCop helps detect repeated actions, repeating cycles, and excessive steps in agent workflows. Choose offline local checks or hosted checks with incident timelines, usage quotas, and reported-spending controls.

Your application must honor the result. Installing the SDK does not automatically protect every model or tool call.

## Installation

Requires **Python 3.11+**.

```bash
python -m pip install --upgrade 'agenttrafficcop==1.6.0'
```

Check your installed version:

```bash
python -c "from importlib.metadata import version; print(version('agenttrafficcop'))"
```

Base dependency: `httpx>=0.27.0,<0.29.0`. Optional framework integrations have additional dependencies.

## Choose Your Integration

| Option | Use it for | Important boundary |
|---|---|---|
| `LocalGuard` | Offline exact-repeat, cycle, and step checks | History belongs to one guard instance |
| `GuardRuntime` | Unified sync/async checks, optional policies, and execution helpers | Requires the hosted API |
| `Guard` / `GuardSync` | Direct async/sync hosted clients | You manage the client lifecycle |

### Capabilities

- **Deterministic detection:** exact repeats, repeating sequences, and approved-step limits.
- **Payload normalization:** explicit field exclusions and an optional scoped metadata preset.
- **Semantic policies:** experimental warnings or opt-in blocking using your embedding encoder.
- **Hosted evidence:** bounded timelines, threshold comparison, and client-reported semantic observations.
- **Human review:** owner-authorized, one-action continuation without clearing detector history.
- **Spending controls:** report-driven limits, run budgets, and estimated-cost reservations.
- **Usage accounting:** configured-price adapters for supported non-streaming OpenAI and Anthropic token usage.
- **Framework hooks:** supported LangGraph, CrewAI, current AutoGen, and MCP execution paths.

Advanced policies and integrations require explicit configuration. They are not enabled merely by installing the SDK.

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

Reuse the **same guard instance and session ID** throughout a run. A new guard or session ID starts independent history.

### Local Configuration

| Option | Default | Purpose |
|---|---:|---|
| `max_repeats` | `3` | Consecutive identical-action threshold |
| `max_steps` | `50` | Maximum approved checks per session |
| `max_cycle_length` | `2` | Largest repeating sequence checked |
| `max_cycle_repeats` | `3` | Sequence repetitions that trigger rejection |
| `max_sessions` | `1000` | Maximum retained, unexpired sessions |
| `session_ttl` | `3600` seconds | Inactivity expiry |
| `ignore_paths` | No exclusions | Explicit fields omitted before hashing |

`check()` returns a `LocalResult` with:

- `approved`
- `session_id`
- `step`
- `payload_hash`
- `reason`

Local rejection codes are `REPEATED_PAYLOAD_LOOP`, `CYCLIC_PAYLOAD_LOOP`, `STEP_LIMIT_EXCEEDED`, and `LOCAL_CAPACITY_EXCEEDED`.

Invalid inputs raise `ValueError`. Do not execute after a rejected or failed check.

**Local boundaries:**

- Checks are atomic and thread-safe within one instance.
- Separate instances and processes do not share history.
- Restart, inactivity expiry, or `guard.reset(session_id)` removes history.
- New sessions are rejected at capacity rather than evicting active protection.
- Local checks do not enforce hosted quotas, schema-change rules, or spending controls.
- Approved steps count checks—not verified executions.

## Quick Start: Hosted Checks

Create an account and generate an API key at the [dashboard](https://agenttrafficcop.com/dashboard.html).

```bash
export ATC_API_KEY="your-api-key"
```

Check immediately before execution:

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
        payload={
            "tool": "search",
            "arguments": {"query": "refund policy"},
        },
    )
except AgentTrafficCopError as exc:
    print("Action not executed:", exc.error_code)
else:
    if decision.execution_allowed:
        # Execute your protected action here.
        print("Approved")
```

Reuse `run_id` for subsequent checks in that run.

For async applications:

```python
decision = await runtime.acheck(
    session_id=run_id,
    sender="planner",
    recipient="search",
    payload={"tool": "search", "arguments": {"query": "refund policy"}},
)
```

`GuardRuntime` creates and closes a client per call. Use `acheck()` inside an event loop.

### Direct Hosted Clients

For explicit lifecycle management and connection reuse:

```python
import os

from agenttrafficcop import GuardSync

with GuardSync(
    url="https://api.agenttrafficcop.com",
    api_key=os.environ["ATC_API_KEY"],
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

Exact-repeat detection depends on the fields included in the hash. Changing timestamps or request IDs can hide repeats; excluding meaningful arguments can make distinct actions appear identical.

### Explicit Field Exclusions

Local:

```python
guard = LocalGuard(ignore_paths=["/timestamp", "/request/id"])
```

Inside an open hosted `Guard` context:

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

Paths are JSON pointers through objects—not array selectors or wildcards. The original action is not modified.

### Optional Metadata Preset

```python
runtime = GuardRuntime(
    url="https://api.agenttrafficcop.com",
    api_key="YOUR_API_KEY",
    normalize_volatile_metadata=True,
)
```

This removes exact-case `timestamp`, `request_id`, and `trace_id` fields at the payload root and directly inside its root `metadata` object.

It is **off by default**, requires hash-only mode, and does not recursively strip tool arguments or arrays. Review your action schema before enabling it.

### Hash-Only Mode

- `GuardRuntime` defaults to hash-only checks.
- Direct `Guard` and `GuardSync` checks default to raw payload transmission.
- Hash-only requests omit raw payloads and reject separate request metadata.
- Hashes, session IDs, agent names, and routing fields still reach the server.
- Hashes reveal equality; they are not encryption or guaranteed anonymization.
- The server cannot prove that a submitted hash matches the action eventually executed.

## Experimental Semantic Policies

Deterministic checks compare hashes—not meaning. Supply an embedding encoder to identify potentially similar or paraphrased attempts:

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

- No embedding model is bundled or downloaded automatically.
- Your encoder may transmit text externally and incur separate charges.
- History is bounded, process-local, and tracks attempted checks—not confirmed executions.
- False positives and missed loops are possible.
- Block mode stops on a semantic warning or unavailable monitoring.
- Optional hosted evidence is labelled **client-reported**, not a verified hosted decision.

Semantic policies have **no paid-plan gate**, but hosted checks still use the applicable account allowances.

## Outage Behavior

Hosted checks **fail closed by default**.

`OutagePolicy` supports up to two connection-establishment retries and an optional redacted synchronous failure callback. Ambiguous read/write failures and HTTP errors are not automatically retried.

Explicit connection-only fail-open is available through `GuardRuntime`:

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

Fail-open does not bypass HTTP rejections, ambiguous delivery errors, semantic blocks, or authentication failures. Reserved execution requires an actual hosted approval.

## Spending Controls and Accounting

Hosted spending protection evaluates **trusted reported costs**. Setting a budget does not connect provider billing.

| Control | Scope | Availability |
|---|---|---|
| Default rolling reported-spend threshold | API key | All hosted tiers |
| Custom rolling spend threshold | API key | Pro/Team |
| Cumulative run budget | API key + session | Pro/Team |
| Estimated-cost reservations | API key + session | Pro/Team |

### Run Budgets

Inside an open `GuardSync` context:

```python
budget = guard.set_run_budget(
    session_id=run_id,
    budget_usd="2.00",
)
```

Async clients support `await guard.set_run_budget(...)`.

Changing a budget preserves accumulated spending. Budgets do not reset monthly; use a new session ID for an independent run.

### Reserved Execution

`GuardRuntime.execute(...)` and `aexecute(...)` can:

1. Check the action.
2. Reserve estimated spending before execution.
3. Refuse duplicate reservations as execution permission.
4. Execute the supplied callable once.
5. Extract supported usage and submit trusted final-cost settlement.

Settlement releases unused estimated budget. Unknown execution outcomes, cancellation, missing usage, or failed reports leave holds unresolved.

Persist stable operation IDs in your application ledger. Never treat a duplicate reservation as permission to execute again.

### Usage Accounting

`UsageAccountant` extracts supported **non-streaming text-token usage** from OpenAI and Anthropic responses using caller-configured prices for exact model names.

These SDK helpers have no paid-tier gate. However:

- Hosted signed ingestion requires an authorized reporting integration.
- Reservation-based execution requires Pro/Team.
- Streaming, audio, tool fees, discounts, and other billing variations may require custom handling.
- Missing usage or unknown pricing is not silently reported as zero.

Keep ingestion-signing secrets on a trusted backend—never in browser code or an untrusted agent.

If reporting fails after execution, retry the **same cost report**, not the provider action.

> Report-driven controls and estimated reservations are not guaranteed hard spending caps. Delayed reports, underestimated costs, and unreserved calls can cause overshoot.

## Framework and MCP Hooks

Register the nodes or tools you want protected:

| Integration | Helper | Tested version |
|---|---|---|
| LangGraph | `guard_langgraph` | `1.2.24` |
| CrewAI | `guard_crewai_tools` | `1.15.45` |
| AutoGen AgentChat | `guard_autogen_tools` | AgentChat/core `0.7.5` |
| MCP | `runtime.mcp_client(...)` | `1.30.0` |
| Generic callables | `runtime.wrap(...)` / `guard_functions` | Sync/async, non-streaming |

Optional installations:

```bash
python -m pip install 'agenttrafficcop[langgraph]==1.6.0'
python -m pip install 'agenttrafficcop[crewai]==1.6.0'
python -m pip install 'agenttrafficcop[autogen-agentchat]==1.6.0'
python -m pip install 'agenttrafficcop[mcp]==1.6.0'
```

Only registered execution paths are protected. Existing unwrapped nodes, unsupported node types, streaming paths, and direct calls outside the hooks are not automatically covered.

The separate legacy AutoGen adapter supports `pyautogen==0.2.35`; it is not interchangeable with current AgentChat or AG2.

## Shadow Mode, Review, and Evidence

### Shadow Mode

Direct hosted clients accept `mode="shadow"` to return supported detector warnings without blocking those actions.

- Approved shadow checks consume message quota.
- Authentication, spending, quotas, and coordination failures still reject.
- Shadow and enforcement histories are separate.
- Legacy `dry_run=True` is not server-side shadow evaluation.

Use shadow mode only when continuing past detector warnings is acceptable.

### Human Review

Account owners can review eligible repeat, cycle, or step-limit blocks in the dashboard and approve one retry of the exact action.

Approvals expire, require unchanged detector history, and preserve that history. They do not bypass other rules, authentication, quotas, or spending controls.

Review does not execute the action; your application must retry its check.

### Timelines and Threshold Comparison

Open **Dashboard → Recent Sessions → Inspect run** to inspect recorded decisions, hashes, triggered rules, and bounded diagnostics.

Threshold comparison evaluates retained deterministic sequences without rerunning tools or changing live settings. Semantic observations are reference evidence—not recomputed semantic replay.

Timeline evidence is limited to:

- The latest **200 records per run**
- Up to **10,000 records per API key**
- The applicable plan’s retention period

It is not a complete execution trace or proof of savings.

## Plans and Feature Availability

Local checks require no hosted account and consume no hosted quota.

### Hosted Allowances

| Allowance | Free | Pro | Team |
|---|---:|---:|---:|
| Monthly price | $0 | $49 | $199 |
| Approved messages per usage period | 10,000 | 250,000 | 2,000,000 |
| Tracked agents | 5 | 25 | 100 |
| Tier rate limit | 60/min | 120/min | 300/min |
| Active API keys | 2 | 5 | High implementation cap |
| Webhook destinations | 1 | 5 | High implementation cap |
| Default rolling reported-spend threshold | $0.50 / 60s | $5 / 60s | $50 / 60s |
| Timeline retention¹ | 7 days | 30 days | 365 days |

¹ Retention is subject to the record limits above—not a guarantee of a complete archive.

Account-issued keys share an account-anchored **30-day usage period** and tracked-agent allowance. Creating another key does not create fresh account quota.

Run budgets, reservations, and timelines are **API key + session scoped**.

### Feature Matrix

| Feature | Free | Pro | Team |
|---|:---:|:---:|:---:|
| Exact-repeat, cycle, and step checks | ✓ | ✓ | ✓ |
| Shadow mode | ✓ | ✓ | ✓ |
| Timelines and threshold comparison | ✓ | ✓ | ✓ |
| Owner-reviewed one-action continuation | ✓ | ✓ | ✓ |
| Client-reported semantic evidence | ✓ | ✓ | ✓ |
| Default rolling reported-spend protection² | ✓ | ✓ | ✓ |
| Custom rolling spend thresholds | — | ✓ | ✓ |
| Run budgets and estimated reservations | — | ✓ | ✓ |
| Schema-change detection | — | ✓ | ✓ |
| Custom hosted step/repeat limits | — | — | ✓ |

² Requires authorized cost reporting.

The following SDK capabilities have **no paid-tier gate**:

- Local checks and explicit payload normalization
- Optional runtime metadata normalization
- Experimental semantic warnings and blocking
- Unified sync/async runtime
- Framework/MCP registration hooks
- Outage policies
- Configured-price usage-accounting helpers

Hosted requests still require an API key and follow their applicable allowances. Encoder/provider charges and optional framework dependencies are separate.

**Pro versus Team:** most capabilities are shared. Team adds custom hosted step/repeat limits, higher usage and agent allowances, a higher rate limit, more key/webhook capacity, and longer retention. Shared workspaces or other collaboration features are not implied.

Configuration can override defaults. See the [website](https://agenttrafficcop.com) for current commercial terms.

## History and Deployment Boundaries

| State | Storage boundary |
|---|---|
| `LocalGuard` history | In-memory, one instance |
| Memory-backed hosted detector history | One process; lost on restart |
| Redis-backed hosted detector history | Shared compatible workers; depends on persistence and TTL |
| Timelines and spending records | Separate persistent database |
| Semantic embeddings | Local monitor memory; not shared by hosted Redis |

Persistent timelines do not restore active detector history.

The server supports `ATC_REQUIRE_SHARED_STATE=true` to refuse startup without reachable Redis. This checks connectivity—not disk durability or backups.

**Redis durability is a deployment configuration, not a paid-tier feature.** Production storage must be configured and verified separately.

## Failure Handling

- Inspect local results; invalid local inputs raise `ValueError`.
- Catch `AgentTrafficCopError` for direct hosted checks.
- Direct budget and reservation helpers expose HTTPX failures.
- Runtime callbacks, validation, and accounting can raise additional errors.
- Unless explicitly using the documented degraded policy, stop after any failed check.
- Do not assume a timeout means the server recorded nothing.
- Never retry an executed action because its response or cost report failed.

Keep session IDs, reset operations, policy selection, and reporting authority under trusted application control. Unwrapped execution paths remain unprotected.

## Validation

SDK 1.6.0 release validation included:

- **739 passing Python tests**, with **3 expected skips**
- **6 framework/MCP integration tests**
- Real Redis restart and independent-process coordination tests
- Dashboard and landing behavior/security checks
- Strict wheel and source-distribution checks
- **20 clean-installed-package checks** and fresh PyPI installation verification
- Passing final PR, post-merge CI, and release verification runs

These results do not establish semantic-model accuracy, production Redis configuration, every customer integration, or actual provider billing accuracy.

## Links

- [Website](https://agenttrafficcop.com)
- [Dashboard](https://agenttrafficcop.com/dashboard.html)
- [PyPI](https://pypi.org/project/agenttrafficcop/)
- [SDK repository](https://github.com/belalshafeq/AgentTrafficCop-sdk)
- [Issues](https://github.com/belalshafeq/AgentTrafficCop-sdk/issues)

## License

MIT. See [LICENSE](LICENSE).
