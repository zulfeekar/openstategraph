import { describe, expect, it } from 'vitest';
import {
  deleteConfirmation,
  deletedMessage,
  duplicateNameConfirmation,
  packageFindingsMark,
  publishedMessage,
  rowActionHint,
  rowStatusHint,
  unpublishedMessage,
} from './consequences';

/**
 * Ticket 06 — "deleting says what is lost, publishing says what changed".
 *
 * The copy lives here rather than inline in `WorkflowManager` for one reason:
 * these sentences are the *feature*. A confirm that says only "this cannot be
 * undone" has not told anyone what it is about to remove, and a publish toast
 * that does not name `/chat` leaves the rule the lifecycle exists for
 * invisible. Tested strings are strings somebody has to keep true.
 */

describe('duplicateNameConfirmation', () => {
  it('names the workflow, the slug already holding it, and what happens next', () => {
    const text = duplicateNameConfirmation('AI Workflow', ['ai-workflow']);

    expect(text).toContain('AI Workflow');
    expect(text).toContain('ai-workflow');
    // The offer the ticket asked for: rename, rather than a silent second one.
    expect(text).toContain('rename');
  });

  it('counts them when a name already belongs to more than one', () => {
    const text = duplicateNameConfirmation('AI Workflow', ['ai-workflow', 'ai-workflow-2']);

    expect(text).toContain('2 packages');
    expect(text).toContain('ai-workflow-2');
  });
});

describe('deleteConfirmation', () => {
  it('names the workflow and the folder that goes with it', () => {
    const text = deleteConfirmation('Support Triage', false);
    expect(text).toContain('Support Triage');
    // The document is the least of it — tools, tests and knowledge are files
    // in the same package and they go too.
    expect(text).toContain('folder');
    expect(text).toContain('tools');
    expect(text).toContain('cannot be undone');
  });

  it('adds the consequence a published workflow has and a draft does not', () => {
    expect(deleteConfirmation('Concierge', true)).toContain('/chat');
    expect(deleteConfirmation('Concierge', false)).not.toContain('/chat');
  });
});

describe('deletedMessage', () => {
  it('reports the removal in the same terms the confirm used', () => {
    const text = deletedMessage('Support Triage');
    expect(text).toContain('Support Triage');
    expect(text).toContain('folder');
  });
});

describe('publishedMessage', () => {
  /** What `POST /api/workflows/{slug}/publish` actually answers with today. */
  const BACKEND_NOTE =
    'Concierge routing knowledge was not rebuilt automatically; rebuild it via ' +
    'POST /api/workflows/{root}/knowledge/build when routing should learn about this change.';

  it('says what changed: draft, then visible to the chat app', () => {
    const text = publishedMessage('Support Triage', { note: BACKEND_NOTE });
    expect(text).toContain('Support Triage');
    expect(text).toContain('draft');
    // Plain words, the same ones the toolbar badge uses (ship-it 52) — never
    // the internal surface names the badge was corrected away from.
    expect(text).toContain('chat app');
    expect(text).not.toContain('/chat picker');
    expect(text).not.toContain('Auto routing');
    // Publishing never rebuilds routing knowledge as a side effect, and the
    // one moment somebody cares is this one.
    expect(text).toMatch(/knowledge/i);
  });

  /**
   * `the-cost-of-one-more/18`. The backend's note is **read as a signal and
   * never forwarded**. It is addressed to an API caller — it names an HTTP
   * verb and a path template — and putting that in front of somebody who just
   * clicked Publish tells them to make a REST call by hand, in a product whose
   * whole argument is that they should not have to. Same finding `13` made
   * about `_truncation`'s *"ask again with a higher limit"*, true of the CLI
   * and false of a lane with no such control.
   */
  it('never forwards the backend sentence, verb and path template and all', () => {
    const text = publishedMessage('Support Triage', { note: BACKEND_NOTE });

    expect(text).not.toContain('/api/');
    expect(text).not.toContain('POST');
    expect(text).not.toContain('{root}');
    expect(text).not.toContain(BACKEND_NOTE);
  });

  /**
   * And what it says instead names a control that **exists in this editor**.
   *
   * The rebuild is the Knowledge card's "Build second brain"
   * (`view/nodes/KnowledgeBody.tsx` → `POST .../knowledge/build`), and the
   * routing docs are written by `RootKnowledgeBuilder`, whose topics are the
   * children a document *mounts*. So the card that has to be pressed is on the
   * workflow that mounts this one, not on this one — which the sentence says,
   * because the obvious wrong reading is the expensive one.
   */
  it('names the editor control that does the rebuild, and whose card it is on', () => {
    const text = publishedMessage('Support Triage', { note: BACKEND_NOTE });

    expect(text).toContain('Build second brain');
    expect(text).toMatch(/mounts this one/);
  });

  /**
   * The half that makes this a **read** rather than a mirror with the value
   * thrown away. The clause was hardcoded beside a call that has always
   * carried the backend's own answer, so an install that started rebuilding
   * routing on publish would have gone on being contradicted by this toast.
   * No note, no claim.
   */
  it('drops the routing clause entirely when the backend sent no note', () => {
    const text = publishedMessage('Support Triage', { note: null });

    expect(text).toContain('Support Triage');
    expect(text).toContain('chat app');
    expect(text).not.toMatch(/knowledge|second brain|routing/i);
  });
});

describe('unpublishedMessage', () => {
  it('says the workflow survives and only the chat app surface changed', () => {
    const text = unpublishedMessage('Support Triage');
    expect(text).toContain('draft');
    expect(text).toContain('chat app');
    expect(text).not.toContain('/chat picker');
    // The fear this sentence exists to answer: unpublish is not delete.
    expect(text).toMatch(/nothing is deleted|files are untouched|folder is untouched/i);
  });
});

describe('rowStatusHint', () => {
  it('says who can see it, in the shared plain words — never the internal names', () => {
    expect(rowStatusHint(true)).toContain('chat app');
    expect(rowStatusHint(false)).toContain('chat app');
    for (const text of [rowStatusHint(true), rowStatusHint(false)]) {
      expect(text).not.toContain('/chat picker');
      expect(text).not.toContain('Auto routing');
    }
  });
});

describe('rowActionHint', () => {
  it('names the audience the button affects, not the internal surfaces', () => {
    expect(rowActionHint(true)).toContain('chat app');
    expect(rowActionHint(false)).toContain('chat app');
    for (const text of [rowActionHint(true), rowActionHint(false)]) {
      expect(text).not.toContain('/chat picker');
      expect(text).not.toContain('Auto routing');
    }
    // Unpublish still says nothing is deleted (ship-it 39's own worry).
    expect(rowActionHint(true)).toMatch(/nothing is deleted/i);
  });
});

/**
 * `the-cost-of-one-more/14`. The findings come from `validate_package` and
 * arrive already prefixed, so the whole of the decision here is which of two
 * words a row wears and whether it wears one at all.
 */
describe('packageFindingsMark', () => {
  it('says nothing about a clean package', () => {
    // The mark is worth looking at only because most rows do not have one.
    expect(packageFindingsMark([])).toBeNull();
  });

  it('calls a package with an error broken, and quotes every line', () => {
    const mark = packageFindingsMark([
      'error: no workflow.json in half-built/',
      'warning: no AGENTS.md — collaborators (and agents) have no orientation',
    ]);

    expect(mark?.label).toBe('Broken');
    expect(mark?.hint).toContain('cannot run');
    // Both lines, not just the blocking one: the tooltip is the whole answer,
    // and a warning hidden behind an error is a warning nobody ever sees.
    expect(mark?.hint).toContain('error: no workflow.json in half-built/');
    expect(mark?.hint).toContain('warning: no AGENTS.md');
  });

  it('keeps a warnings-only package separate, because it still runs', () => {
    const mark = packageFindingsMark([
      'warning: tools/ without tests/ — hand-written code with no guard',
    ]);

    expect(mark?.label).toBe('Check');
    // The distinction that matters to somebody scanning the list: this one
    // works. Saying "Broken" here would teach a reader to ignore the word.
    expect(mark?.hint).toContain('runs');
    expect(mark?.hint).not.toContain('cannot run');
  });
});
