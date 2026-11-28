# AgentTrafficCop Python SDK

[![PyPI version](https://img.shields.io/pypi/v/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)
[![Python versions](https://img.shields.io/pypi/pyversions/agenttrafficcop/)](https://pypi.org/project/agenttrafficcop/)

**Check the next agent action before it runs.**

AgentTrafficCop provides deterministic checks for repeated actions, repeating cycles, and approved-step limits. Choose local in-process checks or a hosted API with shadow decisions, incident timelines, threshold comparison, and reported-cost controls. Your application must honor every rejected or failed check.

Legacy checks do not execute actions, automatically intercept every model call, understand semantic repetition with deterministic checks, or cancel in-flight work. The new runtime execution helpers invoke only the callable explicitly passed to them. The separate experimental `SemanticMonitor` uses your encoder for warnings only.

## SDK 2.0: the recommended simple path

See [short integration recipes and migration guidance](QUICKSTARTS.md).

Configure protected calls once with `runtime.run`; `execute` and `aexecute` own the full reserved execution path. `SemanticMonitor.openai` provides explicit one-line hosted embedding setup. `UsageAccountant` supports named LiteLLM, OpenRouter, and LangChain non-streaming contracts alongside raw provider responses.

**Breaking default:** `GuardRuntime` strips root `timestamp`, `request_id`, and `trace_id` fields. Use `normalize_volatile_metadata=False` for 1.x strict hashing, and migrate with a new run ID. Nested fields are preserved. Low-level client and `LocalGuard` defaults do not change. Unknown-cost exceptions retain holds; they are never settled as zero.

## Install

Python **3.11+**:

```bash
python -m pip install --upgrade 'agenttrafficcop==2.2.0'
python -c "from importlib.metadata import version; print(version('agenttrafficcop'))"
```

The base dependency is `httpx>=0.27.0,<0.30.0`. Use a virtual environment; optional framework extras have their own requirements.

## CLI setup and deployment checks

The `atc init` setup wizard is available in the repository source but is not included in the currently published PyPI package yet. To try it from a local checkout of this repository, install the SDK from its source directory:

```bash
python -m pip install -e ./sdk
atc init
```

For the LangGraph starter, install the optional extra:

```bash
python -m pip install -e './sdk[langgraph]'
atc init
```

The wizard generates an integration example, an environment-variable template, and setup notes. It does not request or write your real API key. Review the generated files and provide `ATC_API_KEY` securely through your environment or secret manager.

The source version also includes `atc doctor` for Kubernetes diagnostics. Add `--probe-egress` to test ATC reachability and whether public TCP egress is blocked. That probe creates a temporary pod and requires pod create/exec/delete permissions, an image pull, and a NetworkPolicy-enforcing CNI. A passing policy-shape check alone does not prove runtime enforcement.

Once a new SDK release is published, install or upgrade the package with:

```bash
python -m pip install --upgrade agenttrafficcop
```

## Route OpenAI calls through ATC with BYOK

Install the optional OpenAI integration:

```bash
python -m pip install 'agenttrafficcop[openai]'
```

The adapter configures the OpenAI SDK to use the ATC gateway, sends the ATC key as bearer authorization and your provider key separately as BYOK, and attaches a run ID plus a unique operation ID to each Chat Completions request:

```python
import os
from agenttrafficcop import openai_gateway_client

with openai_gateway_client(
    atc_api_key=os.environ["ATC_API_KEY"],
    provider_api_key=os.environ["OPENAI_API_KEY"],  # Your provider key; never give it to us.
    run_id="order-742",  # Set a budget for this run before calling the gateway.
    base_url=os.getenv("ATC_BASE_URL", "https://your-atc-host/v2"),
) as client:
    response = client.chat.completions.create(
        model="your-configured-model",
        messages=[{"role": "user", "content": "Summarize this report."}],
        max_tokens=300,
    )
```

For async applications, create the client with `async_openai_gateway_client` and use the returned client in `async with`. Set `provider="groq"` to route compatible OpenAI SDK calls to the fixed Groq gateway route.

The gateway currently supports text-only, non-streaming Chat Completions for configured models. Configure exact model prices and an eligible run budget on ATC first. No prompts or completions are added to trace telemetry.

The adapter adds one operation ID to each `create` call before handing it to the OpenAI SDK, so its internal retries reuse that ID. For deduplication across application or process restarts, pass your own persisted ID with `extra_headers={"X-ATC-Operation-ID": durable_operation_id}`. Do not blindly retry an ambiguous result with a new ID: it can trigger a second provider call.

This integration covers only requests made through this configured client; it does not monkey-patch other clients or frameworks. A provider key is still required for a live BYOK call, but mock tests and local setup validation need no real provider key.

## Security, recovery, and shared semantic helpers (2.1.0)

These are explicit Python SDK helpers; none patches model or framework calls globally. They are included in the 2.1.0 package.

```python
from agenttrafficcop import RecoveryHooks, SecurityGuard

security = SecurityGuard(
    {"operator": {"search", "delete_record"}},
    approval_required={"delete_record"},
)

# Sanitize untrusted text before adding it to a model request.
scan = security.sanitize_text(user_supplied_text)
if not scan.allowed:
    raise ValueError(f"Suspicious instruction: {scan.findings}")
model_input = scan.text  # Common email/phone/SSN/card/API-key patterns redacted.

# Wrap each sensitive tool explicitly. Derive role from trusted auth context;
# provide a real approval workflow for destructive tools.
protected_delete = security.wrap_tool(
    delete_record,
    tool="delete_record",
    role=authenticated_role,  # Resolved from trusted application auth context.
    approver=approval_service,
)

# Provider adapters sanitize OpenAI/Anthropic text messages, then call your
# existing provider client. No API keys are added to AgentTrafficCop.
secured_create = security.wrap_openai_chat(openai_client.chat.completions.create)

# Bounded provider recovery defaults to explicit HTTP 429 responses only;
# opt into other classifications with retry_if. Never wrap a tool action.
recovered_create = RecoveryHooks(
    max_retries=1,
    fallback_model="your-backup-model",
).wrap_openai_chat(secured_create)

answer = recovered_create(
    model="your-primary-model",
    messages=[{"role": "user", "content": model_input}],
)

# Distributed semantic history with an operator-provided local ONNX model.
# Install: pip install 'agenttrafficcop[semantic-onnx,semantic-redis]'
import os
from agenttrafficcop import SemanticMonitor

monitor = SemanticMonitor.onnx(
    "/models/reviewed-model.onnx",
    "/models/tokenizer.json",
    model_id="reviewed-model-v1",
    redis_url=os.environ["REDIS_URL"],
)
```

Prompt-injection detection is a small local heuristic, not a classifier or a security guarantee. PII redaction covers common patterns only; multimodal inputs are rejected by the provider wrappers unless separately inspected. Roles must come from trusted application identity, and the approval callback must perform an actual human review.

Recovery is bounded and retries explicit HTTP 429 rate-limit responses by default. Timeouts, connection failures, and other statuses are not retried unless the caller explicitly opts in; such retries may duplicate provider cost when completion is ambiguous. Never wrap side-effecting tools.

The ONNX runtime and Redis client are optional dependencies. **Model weights are not bundled or downloaded**—operators must supply and review compatible local ONNX/tokenizer files.

## Opt-in run spans

Use `GuardSync.span(...)` or `Guard.span(...)` around a tool, model, or agent operation to add a timed event to the matching run timeline in the ATC dashboard:

```python
with guard.span(RUN_ID, "search_documents", kind="tool"):
    results = search_documents(query)

# Async equivalent:
async with guard.span(RUN_ID, "summarize", kind="model"):
    result = await summarize_async(text)
```

Allowed kinds are `agent`, `tool`, `model`, `retrieval`, and `other`. Span names must be short safe labels. The SDK reports only the name, kind, parent/span IDs, duration, success/error status, and exception class; it never sends inputs, outputs, exception messages, or tracebacks.

Reporting is best-effort and will not replace an application exception. This is explicit instrumentation—not automatic patching—so wrap only the operations you want to see. Completed spans appear in the run timeline; calls or work not wrapped by the SDK remain invisible. The timed-span and registration-hook helpers are included in SDK 2.1.0.

The registration-time `guard_functions`, `guard_autogen_tools`, `guard_crewai_tools`, and `guard_langgraph` helpers can wrap registered functions or nodes in spans for you. Create the batch around the run, and pass it when registering tools or graph nodes:

```python
with guard.trace_batch(RUN_ID) as batch:
    protected_tools = guard_functions(
        runtime,
        tools,
        context=tool_context,
        trace_batch=batch,
    )
    agent = build_agent(protected_tools)
    agent.run()
```

Use an async batch with async functions. For mixed sync/async registrations, pass `trace_batch={"sync": sync_batch, "async": async_batch}`. CrewAI exposes both execution paths, so pass that mapping when tracing both. Only functions registered through these explicit helpers are traced; nothing is monkey-patched.

To reduce requests for multi-step runs, use `trace_batch`; it sends up to 100 spans per HTTP request by default:

```python
with guard.trace_batch(RUN_ID) as batch:
    with batch.span("search_documents", kind="tool"):
        results = search_documents(query)
    with batch.span("summarize", kind="model"):
        summary = summarize(results)
```

Async code can use `async with guard.trace_batch(RUN_ID) as batch:` and `async with batch.span(...)`. Batches flush at capacity and at scope exit, even when the wrapped work raises. Flush is still awaited once per batch—not a background queue—so reporting failure drops the batch but preserves the work's result or exception.

## Budgeted provider calls: fewer per-call plumbing arguments

These runtime provider-call helpers and the OpenAI gateway adapter are included in SDK 2.1.0. The gateway adapter is the simplest BYOK path for supported non-streaming Chat Completions; the runtime helpers provide separate local reservation/accounting controls for explicitly wrapped provider calls.

For OpenAI Chat Completions or Anthropic Messages, bind the accountant and run context once, then pass the provider's create callable and a durable operation ID. An optional local estimate callback can be bound once too:

```python
run = runtime.run(
    session_id=RUN_ID,
    sender="agent",
    recipient="openai",
    accountant=accountant,
    estimate_cost=estimate_request,
)

response = run.openai_chat(
    client.chat.completions.create,
    operation_id=PERSISTED_OPERATION_ID,
    model=MODEL,
    messages=[{"role": "user", "content": "..."}],
    max_tokens=500,
)
```

Use `await run.aopenai_chat(...)` for async calls. For Anthropic, use `run.anthropic_messages(...)` or `await run.aanthropic_messages(...)` with an Anthropic `UsageAccountant`.

Exact model prices and a trusted reporter are still configured once by the application. The local estimator must use your own pricing/tokenizer and return a positive estimate; it is not a provider hard cap. Operation IDs remain explicit and durable. Calls are non-streaming; only a hash-only action identity is sent by default. These methods do not intercept other provider APIs or add provider SDK dependencies.

## New in 1.7.0: less setup, unchanged safety defaults

- Bind session/routing/accounting once with `run = runtime.run(...)`, then use `run.execute(...)` or `await run.aexecute(...)` for each reserved operation.
- Optional one-line encoder setup: `SemanticMonitor.openai()` reads `OPENAI_API_KEY` and sends text to OpenAI only when observing. Provider charges apply; no model download or implicit opt-in. BYO encoders remain supported.

See the first sections of [RUNTIME_FEATURES.md](RUNTIME_FEATURES.md) for setup, privacy, failure recovery, and prerequisites. Unknown provider outcomes retain holds; post-call reporting failures never rerun executed calls. A configured Pro/Team budget and trusted accountant are still required for reserved execution.

## Included from 1.6.0

- GuardRuntime: one explicit sync/async facade, opt-in semantic blocking, root transport-metadata normalization, and connection-only degraded fail-open.
- Registration-time hooks for a pinned LangGraph/CrewAI/current AutoGen set and an explicit MCP `call_tool` proxy; no global instrumentation or streaming support.
- Configured-price non-streaming OpenAI/Anthropic token-usage adapters and trusted signed reporting; check/reserve/execute/final-settlement helpers.
- Client-reported semantic evidence in compatible hosted timelines/replay; observations are not verified hosted approvals or re-evaluated semantic replay.
- Required-shared-state deployment gate and a durable Redis configuration; Redis must still be provisioned/configured by the operator.

See [RUNTIME_FEATURES.md](RUNTIME_FEATURES.md) for examples, supported versions, privacy, failure/cancellation limits, and infrastructure requirements. Existing client defaults and detector thresholds remain unchanged. The new root metadata preset is opt-in, not the previously reverted recursive field stripper.

## Included from 1.5.0

- **Explicit outage policy:** fail-closed hosted enforcement with optional safe connection-establishment retries and redacted events. No automatic local fallback.
- **Experimental semantic warnings:** opt-in `SemanticMonitor` with your own encoder, bounded embedding history, and no approvals or blocking authority.
- **Human review:** compatible hosted dashboards let account owners authorize one exact retry, without resetting history or bypassing quotas/spend controls.

See [FEATURES.md](FEATURES.md) for usage, privacy, and failure-path limits.

## Included from 1.4.0

- **Optional payload normalization:** explicitly ignore selected object fields when computing action identity. Original action data is not mutated.
- **Threshold comparison:** compare repeat/cycle/step policies offline or against bounded hosted incident history, without executing actions or changing policy.
- **Shared run spending reservations:** reserve estimated cost before participating calls and settle through trusted signed actual-cost reporting. Pro/Team hosted creation; not a provider-side hard spending cap.

LocalGuard shipped in 1.3.0; hosted hash-only helpers shipped in 1.2.0. Defaults remain unchanged in 1.5.0. New hosted helpers require a compatible backend.

## Local or hosted?

| Capability | `LocalGuard` | `Guard` / `GuardSync` |
|---|---|---|
| API key / network required | No | Yes |
| Exact repeats, cycles, step limits | Yes | Yes |
| Optional field exclusions | Yes | With `hash_only=True` |
| Shadow mode | No | Yes |
| Dashboard records and retained-run replay | No | Yes |
| Schema-change heuristic | No | Pro/Team |
| Reported run budgets / reservations | No | Pro/Team |
| State sharing | One guard instance | Depends on backend configuration |
| Automatic action interception | No | No |

## Local quick start

```python
from agenttrafficcop import LocalGuard

guard = LocalGuard(max_repeats=3, max_steps=50)

for _ in range(3):
    result = guard.check(
        session_id="example-run",
        payload={"tool": "search", "arguments": {"query": "refund policy"}},
    )
    if not result.approved:
        print("Not executed:", result.reason)
        break

    print("Approved step", result.step)
    # Execute your protected action here.
```

The first two checks approve; the third returns `REPEATED_PAYLOAD_LOOP`. Reuse one guard instance and stable session ID throughout a run.

Local defaults:

```python
guard = LocalGuard(
    max_repeats=3,
    max_steps=50,
    max_cycle_length=2,
    max_cycle_repeats=3,
    max_sessions=1000,
    session_ttl=3600,
    ignore_paths=(),
)
```

`LocalResult` contains `approved`, `session_id`, `step`, `payload_hash`, and `reason`. Policy rejection reasons are `REPEATED_PAYLOAD_LOOP`, `CYCLIC_PAYLOAD_LOOP`, `STEP_LIMIT_EXCEEDED`, or `LOCAL_CAPACITY_EXCEEDED`. Invalid inputs raise `ValueError`; do not execute after a failed check.

Checks and updates are thread-safe within one instance. History is in memory, expires after inactivity, and is lost on restart or `guard.reset(session_id)`. Separate processes/instances do not share history. At capacity, new unexpired sessions are rejected rather than evicting active protection. Rejected checks refresh existing activity time but do not advance approved history.

Local mode makes no network requests, uploads no decisions, and has no hosted fallback, spending controls, or shadow mode. Approval counts checks, not verified executions. A different action can be approved after a repeat rejection if no other policy blocks it.

## Optional payload normalization

Changing timestamps or request IDs can hide exact repeats. Exclude only fields you explicitly know are irrelevant:

```python
from agenttrafficcop import LocalGuard, normalize_payload

guard = LocalGuard(ignore_paths=["/timestamp", "/request/id"])
action = {"tool": "search", "arguments": {"query": "refund"}, "timestamp": 123}

result = guard.check(session_id="run-1", payload=action)
if result.approved:
    pass  # Execute the ORIGINAL action here.

normalized_copy = normalize_payload(action, ignore_paths=["/timestamp"])
```

Paths are JSON pointers through **objects only**, not arrays or wildcards. `~1` escapes `/`; `~0` escapes `~`. Missing keys are ignored; root deletion is unsupported. Up to 64 paths, 512 characters, and 32 components per path are accepted. Invalid paths/non-finite JSON inputs raise `ValueError`.

No fields are removed automatically. Keep exclusions stable throughout a run; old hashes are not rewritten. Excluding meaningful arguments can make different actions look identical. This is not semantic detection.

## Hosted quick start

Verify your email, create an account, and generate an API key in the [dashboard](https://agenttrafficcop.com/dashboard.html). Store it server-side:

```bash
export ATC_API_KEY="your-api-key"
```

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
                sender="planner",
                recipient="worker",
                payload={"tool": "search", "arguments": {"query": "refund"}},
            )
        except AgentTrafficCopError as exc:
            print("Not executed:", exc.error_code)
            return

        if result.approved:
            print("Approved at step", result.step)
            # Execute your protected action here.


if __name__ == "__main__":
    asyncio.run(main())
```

Use a stable ID throughout a run and a new ID for each independent run. Call at all relevant execution boundaries. Client creation alone does not protect code.

`GuardSync` provides the same check without `await`:

```python
import os

from agenttrafficcop import AgentTrafficCopError, GuardSync


with GuardSync(
    "https://api.agenttrafficcop.com",
    os.environ["ATC_API_KEY"],
    dry_run=False,
) as guard:
    try:
        result = guard.check(
            session_id="my-stable-run-id",
            sender="planner",
            recipient="worker",
            payload={"tool": "search", "arguments": {"query": "refund"}},
        )
    except AgentTrafficCopError as exc:
        print("Not executed:", exc.error_code)
    else:
        if result.approved:
            pass  # Execute your protected action here.
```

## Hosted hash-only checks

Within an open `Guard` context:

```python
result = await guard.check(
    session_id=run_id,
    sender="planner",
    recipient="worker",
    payload={"tool": "search", "query": "refund", "timestamp": 123},
    hash_only=True,
    ignore_paths=["/timestamp"],  # Optional; introduced in 1.4.0.
)
```

`GuardSync` uses the same arguments without `await`. Hosted field exclusions require `hash_only=True`; otherwise they raise `ValueError` before a request. The helper hashes a nonempty JSON object using sorted keys, compact separators, unescaped Unicode, UTF-8, and SHA-256. Non-finite numbers are rejected. This is not RFC 8785 canonicalization. A normalized empty object is rejected.

Raw transmission is the hosted default. Hash-only omits the raw payload, rejects metadata, and never falls back to sending raw contents. Hashes and routing identifiers still leave the application. Hashes reveal equality; predictable inputs can be guessed. They are not encryption or guaranteed anonymization. The backend cannot prove that the submitted hash matches the eventual action.

REST callers use `payload_mode="hash_only"` and a 64-character lowercase hex `payload_hash`, omitting both `payload` and `metadata` entirely, including nulls. Raw and hash-only checks share history when their hashes, key, session, and mode match. Required routing fields and ordinary policies still apply.

## Shadow mode

Within an open hosted client:

```python
result = await guard.check(
    session_id=run_id,
    sender="planner",
    recipient="worker",
    payload={"tool": "search"},
    mode="shadow",
)

if result.would_block:
    print(result.shadow_decision["error"])

if result.approved:
    pass  # Application may execute in shadow mode.
```

Supported repeat/cycle/step and eligible schema detections become warnings. Authentication, validation, rate limits, message/agent quotas, spending blocks, exhausted budgets, and coordination failures can still reject. Approved shadow checks consume quota. Shadow and enforcement histories are separate. Switching modes does not transfer history. Run spending retains its key/run scope.

Keep `dry_run=False`: legacy dry-run is not shadow mode. Do not let untrusted callers change policy modes or reset history when enforcement is mandatory.

## Historical replay and threshold comparison

Offline, supply ordered SHA-256 hashes of observed attempted actions:

```python
from agenttrafficcop import compare_thresholds

comparison = compare_thresholds(
    payload_hashes,
    policies=[
        {"max_repeats": 3, "max_steps": 25},
        {"max_repeats": 4, "max_steps": 40},
    ],
)
```

Up to 10,000 hashes and four policies are accepted. Supported settings are `max_repeats`, `max_steps`, `max_cycle_length`, and `max_cycle_repeats`. Offline omitted settings follow LocalGuard defaults (50 steps). Each simulation starts with empty history and stops at its first block. No actions run or alerts fire.

For retained hosted history, inside an open client:

```python
comparison = await guard.replay_run(
    session_id=run_id,
    policies=[
        {"max_repeats": 3, "max_steps": 25},
        {"max_repeats": 4, "max_steps": 40},
    ],
    mode="shadow",
)
```

`GuardSync` omits `await`. Hosted omitted settings use 3 repeats, 25 steps, cycle length 2, and 3 cycle repetitions. In the dashboard, use **Inspect run → Compare detector thresholds**. Its reference is explicit—not the run's verified original policy. Nothing changes live detector settings.

Results always set `full_history_verified=false`: timelines are bounded to 200 recorded checks per run, up to 10,000 per key within plan retention. Missing hashes stop replay; discontinuous steps are flagged. Enforcement and shadow are selected separately. Resets, expiry, historical policy changes, missing actions, and complete execution traces are not reconstructed. A different threshold cannot invent actions the original workflow never attempted.

Comparison covers repeat/cycle/step rules—not schemas, semantic similarity, quotas, spending, or every custom hosted policy. Hashes cannot be re-normalized without original payloads. Timeline records omit raw payloads and metadata; raw-mode checks still transmit payloads for validation and hashing.

## Reported spending and run budgets — Pro/Team

```python
budget = await guard.set_run_budget(session_id=run_id, budget_usd="2.00")
# GuardSync: budget = guard.set_run_budget(...)
```

Setting a budget does not connect provider billing. An authorized backend must report incremental costs through timestamp/HMAC-signed `POST /v1/ingest/usage` requests. Use matching key/session attribution and stable unique event IDs; never report cumulative run totals or duplicate spending across integrations.

Run budgets are **API key + session** scoped. Rolling thresholds cover a key's reported costs over 60 seconds. Updating budgets preserves spending; a new run needs a new session ID. Delayed reports, unguarded actions, and in-flight work can overshoot. These are not provider-side hard caps.

## Shared spending reservations — Pro/Team

Reserve estimated cost **before** participating calls start, after setting a run budget. Admission atomically checks reported spending plus outstanding holds:

```python
hold = await guard.reserve_spend(
    session_id=run_id,
    reservation_id="operation-123",  # Stable, unique per logical operation.
    estimated_cost_usd="0.20",
)

if hold["duplicate"] or hold["status"] != "held":
    raise RuntimeError("Recover through your execution ledger; do not execute twice")

# Execute this operation once, only after all other required checks pass.
```

Sync clients omit `await`. Estimates are positive, at most $1 billion, with up to 6 decimal places. Missing budgets return 409; insufficient available budget returns 402. Same ID/estimate returns the existing reservation with `duplicate=true`; changed estimates conflict. A duplicate is not permission to execute again. Keep an execution ledger/provider idempotency key for recovery.

A trusted reporter submits one final incremental actual cost per reservation:

```json
{
  "api_key": "YOUR_ATC_KEY",
  "session_id": "run-1",
  "reservation_id": "operation-123",
  "event_id": "final-cost-123",
  "cost": "0.17"
}
```

Send this body to `/v1/ingest/usage` with `X-ATC-Timestamp` and `X-ATC-Signature`. The signature is hexadecimal SHA-256 HMAC of `timestamp + "." + exact_body`, using the server-side ingestion secret. An ordinary API key does not grant access to that signing secret. Arrange an authorized integration for the hosted service; never expose it in browser code.

Settlement records actual cost and clears its hold in one transaction. Retry the same event with unchanged cost/attribution. Do not also report that operation through another integration. Partial/streamed settlements of a single hold are not supported; aggregate the final cost at the trusted reporter. CloudPulse key-level reports do not settle individual run reservations.

There is **no automatic expiry or bearer-token cancellation**: a timed-out worker may still be executing. A trusted reporter can settle at zero only after knowing that no cost was incurred. Unknown outcomes remain held and require recovery. There is a 10,000 unresolved-hold cap per run; active holds are not evicted.

The ledger is persistent and shared only by workers using the same database. Separate SQLite files do not coordinate even when detector history uses Redis. Reservations are key/run scoped, not account-wide or rolling-window allowances. Unreserved calls are not prevented. Actual costs above estimates are still recorded and can exceed the budget. `check()` does not reserve automatically.

Budget reads include `reserved_spend_usd` and `available_to_reserve_usd`. `GET /v1/runs/{session_id}/reservations` supports `after` and `limit` pagination. To inspect one operation without loading a page, use `guard.get_reservation(session_id, reservation_id)` or `await guard.get_reservation(session_id, reservation_id)`. This read-only call returns the reservation's `status`, estimate, actual cost (if settled), and creation time; it returns 404 when the ID is not in that key/run.

A `held` result is not evidence the provider did or did not execute the request: do not retry the provider call or release the hold based on status alone. Reconcile final cost through the trusted signed usage-reporting path.

REST: `GET /v1/runs/{session_id}/reservations/{reservation_id}`. The SDK helper is included in SDK 2.1.0; use this REST route with the existing wheel, or use the pinned source-install instructions above for the sync/async helper. No PyPI version change is required for the HTTP endpoint.

## Framework integrations

### LangGraph

Install the versioned SDK and the optional LangGraph extra:

```bash
python -m pip install 'agenttrafficcop[langgraph]==2.2.0'
```

```python
from agenttrafficcop.langgraph import guarded_node

# Existing graph, open hosted guard, and reviewer_fn:
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

Only wrapped nodes are protected. Keep exceptions propagating so failed checks stop execution. To pause a circuit-breaker trip for a dashboard review, compile with a **durable LangGraph checkpointer** (for example, a production database-backed saver) and enable the built-in ATC verifier:

```python
builder.add_node(
    "reviewer",
    guarded_node(
        reviewer_fn,
        guard=guard,
        sender="coder",
        recipient="reviewer",
        session_id=lambda state: state["run_id"],
        payload=lambda state: {"draft": state["draft"]},
        review_on_trip=True,
    ),
)

# durable_saver is your database-backed LangGraph checkpointer.
graph = builder.compile(checkpointer=durable_saver)
```

When paused, show `__interrupt__[0].value` to the authorized operator and use the dashboard's run-review flow to approve/reject the exact action. Resume with `Command(resume={"review_id": event["review_id"]})`; the resume payload itself is never authorization. The SDK asks ATC to validate the grant against the current detector state and exact action, then rechecks policy and consumes the one-action approval before the node runs.

The status API is read-only; only an authenticated dashboard owner can decide a review. A custom `review_approval` callback is optional and must fail closed.

For a complete live-service walkthrough, install the SQLite checkpointer extra and run the safe no-op example. It pauses after repeated identical requests; approve that exact review in the dashboard before pressing Enter. No model provider or external tool is called:

```bash
python -m pip install 'agenttrafficcop[langgraph]==2.2.0' 'langgraph-checkpoint-sqlite>=3.1.3,<3.2.0'
export ATC_URL='https://api.agenttrafficcop.com'
export ATC_API_KEY='your-server-issued-key'
python examples/langgraph_native_review.py
```

The example persists LangGraph checkpoints to `atc-langgraph-checkpoints.sqlite`. Keep that file and reuse the printed run ID plus `--resume-review-id` after a process restart. For an offline walkthrough, run `python -I examples/langgraph_checkpointed_review.py` from the repository; it uses fake ATC/review services and an in-memory saver, so it is not a production configuration.

A trip creates a checkpoint with only a generic review event, session ID, opaque review ID, and safe detector error code—never state, prompts, results, or exception text. On resume the verifier must approve that exact unchanged action; only then does the node perform a fresh ATC check immediately before running. A resume value by itself is never approval. Do not use an in-memory saver for restart durability.

Approval does not bypass ATC spend/quota/policy controls. Adapters do not automatically enable normalization, hash-only, shadow mode, or spending reservations. Use direct checks for unexposed options.

### Legacy AutoGen

```bash
python -m pip install 'agenttrafficcop[autogen]==2.2.0'
```

This legacy adapter supports only `pyautogen==0.2.35`, not AgentChat or AG2. For current AgentChat 0.7.5 use the separate `guard_autogen_tools` hook documented in `RUNTIME_FEATURES.md`. The legacy adapter does not support other similarly named packages.

`GuardedConversableAgent` checks supported `generate_reply` / `a_generate_reply` pipelines, including registered handlers. Direct sends, direct tool calls, and work outside those methods are not intercepted. One reply can execute multiple tools; costs are not automatically reported or reserved. It is not an execution sandbox. Dry-run guards are rejected. `LocalGuard` is not a drop-in replacement for hosted adapters.

## Failure handling and reliability

- Catch `AgentTrafficCopError` around hosted `check()` calls—not just loop errors.
- Budget, replay, and reservation helpers expose HTTPX HTTP/transport exceptions.
- Local policy failures are results; invalid local input raises `ValueError`.
- Stop on every failed check, including timeouts and HTTP 503 coordination errors.
- A failed response does not prove that no history or quota update occurred.
- Policy-rejected checks do not consume approved-message quota. Ambiguous crash/storage failures can retain conservative charges without client approval.
- Memory-backed hosted detector history remains single-process and is lost on restart/expiry/reset. Redis coordination needs compatible participating workers. Persistent incident records do not restore active detector history.
- Webhook notifications are best effort, not a guaranteed-delivery incident queue.

Use a trusted execution boundary, stable session identity, and a stable payload policy. Different wording with different hashes is not detected semantically. The SDK is Alpha software, not a compliance certification or a zero-error guarantee.

## Links

- [Website and plans](https://agenttrafficcop.com)
- [Dashboard](https://agenttrafficcop.com/dashboard.html)
- [PyPI](https://pypi.org/project/agenttrafficcop/)
- [Public SDK repository and issues](https://github.com/belalshafeq/AgentTrafficCop-sdk)

## License

The Python SDK is licensed under the [MIT License](https://github.com/belalshafeq/AgentTrafficCop-sdk/blob/main/LICENSE). This does not license the hosted service or private backend.
