Type: research
Status: open
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
