# Architecture review — 2026-08-16

The review before the move to a stable public home (production-ready ticket 36).
Baseline: `docs/decisions/production-audit-2026-08-15.md`, which is spent — both
its self-declared blockers closed. This document measures what landed since.

**Scope: 80 commits, 305 files** — `5ba72ab..HEAD`. The ticket said "~80"; git
reports 80. Inside it: the MCP atom and its panel and multi-row config, the
memory segment, the node-family registry, the ceiling reductions across four
families, `sourceMustDeclare`, the canonicalise/autosave fix, the stream-seam
frames, `openstategraph init`, examples-in-the-wheel, and the site/docs work.

**One scope correction.** The ticket lists "the guardrail atom" in range. It is
not: `src/nodes/guard/GuardrailNode.ts` and `backend/openstategraph/abc/guardrail.py`
were both added at `7e7c517`, which `git merge-base --is-ancestor 7e7c517 5ba72ab`
confirms predates the baseline. Only cosmetic field changes (`text` → `textarea`,
`maxRows`) landed in range. The guardrail still produced two findings, and one of
them is now pinned — but they are findings about a pre-existing atom, and saying
otherwise would credit this range with work it did not do.

**Method.** Nothing below is asserted from reading alone where running was
available. Every count is a command; every claim about a test is that test having
been run; the ladder and prompt claims were established by importing the classes
and asking them, not by reading their docstrings — which turned out to matter,
because two of the findings are docstrings that are not true of the class they
sit on.

**Numbers here are measurements of 2026-08-16 and nothing else.** They are left
as measured, per the baseline document's own rule.

New pins landed with this review:
`backend/tests/test_guardrail_field_contract.py`,
`src/core/extendabilityRegistries.test.ts`.

---

## Verification runs

| Run | Result |
| --- | --- |
| `python3 -m pytest -q` (repo root, as CI runs it) | **3091 passed, 1 skipped** |
| `npm run verify` | **passed** — 143 files, 1971 tests, lint + types + format clean |
| `python3 -m pytest backend/tests/test_guardrail_field_contract.py` | 3 passed |
| `npx vitest run src/core/extendabilityRegistries.test.ts` | 3 passed |
| CI on `HEAD` (`a519fec`, run 31925161443) | **failure** — see F1 |

Two notes on the local runs, because both are ways a green result can be weaker
than it looks.

**Scope.** `pytest backend/tests` collects 2861; `pytest` from the repo root
collects 3092. The 231-test difference is `workflows/*/tests/` and
`backend/openstategraph/examples/*/tests/` — the package tests that are the
product's own claim that a package is real code. Verifying only `backend/tests`
is a materially weaker run than CI's, and this review re-ran at root scope after
noticing.

**The known red was not red.** The `dist/`-mtime gate
(`backend/tests/test_the_wheel_ships_a_current_editor.py:174-179`) passed here.
The one skip is `test_distribution_metadata.py:268`, which skips itself when
`openstategraph` is not installed — a gate that goes quiet rather than red on a
developer machine (F17).

---

## What was measured and found sound

These negative results are why the findings list is shaped the way it is: the
architecture held. Where a rule was broken it was almost always broken *around*
the seam rather than at it, and the reason is visible in the code — the pins that
exist are good, and they are pinned where a reviewer named the seam.

### Secrets cannot reach a document, and that is enforced by type

The highest-stakes check for a repository about to become public, and it is
clean. `McpAuthPayload` (`backend/openstategraph/api/schemas.py:159`) has no
field capable of holding a secret *value*; documents and config carry
`authKind` / `authHeaderName` / `authTokenEnv` — a variable **name**. Both
languages independently refuse a pasted token: `mcpServerFields.ts:151-158`
checks the identifier shape *and* known secret prefixes, catching
`ghp_aaaa…`, which is a legal variable name; `config_file.py:679-707` refuses
the same list, and `backend/tests/test_mcp_field_contract.py:100-107` pins that
both sides refuse it. `POST /api/mcp/validate` (`routes/mcp.py:179-230`) is a
pure read — no badge and no discovered tool list is persisted.

A repository-wide scan for private keys, `sk-`/`ghp_`/`AKIA` tokens and tracked
`.env` files returns four hits, all of them test fixtures asserting that such a
value is *rejected*.

### No vendor name reaches a serialised document, and no vendor import reaches `src/`

All 27 documents (`workflows/*/workflow.json` plus
`backend/openstategraph/examples/*/workflow.json`) were scanned key-and-value for
`langgraph|langchain|state_graph|create_agent|runnable|basemessage|recursion_limit|add_node`:
**zero hits**. The full key census is 68 keys of project vocabulary. All 27
round-trip exactly (`json.loads(json.dumps(d)) == d`) with no `Infinity`, `NaN`
or non-finite literal anywhere.

`rg "from '(langchain|@langchain|langgraph)" src/` → no matches. Every
LangGraph mention under `src/core/` is prose in a doc comment. `core/` imports
nothing from `@view`, `@canvas`, React or JointJS, and that is gated by
`eslint.config.js` inside `npm run verify`, not by review.

The one real leak is a *word*, not a type — `mountCycleRule.ts` says "subgraphs"
in a user-facing refusal — and it was already filed as production-ready ticket
37 before this review reached it.

### One-directionality is actively defended in the new code

Not merely unbroken — argued, at the sites where breaking it would have been
convenient. `src/view/nodes/liveInputValue.ts` exists solely to *display* a run
value without writing it. `MemorySegmentNode.ts:68-83` refuses to put the
ledger's entry count on the card, because that would mean reading the
server-side Store back. `compositionSummary.ts:18` — "reading it back would
break the one-directional compile seam". `mcpRowProbe.ts:65-66` throws away the
validate response's tool list and keeps a verdict.

The one exception is the open parent document, which nobody argued for (F6).

### Middleware is still a slot table, end to end

`resolve_middleware()` returns a `MiddlewareSlotTable` (`abc/agent.py:190-203`);
the base owns the canonical order (`SLOT_ORDER`, `abc/agent.py:69-82`);
contributors name a slot (`injection.py:64`); replacement is by name
(`middleware.py:45-49`); the flatten-to-list happens exactly once, last, in the
template method (`abc/agent.py:222`). Workflow-supplied middleware is
`middlewares/<slot>.py`, where **the file stem is the slot name**
(`api/capability_discovery.py:497-509`).

A grep for append / prepend / insert / priority against `middleware` in backend
source returns nothing, and **no ordering number is exposed to a user anywhere** —
not in `MemorySegmentNode.ts`, `mcpServerFields.ts` or `GuardrailNode.ts`, and
not in the MCP panel.

Neither of the two atoms that could have gone in by list position did. Memory is
not middleware at all — it is a built-in node type plus prebuilt tools. Injection
screening is a *workflow* setting contributing a named slot
(`node_runtime.py:1613-1621`), with the per-agent-checkbox alternative rejected
in-comment as "the duplication the Guardrail node exists to abolish".

### The boundary rule held under the pressure that would have broken it

The `PROMPT` collapse (`29572f4`) touched four families at once — exactly the
shape that produces a shared ancestor. It produced the opposite:
`mcp_server.py:133-137` records in code that Agent / Router / Grader /
Orchestrator are "four unrelated ABCs" whose only common supertype mypy can find
is `ABCMeta`, and each declares its own `PROMPT: ClassVar[SystemPrompt]`. There
is no `AbstractPromptedNode`. Prompt composition is a collaborator, as the rule
requires, and `abc/prompt.py:9-19` states the argument.

`DeepAgentNode` is still a sibling: `abc/agent.py:251` and `:260` both extend
`BaseAgentNode`, differing by one line (`self._constructor =
deepagents.create_deep_agent`). MCP landed *inside* the tool family —
`McpTool(BaseTool)` at `prebuilt_mcp.py:631`, `McpServerNodeModel extends
ToolNodeModel` at `McpServerNode.ts:65` — and the single base change,
`BaseTool.as_langchain_tools()`, is within one family, Liskov-safe by
construction, and recorded in the ceiling test with its argument.

Retry / timeout / `error_handler` / `cache_policy` remain purely graph-assembly:
`set_node_defaults(...)` at `workflow_compiler.py:648-660`, per-node override at
`:277-318`, declared once in `ModelRegistry.defineNode`'s
`EXECUTION_OVERRIDE_FIELDS`. `rg 'retry|timeout|cache_policy'` over
`backend/openstategraph/abc/` and `src/nodes/` finds no declaration on any base —
agent, tool, guardrail or MCP.

Token accounting and logging were **not** unified, deliberately. `progress.py:52-56`
draws the line in the file itself: "it is not a log record, and everything it
could grow … belongs to tracing instead". `rg 'BaseCallbackHandler|callbacks='`
over the whole backend returns nothing.

### The ladder is intact, and its one deliberate collapse is recorded

Established by import, not by reading. Only the agent family runs all four rungs:
`IAgent` → `AbstractAgentNode` (abstract member: `build_agent`) → `BaseAgentNode`
(none) → `ReactAgentNode` | `DeepAgentNode`. Six families run three:
`IGrader` → `BaseGrader` → `Grader`, and the same for router, orchestrator, tool,
guardrail and node-family. In every one of those six the `Base*` class carries
exactly **one** abstract member.

That is not drift. `docs/what-is-this.md:39-41` writes the ladder as
"Interface → **Abstract/Base** → Concrete" for precisely those families and spells
each one out. A rung that would exist to carry one abstract method is the depth
CLAUDE.md's "inheritance must earn itself" tells you not to add.

`PROMPT` is on the correct rung in three of four families. The fourth is F13.

### Reducers, expressions and non-finite discipline

Reducers are a named enum (`compile/reducers.py`; `node_runtime.py:69-114` is
`reducer_for(Reducer.X)` throughout). The guardrail's new state key ships correct
on day one — `node_runtime.py:104`, `redactions: Annotated[dict[str, Any],
reducer_for(Reducer.MERGE)]` — pre-empting the multi-writer rule rather than
waiting for an `InvalidUpdateError`.

`rg '\beval\(|new Function\('` over `src/` returns nothing. The only Python
`exec` is `capability_discovery.py:128` importing a package's own `tools/*.py`,
which CLAUDE.md sanctions and whose trust model is in the module docstring. No
document field feeds it source. All 66 `defaultValue`s under `src/nodes/` are
literals.

Non-finite discipline is applied at each new site with the reasoning at the
field: `maxConnections` null-not-`Infinity` (`contracts/ports.ts:48-50`), the
memory segment's `retention` as blank-means-unbounded with `validateRetention`
refusing `0` (`MemorySegmentNode.ts:29-35`). One door is unguarded (F16).

### The pins that exist are good pins

Worth naming, because the findings below are mostly about pins that are *absent*,
and it would be easy to read this document as saying the pinning culture is not
working. It is; it is under-applied.

- **`port_specs.json` is generated, not mirrored** — emitted by
  `src/nodes/portSpecs.ts`, read by `compile/node_catalogue.py:38`, held by CI's
  `generated-port-specs` regenerate-and-diff job. The emitter is a `.spec.ts`
  under a standalone runner so `npm test` cannot rewrite the artifact it checks
  (`portSpecs.emit.spec.ts:22-24`). **This is the model the findings below ask
  the rest to follow.**
- **`docs/openapi.json` ↔ the FastAPI app** — `test_openapi_contract.py` plus
  CI's `generated-openapi` job.
- **`RuntimeClient.ts` is pinned.** CLAUDE.md:124's "to be pinned … rather than
  by codegen" is history, not aspiration: `src/core/runtime/contractDrift.test.ts`
  (8 tests, green) checks paths, SSE event names and `RunRequest` fields against
  `docs/openapi.json`, and carries its own anti-vacuity control at `:80-89`.
- **MCP field keys and secret prefixes** — pinned both directions by
  `test_mcp_field_contract.py`, extractor guarded at `:56`.
- **Both public-surface censuses are exact and complete.** They compare counts,
  not just names (`test_public_surface_ceiling.py:449-457`;
  `publicSurfaceCeiling.test.ts:382-385`), and both catch a class that is over
  the ceiling and unrecorded *and* one recorded that no longer is. The
  "compares key sets only" defect was specifically looked for and is not there.
  `WorkflowController` is 11 in the pin and 11 in CLAUDE.md. Only the surrounding
  prose drifted (F11).

### Extension points, walked

`src/core/extendability.test.ts` walks three of the seven the **O** rule names.
This review walked the remainder by reading — which is the method that test
exists to replace — so the two that are `Registry<T>` on the `Workbench` are now
walked by `src/core/extendabilityRegistries.test.ts`: a connection rule and a
workflow validation rule, each landing with no edit to any file under
`src/core/`. Canvas features are a real `Registry<IPaperFeature>`
(`PaperController.ts:74`) with an `options.features` install seam, unwalked only
because a walk needs JointJS and a DOM. Card bodies are the one that is not a
registry at all (F14).

The new node-family registry is sound and is the best-argued of them:
`compile/node_families.py` is a `Protocol`-checked lookup with attribution, it
returns a sentence rather than raising so one half-installed plugin cannot cost
an adopter every other capability, and `RESERVED_PREFIXES` keeps `function.` and
`workflow.` unshadowable. No built-in family inherits `BaseNodeFamily` — it is a
registry, not an ancestor.

### Subagent isolation is stated correctly on every surface that touches it

`SubgraphNode.ts:62` "run as one isolated step — task in, answer out";
`WorkerNode.ts:20-22` "a worker never sees the parent's message history or graph
state"; `CompositionBody.tsx:243` "its own overrides, not the shared definition.
Other mounts are unaffected." The Ask panel's spawn row shows the *instruction*,
reinforcing task-in/result-out. No finding.

### Lexicon surfaces that were clean

The MCP panel and the MCP node card and multi-row config: zero forbidden words.
The memory segment card, notably careful — "Leave empty to keep everything —
there is no number here that means unbounded" avoids the non-finite field *and*
the iteration vocabulary in one sentence. **`openstategraph init` is entirely
clean**: nothing it prints or writes contains a banned word, and
`config_file.py:569-571` avoids the *instance* collision by construction. The CLI
help surface is exemplary — package, template and eval each used in exactly one
settled sense. `site/gallery.html` is the strongest copy in the range, refusing
"iterations" by name at `:967`. `docs/on-the-canvas.md` states the lexicon
outright; `docs/evaluation.md`'s "not a third axis" paragraph survived its edit
intact.

---

## Findings

Severity is this review's own judgement and differs in two places from the
sub-audits that produced the evidence; where it does, that is said.

### F1 — the public-API gate is red on the version floor we advertise. HIGH.

CI on `HEAD` is **failing** (run 31925161443). Seven jobs pass, including
`clean-install`, `generated-port-specs`, `generated-openapi`, `e2e` and
`backend (3.13)`. One fails: **`backend (3.11)`**, at
`test_public_api.py::TestTheSurfaceIsWhatWeSaidItWas::test_it_matches_the_committed_snapshot`.

The whole diff is one line:

```
-openstategraph.abc.Progress = class(BaseModel)(*, message: str, current: Annotated[int | None, Ge(ge=0)] = None, …)
+openstategraph.abc.Progress = class(BaseModel)(*, message: str, current: typing.Annotated[int | None, Ge(ge=0)] = None, …)
```

`str(inspect.signature(obj))` (`test_public_api.py:88`) renders `Annotated` bare
on 3.12+ and prefixed with `typing.` on 3.11. `backend/pyproject.toml:10`
declares `requires-python = ">=3.11"`. `Progress` was added **in this range**, at
`6cca9ba`. So the snapshot was generated on a modern interpreter and can only
ever match one.

This is the worst-shaped failure a stability gate can have, and it is worth being
precise about why. The gate exists to tell an adopter that the public surface did
not move. On the floor version it reports that the surface **did** move, on a
clean checkout, with no change — and the message it prints is *"If it was not
intended, you have just changed something an adopter imports."* A gate that cries
wolf on a clean tree on the advertised minimum is a gate people learn to ignore,
and it is the last gate you want that to happen to. Local development is 3.13, so
nobody sees it; one of two matrix legs sees it every time.

*Fix: normalise the annotation repr in the renderer (`re.sub(r"\btyping\.", "", signature)`
at `test_public_api.py:88-91`), regenerate `public_api.txt`, and add a comment
saying why the normalisation is there. XS.*

### F2 — `chat.html` is a third SSE client outside the pin, and it already drops a frame this range added for it. HIGH.

`streaming.py:659` declares `PROGRESS_EVENTS = ("update", "token", "progress", "spawn")`.
`backend/openstategraph/api/static/chat.html:1054-1153` branches on `update`,
`spawn`, `token`, `error`, `interrupt`, `done`. `grep -c 'event === "progress"'`
→ **0**.

`progress` was added at `6cca9ba` and `streaming.py:1146` says why: a silent
forty-second gap "is worse for the audience that cannot open a trace to explain
it." That audience is the customer-facing chat page. It is the one client that
ignores the frame built for it.

The same file also has no `d.block` branch — `chat.html:1131` does
`tokens += d.content` — so reasoning and answer concatenate into one blob. That
is the exact bug `7cd90c6` fixed for the editor, still live on the other surface.

The cause is structural: `contractDrift.test.ts:34` reads `RuntimeClient.ts` and
`McpRegistryClient.ts`. `chat.html` is a client of the same contract and is not
in the list, so both regressions were invisible to a green suite.

*Fix: add `chat.html` to the pin's client list (the matcher needs `event === "x"`
as well as `eventName === 'x'`), then add the two missing branches. S.*

### F3 — `NodeBuildContext.services` publishes the whole runtime to plugins, typed `Any`. MEDIUM.

`abc/node_family.py:76` declares `services: Any = None`, and
`node_runtime.py:1248` passes `services=self.services` — the entire 13-field
`RuntimeServices` (`node_runtime.py:779-836`), including `document_loader`,
`package_loader`, `memory_store`, `knowledge_dir_override` and `advisor_catalog`.

The module docstring two dozen lines above says the opposite of what the field
does: "What a family may see is `NodeBuildContext`, not the runtime … the narrow,
named set of things building a node legitimately needs" (`node_family.py:30-36`).
Every other field on that context delivers exactly that. This one re-widens the
seam to the compiler internal the context exists to hide.

It is not a private slip. `NodeBuildContext` is **in the committed public-API
snapshot**, `services` included:

```
openstategraph.abc.NodeBuildContext = dataclass(object) fields(node_id,node,plan,services,diagnostics,upstream_text,resolve_model)
```

So this is the one new semver-public extension seam in the range, and `Any` means
nothing pins its width: a field added to `RuntimeServices` next month is
published to every installed plugin with no diff anywhere a reviewer looks. The
`Any` has a stated and legitimate reason — keeping `abc` out of the compiler's
import graph — which is an argument for a typed façade, not for the whole object.

*Fix: replace with the two or three named collaborators a family actually needs,
or a typed frozen façade, so widening it is a visible edit. M.*

### F4 — the SSE pin stops at the event name and never reaches the frame's fields. MEDIUM.

Graded HIGH by the sub-audit; this review says MEDIUM, because the one
demonstrated gap is currently unreachable in the editor.

`contractDrift.test.ts:64-68` extracts event **names** from the OpenAPI
description. The per-frame **field** vocabulary — `docs/api.md:97-99`
authoritative, `streaming.py:508-602` emitting, `RuntimeClient.ts:802-880`
re-declaring ~30 field names by hand — is an unpinned hand-mirror.

The live gap: `withheld` is emitted (`streaming.py:548`), documented
(`docs/api.md:98`), Python-tested (`test_customer_token_stream.py:188`), and read
by **nothing** in `src/` or in `chat.html`. `audience.py:80` says the field exists
precisely so a client can distinguish "emptied deliberately" from "nothing
happened"; no client can. It is unreachable today only because the editor always
sends `audience: 'developer'` — but `RunRequest.audience` is public on the
client's own type at `RuntimeClient.ts:79`, so the mitigation is a caller
convention, not a guarantee.

*Fix: extend the extractor to the `docs/api.md:97-99` field table, or emit the
field list from `sse_contract.py` beside the names, and assert each field appears
in each client. M.*

### F5 — the provider credential key is a mirror whose failure mode is a silent drop. MEDIUM.

Graded HIGH by the sub-audit; MEDIUM here, because no drift exists today.

`runtimeCredentialKey` in `AnthropicProvider.ts:41,45`, `OpenAIProvider.ts:33,37`
and `OllamaProvider.ts:61,72` mirrors `ProviderSpec.env_vars` in
`providers.py:626-667`. `providerCredentials.ts:27` sends `{[runtimeCredentialKey]: key}`;
`model_resolution.py:218-220` **silently `continue`s** on a name not in
`accepted_credential_keys()`.

`OllamaProvider.ts:42` quotes the Python tuple `env_vars=("OLLAMA_API_KEY", "OLLAMA_HOST")`
in prose — the mirror is acknowledged in a comment and held by nothing. Each side
tests its own half; nothing compares them. A one-character divergence produces
exactly the bug `providerCredentials.ts:6-12` says it was written to fix: key
pasted in the editor, run reports "no model configured", nothing logged.

*Fix: one pytest reading the three `*Provider.ts` files for
`runtimeCredentialKey = '…'` — guarded by asserting three matches — and asserting
the set is a subset of `accepted_credential_keys()`. S.*

### F6 — asking a question rewrites the committed document. MEDIUM.

`AskPanel.tsx:830` — `if (entry) controller.nodes.setField(entry.id, 'prompt', trimmed);` —
writes the typed question into the open document's entry node.
`WorkbenchContext.tsx:490` subscribes autosave to `controller.onChange`, and
`:471` carries it to `workflow_store.py:463`, which writes the file. So running a
workflow mutates the vendor-neutral source artifact that `git diff` and the CLI
read.

The codebase already states the principle and applies it to *children* only:
`liveInputValue.ts:13-19` says the live question "must not be written even when
the child *is* opened, because that would edit a saved document to display a fact
about a run." The open parent is the exception nobody argued for.

The working tree at review time carried the evidence: `workflows/workflow-architect/workflow.json`
was modified, `savedAt` moved from `2026-08-08` to `2026-08-15T22:46:24`, with
geometry written onto every node. (Two things that *look* like damage in that
diff are not: `hidden: true` is carried over and re-appended at `:221` by
`WorkflowStore._write`, and node `in1` is reordered, not deleted. Both were
checked rather than assumed.)

*Fix: hold the question in run state and render it through `liveInputValue`, as
children already do; drop the `setField`. S.*

### F7 — the guardrail's `detector` regex is validated by running it. MEDIUM.

`abc/guardrail.py:106` stores `detector: str`. It becomes a pattern only inside
`resolved()`, called from `screen()` at run time (`:273`), and the surrounding
`try` catches `PIIDetectionError` only (`:274-276`) — so a malformed pattern
raises `re.error` mid-run. `node_runtime.py:2004` constructs `Guardrail(...)`
without resolving, so compile never touches it. Nothing in `validation.py`,
`compile/diagnostics.py` or `src/core/validation/` mentions `detector`, and the
TypeScript field (`GuardrailNode.ts:224-232`) carries no `validate:`.

A real pattern already ships in a document
(`examples/guarded-lookup/workflow.json`), so this is a live path. The
regex-not-lambda choice is correct and well argued (`guardrail.py:89-103`); this
is about the unvalidated hop between the two. The recorded trust argument — "a
pathological pattern is the author's own to run on the author's own server" —
assumes author and operator are the same person, which a mounted third-party
package and the Workflow Architect both break.

*Fix: `re.compile` at compile time with a length cap, emitting a diagnostic
instead of a run-time raise. S.*

### F8 — the plugin field `kind` is a closed set defined three times, with three memberships. MEDIUM.

| Where | Set |
| --- | --- |
| `src/core/model/contracts/fields.ts:41-172` (authoritative) | text, textarea, select, combobox, slider, toggle, file, readonly, repeatable-group |
| `abc/tool.py:63-64` ("deliberately from a small closed set") | text, textarea, select, toggle, **number** |
| `docs/building-an-atom.md:69` | text, textarea, select, combobox, slider, toggle, … |
| `src/app/pluginNodes.ts:175-198` (the renderer) | textarea, toggle, select, **default → text** |

`number` is documented as a member at `abc/tool.py:64` and
`docs/building-an-atom.md:504`, and `pluginNodes.ts` has no `number` branch — so a
plugin author following the documented set gets a text box, silently.
`schemas.py:643` types it `kind: str` with no `Literal`, and
`plugin_capabilities.py:90` defaults to `"text"` without validating. The wire
*shape* is properly published as `ToolFieldResponse`; the *vocabulary* has no
owner.

*Fix: export the supported-kind list from `pluginNodes.ts`, pin it against a
`PLUGIN_FIELD_KINDS` constant in `abc/tool.py`, and route an unsupported kind
through the existing warnings channel. M.*

### F9 — "instance default" is a second live sense of a settled word, and this range spread it. MEDIUM.

CLAUDE.md fixes **Instance** as one mount of a package carrying its own
`data.overrides`. "Instance default" means the *installation's* elected provider —
a different noun entirely — and this range put it in user-facing copy in five
places: `docs/adoption.md:648` and `:542`,
`examples/chained-summarizer/AGENTS.md:52`,
`examples/youtube-trend-digest/AGENTS.md:58`, `openstategraph.example.yaml:26`.
The two `AGENTS.md` files ship inside copied packages, so a user reads them.

This is the same shape as the *loop* and *template* collisions the lexicon table
was written to settle, caught earlier this time.

*Fix: **installation default** in user-facing copy; the internal `elected_default`
identifier can stay. S.*

### F10 — "package" is used in the forbidden PyPI sense in three entry documents. MEDIUM.

CLAUDE.md: **Package** = `workflows/<slug>/`, never "a PyPI distribution, in
user-facing copy". All three added in range: `README.md:66`, `docs/adoption.md:27`
and `docs/what-is-this.md:65` all say **"four-package core"**.

The collision is sharp because `docs/adoption.md` uses the settled sense heavily
in the same document (`:195` "Every scaffolded package carries an `AGENTS.md`",
`:201` "Twenty-three finished packages ship in the wheel") — a reader meets both
senses within one page, and one of the two is the first page an adopter opens.

*Fix: "a four-module core". XS.*

### F11 — three prose claims that have gone stale beside pins that are sound. MEDIUM.

The defect this repository names most often, found three more times — and once
inside the paragraph congratulating itself for having fixed it.

1. **CLAUDE.md** — *"The exception is **43**, and that number is now pinned too …
   A forty-fourth member is a red test."* The pin says **41**
   (`publicSurfaceCeiling.test.ts:112`), and its own `:131` explains the drop
   (install-experience 21 removed `requireNode` and `isEmpty`). A **forty-second**
   member is the red test. The pin worked exactly as designed; the prose drifted
   anyway, because only the test's number was ever pinned and the sentence about
   it was not.
2. **`publicSurfaceCeiling.test.ts:75`** — the same file's own header still says
   "`WorkflowModel` at 43", two screens above the 41 it asserts.
3. **`CONTRIBUTING.md`** — two rows of the gate table are now wrong in the
   reassuring direction. The god-class row says *"**No gate.** Nothing counts
   members"*; two censuses count members exactly. The Pydantic-seam row says
   *"Until that test lands, a hand-mirror is review-only"*; `contractDrift.test.ts`
   landed and passes.

*Fix: 43→41 and 44→42 in CLAUDE.md and in the test's header; rewrite the two
CONTRIBUTING rows to name the pins that exist. XS.*

### F12 — six of the eight settled words have no pin, and the guard reaches one tree. LOW.

`src/core/lexicon.test.ts` pins exactly two patterns — `/revise loop/i` and
`/max iterations/i` — over quoted strings in `src/` only. So `site/`, `docs/` and
the CLI copy under `backend/openstategraph/` are outside it entirely, and
*template*, *package*, *instance*, *workflow node*, *eval* and *step budget* have
no pin on any surface. F9 and F10 are both words this guard was written for and
could not see.

By this repository's own standard — "an argument with no way to fail is a story" —
three quarters of the lexicon is currently a story.

Also here, as the smallest instance of the same thing:
`site/behind-the-scenes.html:435` opens with *"You drew four boxes and one loop"*,
unqualified, twenty lines before the page defines *revision loop* at `:456`. Every
later use on that page is correct.

*Fix: widen the guard's roots to `site/`, `docs/` and `backend/openstategraph/**/*.py`;
add patterns for `max turns`, bare `iterations` near `recursion_limit`, and
`instance default`; fix the hero line. M.*

### F13 — `CustomGraphNode` carries the prompt that five documents say it has not. LOW.

The argument against `AbstractPromptedNode` is stated in CLAUDE.md, in
`abc/prompt.py:9-19`, in `abc/router.py:229`, in `docs/what-is-this.md:45` and in
`abc/agent.py:291-296`, and every one of them turns on the same clause: it "would
force a prompt onto `CustomGraphNode`, which has none."

It has one. Measured by construction, not by reading:

```
>>> n = CustomGraphNode(name='c', runnable=object())
>>> n.resolve_prompt() is None
False
>>> len(n.resolve_prompt())
296
```

`PROMPT` is a `ClassVar` on `AbstractAgentNode` (`abc/agent.py:112`) with 289
characters of `default_rules`; `CustomGraphNode` extends `AbstractAgentNode`
directly, so `__init__` composes `self.prompt` for it and `resolve_prompt()`
returns those rules. Nothing consumes them — `build()` returns the runnable
untouched — so this is dead state rather than a behavioural bug.

But the rule was obeyed in letter and lost in substance: the shared prompt
ancestor was not created, and then `PROMPT` was put on the one class that is
`CustomGraphNode`'s parent, which forced a prompt onto it by the shorter route.
The five sentences are the design intent; the class is what shipped.

*Fix: move `PROMPT` and the prompt composition down to `BaseAgentNode`, where
`ReactAgentNode` and `DeepAgentNode` both live. `CustomGraphNode` then genuinely
has none, and its recorded ceiling count drops by the members it never used. S.*

### F14 — card bodies are the extension point that never became a registry. LOW.

The **O** rule names seven extension points and says every one is a `Registry<T>`.
Six are. `src/view/nodes/nodeBodyRegistry.tsx:31` is a module-level
`const BODIES = new Map<string, NodeBody>()` with a bare `registerNodeBody`
setter.

What it loses against `Registry<T>` is not cosmetic: `Registry.register` throws on
a duplicate id (`Registry.ts:36`), `BODIES.set` silently overwrites — so a plugin
can replace a built-in card body with no error and no way to notice. There is no
`list()`, so nothing can enumerate what is registered; there are no events; and
because it is module-global rather than owned by the `Workbench`, no test can get
a fresh one.

The docstring advertises the escape hatch — "a plugin can ship a bespoke body
without touching the card" — and `rg registerNodeBody src/` finds **zero callers
outside the file itself**. The hatch has never been used, which is why the shape
has never been felt.

*Fix: make it a `Registry<NodeBody>` on the `Workbench` alongside the other six,
and walk it in `extendabilityRegistries.test.ts`. S.*

### F15 — three tests that can go quiet. LOW.

- **`nodeWriteSeam.test.ts:52-60`** asserts `expect(offenders).toEqual([])` where
  `offenders` comes from a regex over all sources. Rename the write seam and the
  extractor matches nothing and the test passes forever. Not vacuous today (six
  live calls in `WorkflowModel.ts`), but its two siblings —
  `contractDrift.test.ts:80-89` and `test_mcp_field_contract.py:56` — both added
  exactly this control and this file did not.
- **`seedDemo.test.ts:126-139`** greps built `dist/assets/*.js`. It correctly
  fails when `dist/` is missing, but a **stale** `dist/` passes: reintroduce the
  seed in `src/` without rebuilding and it stays green. The source-level claim is
  separately pinned at `:118-124`, so this is belt-and-braces rather than the only
  guard — but it couples `npm test` to having run `npm run build`.
- **`test_distribution_metadata.py:268`** skips itself when `openstategraph` is
  not installed. It is the one skip in the suite, and on a developer machine it is
  a gate that reports nothing rather than red.

*Fix: a positive control on the first, a source-level assertion replacing the
`dist/` grep on the second, and a decision on whether the third should be a hard
failure outside CI. S.*

### F16 — node geometry has no non-finite guard; edges do. LOW.

`EdgeModel.ts:86-91` filters `Number.isFinite` and its comment calls itself "the
one door they can come through" (`:81-84`). `AbstractNodeModel.ts:188-194`
assigns `{...position}` / `{...size}` verbatim from canvas drags — a second door.
A `NaN` would `JSON.stringify` to `null` and land in a document as `"x": null`.
Pre-existing; no commit in range touches the file. It is listed because F6 shows
the canvas does reach the file on disk.

*Fix: the same `Number.isFinite` filter in `write.position` / `write.size`. XS.*

### F17 — one seam direction is real, sanctioned, and unrecorded. LOW.

`capability_discovery.py:128` imports a package's `tools/*.py`;
`capabilityRefresh.ts` → `workflowScoped.ts:177-200` → `DiscoveredToolNode.ts:49-52`
mints a node *type* whose id is the Python qualified name
(`<slug>/tools.QueryTool`), placeable and therefore writable into a document. The
result is still serialisable and vendor-neutral, and the type travels with the
package — but the document now names a type that is absent from `port_specs.json`
and resolvable only by importing Python.

Portability guardrail 3 says "the compile seam is one-directional:
`workflow.json` → runtime". This is a *code → canvas* channel, not a runtime →
model one, so it does not break the rule — but the rule is silent about it, and a
reader checking the guardrail against the code will find a direction the guardrail
does not mention.

*Fix: record `code → canvas` as a named, bounded exception in CLAUDE.md's
portability guardrails. XS.*

---

## The pattern behind the pin findings

F2, F4, F5, F8 and the two pins that landed with this review are one defect
wearing six hats, and it is worth stating because the fix for each is cheap while
the fix for the shape is a habit.

The cadence built a good pin **whenever a reviewer named the seam** — port specs,
OpenAPI, MCP keys, the ceilings, the guardrail vocabulary. What it missed, every
time, was the **second consumer**: `chat.html` behind `RuntimeClient.ts`,
`WorkflowFileClient.ts` behind the two clients that are pinned, `pluginNodes.ts`
behind `fields.ts`, the browser provider behind the server provider. And where a
pin exists, it stops at the **name** and does not reach the **value** — event
names but not frame fields, MCP field keys but not MCP vocabularies, `audience`
as a key but not its two values.

Both are the same thing: the pin was written against the file that was in front
of the author. `port_specs.json` is the counter-example and the model — it is
*generated*, so a second consumer cannot exist without the generator knowing.

---

## Is this ready to be public?

**Not yet — but the gap is two days of work, not a rewrite, and none of it is
architectural.**

The architecture holds. That is the substantive finding of this review and it is
not a courtesy: the boundary rule survived a four-family sweep that was shaped
exactly like the pressure that breaks it; the compile seam is one-directional and
is *argued* to be at four separate sites where breaking it would have been
convenient; no secret can reach a document, by type rather than by convention; no
vendor name is in any of the 27 shipped documents; middleware never acquired a
position number; the ladder is intact and its one collapse is written down. Of
the seventeen findings, exactly one (F13) is about a class shape, and it is dead
state behind a true design decision.

What is not ready is the **evidence layer**, and for a project whose entire pitch
is "the output is a standard Python object you can run without this editor", the
evidence layer is the product. An adopter's first three encounters are `pip
install`, `README.md`, and a red or green CI badge. Today the first of those is
fine, the second uses a forbidden word in its own vocabulary, and the third is
red on the minimum Python version the first one promises.

### Blockers

1. **F1 — CI is red on `HEAD`, on the declared floor.** Nothing ships from a red
   main, and this particular red is worse than an ordinary failure: it is the
   stability gate falsely reporting that the public API moved, on a clean
   checkout, on the version `pyproject.toml` advertises. XS to fix.
2. **F2 — the customer-facing chat page drops two frames the editor handles.**
   `progress` was built in this range for exactly that page, and it is the one
   client that ignores it; reasoning and answer concatenate there as well. This is
   a live user-visible defect on a shipped surface, not a latent risk. S to fix.
3. **F10 — `README.md` breaks the project's own lexicon on line 66.** Trivially
   small, and it is the first document a stranger reads. XS to fix.

### Not blockers, but fix before the second week

F6 (a chat turn rewriting the committed document) will produce confused bug
reports the moment two people share a repository, and the working tree already
carried an instance of it. F5 and F8 are silent-failure paths whose symptom is
"it just doesn't work, with no message" — the most expensive kind of adopter
issue. F3 is the one new semver-public seam, and it is cheaper to narrow now than
after a plugin depends on its width.

### What this verdict is not

It is not a claim that the seventeen findings are the whole surface. Two things
this review could not establish are worth naming: whether F6 was a decided
trade-off (the counter-argument is written for children and no decision document
covers the open parent), and whether `rubric`'s flatten position is *semantically*
wrong for deepagents' middleware (established only that the slot is missing from
the base's declared order — the process defect, not the behaviour). Neither
changes the verdict; both would change a ticket.

---

## Tickets filed

Twelve tickets, grouped by defect shape rather than one per finding — the
`F4`/`F5`/`F8` cluster is one habit wearing three hats and splitting it would
have produced three tickets with the same fix written three times.

| Finding | Ticket | Size |
| --- | --- | --- |
| F1 | `production-ready/40-the-stability-gate-is-red-on-our-own-floor.md` | XS |
| F2 | `production-ready/41-the-page-the-frame-was-built-for-ignores-it.md` | S |
| F6 | `production-ready/42-asking-a-question-rewrites-the-document.md` | S |
| F9, F10, F12 | `production-ready/43-four-of-eight-settled-words-are-prose.md` | M |
| F11 | `production-ready/44-three-numbers-that-outlived-their-pins.md` | XS |
| F13 | `production-ready/45-the-node-with-no-prompt-has-one.md` | S |
| F16, F17, + two middleware nicks | `production-ready/46-a-second-door-and-an-unnamed-direction.md` | S |
| F15 | `production-ready/47-three-tests-that-can-go-quiet.md` | S |
| F3 | `framework-packaging/09-a-plugin-seam-that-hands-over-the-runtime.md` | M |
| F4 (+ MCP values, `audience` enum) | `framework-packaging/10-the-pins-stop-at-the-name.md` | M |
| F5, F8 (+ `WorkflowFileClient`) | `framework-packaging/11-the-second-consumer-nobody-pinned.md` | M |
| F14 | `framework-packaging/12-the-seventh-extension-point.md` | S |
| F7 | `guardrails/05-a-pattern-validated-by-running-it.md` | S |

Two middleware nicks found in passing did not earn a finding number and are
carried in `production-ready/46`: `"rubric"` is contributed at
`node_runtime.py:1639` but absent from `SLOT_ORDER` (`abc/agent.py:69-82`), so it
flattens through the unknown-slot bucket — a position chosen by "the base has
never heard of this" rather than by an argument; and `MiddlewareSlotTable.merge`
(`abc/middleware.py:63`) reads another table's private `_slots`, which is set
order rather than the source's own `flatten()` order.

Four tickets were filed by this review before the report was written and are not
re-filed here: `production-ready/37` (the `--xray` claim on the two surfaces a
reader actually reads — which is also where `mountCycleRule.ts`'s "subgraphs"
string is handled), `production-ready/38` (a dead TypeScript prompt mirror that
has already drifted), `production-ready/39` (the Agent's locked prompt layer is
published by nothing), and `memory-hardening/10` (a memory card promising a bound
the ledger does not keep).
