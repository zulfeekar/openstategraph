# OpenStateGraph — engineering rules

The non-negotiables a generated tool, node type or workflow must obey. Short
form: every section here names a section of the platform's own architecture
document, which carries the arguments. Read this before you build; read
`get_node_vocabulary` before you compose.

## No god classes

A class with many public members is a design failure, not a convenience. If
it can be described only with "and", split it.

Ceiling: about ten public members, one reason to change. Extend a class that
is at the ceiling by giving it a collaborator, never another method.

A module has a ceiling too — 500 code lines, counting lines that carry a
token which is not a comment and not a docstring. Long argued docstrings are
free; a long prompt string is not, because somebody has to read it.

## Interface → Abstract → Base → Concrete

Every entity family declares this ladder, and every layer earns its place:

- `I*` — the contract consumers depend on. Consumers import the interface.
- `Abstract*` — shared behaviour with genuinely abstract members.
- `Base*` — a usable default implementation.
- Concrete — one node type, one tool, one provider.

This applies to every concept: node, edge, tool, provider, workflow. Where a
hierarchy exists only to share two fields, use composition and say so. Depth
is not a virtue, and an override that throws or no-ops means the hierarchy is
wrong.

### Never invent a node type

Never a type the registry does not know. A document naming a type nothing
resolves is a workflow that cannot run, and a model that guesses a type
guesses its ports too.

That is not a rule against new types. When nothing registered fits, extend
through the family's base — `I*` → `Abstract*` → `Base*` → concrete — then
register it, and only then use it. `docs/building-an-atom.md` is the
pipeline. Ask `get_node_vocabulary` what exists before deciding nothing does.

## Shared concerns live on the base

Anything every member of a family uses — middleware, model resolution, token
accounting, retry, error handling — is declared once on the abstract base,
never re-declared per concrete type.

But inherit the *capability* to compose, not the composition. A base that
instantiates a fixed middleware list is a fragile base class: adding one
silently changes every subclass. Middleware order is a slot table, because
list position means three different things at once — `before_*` runs first to
last, `after_*` runs in reverse, `wrap_*` nests. Any scheme expressing
position as one number expresses something that does not exist.

## A prompt is composed

Every node that drives a model splits its system prompt in four, and only one
part is editable:

| Part | Owner | Editable |
| --- | --- | --- |
| Preamble — what this node is | the base | no |
| Context — branches, schema, rubric | generated | no |
| Rules — the domain logic | the developer | yes |
| Output contract — the shape of the answer | the base | no |

Order is the substance: the output contract goes last, because later
instructions win ties. Never ship the contract as a pre-filled editable field
— the first thing anyone does is clear it.

## The boundary

Sharing has two axes and only one of them is inheritance.

- Shared **within** a family — every agent needs summarization config — is an
  abstract base class.
- Shared **across** families — an agent and a tool node both want retry — is
  composition: a registry, a mixin, a decorator, a graph-assembly parameter.

Pushing a cross-family concern into a common ancestor is how a god base class
starts, and it forces members to carry capabilities they never use.

## SOLID, applied concretely here

- **S** — one reason to change.
- **O** — extend by registering, never by editing the engine. Every extension
  point is a registry: node types, executors, providers, connection rules,
  validation rules, card bodies. A new capability must not require touching
  the core.
- **L** — a subclass is substitutable for its base.
- **I** — narrow interfaces, so a node opts into being a tool without
  carrying methods it does not implement.
- **D** — depend on abstractions. The framework-free core imports no UI
  framework, ever.

## DRY — but not by accident

Duplication of *knowledge* is the defect; duplication of *shape* is often
fine. Two things that look alike but change for different reasons stay apart.

Hard rules: node configuration is declared once as a field schema, and the
card, the inspector, the defaults and the validation all derive from it; one
binding table drives both a dispatcher and the drawer that documents it; a
hand-written mirror of a generated contract needs a drift test pinning it, or
it is not allowed to exist.

## Cardinality belongs to the port

There is no node-level "accepts multiple edges" flag. Cardinality is
`maxConnections` on the port descriptor — in = 1, out = unlimited by default
— and one node has ports of different cardinality at the same time.

Two distinct mechanisms, kept distinct: a port that accepts many links is a
bus (`maxConnections`); a node whose *number* of ports varies with config
declares its ports as a function of its data. Prefer varying the number of
ports. A port that is sometimes a scalar and sometimes a list changes type at
runtime, which is what typed ports exist to prevent.

## Read a model's answer tolerantly; trust it strictly

A protocol that only works when the model formats its reply perfectly fails
in production.

- **Tolerant in reading.** Accept the shapes a model actually produces: the
  object as well as the string, a line with a `key:` prefix, a reply with no
  code fence, a numbered list. Try the whole thing, then its head.
- **Strict in trusting.** Every candidate is still resolved against a known
  set. An invented name falls to the default; an unfenced object is taken
  only when it carries the keys that make it what it claims to be.

When the prompt teaches a format the parser cannot read, suspect the parser.

## Never put a non-finite number in a serialisable field

`Infinity` and `NaN` are not representable in JSON, and neither Pydantic nor
JSON Schema can express them. Use `int | None`, with `None` meaning
unbounded.

`maxConnections` is the worked example: `JSON.stringify(Infinity)` is
`"null"`, so an infinite value would not survive its own round trip and
nothing would report the loss.

## Small, named packages

A directory is a bounded context with an explicit public surface. No `utils/`
dumping ground. If a module has no one-sentence description, it has no reason
to exist.

Expressions in a saved workflow are serialisable data, never host-language
code; reducers are a named enum, never arbitrary functions. A workflow
document that holds a function is neither portable nor saveable.

## Tests

Test-driven. The failing test comes first, at the layer the defect lives, and
you watch it fail before writing the code that passes it. A test written
after its code asserts what the code does, which is not the same as what it
should do.

Then break the fix and watch the test go red, so you know the test is the
thing holding the behaviour. Never refactor a class with many public members
without tests in place first.
