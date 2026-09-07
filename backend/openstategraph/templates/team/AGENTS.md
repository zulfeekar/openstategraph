# {{name}} (a Team)

An OpenStateGraph **team package**, scaffolded from the **team** template:
supervisor + default worker + a grader whose criteria are the team's outcome
contract.

## What is in here

```
input.text → lead1 (supervisor) ⇉ member1 (worker) → join1 (report) → grader1 ──pass──→ output
                  ▲                                                        │
                  └──────────────────────── revise ────────────────────────┘
```

- **`lead1` (`orchestrate.supervisor`)** — splits the request into at most
  `maxSubtasks` independent subtasks and fans them out. The fan-out is real
  parallelism, not a loop in disguise.
- **`member1` (`orchestrate.worker`)** — the default archetype: whatever the
  supervisor cannot assign to a specialist comes here. Each additional worker
  you add is a new archetype, named by its title.
- **`join1` (`function.format_report`)** — merges the workers' results into one
  document. Deterministic Python, not a model call.
- **`grader1` (`route.grader`)** — the outcome contract. `revise` goes **back**
  to the supervisor, which is what makes this a loop rather than a pipeline; a
  cycle needs a conditional edge to terminate, and the grader is it.

Discovered by convention: `tools/`, `functions/`, `middlewares/`, `tests/`.

## Mount it

A team is meant to be *used by* another workflow. Add a **Team** node in any
workflow and point it at the slug `{{slug}}`. It also runs on its own:

```bash
openstategraph validate .
openstategraph run . "the task"
```

## The obvious next step

1. **Edit `grader1`'s criteria.** That is what "done" means for this team, and
   it is the first thing worth writing by hand.
2. **Add a member.** A second `orchestrate.worker` with a distinct title
   becomes a distinct archetype the supervisor can dispatch to by name.
3. **Wire tools.** Drop `BaseTool` subclasses into `tools/` and bind them to
   the workers that need them; `middlewares/` and `functions/` are discovered
   the same way.
4. **Publish it.** This package is a **draft** (`"published": false`) — publish
   only if you want it on the customer `/chat` surface in its own right. A team
   mounted inside another workflow does not need to be published.
