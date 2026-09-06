import { describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { announcementFor } from './explainConnection';

/**
 * Why a link was refused, said out loud.
 *
 * The rules already know: *"Text output can't feed a Skill input"*, *"That
 * would create a loop. Route it through a Grader's 'revise' output instead."*
 * All of it was computed and then destroyed one line later —
 * `ConnectionValidator.canConnect` returns `verdict.ok`, dropping
 * `verdict.reason`, and `validateConnection` hands JointJS that bare boolean.
 * A `false` there makes JointJS refuse the link outright, so `link:connect`
 * never fires and the rejection channel that already existed was never
 * reached.
 *
 * Observed as: drag `text` → `skill`, drag a node's `result` back to its own
 * `prompt` — both refused in silence. The type system is the editor's best
 * idea and it was invisible.
 */
describe('what to announce when a drag ends', () => {
  it('says nothing when the link was made', () => {
    // The overwhelmingly common case. A successful connection must be quiet:
    // the new edge on the canvas is the feedback.
    expect(announcementFor({ connected: true, lastRefusal: 'anything' })).toBeNull();
  });

  it('says nothing when the drag simply ended on empty canvas', () => {
    // Releasing over nothing is not a refusal — `linkPinning: false` already
    // drops the link, and there is no rule to quote. Nagging here would make
    // every abandoned gesture an error.
    expect(announcementFor({ connected: false, lastRefusal: null })).toBeNull();
  });

  it('reports the reason when a real port refused the link', () => {
    expect(
      announcementFor({ connected: false, lastRefusal: "Text output can't feed a Skill input" }),
    ).toBe("Text output can't feed a Skill input");
  });

  it('prefers the refusal even after an earlier valid hover', () => {
    // A drag crosses several ports. What matters is the one under the pointer
    // when the user let go, which is what `lastRefusal` holds.
    expect(
      announcementFor({ connected: false, lastRefusal: 'A node cannot connect to itself' }),
    ).toBe('A node cannot connect to itself');
  });

  it('says which link a replacement took, workflow-gallery/77', () => {
    // The one exception to "a made link speaks for itself": connecting also
    // displaced an incumbent link, which otherwise vanished with no word.
    expect(
      announcementFor({
        connected: true,
        lastRefusal: null,
        connectedMessage: 'Replaced the link from Billing desk',
      }),
    ).toBe('Replaced the link from Billing desk');
  });

  it('stays quiet for an ordinary connect with nothing displaced', () => {
    expect(
      announcementFor({ connected: true, lastRefusal: null, connectedMessage: null }),
    ).toBeNull();
  });
});

describe('the reasons the rules actually give', () => {
  /**
   * These are the strings a user will read, so they are pinned here rather
   * than left to whatever a rule happens to say. If one changes, this test is
   * the place to argue about the new wording.
   */
  const bench = () => new Workbench();

  it('explains a type mismatch in the port types own words', () => {
    const workbench = bench();
    const { controller } = workbench;
    controller.nodes.add('input.text', { x: 0, y: 0 });
    controller.nodes.add('agent.llm', { x: 400, y: 0 });
    const [input, agent] = workbench.model.nodes();

    const verdict = controller.edges.explainConnection(
      { nodeId: input!.id, portId: 'text' },
      { nodeId: agent!.id, portId: 'skill' },
    );

    expect(verdict.ok).toBe(false);
    if (!verdict.ok) {
      expect(verdict.reason).toMatch(/can't feed/i);
      // Names both ends, so the reader knows which half to change.
      expect(verdict.reason.length).toBeGreaterThan(10);
    }
  });

  it('explains a self-connection', () => {
    const workbench = bench();
    const { controller } = workbench;
    controller.nodes.add('agent.llm', { x: 0, y: 0 });
    const [agent] = workbench.model.nodes();

    const verdict = controller.edges.explainConnection(
      { nodeId: agent!.id, portId: 'result' },
      { nodeId: agent!.id, portId: 'prompt' },
    );

    expect(verdict.ok).toBe(false);
    if (!verdict.ok) expect(verdict.reason).toBe('A node cannot connect to itself');
  });

  it('accepts a legal link, with no reason to give', () => {
    const workbench = bench();
    const { controller } = workbench;
    controller.nodes.add('input.text', { x: 0, y: 0 });
    controller.nodes.add('agent.llm', { x: 400, y: 0 });
    const [input, agent] = workbench.model.nodes();

    expect(
      controller.edges.explainConnection(
        { nodeId: input!.id, portId: 'text' },
        { nodeId: agent!.id, portId: 'prompt' },
      ).ok,
    ).toBe(true);
  });
});
