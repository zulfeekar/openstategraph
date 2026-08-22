/**
 * A deep agent declares its own workers — `organisms-first-class/84`.
 *
 * The backend's `compile/subagents.py` reads these exact keys, so the two
 * halves of one contract are pinned here rather than described: a rename on
 * either side without the other is a subagent that silently does not exist,
 * which is the `skills=` failure `docs/decisions/deep-agent-slots.md` measured.
 *
 * The second thing pinned is the **decision**: `create_deep_agent` auto-adds a
 * `general-purpose` worker and this product cannot disable it, so it is named
 * on screen. Ticket 84's "done when" makes silently having one not a decision.
 */
import { describe, expect, it } from 'vitest';
import { CredentialStore, ProviderRegistry } from '@core/providers/ProviderRegistry';
import type { FieldSchema } from '@core/model/contracts/fields';
import { createAgentNode } from './AgentNode';

const fields = (): readonly FieldSchema[] => createAgentNode(new ProviderRegistry(new CredentialStore(false))).fields ?? [];

const field = (key: string): FieldSchema | undefined => fields().find((f) => f.key === key);

const subagents = () => {
  const schema = field('subagents');
  if (schema?.kind !== 'repeatable-group') throw new Error('agent.llm has no subagent rows');
  return schema;
};

describe('an agent declares its subagents as data', () => {
  it('offers a repeatable group under its own inspector section', () => {
    expect(subagents().group).toBe('Delegation');
    expect(subagents().onCard).toBe(false);
    expect(subagents().defaultValue).toEqual([]);
  });

  it('asks for exactly the three strings the deep runtime requires, plus a tool choice', () => {
    expect(subagents().fields.map((f) => f.key)).toEqual([
      'name',
      'description',
      'systemPrompt',
      'tools',
    ]);
  });

  it('refuses a row missing any of the three', () => {
    for (const key of ['name', 'description', 'systemPrompt']) {
      const sub = subagents().fields.find((f) => f.key === key);
      expect(sub?.validate?.('   ' as never)).toBeTruthy();
      expect(sub?.validate?.('something' as never)).toBeNull();
    }
  });

  it('offers the library’s two tool states and no invented third', () => {
    const tools = subagents().fields.find((f) => f.key === 'tools');
    if (tools?.kind !== 'select') throw new Error('tools is not a select');
    const options = typeof tools.options === 'function' ? tools.options({}) : tools.options;
    expect(options.map((o) => o.value)).toEqual(['inherit', 'none']);
    expect(tools.defaultValue).toBe('inherit');
  });
});

describe('the worker every deep agent already had is named', () => {
  it('says the built-in general-purpose subagent exists and how to replace it', () => {
    const note = field('subagentsNote');
    if (note?.kind !== 'readonly') throw new Error('no delegation note');
    expect(note.defaultValue).toContain('general-purpose');
    expect(note.defaultValue).toMatch(/replace/i);
  });

  it('keeps both isolation sentences, which read as a contradiction and are both true', () => {
    const note = field('subagentsNote');
    const text = String(note?.defaultValue ?? '');
    // Never the parent's messages or the workflow's state...
    expect(text).toMatch(/never sees/i);
    // ...but the run's context does reach its tools (`a86b4d8`).
    expect(text).toMatch(/context/i);
  });

  it('does not call a subagent a workflow, a mount, or a package', () => {
    const text = [
      String((field('subagentsNote') as { defaultValue?: string })?.defaultValue ?? ''),
      String(subagents().hint ?? ''),
    ].join(' ');
    expect(text).not.toMatch(/\bmount\b/i);
    expect(text).not.toMatch(/\bpackage\b/i);
    expect(text).not.toMatch(/\bslug\b/i);
  });
});
