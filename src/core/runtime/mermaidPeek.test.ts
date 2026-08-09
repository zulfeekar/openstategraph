import { describe, expect, it } from 'vitest';
import { peekDiagramId, peekMermaid } from './mermaidPeek';

describe('peekMermaid', () => {
  it('prefixes a compiled diagram with the card-sized init directive', () => {
    const out = peekMermaid('graph TD;\n  a --> b;');
    expect(out.startsWith('%%{init:')).toBe(true);
    expect(out).toContain('graph TD;');
    expect(out).toContain('"fontSize":"9px"');
  });

  it('leaves a diagram that configures itself alone', () => {
    const source = '%%{init: {"theme":"dark"} }%%\ngraph TD;\n  a --> b;';
    expect(peekMermaid(source)).toBe(source);
  });

  it('leaves YAML front-matter alone', () => {
    const source = '---\ntitle: Compiled\n---\ngraph TD;';
    expect(peekMermaid(source)).toBe(source);
  });

  it('is a no-op on empty text', () => {
    expect(peekMermaid('')).toBe('');
    expect(peekMermaid('   \n ')).toBe('');
  });

  it('adds exactly one directive when applied to its own output', () => {
    const once = peekMermaid('graph TD;');
    expect(peekMermaid(once)).toBe(once);
  });
});

describe('peekDiagramId', () => {
  it('is unique per slug and sequence', () => {
    expect(peekDiagramId('chinook-metrics-team', 1)).toBe('peek-chinook-metrics-team-1');
    expect(peekDiagramId('chinook-metrics-team', 2)).not.toBe(peekDiagramId('chinook-metrics-team', 1));
  });

  it('strips characters that are illegal in a DOM id', () => {
    expect(peekDiagramId('a/b c.d', 0)).toBe('peek-a-b-c-d-0');
  });
});
