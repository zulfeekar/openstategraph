Type: grilling
Status: open
Blocked by: 34, 37

## Question

A prebuilt **Team** node: a workflow-inside-a-workflow that runs its own loop
until it meets an expected outcome, then emits one output — usable out of the
box, customizable by the developer (user decision, 2026-08-07: every prebuilt
node ships minimum viable behaviour; extension is dropping files into the
workflow's own directory).

What exists to build on: `workflow.subgraph` (ticket 34, v1 — compiles a named
child document as one node) and the supervisor archetypes (ticket 37 — hybrid
dispatch). A Team is more than either: it *contains* its members (agents,
tools, a grader closing the loop) as an editable subgraph with a defined
entry point and an expected-outcome contract.

Decisions to grill:

- **Containment vs reference.** Is a Team an inline subgraph stored in the
  parent document (one file, moves with it), or a reference to its own
  workflow package (reusable across workflows, shadowable files)? Ticket 34
  chose reference-by-slug; a Team's "customize in place" pull suggests
  inline. Both? What does `annotate.group` become if inline wins?
- **The outcome contract.** "Solves until it meets the expected outcome"
  is a grader closing a loop — is the Team's exit criterion a built-in
  grader node the prebuilt ships with (developer edits its criteria), or a
  structured-output schema the team must satisfy? Where does the step
  budget live?
- **Prebuilt composition.** What is the minimum viable Team the palette
  drops: supervisor + N workers + grader? A ReAct pair? Which parts are
  locked machinery vs editable?
- **UX: focus and collapse.** Selecting a Team opens it for focused editing
  (enter/close); collapsed, the parent view must still show its **entry
  point and outcome** on the card. What does the collapsed card render —
  member count, last run status, the outcome contract?
- **Drag-and-drop vocabulary.** See ticket 53's research for what else in
  LangGraph/LangChain can become a draggable construct; whatever it finds
  feeds the Team's member palette.
