# Archetype Orchestrator Report

Gallery example 5 of twenty — **orchestrator-worker with heterogeneous
archetypes**. Two different worker roles are wired; the supervisor labels each
subtask with the archetype best suited to it, and `Send` dispatches it there.

| Node | One line |
| --- | --- |
| `in1` **Brief** | where the brief enters |
| `lead1` **Planner** | splits the brief, then labels each subtask with an archetype |
| `worker-research` **Analyst** | facts, options, trade-offs from what it knows — and the `default` catch-all |
| `worker-write` **Writer** | finished prose: an agenda, a summary, a message |
| `join1` **Join** | joins the results, deterministically, no model |
| `out1` **Report** | renders the joined report |

Contrast example 2, where one archetype runs N times. Here N archetypes are
wired and the plan decides which one each subtask reaches.

## The dispatch key is the worker's **title**

Slugified: `Analyst` → `analyst`. Not its node id, not its `role`. Two
workers whose titles slugify the same are unreachable and the compiler refuses
the document; `tests/` refuses it earlier and says why.

With two or more archetypes wired, the supervisor makes **one extra model
call** whose whole job is to emit one archetype key per subtask. Anything it
invents is validated against the wired keys and collapses to the `default`
worker rather than being trusted — dispatching work to the wrong specialist on
a model's say-so is a silent wrong answer. An unlabelled subtask degrades to
the default the same way, and that degradation is part of the demo.

`role` is what the labelling call is shown as the archetype's description
**and** context in that worker's own system prompt (gallery ticket 16, fixed):
one string, two audiences, which is right because they describe the same
thing. It is context rather than a rules layer, so a wired `input.skill` — or
`rulesMode: replace` — customises behaviour without deleting the worker's
identity.

## Read this before you judge the output

**Decomposition is a plan now, because this card writes rules** (gallery
ticket 15). It used to be a regex — a numbered list, then semicolons, then the
literal word **and**, then the whole brief as one subtask — and the
supervisor's `rules` reached the *labelling* call only, so the planning prose
on this card changed nothing. Rules now drive one planning call; a card that
leaves the field empty keeps the free deterministic splitter.

A worker still receives its subtask text and nothing else, because a `Send`
payload does not inherit the parent's state. That is why the rules ask for
self-contained subtasks rather than fragments.

## Smoke run

```
# it ships in the wheel; copy it into ./workflows once, then run it
openstategraph examples copy archetype-orchestrator-report
openstategraph run workflows/archetype-orchestrator-report \
  "Plan a 30-minute onboarding session for a new engineer."
```

**Before (2026-08-14, batch A, `ollama:gpt-oss:120b-cloud`, ~15s).** It
produced a good `# Onboarding plan` — a full timed agenda — but **it did not
demonstrate what this example is for**, and the catalogue's expected shape was
not met:

- The brief contains no numbered list, no semicolon and no "and", so the
  splitter returned **one** subtask. One subtask cannot come from two roles.
- `decisions` was `{}`. The archetype label was written into
  `state["subtasks"]` and surfaced in a run result nowhere at all — no
  `decisions` entry, no `subtasks` key. Which worker ran was unobservable from
  the CLI. Gallery ticket 17.

**After (2026-08-15, tickets 15 + 17, same model, ~13s).** Both roles run and
the result says which:

```
task-1  analyst  compile essential onboarding topics, required materials …
task-2  writer      draft a 30-minute onboarding agenda with time slots …
task-3  writer      draft a concise welcome email …

decisions  {"lead1#task-1": "analyst", "lead1#task-2": "writer",
            "lead1#task-3": "writer"}
outputs    in1, lead1, worker-research#task-1, worker-write#task-2,
           worker-write#task-3, join1, out1
```

The catalogue's expected shape for example 5 — "`decisions` shows the
archetype label per subtask" — is met and is now assertable; `tests/` asserts
it.

**Two of three post-fix runs labelled; one collapsed every subtask onto the
default worker.** Same document, same model, same question. The labelling call
is one model call and it is allowed to come back unusable — what changed is
that it is no longer *silent*: an unrecognised label logs the label it could
not place, a failed call logs that it failed, and `decisions` writes
`"analyst (default)"` rather than `"analyst"` so the run result
distinguishes a choice from a fallback. That distinction is the half of ticket
17 a run result could not express before.

Two control runs, same package, same day:

| Brief | Plan | Result |
| --- | --- | --- |
| "…agenda…for a new engineer **and** list the accounts **and** tools they need on day one." | 3 subtasks | Split mid-noun-phrase. `task-2` = "list the accounts", `task-3` = "tools they need on day one." — both asked the user to clarify. |
| "Research what a new engineer needs access to on day one**;** write a 30-minute onboarding agenda for them." | 2 subtasks | Clean split, but `task-1` came back **empty** — rendered as `_(this member produced no result)_`, with `warnings: []`. Gallery ticket 18. |

Recorded rather than tidied away. The example is wired exactly as the catalogue
specifies and validates clean; what the runs found is a platform gap, and four
tickets carry it.


## Why this worker is an *Analyst* and not a *Researcher*

It was titled **Researcher** and wired to no tools at all, so it could look
nothing up. Asked to research, `gpt-oss:120b-cloud` narrated its attempts —
*"Let's search.Let's actually run the search.Search."* — and that narration was
published as the report (`every-workflow-green` 19).

The engine half of that is fixed: a worker can now say it is missing a
capability, the same way an agent always could. But a title that promises
lookup over a worker that cannot look anything up is a promise the example
itself was making, and no engine fix repairs a wrong label.

**Renamed rather than given a tool, deliberately.** This example teaches
archetype dispatch — one planner, two kinds of worker, one join. A live web
tool would add a network dependency, a rate limit and a second reason for the
example to fail, none of which teaches anything about dispatch. The `role` now
says outright that this worker holds no tools.
