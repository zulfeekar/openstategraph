# Parallel Workers Join

Gallery example 2 of twenty — **parallelization**: one worker archetype, run
several times in parallel, joined deterministically.

| Node | One line |
| --- | --- |
| `in1` **Request** | where the request enters |
| `lead1` **Planner** | splits the request into subtasks and `Send`s each one out |
| `worker1` **Analyst** | the only archetype — answers whichever subtask it is handed |
| `join1` **Join** | `function.format_report`: joins the results, no model involved |
| `out1` **Report** | renders the joined report |

Contrast example 5, which fans out to *different* roles. Here the same role
runs N times.

## The join costs nothing, and that is the point

`function.format_report` is a **function**, not a tool and not an agent: the
compiler always runs it, no model decides anything, and the same worker results
always produce the same bytes. It reads `state["worker_results"]`, keyed by the
subtask ids the planner assigned, and emits:

```
# <reportTitle>

### <task-id>
<that worker's result>
```

in task-id order. It **ignores its own incoming edges** — the edge from
`worker1.result` exists to make the graph legible and legal, not to carry data.
That is also why `candidate` is the one unlimited fan-in port in the whole
catalogue, and why it is not a general fan-in mechanism (gallery ticket 14).

A subtask that died renders as a named gap rather than vanishing.

## Read this before you edit the Planner

**Rules on the supervisor are the switch between two decompositions**
(gallery ticket 15). Leave the field empty and `Orchestrator.split` is a regex,
tried in this order:

1. a numbered list (`1.` / `1)`), else
2. semicolons, else
3. the literal word **and**, else
4. the whole instruction as one subtask.

Free, reproducible, and good at a punctuated brief. Write rules and the
supervisor makes one planning call instead, which is what this package now
does — because the recorded smoke question is precisely what a regex cannot
handle, and the rules field carries that question's own failure as its example.

The worker's `role` is now **both** the archetype description the supervisor
labels against and context in the worker's own system prompt (gallery ticket
16), so what is typed there changes how the worker answers. The rules layer
above it is still a wired `input.skill` — that is gallery example 14.

**A worker sees its subtask text and nothing else** — not the original request,
not the other subtasks. A `Send` payload does not inherit the parent's state.
So if the split produces a fragment, the worker gets a fragment.

## Smoke run

```
# it ships in the wheel; copy it into ./workflows once, then run it
openstategraph examples copy parallel-workers-join
openstategraph run workflows/parallel-workers-join \
  "Give me two arguments for and against daily standups."
```

**Before (2026-08-14, batch A, `ollama:gpt-oss:120b-cloud`, ~9s).** The
**shape** was exactly as specified — a `# Standup arguments` heading and two
`###` sections — and the **content** showed the splitter honestly. The
question split on " and " into "Give me two arguments for" and "against daily
standups", so `task-1` was unanswerable on its own and the worker said so:

> ### task-1
> I'm not sure what you'd like arguments about — could you let me know the
> specific topic or claim you'd like two arguments for?

**After (2026-08-15, gallery ticket 15, same model, ~9s).** The planner is a
model call now, and it plans the two stances:

| id | instruction | archetype |
| --- | --- | --- |
| `task-1` | Provide two arguments in favor of daily standups. | `analyst` |
| `task-2` | Provide two arguments against daily standups. | `analyst` |

Two `###` sections again, but each is two real arguments — alignment and
faster issue resolution for the first, fragmented deep work for the second —
and neither worker asks the user anything. `decisions` carries
`{"lead1#task-1": "analyst", "lead1#task-2": "analyst"}` and `outputs` carries
`worker1#task-1` / `worker1#task-2`, so every dispatched instance is
addressable from the run result (gallery ticket 17).
