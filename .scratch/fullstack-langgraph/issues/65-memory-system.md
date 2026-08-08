Type: research
Status: resolved (2026-08-08)
Blocked by:

## Question

Design the memory system on LangGraph/LangChain's own best practices (docs,
never invented): **long-term** (facts that survive threads — LangGraph
`Store`, namespaced by user), **episodic** (what happened in past runs —
checkpointer threads + run summaries), **procedural** (how to do things —
skills/instructions the agent retrieves, cf. deepagents skills +
`SkillsMiddleware`). Deliverable: the mapping from each memory kind to the
concrete LangGraph construct, where namespaces come from
(`user_email`/`session_id`/`thread_id`, ticket 64), what is prebuilt vs
workflow-supplied, and which nodes/middleware slots expose it.

## Resolution

Research complete: [research/65-memory-system.md](../research/65-memory-system.md). One-liners: long-term = Store at compile(store=) namespaced ('memories', user_email); episodic = checkpointer threads + Store-held few-shots; procedural = skills + Store-backed instructions with a reflection node; thread/session never in Store namespaces; memory middleware after prompt caching (validates the slot table); build prebuilt save/search-memory tools next.

## Implementation (2026-08-08)

Built: `backend/dyflow/memory.py` — process-wide Store at compile(store=) on all endpoints (children included), prebuilt `save_memory`/`search_memory` auto-bound to every agent when a store exists (tools resolve store+namespace via get_store/get_config at run time; emails sanitised for namespace rules), `settings.checkpointer: sqlite` opt-in durability. 7 tests. Live: fact saved in one thread, recalled in a brand-new thread, namespaced to user_email.
