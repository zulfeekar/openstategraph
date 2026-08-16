# The Skill layer — what a skill is, and where it lands in a prompt

**Status: accepted and built, front to back.** The header said "backend
implemented", with ports and fields (ticket 05) and the palette and inspector
(ticket 06) still ahead of it; both landed. `SKILL_PORT_ID` and
`RULES_MODE_KEY` are in `src/nodes/skillLayer.ts`, `input.skill` is a
registered node type with a palette card, and every model-driving node
declares a `skill` port. Corrected 2026-08-16 (production-ready ticket 20).

## Problem

A prebuilt node ships with an inline `systemPrompt` so it works out of the box.
Customising it means editing that textarea on that node in that document — the
opposite of reuse. The wanted shape is: write the domain rules once in a
Markdown file, wire it into any workflow, and have the node's machinery survive
intact.

Two halves were already settled by the owner and are not re-argued here:

- a skill goes on the **five model-driven node types only** — `agent.llm`,
  `orchestrate.worker`, `route.classifier`, `route.grader`,
  `orchestrate.supervisor`. A tool or an I/O atom has no prompt, so a skill
  port there would be a control that reaches nothing;
- a wired skill **extends or replaces the RULES**, never the preamble and never
  the output contract.

What was open: what a skill file *is*, where exactly it composes, what happens
when a node has both an inline prompt and a wired skill, and whether the mode
switch already exists as the Grader's `criteriaMode`.

## Decision

### 1. A skill file is Markdown. Frontmatter is optional, and it is the spec's.

```md
---
name: sql-analyst
description: Answers questions against the Chinook database. Use for revenue,
  genre and artist questions.
---

List the tables, read the schema of the ones you need, then run a single
SELECT. State the SQL you used.
```

- **The body is the entire prompt contribution.** Everything before the closing
  `---` is metadata for humans and pickers. A plain `.md` file with no
  frontmatter — the seeded `sql-analyst.md` — is a complete, valid skill.
- **The frontmatter fields are `name` and `description`, and nothing of ours.**
  Those are the Agent Skills specification's own required fields, which
  `deepagents` reads at discovery (docs-langchain, *Deep Agents → Skills*: the
  middleware "parses each `SKILL.md` frontmatter, and injects the `name` and
  `description` fields into the system prompt"). Adopting them costs one small
  parser and buys interop in both directions — `plugin_interop.py` currently
  *synthesizes* a description on export and *drops* frontmatter on import, and
  both lossy conversions existed only because nothing here could read it.
- Parsed by hand, not with PyYAML: the runtime's four-package dependency floor
  is deliberate, and the specification's frontmatter is a flat string map.
- `description` is never synthesized from the body. A guessed description read
  as authoritative is worse than an absent one.

Implementation: `backend/openstategraph/skills.py` — `SkillDocument` and the
one function the compile path calls, `skill_text()`.

**There is deliberately no `mode:` field in a skill file.** Rejected below.

### 2. Composition: the skill is a rules layer, rendered after the inline rules

`SystemPrompt` (`backend/openstategraph/abc/prompt.py`) is still the single
place order is decided, and the order is now:

```
preamble  →  context  →  [ default rules → inline rules → wired skill ]  →  output contract
   locked     generated                the rules block                        locked
```

Three rules layers, bottom to top:

| Layer | Where it comes from | Editable |
| --- | --- | --- |
| `default_rules` | what the node type ships with (the Grader's default criteria, the Worker's tool directive, and — since ticket 10 — the Agent's and the Router's) | no |
| `rules` | the node's own `systemPrompt` / `criteria` / `rules` field | yes |
| `skill` | the body of the file wired to the node's `skill` port | in the file |

**Why the skill goes above the inline rules and not below.** Later instructions
win ties. A skill is the *deliberate customisation* of a node that already had
a prompt; underneath the inline text it would lose every disagreement with the
thing it was wired to override. This is also a correction: before this ticket
the wired skill rode in `context`, i.e. *below* the rules — so wiring a skill
into a prebuilt agent quietly lost to the prompt the prebuilt shipped with.

**The output contract still comes last, and nothing a skill says can move it.**
`render()` appends the contract after the rules block unconditionally, and
`replace` (below) reaches the rules layers only. Proven in
`backend/tests/test_skill_layer.py::TestTheContractIsLast`, family by family —
agent, router, grader, supervisor — because a new family could compose
`SystemPrompt` in the wrong order while every `SystemPrompt` unit test still
passed.

**Ambient package skills stay context.** `workflows/<slug>/skills/*.md`, loaded
by `discover_skills()`, are house style for every agent in the package — not a
choice made about one node — and they keep riding as generated context, as the
2026-08 audit pinned. A *wired* skill is the other thing. One word, two
mechanisms, and the distinction is which node asked for it.

### 3. Both supplied: they concatenate, inline first, skill last

Not "one wins". With `rulesMode: extend` (the default):

```
default rules
inline systemPrompt
wired skill
```

With `rulesMode: replace`, the **topmost supplied layer** is kept and the ones
beneath it are dropped:

| inline | skill | extend | replace |
| --- | --- | --- | --- |
| yes | yes | defaults + inline + skill | skill |
| yes | no | defaults + inline | inline |
| no | yes | defaults + skill | skill |
| no | no | defaults | defaults |

An empty layer is not a layer: replacing with a blank skill falls back to the
inline rules rather than producing a node with no rules at all. Clearing a
field is far more often a mistake than a request for no guidance.

### 4. The mode field is `criteriaMode`, generalised — one field, not two

`rulesMode: "extend" | "replace"`, default `extend`, declared **once** for all
five model-driven types (ticket 05 owns the TS declaration; the precedent is
`modelField.ts`, created this session for exactly this reason).

`criteriaMode` **is** this field with a narrower name. Its semantics —
"the developer's text replaces the prebuilt text" — are the same verb on the
same layers; the generalisation only adds a third layer above.

**Nothing breaks, and that is checkable rather than hopeful.** With no skill
wired, the table above reduces to precisely today's behaviour: `replace` keeps
the inline text and drops the defaults. So every saved document storing
`criteriaMode` renders the same prompt it rendered yesterday. The backend reads
`rulesMode` and falls back to `criteriaMode`
(`node_runtime._replaces_rules`) — a compatibility *fallback*, never a second
setting: `rulesMode` wins wherever both appear. The fallback may be deleted
once no shipped template or saved document carries `criteriaMode`; until then
it costs one `or`.

**Update (one-chinook ticket 10): half of that precondition is now met, and
the other half never can be.** No shipped document or template carries
`criteriaMode` any more — `workflows/**` and
`backend/openstategraph/templates/**` were swept, and
`workflow-architect/skills/document-grammar.md`, which was *teaching the model
to emit it*, now names `rulesMode` and says outright never to write the old
spelling. That last one was the real leak: left alone, every workflow the
Architect generated would have carried the deprecated field forever, and the
"fallback" would have become a second live spelling.

The precondition's other half — "or saved document" — is not checkable. A
user's saved workflow is not in this tree. So the backend `or` stays, and this
record's original wording was optimistic: it implied a date on which the
fallback could simply go. It cannot, until the editor's own migration
(`skillLayer.ts` rewrites `criteriaMode` → `rulesMode` on load) has been
through a release the project is willing to make a floor.

### 5. Frontmatter is a **disk** format. The wire carries a body. (ticket 28)

The `input.skill` node shipped composing `---\nname: …\ndescription: …\n---\n`
in TypeScript and emitting it on its `skill` port, where `skill_text()` parsed
it straight back into the three values the document already carried. Two
implementations of one format in two languages, and a round trip that produced
nothing that was not already there. Both are now gone:

- **The node emits its body.** `name` and `description` stay in the document as
  `skillName` / `skillDescription`, which is where a picker, an exporter and a
  human read them without paying prompt budget or a parse.
- **Python is the only implementation.** `SkillDocument.parse` reads the
  format, `SkillDocument.render` writes it, in one module, round-trip tested
  (`test_skill_layer.py::TestTheFormatHasExactlyOneImplementation`).
  `plugin_interop`'s `SKILL.md` export — the one place a *file* is genuinely
  produced — goes through `render()` instead of its own third spelling of the
  header, and its own fourth spelling of the *parser* (`_strip_frontmatter`) is
  gone with it. Reading before writing fixed a live defect on the way: a
  `skills/*.md` that already declared frontmatter was exported with a second
  header stacked on the first and a description synthesized from the line
  `---`.

This also fixed a quieter editor-side bug. The canvas preview's `AgentNode`
executor passes whatever arrives on `skill` straight into `system:` — nothing
in TypeScript ever stripped frontmatter — so the local preview was feeding raw
YAML to the model while the backend was not.

**If the string ever must be built in TypeScript again**, it needs a generated
contract test pinning writer against reader. It does not, and the reason is
worth keeping: the editor has no use for the file, only for its parts.

### 6. The blank check is a workflow rule, not an executor branch (ticket 28)

The Skill template ships `{{…}}` blanks, and an unfilled one is a defect: passed
through, `{{the first rule}}` reaches a model as an instruction; deleted, a
half-written skill runs as if finished. That check lived in `skillExecutor`, so
it fired *during* a run — the one moment it is too late to be useful. It is now
`skillBlanksRule` in `WorkflowValidator`'s `Registry<IWorkflowRule>`, an `error`
diagnostic attached to the node and its `instruction` field, so a half-written
skill shows in the panel and on the card before the run button. The node's
"a skill has no name" refusal moved the same way, into the `skillName` field's
own `validate` — declared once in the schema, reported by `fieldValidationRule`
like every other field error. `skillExecutor` now only emits.

### 7. The body key is `instruction`, and `instructions` is declared legacy (ticket 28)

The backend builds `input.markdown` and `input.skill` with one factory,
`_static_text`, which reads the union of the keys those types declare. The Skill
node's private spelling `instructions` made that a three-branch `or`-chain
(`instruction or instructions or content`) — "the shape that hides a fourth".

`legacy_data_keys` is the declared mechanism for a key the backend reads that no
field writes, and it is now used for exactly that: the Skill node's body field
is `instruction`, the Markdown File node's own spelling, and `instructions` is
declared legacy in `port_specs.json`, rewritten out of a document on load by
`withMigratedSkillBody` (the same treatment, for the same reason, as
`criteriaMode` → `rulesMode`). What remains in `_static_text` is one node type's
documented precedence — an edited `instruction` beats a loaded file's `content`
— plus one declared legacy fallback, which `test_data_key_contract.py` now
sanctions explicitly rather than tolerating by accident.

Note what was **not** done: routing the live keys through `legacy_data_keys`
would have been the wrong repair. That list means "no node type declares this
any more", and it is the *only* sanctioned exemption from the data-key
contract; declaring live fields dead there would have switched off the check
that guarantees each key is writable from the editor.

### 8. Skill and Markdown File stay two node types (ticket 28, re-argued)

The counter-evidence is real and was weighed: the compiler gives both types the
same builder, so at runtime they are one concept — a static text source on a
`skill` wire — and after decision 5 above their executors emit the same thing.
A single node with a `source: file | written` mode is a coherent design.

Kept as siblings anyway, on this project's own test — *do they change for
different reasons?*

- **Markdown File** changes when file handling changes: the picker, the accepted
  extensions, the `content`-vs-`instruction` precedence when someone edits a
  loaded file. It has no identity and never will; its name is its filename.
- **Skill** changes when the Agent Skills specification changes: `name`,
  `description`, the template, the blanks, and one day a `SKILL.md` export or a
  skills-directory picker. Its validation rules — a required name, no unfilled
  blanks — are meaningless on an arbitrary `.md` file.

Merging them would put those two change-reasons in one card and force both the
field set *and* the validation to branch on a mode, which is the "one card, two
personalities" shape the `RouterNode` `instruction` bug already cost us once.
Sharing a compile target is evidence about the **runtime**, not about the
editor: a compiler collapsing two authoring concepts onto one construct is the
compiler doing its job, and `_static_text` is deliberately named for the
construct rather than for either node.

**The trip-wire, so this is falsifiable.** If Skill gains a file picker, or
Markdown File gains identity fields, the two have converged and this decision is
wrong — merge them then, with the mode. Until then the duplication left between
them is one shared data key, which is the point of decision 7.

## Alternatives rejected

**A skill file carries its own `mode:` in frontmatter.** Tempting — a skill
author knows whether their text is an addendum or a complete persona. Rejected:
the same file is legitimately an addendum on one node and a persona on another,
so the setting belongs to the wiring, not the file. Worse, a setting readable
from two places is exactly how a developer ends up with a prompt they cannot
predict, which is the failure this ticket exists to prevent. The consuming node
owns it, once.

**A skill *replaces* the inline `systemPrompt` always (last writer wins).**
Simple to state, but it makes the two mechanisms mutually exclusive and forces
a developer to choose reuse *or* a node-specific note. Extending is also the
safe direction for the Worker, whose default directive is what stopped it
answering a database question from parametric memory.

**A skill sits below the inline prompt (skill as a default, inline as an
override).** Coherent-sounding, and it is what the code accidentally did by
putting the skill in `context`. Rejected because it inverts the intent: the
skill is the considered, reusable, reviewed artefact and the inline text is
whatever the prebuilt happened to ship. A customisation that loses every tie to
the thing it customises is not a customisation.

**A skill may extend the preamble or the output contract, "for power users".**
Rejected on CLAUDE.md's rule. It reintroduces the original RouterNode bug in a
new costume: a file that ends "explain your reasoning" would countermand the
output format and every parse would fail — and now it would do so in every
workflow the file is wired into, not one.

**Full progressive disclosure (deepagents' three-level `SKILL.md` loading) as
the wiring mechanism.** That is how the *deep* tier discovers skills it may
choose to read; a wired skill is a skill the developer has already chosen. The
two are complementary and the ladder's honest bottom rung is what this is
(recorded on ticket 66). Nothing here forecloses adding the deep tier's
`skills=[...]` path later — a skill file written to this contract is already a
valid `SKILL.md`.

**Keep `criteriaMode` and add a second `skillMode` beside it.** Two fields on
one node that both spell extend/replace is the duplication-of-knowledge defect,
and the combinatorics of two modes over three layers is not a prompt anyone can
predict.

**A second skill port, or a skill bus.** Out of scope and not needed: `skill`
is `maxConnections: 1` and stays that way. Layering several skills is what the
package's ambient `skills/` directory already does.

## What this enables, and what it constrains

- **Ticket 05** adds the `skill` port and the `rulesMode` field to the five
  model-driven types. The backend already reads both, for all five; nothing on
  this side needs to change.

  **Correction (ticket 07): the middle layer was missing on one of the five.**
  The table above names the `rules` layer as "the node's own `systemPrompt` /
  `criteria` / `rules` field" — and for `orchestrate.supervisor` there was no
  such field. Its factory passed `rules=_text(data, "instruction")`, and
  `instruction` is that node's input **port** id, so the layer this document
  describes as the developer's own could not be written at all: the switch had
  two layers to move between rather than three, and a supervisor's dispatch
  could only be shaped by wiring a file. The supervisor now declares a `rules`
  textarea — same spelling as the Router's, since a fifth name for one layer
  would be the duplication this record already rejects — and
  `backend/tests/test_data_key_contract.py` generalises the guard so no future
  family can read a rules key the editor never declared.
- **Ticket 06** can show the assembled prompt read-only:
  `SystemPrompt.describe()` returns every layer separately, including `skill`,
  with `editable` still naming only `rules` and `replace_defaults`. The skill's
  text is authored in a file and arrives over a wire — it is shown, never typed
  there.
  **Correction (ticket 10): the bottom layer was missing on two more of the
  five, and the bar it exists to meet was never enforced.** The table above
  names `default_rules` as "what the node type ships with" — and neither
  `agent.llm` nor `route.classifier` shipped anything. The router's prompt
  composition did not call `.with_defaults()` at all (two layers, not three), and
  `AbstractAgentNode` accepted a `default_rules` argument that only the Worker
  ever passed, so a stock Agent's `resolve_prompt()` returned `None`.

  That is not cosmetic. The owner's bar for this whole layer is *"works out of
  the box with minimum capability on any workflow"*, and an agent with no rules
  is precisely the state CLAUDE.md records as having let a tool-holding agent
  answer a database question out of parametric memory. Both families now
  declare that layer on their `PROMPT` ClassVar (`PROMPT.default_rules`, one
  `SystemPrompt` per node type since install-experience 19) — generic, about
  honesty and tool discipline only, never domain-shaped, because a domain rule
  on a base class reaches every agent in every workflow and a subclass can only
  append to it.

  One consequence is worth stating because it reverses an earlier reading:
  `resolve_prompt()` returning `None` used to mean "defer to the library's own
  default", and now means "this tier deliberately blanked its defaults". A
  stock agent always passes a `system_prompt`.

- **Prebuilt packages may ship default skill files** — `skills/*.md` in the
  package — and those remain *ambient* context. A prebuilt that wants a skill
  to be its rules wires an `input.markdown` node like any other workflow. A
  prebuilt node must still work with nothing wired, which the `default_rules`
  layer is what guarantees.
