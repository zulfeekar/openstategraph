import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';

/**
 * CLAUDE.md's ceiling, on the TypeScript side.
 *
 *     "A class with many public members is a design failure, not a
 *     convenience. If it can be described only with 'and', split it.
 *     Ceiling: ~10 public members, one reason to change."
 *
 * `backend/tests/test_public_surface_ceiling.py` is the sibling; this is the
 * half the system design review measured and nobody pinned
 * (reviews-2026-08-14 tickets 07 and 14).
 *
 * **Three classes carry a recorded exception, and that is the point of the
 * file.** The review's finding was not only that they were wide — it was that
 * *"none is recorded as an exception the way `WorkflowModel` is, which is the
 * part that makes them violations rather than decisions."* A number written
 * down with its reasoning is a decision; the same number undocumented is a
 * class nobody has looked at. Every entry below therefore has to say what was
 * removed, what was considered, and what would take it further.
 *
 * The numbers are exact, not upper bounds. A class that drops a member should
 * fail here and be re-recorded lower — an exception that quietly has room to
 * spare is how a ceiling becomes a floor.
 */
const read = (relative: string): string =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

/**
 * What a consumer can reach: public methods, accessors and properties.
 *
 * A collaborator counts as one member — `paper.viewport` is a member,
 * `paper.viewport.fit` is not. That is the whole mechanism by which a class
 * gets under the ceiling, and it is how CLAUDE.md describes
 * `WorkflowController`'s ten.
 */
function publicMembers(file: string, className: string): string[] {
  const source = ts.createSourceFile(file, read(file), ts.ScriptTarget.Latest, true);
  const found = new Set<string>();
  const walk = (node: ts.Node): void => {
    if (ts.isClassDeclaration(node) && node.name?.text === className) {
      for (const member of node.members) {
        if (ts.isConstructorDeclaration(member)) continue;
        const flags = ts.getCombinedModifierFlags(member);
        if (flags & (ts.ModifierFlags.Private | ts.ModifierFlags.Protected)) continue;
        const name =
          member.name && ts.isIdentifier(member.name) ? member.name.text : member.name?.getText();
        if (!name || name.startsWith('#') || name.startsWith('_')) continue;
        found.add(name);
      }
    }
    ts.forEachChild(node, walk);
  };
  walk(source);
  if (found.size === 0) throw new Error(`${className} not found in ${file}`);
  return [...found];
}

const CEILING = 10;

interface Subject {
  readonly file: string;
  readonly className: string;
  /** Exact expected count. `CEILING` where the class is genuinely under it. */
  readonly members: number;
  /** Why it is allowed to be wide. Absent means it is not. */
  readonly exception?: string;
}

const SUBJECTS: readonly Subject[] = [
  {
    file: './canvas/PaperController.ts',
    className: 'PaperController',
    members: 15,
    exception: `Nine of the fifteen are collaborators — graph, paper, adapter, viewport,
      autoLayout, follower, mounts, features, shortcuts — which is the shape
      CLAUDE.md describes for WorkflowController ("each a collaborator...
      extend it by adding a collaborator, never a method"). Ticket 14 removed
      the three that were not: a dead 'element' getter with no caller in the
      repository, a 'clientToLocal' that forwarded verbatim to the already
      public 'viewport', and a 'viewportCenter' that derived a camera fact
      from 'viewport.visibleRect' — that one moved onto Viewport as 'center',
      where a camera calculation belongs.

      What is left over ten is grid state (isGridVisible/setGridVisible),
      'observeConnectionRejections', and the two framing calls that genuinely
      compose two collaborators the consumer cannot reach separately —
      'fitToContent' and 'contentBounds' both need the model, which is
      private here. Taking it under the ceiling means making grid a canvas
      feature in the 'features' registry, which is a real change with a real
      question attached (React toggles it, so it needs a handle) rather than
      a rename. Named here so the next person starts from it.`,
  },
  {
    file: './canvas/Viewport.ts',
    className: 'Viewport',
    members: 19,
    exception: `One reason to change: where the camera is and how it moves. The members
      are the vocabulary of a camera — read the transform, convert between
      screen and model, pan, zoom, frame, glide — and there is no sub-object
      here that consumers ask for together.

      Splitting the glide was the candidate and it does not pay. 'glideTo'
      and 'stopGlide' do have their own reason to change (easing, reduced
      motion, the rAF handle), but both go through the private 'apply', so a
      separate collaborator would need that made public: minus two members,
      plus two, and the transform's single funnel — the thing that guarantees
      every listener hears a change exactly once — widened for nothing.

      The value ticket 14 actually added here is the tests. This class is 250
      lines of arithmetic every canvas gesture depends on and it had **no test
      at all**; 'Viewport.test.ts' now covers the zoom anchor, the
      conversion round trip, the fit cap, the empty-graph and unmeasured-
      container paths, and the change-notification contract. Three deliberate
      mutations to the source were checked to fail it. An exception recorded
      without that would be a guess.`,
  },
  {
    file: './core/model/AbstractNodeModel.ts',
    className: 'AbstractNodeModel',
    members: 24,
    exception: `The 'WorkflowModel' case, and CLAUDE.md's recorded reasoning for that
      exception transfers: its members are read from canvas, execution,
      validation and view code in the hundreds, so collapsing 'node.position'
      onto 'node.geometry.position' is a very large rename for a smaller
      surface rather than a clearer design.

      Ticket 14 did take the part that was not that. Seven public 'apply*'
      mutators sat under a comment reading "WorkflowModel only" — with the
      comment as the entire enforcement — and they are now 'node.write', with
      'nodeWriteSeam.test.ts' holding the layering rule the comment asked for.
      That was worth doing independently of the count: seven public setters
      are seven ways to move a node without a command, which does not fail,
      it silently drops out of undo. Two dead members went with them
      ('applyData', 'getFlag' — no caller anywhere in src/).

      The ports group (ports, port, inputs, outputs, primaryInput,
      primaryOutput) is the next-largest cluster and was **considered and
      rejected**. Ticket 07's rule is to prefer a grouping the call sites
      already make; these are each read by a different consumer — the adapter
      takes 'port', edgeCommands takes the primaries, layout takes the lists —
      and never together. That is a grouping invented rather than found, and
      ticket 07 records what those are worth.`,
  },
];

describe.each(SUBJECTS)('$className', (subject) => {
  it('has exactly the public surface recorded for it', () => {
    const members = publicMembers(subject.file, subject.className);

    expect(members.length, `${subject.className}: ${members.sort().join(', ')}`).toBe(
      subject.members,
    );
  });

  it(
    subject.exception
      ? 'carries a written reason for being over the ceiling'
      : 'is under the ceiling',
    () => {
      if (!subject.exception) {
        expect(subject.members).toBeLessThanOrEqual(CEILING);
        return;
      }
      // A number over the ceiling with no reasoning is the defect the review
      // named — a violation rather than a decision. Length is a crude proxy
      // for "somebody actually thought about this", and a crude proxy beats
      // none.
      expect(subject.exception.trim().length).toBeGreaterThan(400);
    },
  );
});

it('records an exception only for a class that needs one', () => {
  // Stops the table becoming a place where a comfortable number gets an
  // essay attached to it.
  for (const subject of SUBJECTS) {
    if (subject.members <= CEILING) {
      expect(subject.exception, `${subject.className} is under the ceiling`).toBeUndefined();
    }
  }
});
