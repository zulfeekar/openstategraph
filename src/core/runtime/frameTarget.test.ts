import { describe, expect, it } from 'vitest';
import { frameTarget } from './frameTarget';

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
