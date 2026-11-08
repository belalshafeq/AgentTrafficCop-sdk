# AgentTrafficCop SDK

[![PyPI version](https://img.shields.io/pypi/v/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)
[![Python versions](https://img.shields.io/pypi/pyversions/agenttrafficcop.svg)](https://pypi.org/project/agenttrafficcop/)

The official Python SDK for **AgentTrafficCop** — a runtime circuit breaker for multi-agent systems. 

Stop infinite agent loops and runaway API costs before they hit your bill.

## Installation

```bash
pip install agenttrafficcop
```
## Quick Start (Async)
Works perfectly with LangGraph, asyncio, and async orchestrators.
```python
from agenttrafficcop import Guard, LoopDetected

guard = Guard(url="https://api.agenttrafficcop.com", api_key="your-key")

try:
    await guard.check(
        session_id="run-42",
        sender="coder",
        recipient="reviewer",
        payload={"diff": "fix typo"}
    )
except LoopDetected as e:
    print(f"🛑 Loop caught: {e.error_code}")
```
## Quick Start (Sync)
Works out-of-the-box with CrewAI, AutoGen, and standard Python scripts.
```python
from agenttrafficcop import GuardSync, LoopDetected

guard = GuardSync(url="https://api.agenttrafficcop.com", api_key="your-key")

try:
    guard.check(
        session_id="task-1",
        sender="researcher",
        recipient="writer",
        payload={"topic": "AI safety"}
    )
except LoopDetected as e:
    print(f"🛑 Loop caught: {e.error_code}")
```
## Links
Get a Free API Key: agenttrafficcop.com

Full Documentation & Backend: GitHub Repository

License: MIT


