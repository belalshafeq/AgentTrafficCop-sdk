---
title: "How a Silent Agent Loop Cost Me $3k in API Bills (And How I Fixed It)"
date: "2026-11-06"
summary: "My multi-agent system had 100% uptime. But Agent A and Agent B were stuck in a ping-pong loop burning $3k. Here is how I fixed it."
canonical: "https://agenttrafficcop.com/blog/silent-agent-loop-cost-3k"
---

Last year, I woke up to a **$3,000 OpenAI bill**.

I panicked. I assumed my API key had been leaked, or I was being hit by a massive DDoS attack. I pulled up the logs expecting to find a catastrophic crash or a massive spike in user traffic.

Instead, I found `200 OKs`.

My multi-agent system had 100% uptime. The server was healthy. The database was fine. But Agent A and Agent B were stuck in a polite ping-pong loop. Agent A asked for a review. Agent B provided a review. Agent A asked for a review again.

They had been talking to each other in circles for 8 hours straight. The framework thought everything was fine, and my API budget was draining in the background.

This is the silent killer of multi-agent systems. Here is why it happens, why your standard retry logic won't save you, and how to build a runtime circuit breaker to stop it.

## The Technical Diagnosis: Why Retries Don't Work

If you are using frameworks like LangGraph, CrewAI, or AutoGen, you probably have `max_retries` configured. I did too.

But a retry limit only triggers when an agent throws an error (like a 500, a timeout, or a malformed JSON response).

An agent loop isn't an error. The LLM is successfully generating tokens. It is returning valid, perfectly formatted Pydantic output. The framework sees a successful handoff. The HTTP status is `200 OK`.

There are two patterns that will drain your budget:

1.  **The Repeated Loop:** A -> A -> A -> A. The model gets stuck on a single thought and repeats it indefinitely.
2.  **The Cyclic Loop:** A -> B -> A -> B. Two agents get stuck validating each other's work forever.

If you are only monitoring HTTP codes or infrastructure uptime, you will never catch this. The agents are healthy, they are just burning your runway.

## The Naive Fix (And Why It Fails)

When I realized what was happening, my first instinct was to write a manual loop counter.

I wrote something like this:

# The Naive Counter
execution_count = 0

def guarded_node(state):
    global execution_count
    execution_count += 1
    
    if execution_count > 3:
        raise Exception("Loop detected!")
        
    return agent.run(state)
This worked for a single-agent setup. But it fell apart the moment I scaled to a multi-agent swarm.

It doesn't catch cyclic loops. If Agent A calls Agent B, the counter keeps going up, but it's not catching the A -> B -> A pattern, just the total number of executions.

State resets break it. If an agent crashes and the graph resumes, the Python counter resets to zero, and the loop starts over.

It's a nightmare to maintain. If you have 10 nodes, you have to manually pass and manage this counter across every single edge in your graph.

The Robust Fix: A Runtime Circuit Breaker
To actually stop runaway spend, you need a deterministic check that happens at the handoff layer, before the next API token is generated.

You need to hash the payload.

Every time an agent prepares to pass a message to another agent, you intercept that payload, serialize it, and run it through a SHA-256 hash.

If you keep a sliding window of the last 3 hashes, you can instantly detect loops:

If hash_1 == hash_2 == hash_3, you have a Repeated Loop.

If hash_1 == hash_3 and hash_2 is different, you have a Cyclic Loop.

Instead of letting the agents keep talking, you throw a 422 Unprocessable Entity error back to the orchestrator, forcibly halting the session.

Enter AgentTrafficCop
After spending a weekend writing custom hashing logic and state trackers for my own projects, I realized how tedious this was.

So we built AgentTrafficCop — a lightweight runtime middleware that sits between your agents and acts as a circuit breaker.

We designed it so you don't have to rewrite your graph. If you are using LangGraph, integration is literally one line of code:

from agenttrafficcop import guarded_node

# Wrap your existing node
guarded_node(my_agent_node, guard=guard)
Once installed, AgentTrafficCop intercepts every handoff, hashes the payload, and kills the session if it detects a loop.

But killing the process is only half the battle. If a loop happens, you need to know about it.

When the middleware trips the circuit breaker, it instantly fires a webhook to your Slack or Discord, so your team knows exactly which session was killed before the bill spikes.

We also built a dashboard that tracks Money Saved based on the number of loops prevented, along with a 7-day view of approved vs. rejected handoffs.

The Lesson: Monitor State, Not Uptime
In deterministic software, a 200 OK means everything is working. In probabilistic AI systems, a 200 OK just means the model successfully generated text. It doesn't mean the text was useful, and it certainly doesn't mean you aren't stuck in a loop.

Stop relying on HTTP status codes to monitor your agent health. Monitor the state.

If you want to stop writing custom loop counters and protect your API budget, AgentTrafficCop is live. The free tier protects up to 5 agents and 10,000 messages per month (no credit card required).

You can install the SDK directly from PyPI:

pip install agenttrafficcop
Stop letting your agents burn money in a while(True) loop. Get your free API key at agenttrafficcop.com.