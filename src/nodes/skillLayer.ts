import type { NodeData, SelectFieldSchema } from '@core/model/contracts/fields';
import type { NodeInit } from '@core/model/contracts/node';
import { type IPortDescriptor } from '@core/model/contracts/ports';
import { PORT } from './vocabulary';

/**
 * The skill layer's editor surface, declared **once** for every model-driven
 * node type.
 *
 * Two things travel together and must never be pasted per node type: the
 * `skill` input port, and the one extend/replace switch that governs what a
 * wired skill does to the rules already on the node. The contract they
 * implement is `docs/decisions/skill-layer.md`; this module is only its
 * declaration.
 *
 * **Why one module rather than five copies.** The precedent is exact and
 * recent: `modelField.ts` exists because the model picker had been declared on
 * `agent.llm` alone while the backend read `data["model"]` for six node types,
 * so five nodes ran a model nobody could choose. The skill layer had the same
 * shape of gap — the backend reads `plan.skill_bindings` and `rulesMode` for
 * *five* node types, while the editor declared a `skill` port on two of them
 * and the mode on one, under a third name. Declaring both here, and emitting
 * the fact into `port_specs.json` for `backend/tests/test_skill_layer_contract.py`
 * to assert, is what stops that recurring.
 */

/** The port id both ends of the wire agree on. */
export const SKILL_PORT_ID = 'skill';

/**
 * The `skill` input, shared by every node type that composes a prompt.
 *
 * **An input, drawn where inputs are drawn** — no `side`, so it takes the
 * left-hand default with `prompt` and `feedback`. This reverses the binding
 * treatment recorded in `docs/decisions/edge-legibility.md`, and the reversal
 * is recorded there rather than left implicit here.
 *
 * The short version: `BINDING_SIDE.consumer` bought a layout gain (the skill
 * file left the flow ranks and hung on its consumer's shelf, so its wire
 * stopped climbing across the card above it) at the cost of a hole in the card
 * itself. The footer legend is the card's *complete* list of ports, so it kept
 * listing `prompt`, `feedback`, `skill` while `skill` alone had no dot beside
 * its row. A reader counting dots against labels found two of three, and the
 * only repair on offer was a special "offside" style for the odd one out —
 * decorating the symptom. Three cards feed this one; three wires arrive; the
 * node-editor convention is that they arrive from the left.
 *
 * **Why `tools` did not follow it back.** A bus genuinely gathers many, and the
 * pill is the drawn language for that — one capsule, many wires, one dot. A
 * skill is a single file on a single wire, so it never had a bus's reason to
 * leave the reading axis; it only had a tool's *company*.
 *
 * **No pill, and `maxConnections` left at the input default of 1.** A second
 * skill port, or a skill bus, was considered and rejected — layering several
 * skills is what a package's ambient `skills/*.md` directory already does.
 *
 * Frozen, and spread into each `ports` list rather than shared by reference,
 * so no node type can mutate the declaration the others read.
 */
export const SKILL_PORT: IPortDescriptor = Object.freeze({
  id: SKILL_PORT_ID,
  direction: 'in',
  type: PORT.skill,
  label: 'skill',
  description: 'A Markdown skill file whose rules shape this step’s prompt.',
});

/** The key the backend's `_replaces_rules(data)` reads first. */
export const RULES_MODE_KEY = 'rulesMode';

/**
 * The Grader's older spelling of the same field.
 *
 * Kept only to migrate documents saved before the generalisation — never
 * declared as a field, because two controls that both spell extend/replace is
 * the duplication-of-knowledge defect the decision record rejects by name.
 */
export const LEGACY_RULES_MODE_KEY = 'criteriaMode';

/**
 * The one extend/replace switch every prompted node has.
 *
 * It governs all three rules layers at once — `default rules → inline rules →
 * wired skill` — because a developer cannot predict a prompt assembled from
 * two independent modes, and because with no skill wired the meaning is
 * *exactly* what the Grader's `criteriaMode` always had: the developer's text
 * replaces the prebuilt text.
 *
 * What it deliberately cannot reach: the locked preamble and the output
 * contract. `replace` stops at the rules layers, so no setting here can
 * produce a node whose answer will not parse.
 *
 * **`onCard` is presentation, and the rule is "the mode rides where the rules
 * ride".** The Router and the Grader show their rules text on the card, so the
 * switch that modifies it belongs there too; the Agent, the Worker and the
 * Orchestrator carry a derived intent line instead, and a mode select beside
 * it would name a text the card never shows.
 */
export function rulesModeField(options: { readonly onCard?: boolean } = {}): SelectFieldSchema {
  return {
    kind: 'select',
    key: RULES_MODE_KEY,
    label: 'Rules mode',
    defaultValue: 'extend',
    onCard: options.onCard ?? false,
    group: 'Prompt',
    options: [
      { value: 'extend', label: 'Add to the built-in rules' },
      { value: 'replace', label: 'Replace the built-in rules' },
    ],
    hint: 'Applies to the rules typed here and to any wired skill file. The node’s preamble and output format are never affected.',
  };
}

/**
 * Does this node's data ask for the topmost supplied rules layer alone?
 *
 * The editor-side mirror of `node_runtime._replaces_rules`, down to the
 * precedence: `rulesMode` wins wherever both keys appear, so the legacy key is
 * a fallback and never a second setting.
 */
export function replacesRules(data: Readonly<NodeData>): boolean {
  const own = data[RULES_MODE_KEY];
  const legacy = data[LEGACY_RULES_MODE_KEY];
  const mode = (typeof own === 'string' && own) || (typeof legacy === 'string' && legacy) || '';
  return mode === 'replace';
}

/**
 * Rewrites a legacy `criteriaMode` into `rulesMode` **before** schema defaults
 * are merged in.
 *
 * Read-time tolerance (the way `branchesOf` migrates a router's old branch
 * string) is not enough here, and the reason is worth stating: node data is
 * `mergeData(defaultsFrom(fields), init.data)`, and `toJSON` writes the whole
 * record. So a Grader saved with `criteriaMode: "replace"` would gain
 * `rulesMode: "extend"` from the new field's default, and on the next save the
 * document would carry both — with the *new* key winning on the backend. A
 * document would have silently changed its prompt by being opened.
 *
 * Migrating the init data instead means such a document loads as
 * `rulesMode: "replace"` with no `criteriaMode` at all: same behaviour before
 * and after, one key, and the backend's compatibility fallback is one document
 * closer to being deletable.
 */
export function withMigratedRulesMode(init: NodeInit): NodeInit {
  const data = init.data;
  if (!data || !(LEGACY_RULES_MODE_KEY in data)) return init;
  const { [LEGACY_RULES_MODE_KEY]: legacy, ...rest } = data;
  return {
    ...init,
    data: { ...rest, [RULES_MODE_KEY]: data[RULES_MODE_KEY] ?? legacy },
  };
}
