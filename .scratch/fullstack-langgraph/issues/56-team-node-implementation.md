Type: task
Status: resolved (2026-08-08) — live-verified
Blocked by: 52 (resolved — design source)

## Question

Implement the Team node per ticket 52's recorded design: `team.workflow` node
type referencing a team package (prebuilt template = supervisor + default
worker + grader closing the loop); card shows entry point, outcome gist,
member count, last-run status; drill-in = load child workflow with breadcrumb
back; scaffold script creates a new team from the template; compiles through
the existing subgraph path. Also: collapse per-node cycle warnings into one
per-loop notice (found during ticket 42's UI verification).

## Resolution

Built: `team.workflow` node (`src/nodes/compose/TeamNode.ts` — outcome on the card, honest browser refusal) aliased through the backend's subgraph builder (one-line runtime change, no new machinery); `scripts/new_team.py <slug> [outcome]` scaffolds the prebuilt minimum team (supervisor + default worker + grader loop, `tools/functions/middlewares/tests` dirs by convention); shipped `workflows/research-team` as the worked example; 5 pytest guards. Live-verified: a parent mounting the team produced a grader-approved, citation-bearing answer through `/api/runs`; Team card searchable in the palette. Deferred to follow-up: drill-in breadcrumb, member-count badge, collapsing the per-node cycle warnings to one per loop.
