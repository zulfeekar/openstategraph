import { describe, expect, it } from 'vitest';
import { entryQuestion } from './entryQuestion';

const node = (type: string, prompt: string) => ({
  type,
  getField: (key: string) => (key === 'prompt' ? prompt : ''),
});

const source = (...nodes: ReturnType<typeof node>[]) => ({ nodes: () => nodes });

describe('entryQuestion', () => {
  it('is the entry Text Input node text', () => {
    expect(entryQuestion(source(node('input.text', 'Which genre earns most?')))).toBe(
      'Which genre earns most?',
    );
  });

  it('is empty when the only entry input is blank — the disabled Run case', () => {
    expect(entryQuestion(source(node('input.text', '   \n ')))).toBe('');
  });

  it('is empty when the canvas has no entry input at all', () => {
    expect(entryQuestion(source(node('agent.llm', 'not a question')))).toBe('');
  });

  it('ignores every node type that is not an entry input', () => {
    expect(entryQuestion(source(node('agent.llm', 'system rules'), node('input.text', 'Ask')))).toBe(
      'Ask',
    );
  });

  it('joins several entry inputs in canvas order, skipping the blank ones', () => {
    expect(
      entryQuestion(
        source(node('input.text', 'First'), node('input.text', ' '), node('input.text', 'Second')),
      ),
    ).toBe('First\n\nSecond');
  });

  it('trims — trailing whitespace must not make Run look enabled', () => {
    expect(entryQuestion(source(node('input.text', '  Ask me  ')))).toBe('Ask me');
  });
});
