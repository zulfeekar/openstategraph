import { describe, expect, it } from 'vitest';
import { TYPE, addNode, connect, makeWorkbench } from '@core/testing/fixtures';
import type { Workbench } from '@app/Workbench';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';

/**
 * Port capacity counts **producers that can arrive together**, not edges drawn.
 *
 * `workflow-gallery/64`. `maxConnections: 1` on an agent's `prompt` or a
 * grader's `candidate` exists so two values cannot race into one slot. A
 * router's branches cannot race — exactly one of them is taken per run — so
 * three branches converging on one prompt is not the thing the cap forbids.
 * `capacityRule` could not tell the two apart and resolved both by *replacing*
 * the incumbent, which is why `chinook-assistant` and `examples/support-triage`
 * are graphs their own editor cannot redraw.
 *
 * The tests below drive the **real** `ConnectionValidator` on a real
 * `Workbench`, and each asks the question a user's mouse asks: lift one link,
 * draw it again, and see whether anything else is about to disappear.
 */

/**
 * Redraws `edge`: removes it, then asks the validator about its own endpoints.
 * Returns the ids the validator would displace to make room — empty is the
 * answer a user expects when nothing else is in the way.
 */
function redraw(
  workbench: Workbench,
  edgeId: string,
): { ok: boolean; replaces: readonly string[]; reason?: string } {
  const edge = workbench.model.edge(edgeId);
  if (!edge) throw new Error(`no such edge: ${edgeId}`);
  const { source, target } = edge;
  workbench.model.removeEdge(edgeId);
  const verdict = workbench.connectionValidator.validate(source, target);
  return verdict.ok
    ? { ok: true, replaces: verdict.replaces }
    : { ok: false, replaces: [], reason: verdict.reason };
}

function makeRouter(workbench: Workbench, names: string[], matchMode?: string): AbstractNodeModel {
  const data: Record<string, unknown> = {
    branches: names.map((name) => ({ id: name, name })),
  };
  if (matchMode !== undefined) data['matchMode'] = matchMode;
  return addNode(workbench, TYPE.router, { data: data as never });
}

describe('capacity counts producers that can arrive together', () => {
  it('lets a router’s branches converge on one prompt without displacing each other', () => {
    // `workflows/chinook-assistant`: three branches of one router into one
    // agent's `prompt`, which is `maxConnections: 1`.
    const workbench = makeWorkbench();
    const input = addNode(workbench, TYPE.textInput);
    const route = makeRouter(workbench, ['greeting', 'offtopic', 'general']);
    const agent = addNode(workbench, TYPE.agent);
    connect(workbench, input, 'text', route, 'question');
    const first = connect(workbench, route, 'branch:greeting', agent, 'prompt');
    connect(workbench, route, 'branch:offtopic', agent, 'prompt');
    const third = connect(workbench, route, 'branch:general', agent, 'prompt');

    expect(redraw(workbench, third.id)).toEqual({ ok: true, replaces: [] });
    expect(workbench.model.edge(first.id)).toBeDefined();
  });

  it('sees through the agents a router’s branches feed', () => {
    // `examples/support-triage`: three *different* agents into one grader's
    // `candidate`. The exclusivity is a fact about their common router, one
    // node further back.
    const workbench = makeWorkbench();
    const input = addNode(workbench, TYPE.textInput);
    const route = makeRouter(workbench, ['billing', 'technical', 'account']);
    const grader = addNode(workbench, TYPE.grader);
    connect(workbench, input, 'text', route, 'question');
    const drawn = ['billing', 'technical', 'account'].map((name) => {
      const agent = addNode(workbench, TYPE.agent);
      connect(workbench, route, `branch:${name}`, agent, 'prompt');
      return connect(workbench, agent, 'result', grader, 'candidate');
    });

    expect(redraw(workbench, drawn[2]!.id)).toEqual({ ok: true, replaces: [] });
  });

  it('still displaces the incumbent when two producers can genuinely race', () => {
    // Ticket 14's shape, and the thing the cap exists for: two independent
    // agents into one prompt. Nothing makes these exclusive, so the second
    // still takes the slot.
    const workbench = makeWorkbench();
    const one = addNode(workbench, TYPE.agent);
    const two = addNode(workbench, TYPE.agent);
    const sink = addNode(workbench, TYPE.agent);
    const first = connect(workbench, one, 'result', sink, 'prompt');
    const second = connect(workbench, two, 'result', sink, 'prompt');

    expect(redraw(workbench, second.id)).toEqual({ ok: true, replaces: [first.id] });
  });

  it('still displaces when a router broadcasts to every matching branch', () => {
    // `matchMode: "all"` runs every match in the same superstep, so its
    // branches are *not* exclusive — the premise ticket 64 was filed on.
    const workbench = makeWorkbench();
    const input = addNode(workbench, TYPE.textInput);
    const route = makeRouter(workbench, ['greeting', 'general'], 'all');
    const agent = addNode(workbench, TYPE.agent);
    connect(workbench, input, 'text', route, 'question');
    const first = connect(workbench, route, 'branch:greeting', agent, 'prompt');
    const second = connect(workbench, route, 'branch:general', agent, 'prompt');

    expect(redraw(workbench, second.id)).toEqual({ ok: true, replaces: [first.id] });
  });

  it('still displaces two producers the same branch sets running', () => {
    // Gated is not the same as exclusive. One branch feeding two agents runs
    // both of them, in the same superstep — being downstream of a router only
    // helps when the branches are *different* ones.
    const workbench = makeWorkbench();
    const input = addNode(workbench, TYPE.textInput);
    const route = makeRouter(workbench, ['left', 'right']);
    connect(workbench, input, 'text', route, 'question');
    const grader = addNode(workbench, TYPE.grader);
    const drawn = [0, 1].map(() => {
      const agent = addNode(workbench, TYPE.agent);
      connect(workbench, route, 'branch:left', agent, 'prompt');
      return connect(workbench, agent, 'result', grader, 'candidate');
    });

    expect(redraw(workbench, drawn[1]!.id)).toEqual({ ok: true, replaces: [drawn[0]!.id] });
  });

  it('still displaces when a branch does not decide whether a producer runs', () => {
    // The gate has to be a gate. `format_report` is the one input that takes
    // many links, so it is the one place a node can be reached both from
    // behind a router branch *and* from a path nowhere near it — and then that
    // branch says nothing about whether it produces. Two producers separated
    // by two branches are only exclusive if those branches actually decide
    // them.
    const workbench = makeWorkbench();
    const input = addNode(workbench, TYPE.textInput);
    const route = makeRouter(workbench, ['left', 'right']);
    connect(workbench, input, 'text', route, 'question');

    const viaRouter = addNode(workbench, TYPE.agent);
    connect(workbench, route, 'branch:left', viaRouter, 'prompt');
    const bypass = addNode(workbench, TYPE.agent);
    const other = addNode(workbench, TYPE.textInput);
    connect(workbench, other, 'text', bypass, 'prompt');

    // Reachable from the router's `left` branch and from `other` alike.
    const join = addNode(workbench, TYPE.formatReport);
    connect(workbench, viaRouter, 'result', join, 'candidate');
    connect(workbench, bypass, 'result', join, 'candidate');

    const rightHand = addNode(workbench, TYPE.agent);
    connect(workbench, route, 'branch:right', rightHand, 'prompt');

    const grader = addNode(workbench, TYPE.grader);
    const first = connect(workbench, join, 'report', grader, 'candidate');
    const second = connect(workbench, rightHand, 'result', grader, 'candidate');

    expect(redraw(workbench, second.id)).toEqual({ ok: true, replaces: [first.id] });
  });

  it('still re-points an ordinary single-slot input', () => {
    // The gesture `capacityRule`'s replacement exists for, unchanged: drop a
    // new source on an occupied input and it takes over.
    const workbench = makeWorkbench();
    const first = addNode(workbench, TYPE.textInput);
    const agent = addNode(workbench, TYPE.agent);
    const incumbent = connect(workbench, first, 'text', agent, 'prompt');
    const second = addNode(workbench, TYPE.textInput);

    const verdict = workbench.connectionValidator.validate(
      { nodeId: second.id, portId: 'text' },
      { nodeId: agent.id, portId: 'prompt' },
    );
    expect(verdict).toEqual({ ok: true, replaces: [incumbent.id] });
  });
});
