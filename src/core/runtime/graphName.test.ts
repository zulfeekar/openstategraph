import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { displayNamesByGraphName, safeName } from './graphName';

/**
 * The compiler's node-naming rule, mirrored — and pinned to the compiler.
 *
 * `memory-and-replay` 39. History renders a lane per graph and names it with
 * whatever LangGraph called the graph, which is `safe_name(node_id)`. Reading
 * that back is only honest in the direction the function was written, so the
 * client computes the *forward* mangling for the open document and looks the
 * stored name up in the result.
 */
describe('safeName', () => {
  it('mangles exactly what the compiler mangles', () => {
    expect(safeName('worker-web')).toBe('worker_web');
    expect(safeName('node:agent.llm-1')).toBe('node_agent_llm_1');
    // Already legal: untouched, so a document of simple ids resolves to itself.
    expect(safeName('in1')).toBe('in1');
    expect(safeName('worker_web')).toBe('worker_web');
  });

  /**
   * The pin. Two languages hold one rule, and CLAUDE.md's DRY clause is about
   * exactly this: a hand-mirror without a drift test is what the rule forbids.
   * Asserting the Python expression verbatim is crude and it is the only thing
   * that fails on the day somebody widens the mangling on one side.
   */
  it('mirrors the expression in the compiler, character for character', () => {
    const repo = new URL('../../../', import.meta.url);
    const compiler = readFileSync(
      fileURLToPath(new URL('backend/openstategraph/compile/workflow_compiler.py', repo)),
      'utf8',
    );
    expect(compiler).toContain(
      'return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in node_id)',
    );
  });
});

describe('displayNamesByGraphName', () => {
  const node = (id: string, title: string, hasCustomTitle: boolean) => ({
    id,
    title,
    hasCustomTitle,
  });

  it('answers with the canvas id when the card carries no name of its own', () => {
    // The untitled case, as `support-triage` ships it: three
    // `tool.email-send` nodes with no title, so `title` is the *type* label
    // "Send email" for all three and names none of them.
    const names = displayNamesByGraphName([
      node('node:tool.email-send-1', 'Send email', false),
      node('node:tool.email-send-2', 'Send email', false),
    ]);
    expect(names.get('node_tool_email_send_1')).toBe('node:tool.email-send-1');
    expect(names.get('node_tool_email_send_2')).toBe('node:tool.email-send-2');
  });

  it('answers with the title the moment somebody names the card', () => {
    const names = displayNamesByGraphName([node('worker-web', 'Web researcher', true)]);
    expect(names.get('worker_web')).toBe('Web researcher');
  });

  /**
   * The reason the reverse mangling was refused in the first place, arriving
   * from the forward direction: two ids can land on one graph name, and
   * naming the wrong node is worse than looking technical.
   */
  it('drops a name two nodes claim, rather than letting the first win', () => {
    const names = displayNamesByGraphName([
      node('worker-web', 'Web researcher', true),
      node('worker_web', 'Something else', true),
    ]);
    expect(names.has('worker_web')).toBe(false);
  });

  it('is empty for an empty document, and knows nothing it was not given', () => {
    expect(displayNamesByGraphName([]).size).toBe(0);
    expect(displayNamesByGraphName([node('in1', 'Question', true)]).get('model')).toBeUndefined();
  });
});
