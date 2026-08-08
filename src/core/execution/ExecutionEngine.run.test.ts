import { describe, expect, it } from 'vitest';
import { addNode, connect, makeWorkbench, TYPE } from '@core/testing/fixtures';

/**
 * The engine's HAPPY path — a real topological run over the mock provider
 * (the deterministic two-phase agent), which is exactly what the seeded demo
 * exercises by hand. Coverage push: before this file the engine's main loop
 * was only ever tested through its refusal branches.
 */
describe('ExecutionEngine.run', () => {
  it('runs input -> agent(mock) -> output and lands an answer on the sink', async () => {
    const workbench = makeWorkbench();
    const input = addNode(workbench, TYPE.textInput, { data: { prompt: 'say hello' } });
    const agent = addNode(workbench, TYPE.agent);
    const output = addNode(workbench, TYPE.output);
    connect(workbench, input, 'text', agent, 'prompt');
    connect(workbench, agent, 'result', output, 'result');

    const events: string[] = [];
    workbench.engine.on('run:start', () => events.push('start'));
    workbench.engine.on('run:finish', (payload) =>
      events.push(payload.ok ? 'finish:ok' : 'finish:fail'),
    );

    await workbench.engine.run();

    expect(events).toEqual(['start', 'finish:ok']);
    expect(workbench.model.node(output.id)?.runtime.status).toBe('success');
    expect(workbench.model.node(agent.id)?.runtime.tokens).toBeGreaterThan(0);
  });

  it('a tool wired to the agent is invoked through the engine', async () => {
    const workbench = makeWorkbench();
    const input = addNode(workbench, TYPE.textInput, { data: { prompt: 'search reddit' } });
    const agent = addNode(workbench, TYPE.agent);
    const tool = addNode(workbench, TYPE.redditSearch);
    const output = addNode(workbench, TYPE.output);
    connect(workbench, input, 'text', agent, 'prompt');
    connect(workbench, tool, 'tool', agent, 'tools');
    connect(workbench, agent, 'result', output, 'result');

    await workbench.engine.run();
    expect(workbench.model.node(output.id)?.runtime.status).toBe('success');
  });

  it('cancel mid-run leaves no node stuck in running', async () => {
    const workbench = makeWorkbench();
    const input = addNode(workbench, TYPE.textInput, { data: { prompt: 'x' } });
    const output = addNode(workbench, TYPE.output);
    connect(workbench, input, 'text', output, 'result');
    const running = workbench.engine.run();
    workbench.engine.cancel();
    await running;
    for (const node of workbench.model.nodes()) {
      expect(node.runtime.status).not.toBe('running');
    }
  });
});
