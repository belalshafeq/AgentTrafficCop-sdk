# AgentTrafficCop SDK

[![PyPI version](https://img.shields.io/pypi/v/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)
[![Python versions](https://img.shields.io/pypi/pyversions/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)

**Check the next agent action before it runs.**

Catch repeated actions, repeating cycles, and step-limit overruns. Start locally without an account, or use hosted checks for coordinated decisions, run timelines, and reported-spending controls.

**Installing the SDK does not automatically protect every call.** Your application must check or wrap each execution boundary you want protected—and honor rejected or failed checks.

[Developer guide](https://agenttrafficcop.com/guide/) · [Dashboard](https://agenttrafficcop.com/dashboard.html) · [API reference](https://agenttrafficcop.com/guide/#api)

## Install

Requires **Python 3.11+**.

```bash
python -m pip install --upgrade 'agenttrafficcop==2.2.0'
python -c "from importlib.metadata import version; print(version('agenttrafficcop'))"
```

SDK 2.0 changed `GuardRuntime`’s default metadata normalization: root `timestamp`, `request_id`, and `trace_id` fields are stripped by default; nested fields are preserved. For strict 1.x hashing, set `normalize_volatile_metadata=False` explicitly. Use a new session ID when migrating an active workflow.

SDK 2.1 added optional OpenAI-compatible BYOK gateway helpers and opt-in trace batching. SDK 2.2 added checkpointed LangGraph review support with exact-action verification before a resumed node runs.

[Version differences and migration notes →](https://agenttrafficcop.com/guide/#versions)

## Choose an integration

| You want to… | Use |
|---|---|
| Try offline loop protection without credentials | `LocalGuard` |
| Check actions through the hosted API | `GuardRuntime.check()` / `acheck()` |
| Configure a budget-protected run | `runtime.run(...)` |
| Check, reserve, execute, report, and settle | `run.execute()` / `aexecute()` |
| Flag similar meanings across differently worded actions | `SemanticMonitor` |
| Sanitize provider text and authorize tools | `SecurityGuard` |
| Recover from eligible provider failures | `RecoveryHooks` |
| Manage hosted connections explicitly | `Guard` / `GuardSync` |
| Protect selected framework paths | Explicit framework registration hooks |

## Local protection

This example executes a tool twice, then blocks the third identical attempt. No account, API key, or network connection is required.

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
- Separate processes do not share local history.
- Restart, inactivity expiry, or reset removes history.
- Local checks do not enforce hosted quotas, schema detection, or spending controls.
- Approved steps count checks—not verified tool executions.

Invalid inputs raise `ValueError`. Do not execute after a rejected or failed check.

[Local configuration and return values →](https://agenttrafficcop.com/guide/#local)

## Hosted protection

Create an API key in the [dashboard](https://agenttrafficcop.com/dashboard.html), then keep it in an environment variable or secret manager.

```bash
export ATC_API_KEY="your-api-key"
```

Check immediately before executing the protected action:

```python
import os
import uuid

from agenttrafficcop import AgentTrafficCopError, GuardSync


def search_docs(query):
    return f"Found documentation for: {query}"


run_id = uuid.uuid4().hex

with GuardSync(
    url="https://api.agenttrafficcop.com",
    api_key=os.environ["ATC_API_KEY"],
) as guard:
    try:
        decision = guard.check(
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
        raise
    else:
        if decision.execution_allowed:
            print(search_docs("refund policy"))
```

Reuse the same `run_id` for actions in the same run. For async applications, use `async with Guard(...)` and `await guard.check(...)`.

**Hosted checks fail closed by default.** Other validation or callback errors should also stop execution. Do not catch an error and continue unguarded.

[Hosted checks and async usage →](https://agenttrafficcop.com/guide/#hosted)

## Semantic loop detection

Deterministic detection compares hashes—not meaning. Experimental semantic monitoring can flag similar meanings across differently worded actions.

**This is semantic loop detection, not semantic caching.** It does not store or reuse model answers. Semantic observations are advisory—not an authorization or safety decision.

Set your OpenAI key in the environment:

```bash
export OPENAI_API_KEY="your-openai-api-key"
```

Then create and attach a monitor:

```python
import os

from agenttrafficcop import GuardRuntime, SemanticMonitor

monitor = SemanticMonitor.openai()
runtime = GuardRuntime(
    url="https://api.agenttrafficcop.com",
    api_key=os.environ["ATC_API_KEY"],
    semantic_monitor=monitor,
    semantic_mode="block",  # Explicit opt-in; the default is "warn".
)
```

In `block` mode, the runtime can stop execution on a semantic warning or unavailable monitoring. Handle rejection and failure before executing.

### Shared history and local ONNX

Redis sharing is optional. The local ONNX encoder requires model files you supply:

```bash
python -m pip install 'agenttrafficcop[semantic-redis,semantic-onnx]==2.2.0'
```

```python
import os

from agenttrafficcop import SemanticMonitor

monitor = SemanticMonitor.onnx(
    "/models/reviewed-model.onnx",
    "/models/tokenizer.json",
    model_id="reviewed-model-v1",
    redis_url=os.environ["REDIS_URL"],
)
```

History is bounded by configured capacity and TTL. Redis sharing applies only to monitors configured with the same compatible Redis namespace; it does not share hosted detector history, budgets, or reservations. The ONNX adapter does not download or bundle model weights. Operators must supply and review compatible model and tokenizer files.

### Semantic boundaries

- Constructing `SemanticMonitor.openai()` does not make a request; observing text sends it to OpenAI and may incur charges.
- The default OpenAI embedding model is `text-embedding-3-small`.
- BYO synchronous embedding encoders are supported.
- Default runtime semantic mode is `warn`; `block` must be selected explicitly.
- Similarity may produce false positives or miss loops. It is not a safety classifier, authorization mechanism, or semantic cache.

[Complete semantic examples, tuning, and BYO setup →](https://agenttrafficcop.com/guide/#semantic)

## Security and permissions

`SecurityGuard` provides explicit text sanitization, tool authorization, and approval checks. This example assumes `authenticated_role` comes from trusted application authentication and `approval_service` performs a real human-review process.

```python
from agenttrafficcop import SecurityGuard, SecurityPolicyError

security = SecurityGuard(
    {"operator": {"search", "delete_record"}},
    approval_required={"delete_record"},
)

scan = security.sanitize_text(user_supplied_text)
if not scan.allowed:
    raise SecurityPolicyError("Input needs review")

protected_delete = security.wrap_tool(
    delete_record,
    tool="delete_record",
    role=authenticated_role,
    approver=approval_service,
)
```

Tools are default-deny unless allowed for the supplied role. Approval-required tools proceed only when the approver returns exactly `True`.

The OpenAI-compatible Chat Completions and Anthropic Messages wrappers sanitize inspected text and reject unsupported multimodal blocks rather than passing unscanned content through. They do not patch provider clients globally. Framework and MCP wrappers accept optional security controls, but only explicitly wrapped or registered paths are protected.

Detection is heuristic: it flags a limited set of prompt-injection patterns and redacts common PII and credential forms. It is not comprehensive injection or PII detection, a safety guarantee, or a substitute for trusted identity, authorization policy, or human review.

[Security helper examples and limitations →](https://agenttrafficcop.com/guide/#sdk-20)

## Provider recovery

`RecoveryHooks` supports bounded, caller-controlled retries and optional fallback-model routing. The retry cap is three. Provider adapters retry explicit HTTP 429 responses by default. Timeouts, connection failures, and other statuses are not retried by default because request completion may be ambiguous.

```python
from agenttrafficcop import RecoveryHooks

recovered_create = RecoveryHooks(
    max_retries=1,
    fallback_model="your-backup-model",
).wrap_openai_chat(openai_client.chat.completions.create)
```

Recovery instructions and model routing apply to model-generation requests. They do not retry side-effecting tools. If you explicitly opt into retrying ambiguous provider outcomes, repeated requests may duplicate provider cost. Use only when your application accepts that risk.

[Recovery and failure-path details →](https://agenttrafficcop.com/guide/#recovery)

## Budget-protected execution

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

Use `await run.aexecute(...)` for async work. The helper handles:

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

SDK 2.2.0 includes configured-price adapters for supported non-streaming OpenAI and Anthropic text-token usage, plus named LiteLLM, OpenRouter, and LangChain contracts.

- Duplicate reservations do not authorize another execution.
- Known supported usage can be reported and settled.
- Timeouts, cancellation, and unknown usage retain unresolved holds.
- Reporting failure after execution exposes a cost report to retry.
- **Retry the same report—not the provider action.**
- Keep ingestion-signing secrets on a trusted backend.

Streaming, audio, tool fees, discounts, and other billing variations may need custom handling. Missing usage or unknown pricing is not silently treated as zero.

> Reported-cost controls and estimated reservations are not guaranteed provider-side hard caps. Underestimates, delayed reports, and unreserved calls can exceed a budget.

[Complete budget and accounting setup →](https://agenttrafficcop.com/guide/#budgets)  
[Failure recovery and reporting-only retries →](https://agenttrafficcop.com/guide/#recovery)

## Framework and MCP integrations

Install the extras you need:

```bash
python -m pip install 'agenttrafficcop[langgraph]==2.2.0'
python -m pip install 'agenttrafficcop[crewai]==2.2.0'
python -m pip install 'agenttrafficcop[autogen-agentchat]==2.2.0'
python -m pip install 'agenttrafficcop[mcp]==2.2.0'
```

| Integration | Entry point | Tested version |
|---|---|---|
| LangGraph | `guard_langgraph(...)` or `guarded_node(...)` | `1.2.24` |
| CrewAI | `guard_crewai_tools(...)` | `1.15.45` |
| AutoGen AgentChat | `guard_autogen_tools(...)` | AgentChat/core `0.7.5` |
| MCP client tools | `runtime.mcp_client(...)` | `1.30.0` |
| Generic callables | `runtime.wrap(...)` / `guard_functions(...)` | Supported sync/async functions |

Register the execution paths you want protected and provide application-specific context for run identity and meaningful arguments. Security options are explicit; roles must come from trusted identity. Wrappers do not automatically reserve budgets or account for every internal model call.

The legacy AutoGen adapter supports `pyautogen==0.2.35` via the separate `[autogen]` extra. It is not the same as current AgentChat and does not imply AG2 support.

[Framework registration examples →](https://agenttrafficcop.com/guide/#frameworks)

## LangGraph human review and durable resume

SDK 2.2.0 adds a LangGraph adapter that can pause a protected node for dashboard review. On resume, it verifies the exact review and rechecks the action before the node runs. A LangGraph resume command by itself is **not** approval.

For a complete walkthrough, install the SDK integration and SQLite checkpointer:

```bash
python -m pip install 'agenttrafficcop[langgraph]==2.2.0' 'langgraph-checkpoint-sqlite>=3.1.3,<3.2.0'
export ATC_URL='https://api.agenttrafficcop.com'
export ATC_API_KEY='your-server-issued-key'
```

From a clone of the repository, run the example:

```bash
python examples/langgraph_native_review.py
```

It uses a safe placeholder action—no model provider or real external side effect is called. When ATC pauses the workflow, the example prints a run ID and review ID. Approve or reject that exact review in the dashboard. After approval, press Enter to verify it and resume.

The example stores LangGraph checkpoints in `atc-langgraph-checkpoints.sqlite`. Keep that file, the run ID, and the review ID. To resume after restarting the process, use the same database and run ID:

```bash
export ATC_RUN_ID='the-printed-run-id'
export ATC_REVIEW_ID='the-printed-review-id'

python examples/langgraph_native_review.py \
  --run-id "$ATC_RUN_ID" \
  --resume-review-id "$ATC_REVIEW_ID"
```

The resume input itself never authorizes the action. ATC verifies the dashboard decision for the unchanged action, then performs a fresh check before the node executes. Protect the API key and checkpoint file. Replace the placeholder only after binding the protected action to the exact inputs you intend to review.

[Read the public LangGraph approval/resume guide →](https://agenttrafficcop.com/guide/#langgraph-review) · [View the runnable source example](https://github.com/belalshafeq/AgentTrafficCop/blob/main/examples/langgraph_native_review.py)

## Action identity and privacy

Include stable tool names and meaningful arguments in each payload. Changing timestamps can hide exact repeats. Excluding business arguments can make distinct actions appear identical.

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

### Data boundaries

- `LocalGuard` sends no network requests.
- `GuardRuntime` defaults to hash-only hosted checks.
- Direct `Guard`/`GuardSync` checks default to raw-payload transmission unless configured otherwise.
- Root `timestamp`, `request_id`, and `trace_id` fields are normalized by `GuardRuntime` by default; nested fields are preserved.
- Hashes, session IDs, agent names, and routing fields still reach the hosted service.
- Hashes reveal equality; they are not encryption or guaranteed anonymization.

[Normalization rules and data boundaries →](https://agenttrafficcop.com/guide/#identity)

## Dashboard, shadow mode, and review

Open **Dashboard → Recent Sessions → Inspect run** to inspect recorded decisions.

| Capability | Purpose |
|---|---|
| Shadow mode | Observe supported detector warnings without enforcing those warnings |
| Run timelines | Inspect recorded approvals, blocks, and diagnostics |
| Threshold comparison | Evaluate deterministic policies over retained history |
| One-action review | Authorize one eligible retry without clearing detector history |
| Semantic evidence | Inspect explicitly submitted client-reported observations |

Important boundaries:

- Shadow approvals consume quota; authentication, spending, and coordination failures still reject.
- Legacy `dry_run=True` is not server-side shadow evaluation.
- Review does not execute the action or bypass other controls.
- Threshold comparison does not rerun tools or change live policy.
- Semantic observations are client-reported, not verified semantic replay.
- Evidence is bounded to **200 records per run**, **10,000 per key**, and the plan’s retention window.
- Timelines are not complete execution traces or proof of savings.

[Dashboard behavior and limitations →](https://agenttrafficcop.com/guide/#dashboard)

## Plans and availability

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

*Retention remains subject to record caps. Configuration and commercial terms may differ; check current pricing.*

### Feature comparison

| Feature | Free | Pro | Team |
|---|:---:|:---:|:---:|
| Exact-repeat, cycle, and step checks | ✓ | ✓ | ✓ |
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

Local checks, semantic policies, normalization helpers, framework hooks, outage policies, and configured-price accounting helpers have **no SDK paid-tier gate**. Hosted allowances, paid hosted controls, and external provider charges still apply. Team adds capacity, retention, and custom hosted step/repeat limits—not unbuilt collaboration or shared-workspace features.

[Plans, storage, and production requirements →](https://agenttrafficcop.com/guide/#production)

## Production and failure boundaries

- Hosted checks fail closed by default.
- Optional fail-open permits degraded continuation only after eligible connection-establishment failures.
- Degraded continuation is not hosted approval and cannot enforce hosted quotas, spending, or history.
- Reserved execution requires actual hosted approval.
- Local semantic histories are process-local unless Redis sharing is configured.
- Budgets, reservations, and timelines use a separate persistent ledger.
- Persistent timelines do not restore active detector history.
- Installing the SDK does not provision Redis or a database.

Server operators can use `ATC_REQUIRE_SHARED_STATE=true` to refuse startup without reachable Redis. Connectivity checks do not establish durability or backups. Never assume a timeout means no charge, no execution, or no recorded request.

## Documentation

The website guide contains setup instructions, examples, API signatures, recovery requirements, and migration notes.

- [Getting started](https://agenttrafficcop.com/guide/#getting-started)
- [Local protection](https://agenttrafficcop.com/guide/#local)
- [Hosted protection and async](https://agenttrafficcop.com/guide/#hosted)
- [Identity, normalization, and privacy](https://agenttrafficcop.com/guide/#identity)
- [Semantic detection](https://agenttrafficcop.com/guide/#semantic)
- [Security, recovery, and shared semantic helpers](https://agenttrafficcop.com/guide/#sdk-20)
- [Budgets and accounting](https://agenttrafficcop.com/guide/#budgets)
- [Framework integrations](https://agenttrafficcop.com/guide/#frameworks)
- [LangGraph approval and durable resume](https://agenttrafficcop.com/guide/#langgraph-review)
- [Failure recovery](https://agenttrafficcop.com/guide/#recovery)
- [API reference](https://agenttrafficcop.com/guide/#api)
- [Version differences](https://agenttrafficcop.com/guide/#versions)
- [Troubleshooting](https://agenttrafficcop.com/guide/#troubleshooting)
- [Download the guide as Markdown](https://agenttrafficcop.com/guide.md)

When asking an AI assistant to integrate AgentTrafficCop, provide this guide and specify your installed SDK version.

## Links

[Website](https://agenttrafficcop.com) · [Dashboard](https://agenttrafficcop.com/dashboard.html) · [PyPI](https://pypi.org/project/agenttrafficcop/) · [SDK repository](https://github.com/belalshafeq/AgentTrafficCop-sdk) · [Issues](https://github.com/belalshafeq/AgentTrafficCop-sdk/issues)

## License

MIT. See [LICENSE](LICENSE).
