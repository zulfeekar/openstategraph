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

**Decomposition is deterministic, and no prose can steer it.**
`Orchestrator.split` is a regex, tried in this order:

1. a numbered list (`1.` / `1)`), else
2. semicolons, else
3. the literal word **and**, else
4. the whole instruction as one subtask.

The supervisor's `rules` field shapes only the *archetype-labelling* call — and
with one archetype wired, `label()` short-circuits before making it. So `rules`
here would read like a planning instruction and change nothing, which is why
this package leaves it empty and `tests/` keeps it that way. Gallery ticket 15
carries the gap.

The same applies to the worker's `role`: it is the archetype *description* the
supervisor is shown when labelling, never the worker's own system prompt
(gallery ticket 16). To shape how a worker answers, wire an `input.skill` to
its `skill` port — that is gallery example 14.

**A worker sees its subtask text and nothing else** — not the original request,
not the other subtasks. A `Send` payload does not inherit the parent's state.
So if the split produces a fragment, the worker gets a fragment.

## Smoke run

```
openstategraph run workflows/parallel-workers-join \
  "Give me two arguments for and against daily standups."
```

Recorded 2026-08-14 on `ollama:gpt-oss:120b-cloud`, ~9s. The **shape** is
exactly as specified: a `# Standup arguments` heading and exactly two `###`
sections, `task-1` then `task-2`.

The **content** shows the splitter honestly. That question splits on " and "
into "Give me two arguments for" and "against daily standups", so `task-1` is
unanswerable on its own and the worker said so:

> ### task-1
> I'm not sure what you'd like arguments about — could you let me know the
> specific topic or claim you'd like two arguments for?

That is not a wiring fault and it is not fixable from this package. It is what
a regex splitter does to ordinary English, and it is recorded here rather than
hidden behind a question chosen to flatter it. Semicolons or a numbered list
give clean subtasks today.
