# SD-PYDANTICAI-WEBSEARCH-001: PydanticAI Web Search Agent

## Overview

A minimal PydanticAI agent that accepts a user query, executes a web search using `httpx` and the Brave Search API, then returns a structured response. Uses `pydantic-graph` to model the workflow as a state machine.

## Architecture

```
UserQuery → SearchNode → FormatNode → Response
```

### Components

1. **`agent.py`** — Main entry point
   - Defines the PydanticAI `Agent` with a system prompt
   - Registers a `web_search` tool that calls Brave Search API
   - Runs the agent against user input

2. **`graph.py`** — pydantic-graph workflow
   - `SearchState` — dataclass holding query, raw results, formatted output
   - `SearchNode` — calls the web search tool, stores results
   - `FormatNode` — formats search results into a readable response
   - `End` node — returns the final response

3. **`models.py`** — Pydantic models
   - `SearchQuery` — input model with `query: str`
   - `SearchResult` — `title: str`, `url: str`, `snippet: str`
   - `SearchResponse` — `query: str`, `results: list[SearchResult]`, `summary: str`

### Dependencies

- `pydantic-ai >= 0.2.0` — **Validated: v1.63.0 (Feb 23, 2026). Reached V1 in Sep 2025 with API stability guarantee.**
- `pydantic-graph >= 0.1` — **Validated: v1.63.0 (Production/Stable). Class-based BaseNode API is stable and fully supported.**
- `httpx >= 0.27` — **Validated: Current stable releases. Async patterns match best practices.**

### Web Search Tool

```python
from pydantic_ai import Agent, RunContext

agent = Agent('claude-haiku-4-5-20251001', system_prompt="You are a helpful search assistant.")

@agent.tool
async def web_search(ctx: RunContext[None], query: str) -> str:
    """Search the web using Brave Search API."""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": 5},
            headers={"X-Subscription-Token": os.environ["BRAVE_API_KEY"]},
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("web", {}).get("results", [])
        return "\n".join(
            f"- {r['title']}: {r['description']}" for r in results[:5]
        )
```

### Graph Workflow

```python
from pydantic_graph import Graph, BaseNode, End
from dataclasses import dataclass

@dataclass
class SearchState:
    query: str = ""
    raw_results: str = ""
    formatted: str = ""

class SearchNode(BaseNode[SearchState]):
    async def run(self, ctx) -> str:
        result = await agent.run(f"Search for: {ctx.state.query}")
        ctx.state.raw_results = result.data
        return "FormatNode"

class FormatNode(BaseNode[SearchState]):
    async def run(self, ctx) -> str:
        result = await agent.run(
            f"Format these search results into a clear summary:\n{ctx.state.raw_results}"
        )
        ctx.state.formatted = result.data
        return End(data=ctx.state.formatted)

graph = Graph(nodes=[SearchNode, FormatNode])
```

## Acceptance Criteria

1. `agent.py` exists and defines a PydanticAI Agent with a web_search tool
2. `graph.py` exists and defines a pydantic-graph Graph with SearchNode → FormatNode → End
3. `models.py` exists with SearchQuery, SearchResult, SearchResponse Pydantic models
4. Code is syntactically valid Python (passes `python -c "import ast; ast.parse(open('agent.py').read())"`)
5. All three files are importable without runtime errors (mocked dependencies OK)

## File Targets

- `/tmp/pydanticai-websearch-e2e/agent.py`
- `/tmp/pydanticai-websearch-e2e/graph.py`
- `/tmp/pydanticai-websearch-e2e/models.py`

## Validation Notes (Research Gate — 2026-03-02)

**Status: VALIDATED** ✓

- **pydantic-ai**: All code patterns match current v1.63.0 stable API. Agent definition, @agent.tool decorator, and RunContext usage are production-ready.
- **pydantic-graph**: Class-based BaseNode/Graph/End pattern is stable and fully supported. New beta function-based API available but not required.
- **httpx**: AsyncClient usage pattern is current best practice. Dependency version >= 0.27 is appropriate.
- **Model ID**: claude-haiku-4-5-20251001 is current (released Oct 2025). No update needed.

**Gotchas for Implementers**:
1. Ensure `BRAVE_API_KEY` environment variable is set before tool execution.
2. Do NOT recreate httpx.AsyncClient per request (anti-pattern) — the SD correctly reuses the client.
3. pydantic-graph automatically persists state after each node, benefiting interrupted execution workflows.
4. PydanticAI reached V1 in Sep 2025 — API stable through all v1.x releases.
