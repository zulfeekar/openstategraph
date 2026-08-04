Type: grilling
Status: open
Blocked by: 08, 18

## Question

Make cardinality a first-class property of the field schema.

Stated principle: **anything that can occur more than once is a list by default.** The current `FieldSchema` union has `text | textarea | select | slider | toggle | file | readonly` — every one of them single-valued. There is no way to express "many", which blocks all of:

- Agent → **tools**: pick many from the discovered capabilities (ticket 18). Visually a multi-select list.
- Agent → **subagents**: a list of `{name, description, system_prompt, model, tools}` specs.
- Agent → **skills**: a list.
- Router → **branches**: a list of `{key, predicate, target, fallback?}` (ticket 03 fixed what each branch must carry).

Decisions:
- Two new kinds or one? `multiselect` (pick N from a known set) and `list` (repeatable group of sub-fields) solve different problems — a tool picker is the former, a subagent editor is the latter. Confirm both are needed, or find the one abstraction that covers both without becoming a form-builder.
- Where the options for a `multiselect` come from: the existing `options: () => FieldOption[]` provider already supports runtime resolution, which is how discovered capabilities arrive. Confirm that seam holds.
- Ordering: is a list ordered (does tool order matter to the model?) and is order persisted? Interacts with ticket 19 — an unordered list must serialise canonically or it reintroduces diff noise.
- Rendering on a node card versus in the inspector. A card is ~252px wide; a repeatable group of subagent specs cannot live there. Likely: card shows a count and a summary, inspector holds the editor. Confirm.
- Validation: min/max items, uniqueness, and what a dangling reference looks like when a selected tool is deleted (ticket 18).

---

## Scale problem surfaced by ticket 22

Context-management research enumerated the Agent node's real config surface: **60+ fields** — core, persistence, 11 summarization, 8 context-editing, 7 filesystem/offloading, planning, subagents, HITL, 18 fault-tolerance, PII, plus advanced. Two consequences this ticket must design for rather than discover:

- **A `harness` preset is the master dial**, not one field among many. It sets defaults across whole groups (plain `create_agent` → deep agent), and the other 60 fields are overrides on top. Without it the node is unusable.
- **Progressive disclosure is mandatory.** The card can hold model, a tool count and the preset — nothing more. Everything else is inspector-only, grouped, and collapsed by default. `onCard`/`inInspector` already exist on `FieldSchema`; what is missing is **grouping and collapse**, which likely means a `group` and `advanced` property on the schema. Decide whether that belongs here or in a separate presentation concern.

Also record the two cross-field validations for `WorkflowValidator`: HITL and `thread_limit` require a checkpointer; fractional triggers require a model profile. These are the first rules that span *two* fields, so confirm the validation contract supports that — `FieldSchema.validate` currently receives only its own value.
