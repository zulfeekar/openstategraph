import { describe, expect, it } from 'vitest';
import { frameTarget } from './frameTarget';
import { parseMountAddress } from '@core/model/MountAddress';

const address = (raw: string) => parseMountAddress(raw)!;

/** The open document, as the projection sees it: a set of ids. */
const documentWith =
  (...ids: string[]) =>
  (id: string) =>
    ids.includes(id);

describe('frameTarget — project onto the document that is open', () => {
  describe('on the parent canvas', () => {
    const parent = documentWith('in1', 'team1', 'out1');

    it('lights the mount for a frame from inside it', () => {
      // The child's `researcher` is not on this canvas; the mount that owns
      // it is. This is the behaviour that already existed and must not change.
      expect(frameTarget({ node: 'researcher', activeNode: 'team1' }, parent)).toBe('team1');
    });

    it('lights a top-level node by its own id', () => {
      expect(frameTarget({ node: 'in1', activeNode: 'in1' }, parent)).toBe('in1');
    });
  });

  describe('after opening the mount', () => {
    // "Edit team" navigates: the editor now holds the *child* document.
    const child = documentWith('researcher', 'writer', 'child-out');

    it('lights the step that actually ran, not the mount', () => {
      // The defect: `activeNode` won unconditionally, and `team1` does not
      // exist here — so nothing lit, and a running team looked like a static
      // diagram to the developer who opened it to watch it run.
      expect(frameTarget({ node: 'researcher', activeNode: 'team1' }, child)).toBe('researcher');
    });

    it('keeps following the run as it moves through the child', () => {
      expect(frameTarget({ node: 'writer', activeNode: 'team1' }, child)).toBe('writer');
    });
  });

  describe('when neither end is on this canvas', () => {
    it('lights nothing rather than guessing', () => {
      // A frame from a document nobody is looking at. The alternative to
      // `null` is lighting whichever card happens to share an id.
      expect(
        frameTarget({ node: 'researcher', activeNode: 'team1' }, documentWith('a')),
      ).toBeNull();
    });
  });

  // The fields above are what a frame could say before tickets 33/34. They
  // were not enough, and the browser is where that showed: a real mounted run
  // reports `node: "tools"` and `activeNode: "wf-music"`, so opening the child
  // matched neither and lit nothing at all. `path` is the frame saying where
  // it is on *every* canvas, outermost document first.
  describe('with a resolved path', () => {
    const parent = documentWith('in1', 'wf-music', 'out1');
    const child = documentWith('in1', 'agent-sql', 'out1');
    // What the wire actually carries for a tool step inside the mount.
    const insideTheMount = {
      node: 'tools',
      activeNode: 'wf-music',
      path: ['wf-music', 'agent-sql'],
    } as const;

    it('lights the mount on the parent canvas', () => {
      expect(frameTarget(insideTheMount, parent)).toBe('wf-music');
    });

    it('lights the real step once the mount is open', () => {
      // Neither `node` nor `activeNode` could ever answer this: `tools` is a
      // LangGraph loop step and `wf-music` belongs to the parent.
      expect(frameTarget(insideTheMount, child)).toBe('agent-sql');
    });

    it('is walked outermost-first, so a shared id cannot pull the parent in', () => {
      // Both documents have `in1`. Walking inward-first would light the
      // parent's own input node while the CHILD's input step ran.
      const childInput = { node: 'in1', activeNode: 'wf-music', path: ['wf-music', 'in1'] };
      expect(frameTarget(childInput, parent)).toBe('wf-music');
      expect(frameTarget(childInput, child)).toBe('in1');
    });

    it('falls back to the old rule when the path resolves to nothing here', () => {
      // A frame from a sibling document. The path names no card of ours, so
      // the pre-existing node/owner rule decides — and also finds nothing.
      expect(frameTarget({ node: 'x', activeNode: 'y', path: ['p', 'q'] }, child)).toBeNull();
    });

    it('ignores an empty path rather than treating it as an answer', () => {
      expect(frameTarget({ node: 'in1', activeNode: 'in1', path: [] }, child)).toBe('in1');
    });
  });

  // Ids are unique only within a document. `concierge` and `chinook-assistant`
  // — the pair the ticket was reported against — share `in1`, `router1` and
  // `out1`, so the id walk alone cannot tell whose step a frame is about.
  describe('when the caller knows which document it is showing', () => {
    const child = documentWith('in1', 'router1', 'agent-sql');
    const topLevelInput = {
      node: 'in1',
      activeNode: 'in1',
      path: ['in1'],
      pathSlugs: ['concierge'],
    };

    it('claims nothing for a step that happened in another document', () => {
      // Without the slug this lights the child's own `in1` — the parent's
      // input step painted onto the child's card.
      expect(frameTarget(topLevelInput, child, address('chinook-assistant'))).toBeNull();
      expect(frameTarget(topLevelInput, child)).toBe('in1');
    });

    it('takes the level whose document this is', () => {
      const inside = {
        node: 'in1',
        activeNode: 'wf-music',
        path: ['wf-music', 'in1'],
        pathSlugs: ['concierge', 'chinook-assistant'],
      };
      expect(frameTarget(inside, child, address('chinook-assistant'))).toBe('in1');
      expect(frameTarget(inside, documentWith('in1', 'wf-music'), address('concierge'))).toBe('wf-music');
    });

    it('tells two mounts of one package apart', () => {
      // The live bug tranche 6 exists for. `concierge` can mount
      // `chinook-assistant` twice, so `pathSlugs` holds that slug at more than
      // one level and `indexOf` answers with the *first* — lighting a card in
      // the instance the user is not looking at, with the other instance's
      // values. A slug names the class; only the address names which one.
      const inSecondMount = {
        node: 'agent_sql',
        activeNode: 'wf-other',
        path: ['wf-other', 'agent-sql'],
        pathSlugs: ['concierge', 'chinook-assistant'],
      };
      const inFirstMount = {
        node: 'agent_sql',
        activeNode: 'wf-music',
        path: ['wf-music', 'agent-sql'],
        pathSlugs: ['concierge', 'chinook-assistant'],
      };

      // Viewing `wf-other`: its own frame lights, the sibling's does not.
      expect(frameTarget(inSecondMount, child, address('concierge/wf-other'))).toBe('agent-sql');
      expect(frameTarget(inFirstMount, child, address('concierge/wf-other'))).toBeNull();

      // …and the mirror image, from inside the other instance.
      expect(frameTarget(inFirstMount, child, address('concierge/wf-music'))).toBe('agent-sql');
      expect(frameTarget(inSecondMount, child, address('concierge/wf-music'))).toBeNull();
    });

    it('still lights the mount card on the parent canvas', () => {
      const inside = {
        node: 'agent_sql',
        activeNode: 'wf-music',
        path: ['wf-music', 'agent-sql'],
        pathSlugs: ['concierge', 'chinook-assistant'],
      };
      const parent = documentWith('in1', 'wf-music', 'wf-other', 'out1');
      expect(frameTarget(inside, parent, address('concierge'))).toBe('wf-music');
    });

    it('falls back to the slug rule when the run is rooted elsewhere', () => {
      // Someone opened the shared definition (`?w=chinook-assistant`) while a
      // run of `concierge` is going. The address cannot index this run's path,
      // so the older class-level rule decides — which is the right answer for
      // a document that is not in the run's tree at all.
      const inside = {
        node: 'in1',
        activeNode: 'wf-music',
        path: ['wf-music', 'in1'],
        pathSlugs: ['concierge', 'chinook-assistant'],
      };
      expect(frameTarget(inside, child, address('chinook-assistant'))).toBe('in1');
    });

    it('falls back to the id walk when a level could not be named', () => {
      // An empty slug means "unknown", never "not you" — refusing on
      // incomplete evidence would blank a canvas that the id walk can still
      // light correctly.
      const partial = {
        node: 'agent-sql',
        activeNode: 'wf-music',
        path: ['wf-music', 'agent-sql'],
        pathSlugs: ['concierge', ''],
      };
      expect(frameTarget(partial, child, address('chinook-assistant'))).toBe('agent-sql');
    });
  });

  describe('degenerate frames', () => {
    const doc = documentWith('a', 'b');

    it('falls back to the owner when the frame names no node', () => {
      expect(frameTarget({ node: '', activeNode: 'a' }, doc)).toBe('a');
    });

    it('is null when the frame names nothing at all', () => {
      expect(frameTarget({ node: '' }, doc)).toBeNull();
    });

    it('does not treat whitespace as an id', () => {
      expect(frameTarget({ node: '   ', activeNode: '  ' }, doc)).toBeNull();
    });
  });
});
