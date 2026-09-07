import { describe, expect, it } from 'vitest';
import { addNode, makeWorkbench } from '@core/testing/fixtures';
import { DISPLAY_KEY, type ExecutionContext } from '@core/execution/INodeExecutor';
import type { Workbench } from '@app/Workbench';
import { formattedOutputNode } from './FormattedOutputNode';
import { STATIC_OUTPUT_TYPE, staticOutputExecutor, staticOutputNode } from './StaticOutputNode';

/**
 * `osg-agent-experience/55` — the two exits, and the line between them.
 *
 * The whole design is that the ambiguity a `text` field on `output.formatted`
 * would have carried has nowhere to live: one type prints what reaches it, the
 * other prints its own sentence, and neither can drift into doing both. So the
 * assertions here are about the *difference*, not about either node's fields
 * in isolation — a `text` on the sink or a `result` read on this one would be
 * the same defect back, one layer down.
 */

function ctxFor(
  workbench: Workbench,
  nodeId: string,
  inputs: Record<string, unknown> = {},
): ExecutionContext {
  const node = workbench.model.node(nodeId);
  if (!node) throw new Error(`no node ${nodeId}`);
  return {
    node,
    workflow: workbench.model,
    providers: workbench.providers,
    signal: new AbortController().signal,
    input: <T>(port: string) => inputs[port] as T | undefined,
    inputs: <T>(port: string) => (inputs[port] === undefined ? [] : [inputs[port]]) as T[],
    toolsOn: () => [],
    invokeTool: async () => ({ ok: true, value: 'stub' }) as const,
    log: () => undefined,
    reportUsage: () => undefined,
  };
}

describe('the two exits are two node types', () => {
  it('only the static one has a sentence of its own', () => {
    const keys = (definition: typeof staticOutputNode) =>
      new Set(definition.fields.map((field) => field.key));
    expect(keys(staticOutputNode).has('text')).toBe(true);
    expect(keys(formattedOutputNode).has('text')).toBe(false);
  });

  it('the static one is a sink: one inbound port and nothing out', () => {
    const inbound = staticOutputNode.ports({}).filter((port) => port.direction === 'in');
    const outbound = staticOutputNode.ports({}).filter((port) => port.direction === 'out');
    expect(inbound.map((port) => port.id)).toEqual(['when']);
    expect(outbound).toEqual([]);
  });

  it('its port is required, because an exit nothing reaches is never run', () => {
    const when = staticOutputNode.ports({}).find((port) => port.id === 'when');
    expect(when?.required).toBe(true);
  });

  it('its port takes many, because two branches can end in one reply', () => {
    const when = staticOutputNode.ports({}).find((port) => port.id === 'when');
    // `null`, never `Infinity`: the value is serialised into `workflow.json`
    // and would not survive its own round trip.
    expect(when?.maxConnections).toBeNull();
  });
});

describe('the static output executor', () => {
  it('prints the text it was configured with', async () => {
    const workbench = makeWorkbench();
    const id = addNode(workbench, STATIC_OUTPUT_TYPE, {
      data: { text: 'Name a year or a quarter.' },
    });

    const outcome = await staticOutputExecutor.execute(ctxFor(workbench, id.id));
    expect(outcome.ok).toBe(true);
    if (outcome.ok) expect(outcome.value[DISPLAY_KEY]).toBe('Name a year or a quarter.');
  });

  it('ignores what arrived, which is the whole point of the type', async () => {
    const workbench = makeWorkbench();
    const id = addNode(workbench, STATIC_OUTPUT_TYPE, {
      data: { text: 'Name a year or a quarter.' },
    });

    const outcome = await staticOutputExecutor.execute(
      ctxFor(workbench, id.id, { when: 'How much did we export?' }),
    );
    expect(outcome.ok).toBe(true);
    if (outcome.ok) expect(outcome.value[DISPLAY_KEY]).toBe('Name a year or a quarter.');
  });
});
