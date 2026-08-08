The workflow document grammar (compose EXACTLY this shape):

{"version": 2, "name": "...", "settings": {}, "nodes": [...], "edges": [...]}

Node: {"id": "unique-id", "type": "<type>", "data": {...}, "position": {"x": N, "y": N}}
Edge: {"source": {"nodeId": "...", "portId": "..."}, "target": {"nodeId": "...", "portId": "..."}}

Node types and their ports (in → out):
- input.text — the user's question enters here. out: text
- agent.llm — data: {systemPrompt, rubric?, summarize?, tier: "react"|"deep"}. in: prompt, feedback, tools(bus), skill. out: result
- route.classifier — data: {branches: [{id, name}...], fallback, rules}. in: question. out: branch:<id> per branch
- route.grader — data: {criteria, criteriaMode: "extend"|"replace", maxAttempts, rubric?: [{criterion, required}]}. in: candidate. out: pass, revise (revise MUST loop back to an upstream feedback/instruction port)
- orchestrate.supervisor — data: {maxSubtasks, instruction}. in: instruction, feedback. out: workers (one edge per worker archetype)
- orchestrate.worker — title = its archetype name; data: {role, default?: true}. in: dispatch, tools(bus). out: result
- function.format_report — data: {reportTitle}. in: candidate (accepts many). out: report
- human.approval — data: {message}. in: candidate. out: approved, rejected
- workflow.subgraph / team.workflow — data: {workflow: "<slug>"}. in: input. out: result
- output.formatted — the final answer. in: result (accepts many)

Rules that make a document valid:
- Exactly one input.text with no incoming edge (the entry); flow must reach output.formatted.
- Every cycle needs a conditional exit: grader pass leaves the loop, revise re-enters via a feedback port.
- Tool edges (tool -> tools) are BINDINGS, not sequence: never chain a tool between two agents.
- Router branch port ids are "branch:<branch id>", matching branches[].id exactly.
- A supervisor with several workers: give each worker a distinct title (its archetype) and a role; mark one {"default": true}.

Team template (customize roles, criteria, counts):
input.text -> supervisor -> workers (with roles+tools) -> format_report -> grader(criteria = the outcome) -pass-> output; grader -revise-> supervisor.feedback

ALWAYS call validate_workflow on your composed JSON and fix every problem it
reports before answering. Present the final document in a ```json fence.
