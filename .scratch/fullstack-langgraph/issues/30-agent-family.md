Type: grilling
Status: resolved (2026-08-07) — built in f5f7076
Blocked by: 29

## Question

There is no agent family in `backend/dyflow/abc/` — an "agent" is
`create_agent(...)` called inline in `NodeRuntime._agent` and `._worker`.
CLAUDE.md's three-tier table (`CustomGraphNode` / `ReactAgentNode` /
`DeepAgentNode` under `AbstractAgentNode`) exists in prose only, and
`create_deep_agent` is only ever invoked with `tools=[]` as a judgement
harness for Router/Grader tiers.

Design `backend/dyflow/abc/agent.py`:

```
IAgent (Protocol)         build(...) -> Runnable
AbstractAgentNode (ABC)   resolve_model() · resolve_prompt() · resolve_middleware()
                          + template method; abstract build_agent()
BaseAgentNode             usable default — plain create_agent
  ReactAgentNode          create_agent + its middleware slot preset
  DeepAgentNode           create_deep_agent + the deepagents slot preset
  CustomGraphNode         user-authored callable / StateGraph from functions/
```

Decisions:
- The base holds the minimum: the three resolvers and the template method,
  nothing else. Which fields are shared config (model, prompt rules,
  middleware slots) vs concrete-only (deep agent's subagents/planning)?
- `NodeRuntime._agent` and `._worker` delegate to this family — what do the
  factories still own (state plumbing) vs what moves (agent construction)?
- Sibling rule: DeepAgentNode is a sibling of ReactAgentNode, never a
  subclass — the deepagents stack is data (a slot preset), not inheritance.
- TS `agent.llm` gains `tier` mirroring Router/Grader; how does the palette
  present the tiers without three near-identical cards?

## Resolution

Built as designed: `backend/dyflow/abc/agent.py`, base holds the three resolvers + template method; Deep is a sibling of React; `agent_node_for_tier` is the one tier lookup; `_agent`/`_worker` delegate. TS `agent.llm` gained the tier select (8ce5a22).
