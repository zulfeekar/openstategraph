# Archetype Orchestrator Report

Gallery example 5 of twenty — **orchestrator-worker with heterogeneous
archetypes**. Two different worker roles are wired; the supervisor labels each
subtask with the archetype best suited to it, and `Send` dispatches it there.

| Node | One line |
| --- | --- |
| `in1` **Brief** | where the brief enters |
| `lead1` **Planner** | splits the brief, then labels each subtask with an archetype |
| `worker-research` **Researcher** | facts, options, trade-offs — and the `default` catch-all |
| `worker-write` **Writer** | finished prose: an agenda, a summary, a message |
| `join1` **Join** | joins the results, deterministically, no model |
| `out1` **Report** | renders the joined report |

Contrast example 2, where one archetype runs N times. Here N archetypes are
wired and the plan decides which one each subtask reaches.

## The dispatch key is the worker's **title**

Slugified: `Researcher` → `researcher`. Not its node id, not its `role`. Two
workers whose titles slugify the same are unreachable and the compiler refuses
the document; `tests/` refuses it earlier and says why.

With two or more archetypes wired, the supervisor makes **one extra model
call** whose whole job is to emit one archetype key per subtask. Anything it
invents is validated against the wired keys and collapses to the `default`
worker rather than being trusted — dispatching work to the wrong specialist on
a model's say-so is a silent wrong answer. An unlabelled subtask degrades to
the default the same way, and that degradation is part of the demo.

`role` is what the labelling call is shown as the archetype's description. It is
**not** the worker's system prompt — a worker's own behaviour comes from a
wired `input.skill`, or from the built-in tool directive when tools are bound.
Gallery ticket 16.

## Read this before you judge the output

**Decomposition is a regex, not a plan.** `Orchestrator.split` tries a numbered
list, then semicolons, then the literal word **and**, then gives up and treats
the whole brief as one subtask. The supervisor's `rules` cannot change that —
`rules` reaches the labelling call only. And a worker receives its subtask text
and nothing else, because a `Send` payload does not inherit the parent's state.

The consequence is visible in every run below, and it is gallery ticket 15.

## Smoke run

```
openstategraph run workflows/archetype-orchestrator-report \
  "Plan a 30-minute onboarding session for a new engineer."
```

Recorded 2026-08-14 on `ollama:gpt-oss:120b-cloud`, ~15s. It produced a good
`# Onboarding plan` — a full timed agenda — but **it did not demonstrate what
this example is for**, and the catalogue's expected shape is not met:

- The brief contains no numbered list, no semicolon and no "and", so the
  splitter returned **one** subtask. One subtask cannot come from two roles.
- `decisions` is `{}`. The archetype label is written into `state["subtasks"]`
  and is **not** surfaced in a run result at all — no `decisions` entry, no
  `subtasks` key. Which worker ran is currently unobservable from the CLI.
  Gallery ticket 17.

Two control runs, same package, same day:

| Brief | Plan | Result |
| --- | --- | --- |
| "…agenda…for a new engineer **and** list the accounts **and** tools they need on day one." | 3 subtasks | Split mid-noun-phrase. `task-2` = "list the accounts", `task-3` = "tools they need on day one." — both asked the user to clarify. |
| "Research what a new engineer needs access to on day one**;** write a 30-minute onboarding agenda for them." | 2 subtasks | Clean split, but `task-1` came back **empty** — rendered as `_(this member produced no result)_`, with `warnings: []`. Gallery ticket 18. |

Recorded rather than tidied away. The example is wired exactly as the catalogue
specifies and validates clean; what the runs found is a platform gap, and four
tickets carry it.
