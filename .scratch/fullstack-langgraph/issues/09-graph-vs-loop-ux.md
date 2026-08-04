Type: grilling
Status: open
Blocked by: 03, 05, 08

## Question

How are "graph" and "loop" exposed to the user in the editor?

Given: canvas = `StateGraph`, Agent node = `create_agent` loop, composition = subgraphs.

Decisions:
- Is there one document type (a graph, in which some nodes happen to be loops), or two authorable kinds? The user distinguishes them conceptually — does the UI need to?
- How are **conditional edges** authored? A router node with N labelled outputs, a predicate on the edge itself, or both? What does the canvas capture per edge (depends on 03)?
- How does a user see that an Agent node is internally a loop — is the loop inspectable / expandable on the canvas?
- **Cycles are on the critical path, not optional.** Phase 1 forbids them via `acyclicRule`, but the use case *requires* one: grader rejects → loop back to the generator (LangGraph's evaluator-optimizer pattern). So the rule must be scoped, not global. Decide what remains forbidden — an unbounded cycle with no termination path is still a bug worth catching, and LangGraph's own answer is a `recursion_limit` raising `GraphRecursionError`. Likely: allow cycles, but require every cycle to contain at least one conditional edge with a reachable exit, and surface `recursion_limit` as workflow config. Feeds ticket 24.
- Where does a compiled-graph preview belong (LangGraph can emit Mermaid)?
