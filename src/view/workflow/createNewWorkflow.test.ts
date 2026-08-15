import { describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { Ok, Err, type Result } from '@core/kernel/Result';
import type { IWorkflowTemplates, WorkflowTemplate } from '@core/runtime/WorkflowFileClient';
import {
  BLANK_TEMPLATE,
  createNewWorkflow,
  defaultWorkflowName,
  discardWarning,
} from './createNewWorkflow';

/**
 * Ticket 06 — **Create New** moved to the toolbar, where a first-time user
 * looks for it, and the Workflows panel keeps its own button.
 *
 * Two surfaces, one implementation. The ticket's own guard is "do not
 * duplicate the manager", so what moved is a *button*, and the knowledge it
 * presses — clear, apply a template, name, forget the slug and the drill trail
 * — is this module, exactly as `loadWorkflowIntoEditor` is for the other
 * direction.
 */

const DOCUMENT = {
  version: 2,
  name: 'Templated',
  nodes: [
    {
      id: 'n1',
      type: 'input.question',
      position: { x: 0, y: 0 },
      size: { width: 240, height: 96 },
      parentId: null,
      data: {},
    },
  ],
  edges: [],
};

const templatesServing = (templates: readonly WorkflowTemplate[]): IWorkflowTemplates => ({
  templates: (): Promise<Result<readonly WorkflowTemplate[], string>> =>
    Promise.resolve(Ok(templates)),
});

const templatesFailing = (): IWorkflowTemplates => ({
  templates: (): Promise<Result<readonly WorkflowTemplate[], string>> =>
    Promise.resolve(Err('runtime unreachable')),
});

describe('createNewWorkflow', () => {
  it('empties the canvas and names the document', async () => {
    const workbench = new Workbench();
    workbench.controller.document.importJSON(JSON.stringify(DOCUMENT));

    const outcome = await createNewWorkflow(
      { name: 'Support Triage', template: BLANK_TEMPLATE },
      workbench.controller,
      templatesServing([]),
    );

    expect(outcome.ok).toBe(true);
    expect(workbench.model.nodeCount).toBe(0);
    expect(workbench.model.name).toBe('Support Triage');
  });

  it('applies a template document when one is chosen', async () => {
    const workbench = new Workbench();

    const outcome = await createNewWorkflow(
      { name: 'From Minimal', template: 'minimal' },
      workbench.controller,
      templatesServing([{ name: 'minimal', summary: 'Input, agent, output.', document: DOCUMENT }]),
    );

    expect(outcome.ok).toBe(true);
    expect(outcome.ok && outcome.value.template).toBe('minimal');
    expect(workbench.model.nodeCount).toBe(1);
    // The name the user typed wins over the template's own.
    expect(workbench.model.name).toBe('From Minimal');
  });

  it('leaves the canvas exactly as it was when the template cannot be fetched', async () => {
    const workbench = new Workbench();
    workbench.controller.document.importJSON(JSON.stringify(DOCUMENT));

    const outcome = await createNewWorkflow(
      { name: 'Doomed', template: 'minimal' },
      workbench.controller,
      templatesFailing(),
    );

    expect(outcome.ok).toBe(false);
    // Not empty and templateless: a failed fetch must cost nothing.
    expect(workbench.model.nodeCount).toBe(1);
  });

  it('refuses a template the runtime does not offer, rather than silently blanking', async () => {
    const workbench = new Workbench();
    workbench.controller.document.importJSON(JSON.stringify(DOCUMENT));

    const outcome = await createNewWorkflow(
      { name: 'Doomed', template: 'no-such-template' },
      workbench.controller,
      templatesServing([]),
    );

    expect(outcome.ok).toBe(false);
    expect(workbench.model.nodeCount).toBe(1);
  });

  it('falls back to a dated default when no name is typed', async () => {
    const workbench = new Workbench();

    const outcome = await createNewWorkflow(
      { name: '   ', template: BLANK_TEMPLATE },
      workbench.controller,
      templatesServing([]),
    );

    expect(outcome.ok).toBe(true);
    expect(workbench.model.name).toBe(defaultWorkflowName());
  });
});

/**
 * The toolbar button creates *immediately* — no panel, no form — so it is the
 * one surface that can discard work with a single click. The panel never could
 * either, which was a defect nobody had noticed; the warning is shared.
 */
describe('discardWarning', () => {
  it('is silent for a workflow that has a folder on disk', () => {
    expect(discardWarning({ name: 'Saved', nodeCount: 6, saved: true })).toBeNull();
  });

  it('is silent for an empty canvas', () => {
    expect(discardWarning({ name: 'Untitled', nodeCount: 0, saved: false })).toBeNull();
  });

  it('says what is lost when an unsaved document holds work', () => {
    const warning = discardWarning({ name: 'Untitled', nodeCount: 3, saved: false });
    expect(warning).toContain('Untitled');
    expect(warning).toContain('3 nodes');
    // The consequence, in the same breath as the question.
    expect(warning).toContain('never been saved');
  });

  it('counts one node in the singular', () => {
    expect(discardWarning({ name: 'Untitled', nodeCount: 1, saved: false })).toContain('1 node');
  });
});
