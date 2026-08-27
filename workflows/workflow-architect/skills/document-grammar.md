---
name: document-grammar
description: >-
  MANDATORY: read this before composing or editing any workflow JSON. Gives
  the exact document/node/edge shape, every node type and its ports, and the
  rules a document must satisfy before validate_workflow will accept it.
---

The workflow document grammar (compose EXACTLY this shape):

{"version": 2, "name": "...", "settings": {}, "nodes": [...], "edges": [...]}

Node: {"id": "unique-id", "type": "<type>", "data": {...}, "position": {"x": N, "y": N}}
Edge: {"source": {"nodeId": "...", "portId": "..."}, "target": {"nodeId": "...", "portId": "..."}}

Node types and their ports (in → out):
- input.text — the user's question enters here. out: text
- input.markdown — a skill file. data: {filename, instruction}. out: skill (wire it into a model-driven node's `skill` port)
- agent.llm — data: {systemPrompt, rulesMode?, rubric?, summarize?, tier: "react"|"deep"}. in: prompt, feedback, tools(bus), skill. out: result
- route.classifier — data: {branches: [{id, name}...], fallback, rules, rulesMode?}. in: question. out: branch:<id> per branch
- route.grader — data: {criteria, rulesMode: "extend"|"replace", maxAttempts, rubric?: [{criterion, required}]}. in: candidate, skill. out: pass, revise (revise MUST loop back to an upstream feedback/instruction port)
- orchestrate.supervisor — data: {maxSubtasks, rules, rulesMode?}. in: instruction, feedback, skill. out: workers (one edge per worker archetype)
- orchestrate.worker — title = its archetype name; data: {role, default?: true}. in: dispatch, tools(bus), skill. out: result
- function.format_report — data: {reportTitle}. in: candidate (accepts many). out: report
- human.approval — data: {message}. in: candidate. out: approved, rejected
- workflow.subgraph / team.workflow — data: {workflow: "<slug>", overrides?, outcome?}. in: input. out: result. The slug must be one platform_list_workflows returned; never invent one. Both types compile identically; "outcome" is a card label on team.workflow that nothing enforces.
- output.formatted — the final answer. in: result (accepts many)

Rules that make a document valid:
- Exactly one input.text with no incoming edge (the entry); flow must reach output.formatted.
- Every cycle needs a conditional exit: grader pass leaves the loop, revise re-enters via a feedback port.
- Tool edges (tool -> tools) are BINDINGS, not sequence: never chain a tool between two agents.
- Router branch port ids are "branch:<branch id>", matching branches[].id exactly.
- A supervisor with several workers: give each worker a distinct title (its archetype) and a role; mark one {"default": true}.
- rulesMode is ONE field across all five model-driven types (agent.llm, route.classifier, route.grader, orchestrate.supervisor, orchestrate.worker): "extend" (default) adds the developer's text to the type's built-in rules, "replace" keeps only the topmost supplied layer. Never emit "criteriaMode" — that was the grader-only spelling of the same field and it is superseded.
- Every model-driven type works with NO rules written and NO skill wired: each ships built-in rules. Write rules only where the domain needs them.
- A mount is a REFERENCE, so the same package can be mounted twice and configured differently each time. "overrides" on the mount is how: {"<child node id>": {"<field>": value}}, applied per field to a copy of the child. It is stored on THIS document, never on the child — the mounted package is never rewritten. Use it to make one mount stricter or cheaper than another; do not copy a package to change one setting.
- Two keys "overrides" cannot set. "workflow" is reserved — an override narrows a mount, it never redirects it to a different package. And null does not mean "no override": it overrides the child's value WITH null. Omit the key instead.
- Overrides nest by mount id for a mount inside a mount: {"<their mount id>": {"overrides": {...}}}. Only reach for that when a grandchild genuinely needs per-instance settings.

Team template (customize roles, criteria, counts):
input.text -> supervisor -> workers (with roles+tools) -> format_report -> grader(criteria = the outcome) -pass-> output; grader -revise-> supervisor.feedback

ALWAYS call validate_workflow on your composed JSON and fix every problem it
reports before answering. Present the final document in a ```json fence.
