import { describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { Ok, Err, type Result } from '@core/kernel/Result';
import type { IWorkflowTemplates, WorkflowTemplate } from '@core/runtime/WorkflowFileClient';
import {
  BLANK_TEMPLATE,
  createNewWorkflow,
  defaultWorkflowName,
  discardDeclined,
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
    // The verb agrees too, or the commonest case reads "its 1 node live".
    expect(discardWarning({ name: 'Untitled', nodeCount: 1, saved: false })).toContain(
      '1 node lives',
    );
    expect(discardWarning({ name: 'Untitled', nodeCount: 2, saved: false })).toContain(
      '2 nodes live',
    );
  });
});

/**
 * `say-it-on-the-surface` 02 — **the fifth path**.
 *
 * The ticket's audit closed four refusals and predicted this one: *"if the
 * answer is 'nothing at all', the remaining bug is a fifth path this audit did
 * not find."* It was found by reproducing the owner's own sentence — *"why is
 * it not able to add another workflow?"* — in the browser: draw a node on a
 * never-saved document, press **New**, decline the discard confirm, and the
 * editor does nothing and says nothing.
 *
 * It is the same defect `saveWorkflow`'s duplicate-name confirm had, in the
 * same shape, on the gesture next door: `if (!confirm(...)) return;`. And it is
 * worse in the case nobody chooses, for the reason recorded there — a browser
 * that suppresses dialogs answers "no" on the user's behalf, so **New** simply
 * appears broken to someone who was never asked anything.
 *
 * The standard is the one the ticket set: *a refusal is audible on the gesture
 * that was refused* — and each names itself, rather than four rules sharing one
 * generic sentence.
 */
describe('discardDeclined', () => {
  it('says the new workflow was not started, and that nothing was lost', () => {
    const message = discardDeclined({ name: 'Untitled', nodeCount: 3, saved: false });
    expect(message).toContain('Untitled');
    // What was refused — in the words of the gesture that was refused.
    expect(message).toContain('New');
    // The reassurance is the substance: the fear this confirm exists to serve
    // is losing the work, so the answer has to say the work is still there.
    expect(message).toContain('3 nodes');
  });

  it('counts one node in the singular, as the warning it answers does', () => {
    expect(discardDeclined({ name: 'Untitled', nodeCount: 1, saved: false })).toContain(
      '1 node is untouched',
    );
    expect(discardDeclined({ name: 'Untitled', nodeCount: 3, saved: false })).toContain(
      '3 nodes are untouched',
    );
  });

  it('tells the user what to do instead', () => {
    expect(discardDeclined({ name: 'Untitled', nodeCount: 2, saved: false })).toContain('Save');
  });
});
