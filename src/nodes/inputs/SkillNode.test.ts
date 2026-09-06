import { describe, expect, it } from 'vitest';
import { LEGACY_SKILL_BODY_KEY, SKILL_BODY_KEY, skillExecutor, skillNode } from './SkillNode';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { ExecutionContext } from '@core/execution/INodeExecutor';
import { validateFields, type NodeData } from '@core/model/contracts/fields';

function contextFor(fields: Record<string, string>): ExecutionContext {
  return {
    node: {
      skillName: fields['skillName'] ?? '',
      skillDescription: fields['skillDescription'] ?? '',
      body: fields[SKILL_BODY_KEY] ?? '',
    },
    log: () => {},
  } as unknown as ExecutionContext;
}

function create(data: Partial<NodeData>): AbstractNodeModel {
  return skillNode.create({ position: { x: 0, y: 0 }, data }) as AbstractNodeModel;
}

/**
 * Ticket 28. The node used to serialise `---\nname: …\n---\n` and ship it over
 * the wire, so the skill file format had two implementations — `skills.py`
 * parsed it and this module wrote it, in two languages, free to drift.
 */
describe('the wire carries a body, never a file', () => {
  it('emits the instructions verbatim, with no frontmatter around them', () => {
    return skillExecutor
      .execute(
        contextFor({
          skillName: 'terse',
          skillDescription: 'Keeps answers short.',
          [SKILL_BODY_KEY]: '## Rules\n\n- Answer in one sentence.',
        }),
      )
      .then((outcome) => {
        expect(outcome.ok).toBe(true);
        if (!outcome.ok) return;
        expect(outcome.value['skill']).toBe('## Rules\n\n- Answer in one sentence.');
      });
  });

  it('never spends prompt budget on the identity fields', () => {
    return skillExecutor
      .execute(
        contextFor({
          skillName: 'api-endpoint-creator',
          skillDescription: 'Creates REST endpoints.',
          [SKILL_BODY_KEY]: '- Be terse.',
        }),
      )
      .then((outcome) => {
        expect(outcome.ok).toBe(true);
        if (!outcome.ok) return;
        const emitted = String(outcome.value['skill']);
        expect(emitted).not.toContain('api-endpoint-creator');
        expect(emitted).not.toContain('---');
      });
  });

  it('emits a half-written skill rather than failing at run time', () => {
    // The blank check is now `skillBlanksRule` in `WorkflowValidator`, so it
    // shows in the diagnostics panel before a run instead of dying inside one.
    return skillExecutor
      .execute(contextFor({ skillName: 'drafty', [SKILL_BODY_KEY]: '- {{the first rule}}' }))
      .then((outcome) => {
        expect(outcome.ok).toBe(true);
      });
  });
});

describe('a skill names itself', () => {
  it('reports a missing name through the field schema, not at run time', () => {
    const errors = validateFields(skillNode.fields, { skillName: '  ' });
    expect(errors['skillName']).toBeTruthy();
  });

  it('accepts a named skill', () => {
    const errors = validateFields(skillNode.fields, { skillName: 'terse' });
    expect(errors['skillName']).toBeUndefined();
  });
});

/**
 * The body key is `instruction` — the same spelling `input.markdown` uses, so
 * the one builder serving both node types reads one key rather than three.
 * `instructions` is what shipped first and is declared legacy.
 */
describe('the body key', () => {
  it('is the Markdown File node’s spelling', () => {
    expect(SKILL_BODY_KEY).toBe('instruction');
    expect(LEGACY_SKILL_BODY_KEY).toBe('instructions');
  });

  it('migrates a document saved with the first spelling', () => {
    const node = create({ [LEGACY_SKILL_BODY_KEY]: '- Answer in one sentence.' });
    expect(node.data[SKILL_BODY_KEY]).toBe('- Answer in one sentence.');
    expect(LEGACY_SKILL_BODY_KEY in node.data).toBe(false);
  });

  it('keeps the current spelling when a document carries both', () => {
    const node = create({ [SKILL_BODY_KEY]: 'current', [LEGACY_SKILL_BODY_KEY]: 'old' });
    expect(node.data[SKILL_BODY_KEY]).toBe('current');
    expect(LEGACY_SKILL_BODY_KEY in node.data).toBe(false);
  });
});
