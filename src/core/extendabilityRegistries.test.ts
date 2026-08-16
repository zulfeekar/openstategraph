import { describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import type { IConnectionRule } from '@core/validation/ConnectionValidator';
import type { IWorkflowRule } from '@core/validation/WorkflowValidator';

/**
 * The extension points `extendability.test.ts` does not walk.
 *
 * That file is the walk CLAUDE.md's **O** asks for — "extend by registering,
 * never by editing the engine" — and it covers a node type, a tool and a
 * provider. The rule names more than three: *"node types, executors,
 * providers, connection rules, validation rules, canvas features, card
 * bodies"*. The architecture review of 2026-08-16 checked the remainder by
 * reading, which is exactly the method that file exists to replace, so the
 * two that are `Registry<T>` on the `Workbench` are walked here.
 *
 * Card bodies are deliberately **not** pinned here. They are a module-level
 * `Map` in `src/view/nodes/nodeBodyRegistry.tsx` rather than a `Registry<T>`,
 * they live above `core/`, and the review filed the shape question as its own
 * ticket rather than settling it in a test.
 *
 * As in the sibling file, the imports are the assertion that matters: nothing
 * below imports a `core/` module it had to modify, and adding these two rules
 * took no edit to any file under `src/core/`.
 */

/** A third-party policy: nothing may be wired into a node whose title is locked. */
const lockedTitleRule: IConnectionRule = {
  id: 'acme-locked-title',
  // Before `capacity` (50), so the refusal is the policy's own sentence
  // rather than a report about the bus being full.
  order: 20,
  check: ({ targetNode }) =>
    targetNode.title.startsWith('[locked]') ? { reason: 'That node is locked' } : null,
};

describe('a new connection rule lands by registration only', () => {
  it('refuses an edge the shipped rules allow', () => {
    const workbench = new Workbench();
    const agent = workbench.registry.nodeTypes
      .require('agent.llm')
      .create({ position: { x: 0, y: 0 } });
    const input = workbench.registry.nodeTypes
      .require('input.text')
      .create({ position: { x: 0, y: 200 } });
    workbench.controller.model.addNode(agent);
    workbench.controller.model.addNode(input);
    const source = { nodeId: input.id, portId: 'text' };
    const target = { nodeId: agent.id, portId: 'prompt' };

    // The shipped rule set allows it, which is what makes the refusal below
    // attributable to the registered rule and not to something else.
    expect(workbench.connectionValidator.validate(source, target).ok).toBe(true);

    workbench.controller.model.setNodeTitle(agent.id, '[locked] Agent');
    workbench.connectionValidator.rules.register(lockedTitleRule);

    const verdict = workbench.connectionValidator.validate(source, target);
    expect(verdict.ok).toBe(false);
    expect(verdict.ok ? '' : verdict.reason).toBe('That node is locked');
  });

  it('joins the registry the validator orders', () => {
    const workbench = new Workbench();
    const before = workbench.connectionValidator.rules.list().length;

    workbench.connectionValidator.rules.register(lockedTitleRule);

    expect(workbench.connectionValidator.rules.list().length).toBe(before + 1);
    expect(workbench.connectionValidator.rules.get('acme-locked-title')).toBeDefined();
  });
});

describe('a new workflow validation rule lands by registration only', () => {
  it('adds a diagnostic the shipped rule set never produces', () => {
    const workbench = new Workbench();
    const node = workbench.registry.nodeTypes
      .require('agent.llm')
      .create({ position: { x: 0, y: 0 } });
    workbench.controller.model.addNode(node);

    const houseStyleRule: IWorkflowRule = {
      id: 'acme-house-style',
      check: ({ model }) =>
        model
          .nodes()
          .filter((candidate) => candidate.title.startsWith('[draft]'))
          .map((candidate) => ({
            code: 'acme-draft-title',
            severity: 'warning' as const,
            message: 'A draft node is not ready to run',
            nodeId: candidate.id,
          })),
    };

    workbench.controller.model.setNodeTitle(node.id, '[draft] Agent');
    expect(workbench.workflowValidator.validate().some((d) => d.code === 'acme-draft-title')).toBe(
      false,
    );

    workbench.workflowValidator.rules.register(houseStyleRule);

    const diagnostics = workbench.workflowValidator.validate();
    expect(diagnostics.some((d) => d.code === 'acme-draft-title')).toBe(true);
    expect(diagnostics.find((d) => d.code === 'acme-draft-title')?.nodeId).toBe(node.id);
  });
});
