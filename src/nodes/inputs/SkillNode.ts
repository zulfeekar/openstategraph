import { Ok, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { INodeDefinition, NodeInit } from '@core/model/contracts/node';
import type { ExecutionContext, INodeExecutor, PortOutputs } from '@core/execution/INodeExecutor';
import { CATEGORY, PORT } from '../vocabulary';

const FIELD_NAME = 'skillName';
const FIELD_DESCRIPTION = 'skillDescription';

/**
 * The body's data key — **the same spelling `input.markdown` uses**.
 *
 * Both node types compile through one backend builder (`_static_text`), and
 * that builder reads the union of the keys its types declare. A private
 * spelling here bought nothing and cost a third branch in its `or`-chain,
 * which is the shape ticket 28 names as "hides a fourth". One key for one
 * concept — the text a static source contributes.
 */
export const SKILL_BODY_KEY = 'instruction';

/**
 * The spelling the Skill node shipped with, for one day.
 *
 * Declared, never a field — the same treatment `LEGACY_RULES_MODE_KEY` gets,
 * and for the same reason: it is carried in `port_specs.json`'s
 * `legacy_data_keys` so `test_data_key_contract.py` knows the backend may
 * still read it, and it is rewritten out of a document on load (below) so it
 * can never become a second live setting.
 */
export const LEGACY_SKILL_BODY_KEY = 'instructions';

/**
 * The shape a new Skill arrives with.
 *
 * Deliberately small. The section list a developer meets on a public skills
 * directory — Overview / When to Use / Process / Output Format / Conventions /
 * Example — is that directory's house style, not the Agent Skills
 * specification, which mandates only `name` and `description` and says nothing
 * about the body. A template with six headings produces four that nobody
 * fills, which is the pre-filled-field-you-immediately-clear defect wearing a
 * new costume. Three sections, one of them explicitly deletable.
 *
 * **No `## Output Format` section, and that is not an oversight.** The shape of
 * the answer belongs to the node's locked output contract, which is composed
 * last precisely so developer text cannot countermand it. A template inviting
 * someone to specify an output format would be inviting them to write a rule
 * the machinery is built to overrule.
 *
 * The `{{…}}` markers are blanks the developer fills; an unfilled one is a
 * diagnostic, raised by `skillBlanksRule` before a run rather than by this
 * node's executor during one.
 */
const TEMPLATE = `## Purpose

{{what this skill makes the agent good at}}

## Rules

- {{the first rule the agent must follow}}

## Conventions

{{formats, names, units the agent must always use — delete this section if there are none}}
`;

/** Rewrites the first spelling of the body key into the current one, on load. */
export function withMigratedSkillBody(init: NodeInit): NodeInit {
  const data = init.data;
  if (!data || !(LEGACY_SKILL_BODY_KEY in data)) return init;
  const { [LEGACY_SKILL_BODY_KEY]: legacy, ...rest } = data;
  return {
    ...init,
    data: { ...rest, [SKILL_BODY_KEY]: data[SKILL_BODY_KEY] ?? legacy },
  };
}

/**
 * A skill: a named, described rules layer built from a standard template.
 *
 * **What travels is the body, and only the body.** `name` and `description`
 * are the Agent Skills specification's *file* header — a disk format for
 * hand-written `SKILL.md` files, not a wire format between our own layers.
 * This node used to serialise that header and ship it, so the backend parsed
 * straight back into the three values the document already carried; worse, the
 * format then had two implementations in two languages. `skills.py` owns the
 * format — `SkillDocument.parse` reads it, `SkillDocument.render` writes it —
 * and this node carries its identity as data, where a picker, an exporter and
 * a human can all read it without a round trip.
 *
 * Distinct from `input.markdown`, which stays exactly what its name says — an
 * arbitrary Markdown file. `docs/decisions/skill-layer.md` records why they are
 * two node types and not one node with a mode, re-argued against the evidence
 * that the compiler gives them one builder.
 */
export class SkillNodeModel extends AbstractNodeModel {
  constructor(definition: INodeDefinition, init: NodeInit) {
    super(definition, withMigratedSkillBody(init));
  }

  get skillName(): string {
    return this.getText(FIELD_NAME).trim();
  }

  get skillDescription(): string {
    return this.getText(FIELD_DESCRIPTION).trim();
  }

  get body(): string {
    return this.getText(SKILL_BODY_KEY).trim();
  }
}

export const skillNode: INodeDefinition = defineNode(
  {
    id: 'input.skill',
    category: CATEGORY.inputs,
    label: 'Skill',
    description: 'A named rules layer, written from a standard template.',
    iconId: 'node-markdown',
    accent: 'orange',
    keywords: ['skill', 'instruction', 'persona', 'rules', 'system', 'template'],
    defaultSize: { width: 252, height: 300 },
    fields: [
      {
        kind: 'text',
        key: FIELD_NAME,
        label: 'Name',
        placeholder: 'api-endpoint-creator',
        defaultValue: '',
        // A skill is identified by its name — for the picker, for an export to
        // a `SKILL.md`, and for a human reading the document. Declared here so
        // `fieldValidationRule` reports it in the diagnostics panel, rather
        // than the executor refusing mid-run.
        validate: (value) => (value.trim() ? null : 'A skill is identified by its name'),
      },
      {
        kind: 'textarea',
        key: FIELD_DESCRIPTION,
        label: 'Description',
        placeholder: 'What this skill is for, and when to reach for it.',
        defaultValue: '',
        minRows: 2,
      },
      {
        kind: 'textarea',
        key: SKILL_BODY_KEY,
        label: 'Instructions',
        placeholder: 'The rules this skill contributes.',
        // Prebuilt, so the node is usable the moment it lands on the canvas —
        // the owner's standing requirement. An empty Skill node that demands a
        // document has failed the brief even if everything under it works.
        defaultValue: TEMPLATE,
        minRows: 8,
      },
    ],
    ports: [
      {
        id: 'skill',
        direction: 'out',
        type: PORT.skill,
        label: 'skill',
        description: 'Becomes the agent’s rules layer.',
      },
    ],
  },
  SkillNodeModel,
);

export const skillExecutor: INodeExecutor = {
  id: skillNode.id,
  execute(ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
    const node = ctx.node as SkillNodeModel;
    ctx.log(node.skillName ? `Skill “${node.skillName}” ready` : 'Skill ready');
    // The body, unwrapped. Everything a run needs from a skill is its text;
    // the name and description stay in the document.
    return Promise.resolve(Ok({ skill: node.body }));
  },
};
