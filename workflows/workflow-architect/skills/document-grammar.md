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
- workflow.subgraph / team.workflow — data: {workflow: "<slug>"}. in: input. out: result. The slug must be one platform_list_workflows returned; never invent one.
- output.formatted — the final answer. in: result (accepts many)

Rules that make a document valid:
- Exactly one input.text with no incoming edge (the entry); flow must reach output.formatted.
- Every cycle needs a conditional exit: grader pass leaves the loop, revise re-enters via a feedback port.
- Tool edges (tool -> tools) are BINDINGS, not sequence: never chain a tool between two agents.
- Router branch port ids are "branch:<branch id>", matching branches[].id exactly.
- A supervisor with several workers: give each worker a distinct title (its archetype) and a role; mark one {"default": true}.
- rulesMode is ONE field across all five model-driven types (agent.llm, route.classifier, route.grader, orchestrate.supervisor, orchestrate.worker): "extend" (default) adds the developer's text to the type's built-in rules, "replace" keeps only the topmost supplied layer. Never emit "criteriaMode" — that was the grader-only spelling of the same field and it is superseded.
- Every model-driven type works with NO rules written and NO skill wired: each ships built-in rules. Write rules only where the domain needs them.

Team template (customize roles, criteria, counts):
input.text -> supervisor -> workers (with roles+tools) -> format_report -> grader(criteria = the outcome) -pass-> output; grader -revise-> supervisor.feedback

ALWAYS call validate_workflow on your composed JSON and fix every problem it
reports before answering. Present the final document in a ```json fence.
