Type: grilling
Status: open

## Question

**Dynamic Workflow / Dynamic Team** (user, 2026-08-08): in chat, describe
what you need and an agent *creates the workflow* — the root (or a dedicated
Architect workflow) is instructed/skilled to compose one dynamically.

Why this is closer than it sounds — every load-bearing piece exists:
- A workflow IS data (`workflow.json`), and the run endpoints accept a
  posted document — an ephemeral, never-saved workflow already runs today.
- The compiler is the validator: `plan()` returns warnings/errors with no
  model and no execution — a perfect grader-evidence source for a
  compose→validate→revise loop (loop-on-evidence, our own adopted rule).
- The node vocabulary is enumerable (registry + `/api/node-contracts` +
  platform tools to read examples); scaffolds show canonical shapes.
- Skills are the instruction surface: an `architect.md` skill teaching the
  document grammar is procedural memory, not code.

Design to grill:
- **Where**: a hidden `workflow-architect` workflow (agent + compile-check
  grader loop) mounted as a routed branch of the concierge ("build me a
  team that...") vs. a tool on the root (`compose_workflow`).
- **The write question**: the concierge is read-only BY DESIGN. Creating a
  workflow is a write. Options: (a) ephemeral-only — architect returns the
  document + a "Save as..." button in chat (human performs the only write);
  (b) a single narrow `save_workflow` tool gated behind human approval
  (HITL node before the save). (a) first, honest and safe.
- **Validation loop**: architect emits JSON → `plan()` + `validate_package`
  findings feed back as grader evidence → revise until clean or capped.
- **Dynamic Team specifically**: the architect composes a Team package
  (supervisor + N workers with roles + grader outcome) — the template is
  `new_team.py`'s document, parameterized by the conversation.
- **Trace/UX**: the composed graph should render via the existing Mermaid
  endpoint before the user runs it — see before you execute.
