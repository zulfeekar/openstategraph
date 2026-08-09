import { beforeEach, describe, expect, it } from 'vitest';
import type { Workbench } from '@app/Workbench';
import {
  addNode,
  connect,
  LOOPABLE_TYPE,
  makeWorkbench,
  registerLoopableType,
  TYPE,
} from '@core/testing/fixtures';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';

/**
 * The connection rule chain.
 *
 * This is the highest-value logic in the editor to pin down: it runs on every
 * pointer move while a link is being dragged, it decides what the user is
 * allowed to build, and its verdicts are the *same* ones the canvas highlights
 * with. A regression here silently changes what graphs are expressible.
 *
 * Each rule gets its own test so a failure names the rule that broke, rather
 * than "connection validation is wrong somewhere".
 */
describe('ConnectionValidator', () => {
  let workbench: Workbench;
  let textInput: AbstractNodeModel;
  let markdown: AbstractNodeModel;
  let agent: AbstractNodeModel;
  let tool: AbstractNodeModel;
  let output: AbstractNodeModel;

  beforeEach(() => {
    workbench = makeWorkbench();
    textInput = addNode(workbench, TYPE.textInput);
    markdown = addNode(workbench, TYPE.markdownFile);
    agent = addNode(workbench, TYPE.agent);
    tool = addNode(workbench, TYPE.redditSearch);
    output = addNode(workbench, TYPE.output);
  });

  const validate = (
    from: AbstractNodeModel,
    fromPort: string,
    to: AbstractNodeModel,
    toPort: string,
  ) =>
    workbench.connectionValidator.validate(
      { nodeId: from.id, portId: fromPort },
      { nodeId: to.id, portId: toPort },
    );

  describe('the happy path', () => {
    it('accepts a matching output → input pair', () => {
      const verdict = validate(textInput, 'text', agent, 'prompt');
      expect(verdict.ok).toBe(true);
      if (verdict.ok) expect(verdict.replaces).toEqual([]);
    });

    it('accepts every link in the seeded demo topology', () => {
      // If any of these were rejected the shipped example would be
      // unbuildable by hand, which would be an obvious contradiction.
      expect(validate(textInput, 'text', agent, 'prompt').ok).toBe(true);
      expect(validate(markdown, 'skill', agent, 'skill').ok).toBe(true);
      expect(validate(tool, 'tool', agent, 'tools').ok).toBe(true);
      expect(validate(agent, 'result', output, 'result').ok).toBe(true);
    });
  });

  describe('direction rule', () => {
    it('rejects starting a link at an input port', () => {
      const verdict = validate(agent, 'prompt', output, 'result');
      expect(verdict).toMatchObject({ ok: false });
      if (!verdict.ok) expect(verdict.reason).toMatch(/output port/i);
    });

    it('rejects ending a link at an output port', () => {
      const verdict = validate(textInput, 'text', agent, 'result');
      expect(verdict).toMatchObject({ ok: false });
      if (!verdict.ok) expect(verdict.reason).toMatch(/input port/i);
    });
  });

  describe('self-loop rule', () => {
    it('rejects a node connecting to itself', () => {
      const verdict = validate(agent, 'result', agent, 'prompt');
      expect(verdict).toMatchObject({ ok: false });
      if (!verdict.ok) expect(verdict.reason).toMatch(/itself/i);
    });
  });

  describe('duplicate rule', () => {
    it('rejects an identical link twice', () => {
      connect(workbench, textInput, 'text', agent, 'prompt');
      const verdict = validate(textInput, 'text', agent, 'prompt');
      expect(verdict).toMatchObject({ ok: false });
      if (!verdict.ok) expect(verdict.reason).toMatch(/already connected/i);
    });
  });

  describe('type compatibility rule', () => {
    it('rejects a skill output feeding a text input', () => {
      const verdict = validate(markdown, 'skill', agent, 'prompt');
      expect(verdict).toMatchObject({ ok: false });
      if (!verdict.ok) expect(verdict.reason).toMatch(/can't feed/i);
    });

    it('rejects a tool output feeding a text input', () => {
      const verdict = validate(tool, 'tool', agent, 'prompt');
      expect(verdict).toMatchObject({ ok: false });
    });

    it('accepts text into a result port, because result declares it accepts text', () => {
      // Deliberate asymmetry: compatibility is declared by the *consumer*,
      // so a plain input can be wired straight to an output node while a
      // graph is being sketched.
      expect(validate(textInput, 'text', output, 'result').ok).toBe(true);
    });
  });

  describe('capacity rule', () => {
    it('replaces the incumbent when a single-slot input is already full', () => {
      const existing = connect(workbench, textInput, 'text', agent, 'prompt');
      const second = addNode(workbench, TYPE.textInput);

      const verdict = validate(second, 'text', agent, 'prompt');

      // Not a rejection: re-wiring an input by dropping a new link on it is
      // the gesture users reach for, so the incumbent is displaced instead.
      expect(verdict.ok).toBe(true);
      if (verdict.ok) expect(verdict.replaces).toEqual([existing.id]);
    });

    it('lets an output fan out to many consumers', () => {
      connect(workbench, agent, 'result', output, 'result');
      const secondOutput = addNode(workbench, TYPE.output);
      const verdict = validate(agent, 'result', secondOutput, 'result');
      expect(verdict.ok).toBe(true);
      if (verdict.ok) expect(verdict.replaces).toEqual([]);
    });

    it('lets many tools converge on the agent tool bus without displacing each other', () => {
      const first = connect(workbench, tool, 'tool', agent, 'tools');
      const secondTool = addNode(workbench, TYPE.redditSearch);

      const verdict = validate(secondTool, 'tool', agent, 'tools');

      expect(verdict.ok).toBe(true);
      // The bus is the one multi-connection input; displacing the first tool
      // here would defeat its purpose.
      if (verdict.ok) expect(verdict.replaces).not.toContain(first.id);
    });
  });

  describe('acyclic rule', () => {
    // Uses a synthetic symmetric-port type so the rule is tested independently
    // of which real ports happen to accept which types. The catalogue-level
    // pins live in "prompt chaining (ticket 08)" below.
    beforeEach(() => registerLoopableType(workbench));

    it('rejects a link that would close a two-node cycle', () => {
      const a = addNode(workbench, LOOPABLE_TYPE);
      const b = addNode(workbench, LOOPABLE_TYPE);
      connect(workbench, a, 'out', b, 'in');

      const verdict = validate(b, 'out', a, 'in');
      expect(verdict).toMatchObject({ ok: false });
      if (!verdict.ok) expect(verdict.reason).toMatch(/loop/i);
    });

    it('rejects a link that would close a longer cycle', () => {
      // Walks forward more than one hop, so a depth-1 check would pass this.
      const a = addNode(workbench, LOOPABLE_TYPE);
      const b = addNode(workbench, LOOPABLE_TYPE);
      const c = addNode(workbench, LOOPABLE_TYPE);
      connect(workbench, a, 'out', b, 'in');
      connect(workbench, b, 'out', c, 'in');

      const verdict = validate(c, 'out', a, 'in');
      expect(verdict).toMatchObject({ ok: false });
      if (!verdict.ok) expect(verdict.reason).toMatch(/loop/i);
    });

    it('allows a chain that does not close', () => {
      const a = addNode(workbench, LOOPABLE_TYPE);
      const b = addNode(workbench, LOOPABLE_TYPE);
      const c = addNode(workbench, LOOPABLE_TYPE);
      connect(workbench, a, 'out', b, 'in');

      expect(validate(b, 'out', c, 'in').ok).toBe(true);
    });

    it('allows a diamond, which is not a cycle', () => {
      // One source fanning into two agents that both feed one sink is
      // acyclic, and a naive "have I seen this node" check would reject it.
      const left = addNode(workbench, TYPE.agent);
      const right = addNode(workbench, TYPE.agent);
      connect(workbench, textInput, 'text', left, 'prompt');
      connect(workbench, textInput, 'text', right, 'prompt');
      connect(workbench, left, 'result', output, 'result');

      expect(validate(right, 'result', output, 'result').ok).toBe(true);
    });
  });

  describe('prompt chaining (ticket 08)', () => {
    // `result` is no longer terminal: the three text-side *inputs* that can
    // legitimately consume a previous step's answer declare `accepts` on the
    // port descriptor. Everything else keeps the default "only itself".
    it('lets one agent’s result feed another agent’s prompt', () => {
      const second = addNode(workbench, TYPE.agent);
      expect(validate(agent, 'result', second, 'prompt').ok).toBe(true);
    });

    it('actually draws the chain through the controller, not just the validator', () => {
      // The gesture path: `edges.connect` is what the canvas calls when a link
      // is dropped, so this is the claim "prompt chaining is drawable".
      const second = addNode(workbench, TYPE.agent);
      const verdict = workbench.controller.edges.connect(
        { nodeId: agent.id, portId: 'result' },
        { nodeId: second.id, portId: 'prompt' },
      );

      expect(verdict.ok).toBe(true);
      expect(workbench.model.edgesInto({ nodeId: second.id, portId: 'prompt' })).toHaveLength(1);
    });

    it('lets an agent’s result be classified by a router', () => {
      const router = addNode(workbench, TYPE.router);
      expect(validate(agent, 'result', router, 'question').ok).toBe(true);
    });

    it('lets an agent’s result instruct an orchestrator', () => {
      const orchestrator = addNode(workbench, TYPE.orchestrator);
      expect(validate(agent, 'result', orchestrator, 'instruction').ok).toBe(true);
    });

    it('still refuses a result into an input that has not opted in', () => {
      // A text input is only widened where chaining is meaningful; the
      // widening is per-port, not a blanket text ← result type rule.
      const grader = addNode(workbench, TYPE.grader);
      expect(validate(agent, 'result', grader, 'candidate').ok).toBe(true);
      expect(validate(textInput, 'text', agent, 'skill').ok).toBe(false);
    });

    it('refuses a chain that loops back on itself through result', () => {
      // The regression pin: widening `accepts` must not make an ordinary
      // cycle drawable. `feedback` stays the only cycle-closing port type.
      const second = addNode(workbench, TYPE.agent);
      connect(workbench, agent, 'result', second, 'prompt');

      const verdict = validate(second, 'result', agent, 'prompt');
      expect(verdict).toMatchObject({ ok: false });
      if (!verdict.ok) expect(verdict.reason).toMatch(/loop/i);
    });

    it('still allows the grader’s revise loop to close', () => {
      const grader = addNode(workbench, TYPE.grader);
      connect(workbench, agent, 'result', grader, 'candidate');

      expect(validate(grader, 'revise', agent, 'feedback').ok).toBe(true);
    });
  });

  describe('unknown endpoints', () => {
    it('rejects a missing node rather than throwing', () => {
      const verdict = workbench.connectionValidator.validate(
        { nodeId: 'node:does-not-exist', portId: 'text' },
        { nodeId: agent.id, portId: 'prompt' },
      );
      expect(verdict).toMatchObject({ ok: false });
      if (!verdict.ok) expect(verdict.reason).toMatch(/unknown node/i);
    });

    it('rejects a missing port rather than throwing', () => {
      const verdict = validate(textInput, 'nope', agent, 'prompt');
      expect(verdict).toMatchObject({ ok: false });
      if (!verdict.ok) expect(verdict.reason).toMatch(/unknown port/i);
    });
  });

  describe('rule ordering', () => {
    it('reports direction before type, so the message names the real mistake', () => {
      // Both rules would fire here. Direction is the actionable one — telling
      // the user about type incompatibility when they dragged backwards
      // sends them down the wrong path.
      const verdict = validate(agent, 'prompt', agent, 'skill');
      expect(verdict).toMatchObject({ ok: false });
      if (!verdict.ok) expect(verdict.reason).toMatch(/output port/i);
    });
  });
});
