---
name: atom-forge
description: Interview-then-build procedure for adding a new module to OpenStateGraph — a tool atom, a node family, a guard, a memory construct, workflow-specific or generic. Grills the developer one question at a time across eight dimensions (trigger, payload, scope and lifetime, read side, failure modes, tier and family, ports and cardinality, compile target), runs the feasibility honesty gates, scores a 10/10 readiness card, and only then builds TDD through this repository's real pipeline. Use it whenever anyone wants a new node, tool, atom, guardrail, memory segment, cache, summariser or capability on the canvas — including phrasings like "can we have an X node", "build a tool that…", "add memory to this workflow", "I want the graph to remember" — and use it even when they ask only for the code, because the interview is what stops a node being built that compiles to nothing.
---

# Atom forge

Build a new module by finding out what it *is* before writing a line of it.

This is a repository skill, not an agent feature. It assumes nothing but the
ability to read files and run shell commands. Every path below is real; check
one if you doubt it.

## Why an interview and not a spec form

Three modules in this repository were designed this way, and each one's design
turned on an answer nobody would have volunteered:

- **The Guardrail atom** — asking *where does the policy apply* rather than
  *which flags do you want* produced "position is the scope": two of the
  library's three boolean scopes are simply where the node sits, and the third
  has no wire to sit on. (`.scratch/guardrails/map.md`)
- **The youtube-transcript atom** — asking *how does this fail* first produced
  seven distinguishable failure messages, one of which (HTTP 200 with zero
  bytes) is the difference between an agent saying "no transcript" and an agent
  describing a video it never read. (`.scratch/workflow-gallery/research/01-youtube.md`)
- **The tollbooth memory segment** — asking *what writes it, and when* produced
  a deterministic node instead of a second memory tool. See
  `references/worked-example-tollbooth.md`, the interview this skill ships with.

A spec form collects fields. An interview finds the one answer that decides the
design, and it usually arrives two questions after the one you were tempted to
skip.

## The two phases

1. **Interview** — eight dimensions, one focused question at a time, each with
   a redirect that ends the build early when the answer says "this is not a new
   module".
2. **Build** — only after the readiness card reads 10/10, and only through the
   pipeline in the checklist below.

Do not interleave them. Writing code mid-interview is how a dimension goes
unasked and reappears as a rewrite.

---

## Phase 1 — the dimensional interview

Ask **one** question, wait for the answer, then decide the next question from
what you just heard. Do not paste all eight at once: the point is that answer 3
changes question 4. Full wordings, the reasoning each question carries, and
follow-ups are in `references/interview-questions.md` — read it before the
first question.

| # | Dimension | The question, in one line | Redirect if the answer is… |
| --- | --- | --- | --- |
| 1 | **Trigger** | What makes this happen — the flow reaching a point, a condition on the data, or a model deciding? | *a model deciding* → it is a **tool an agent calls**, not a node. Bind the existing one (`save_memory` for memory) or write a `BaseTool`. Stop here. |
| 2 | **Payload** | What exactly moves — which bytes, produced by whom, and does producing them cost tokens? | *"the model summarises it first"* → that is a second node (an agent), not a field on this one. |
| 3 | **Scope & lifetime** | Who else can see this, and when is it gone — this step, this run, this thread, this workflow forever, every workflow? | This **decides the backend**. Never ask "checkpointer or Store or file" — that is asking the developer to pick your implementation. Answers map in `references/interview-questions.md`. |
| 4 | **Read side** | Who reads it back, and how does it reach them — a port, a prompt section, the card, a tool result? | *"the developer edits the injected text"* → prompt machinery is not editable. It is a **Context** section; only Rules are editable. |
| 5 | **Failure modes** | List the ways it fails, and give each one a sentence a *model* can act on. Two failures that share a sentence are one failure. | *"it just fails"* → keep going. Ask specifically: refused vs answered-with-nothing. That distinction is the youtube atom's whole design. |
| 6 | **Tier & family** | Is it an atom, a molecule, or an organism — and which existing family does it join? | *a new family with one member* → check the ladder earns itself. Shared across two families → **composition**, never a common ancestor. |
| 7 | **Ports & cardinality** | What comes in, what goes out, what type, how many links each? | *"sometimes one, sometimes a list"* → vary the **number of ports** with config, never a port's type at runtime. |
| 8 | **Compile target** | Name the LangGraph construct this becomes. | *nothing new* → it is **configuration, a template, or a package to mount** — not a node type. This is the Loop-node refusal, twice recorded: *"A Loop node would compile to nothing new."* (`.scratch/production-ready/tickets/01-a-loop-template.md`) |

**The three refusals worth knowing by heart**, because they are the ones a
developer will push back on:

- A **model-decided trigger** is a tool. The canvas is where deterministic
  structure lives; a decision the model makes belongs in the model's hands.
- A capability needed by **two different families** (retry, timeout, caching,
  logging) is a graph-assembly parameter or a collaborator — never pushed up
  into a shared ancestor. `retry_policy`, `timeout`, `error_handler` and
  `cache_policy` are `StateGraph.add_node` parameters and live on the workflow.
- A **second tier that calls a model** needs to name the judgement it makes that
  a grader downstream would not. The Guardrail node lost its second tier to
  exactly this question (`.scratch/guardrails/map.md`).

---

## The honesty gates

Run these *before* promising anything, and again before the commit. The
owner's phrasing is the law here: **do not promise which is not possible.**

The full checklist with the evidence behind each gate is
`references/honesty-gates.md`. In brief, a design fails if it:

1. **writes into the installed package at run time** — the wheel is read-only,
   shared, and replaced on upgrade;
2. **rewrites a package as it is copied** — copy is verbatim, byte for byte;
3. **puts `Infinity` or `NaN` in a serialisable field** — `int | None`, `None`
   meaning unbounded;
4. **adds a node class with no new compile target** — see dimension 8;
5. **assumes pip can do more than it can** — no live push of a new card into an
   open session, no `openstategraph.functions` entry-point group, an entry point
   that raises is jailed and warned about rather than fatal;
6. **promises coverage the platform cannot reach** — a node cannot act on what
   left before it ran (the live token stream is the recorded example);
7. **reads a `data` key no field declares** — that reads `""` forever, silently;
   `backend/tests/test_data_key_contract.py` now fails it;
8. **claims "zero tokens" while calling a model** anywhere in the path;
9. **lets two node types write one state key with no named reducer**;
10. **registers no browser executor** — a `standard` node without one is
    *silently skipped* in preview. Refuse honestly instead.

---

## The 10/10 readiness card

Score before building. Each line is 1 point, awarded when the answer is
**concrete** — or when it is explicitly deferred *with a stated reason*, which
is a different thing from unanswered and must be written down as such.

```
1. Trigger            — deterministic / predicate / (model-decided → redirected)
2. Payload            — the exact bytes, and their token cost
3. Scope & lifetime   — and therefore the backend it implies
4. Read side          — the surface, and who may edit it
5. Failure modes      — each with its own sentence
6. Tier & family      — and the ladder rung it occupies
7. Ports & cardinality— types, directions, maxConnections
8. Compile target     — a named LangGraph construct
9. Honesty gates      — all ten run, none tripped (or the design changed)
10. Smoke plan        — the one run that proves it, and what it must show
                                                        TOTAL: __/10
```

Below 10, keep grilling. Do not build a 9 — the missing point is the one that
rewrites the other nine.

**Write the card down before building.** The ten settled answers, in the
developer's own words where possible, become a spec — in this repository a
ticket under `.scratch/<map>/tickets/`, elsewhere whatever the project uses.
`.scratch/install-experience/tickets/17-the-tollbooth-memory-segment.md` is
exactly this artefact for the worked example, and
`.scratch/workflow-gallery/research/01-youtube.md` §"Spec" is the same thing for
the youtube atom. An interview whose result lives only in a chat log has to be
run again by the next person, and the second run gets different answers.

---

## Phase 2 — the build checklist

Every path here exists today. Work top to bottom; tests genuinely come first.

**1. Red, in Python.** `backend/tests/test_<thing>.py` — the four canonical
assertions from `docs/building-an-atom.md` (happy path, config determinism,
invalid arguments come back as data, `configure` returns a fresh instance),
plus one test per failure mode from dimension 5. Never let a test hit the
network.

**2. Green, in Python.** Either:
- a prebuilt platform module — `backend/openstategraph/prebuilt_<thing>.py`,
  the `prebuilt_web.py` / `prebuilt_youtube.py` shape: keyless where possible,
  works with no configuration; or
- a new rung on an existing ladder under `backend/openstategraph/abc/`
  (`tool.py`, `agent.py`, `grader.py`, `guardrail.py`, `router.py`,
  `orchestrator.py`, `middleware.py`, `prompt.py`). Implement `_execute`, never
  `run`.

**3. Red, in TypeScript.** `src/nodes/**/<Thing>.test.ts` — assert the seam: the
node id string the Python `node_type` declares, the ports, the field defaults.

**4. Green, in TypeScript.** The card and its field schema. Tool atoms use
`defineToolNode` from `src/nodes/tools/AbstractToolNode.ts`; a platform atom can
join `src/nodes/tools/PlatformToolsNode.ts` rather than opening a new file. An
empty `ToolNodeModel` subclass is a test failure — pass `ToolNodeModel` itself.
Declare configuration **once** as fields; card, inspector, defaults and
validation all derive from it.

**5. Register.** App-wide: `registerNodeCatalogue` in `src/nodes/index.ts`, and
`_process_tool_layer` in `backend/openstategraph/api/registries.py` — **not**
`build_tool_registry`, which assembles layers and holds no list. Workflow-scoped:
one line in `src/nodes/workflowScoped.ts`. Discovered: drop the tool in
`workflows/<slug>/tools/` and add the slug to `pythonpath` in `pytest.ini`.

**6. Tier.** If the palette gains a section or a member, `src/nodes/vocabulary.ts`
is the single declaration and `src/nodes/vocabulary.test.ts` locks the ordering.

**7. Regenerate the port table.** `npm run generate:ports` — it rewrites
`backend/openstategraph/compile/port_specs.json`, which is committed and gated
both by `npm run verify` and by CI. Skipping this is a guaranteed red build.

**8. Package tests.** Use `assert_document_shape` from
`backend/openstategraph/package_testing.py` for any example or package that
carries the new node. A new example also needs its entry in
`backend/openstategraph/examples/index.json` and the counts that quote it.

**9. Gates.**
```bash
npm run verify          # typecheck, lint, format:check, vitest
python3 -m pytest -q    # backend + workflow tests
openstategraph validate workflows/<slug>
```

**10. Live smoke, on Ollama cloud.** `OLLAMA_API_KEY` plus a `-cloud` model
(`gpt-oss:120b-cloud`). Never smoke against a local model: a weak model turns a
wiring bug and a capability gap into the same symptom. Record what ran, what it
returned, and which rung answered — the youtube ticket's live-smoke table is the
format.

**11. Commit.** No prefix convention. One sentence saying what changed and why —
the log reads like `RC-01: generate the port table from TypeScript; the hand
copy held 10 of 38 node types`. Add a `CHANGELOG.md` entry for anything a user
can observe. A change under `src/` or `backend/` with genuinely no documentation
surface says `docs: not-needed — <reason>`.

---

## Reference files

| File | Read it when |
| --- | --- |
| `references/interview-questions.md` | before the first question — full wordings, the reasoning each carries, the scope→backend map, follow-ups |
| `references/honesty-gates.md` | before promising anything, and again before the commit |
| `references/worked-example-tollbooth.md` | to see a real interview end to end: the 2026-08-15 memory-module session, each answer and what it decided, and the spec that came out |

The governing rules this skill enforces are in `CLAUDE.md` at the repository
root. Where this skill and `CLAUDE.md` disagree, `CLAUDE.md` wins and this skill
is wrong.
