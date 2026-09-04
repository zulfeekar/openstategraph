import { describe, expect, it } from 'vitest';
import { instructionForCard } from './cardInstruction';
import type { BoardCard } from './patrolBoardModel';

/**
 * `kanban-patrol/19`. The self-contained text "Copy instruction" puts on the
 * clipboard — pasteable into any coding agent with nothing installed. Built
 * from real card fields only; nothing here is invented to look plausible.
 */

function card(overrides: Partial<BoardCard> = {}): BoardCard {
  return {
    id: 'proj-a:thread-1',
    title: 'A tool call with no timeout',
    secondary: 'workflows · bug',
    kind: 'bug',
    lifecycle: 'open',
    when: '2m ago',
    priority: 'high',
    area: 'backend',
    ...overrides,
  };
}

describe('the instruction is self-contained', () => {
  it('carries the task id, so a stage report can reference it', () => {
    expect(instructionForCard(card())).toContain('proj-a:thread-1');
  });

  it('separates every field with a BLANK line, not a bare newline', () => {
    // A single '\n' does not force a line break in the Markdown renderer
    // every real paste destination (a chat-based coding agent) uses — only
    // a blank line does. Caught live: a user pasted this and two fields ran
    // together with no space at all.
    const lines = instructionForCard(card()).split('\n');
    const taskLine = lines.findIndex((l) => l.startsWith('Task:'));
    const titleLine = lines.findIndex((l) => l.startsWith('Title:'));
    expect(titleLine).toBe(taskLine + 2);
    expect(lines[taskLine + 1]).toBe('');
  });

  it('carries the title', () => {
    expect(instructionForCard(card())).toContain('A tool call with no timeout');
  });

  it('states TDD-first, plainly, not as jargon the reader must already know', () => {
    expect(instructionForCard(card())).toMatch(/failing test|red.*before|test-first/i);
  });

  it('tells the agent how to report progress back — the whole point of a card', () => {
    const text = instructionForCard(card());
    expect(text).toMatch(/kanban attend/);
    expect(text).toContain('proj-a:thread-1');
  });
});

describe('the evidence — priorityReason — actually reaches the instruction', () => {
  it("includes the classifier's own reason when the card has one", () => {
    const text = instructionForCard(
      card({
        priorityReason:
          'chinook_list_tables called 2 times with an identical result in one thread — minor, no error.',
      }),
    );

    expect(text).toContain('chinook_list_tables called 2 times');
  });

  it('says nothing was given, rather than a blank line, when there is no reason', () => {
    // Absent, never a false claim of evidence — same rule this whole
    // feature already applies to a card's other optional fields.
    const text = instructionForCard(card({ priorityReason: undefined }));

    expect(text).not.toMatch(/^Why:\s*$/m);
  });
});

describe('an answered judgement carries its decision — `kanban-patrol/15`', () => {
  const decided = () =>
    card({
      kind: 'decision',
      title: 'Which model should the grader use?',
      answer: 'Use the cloud one.',
      answeredBy: 'zulfeekar',
    });

  it('prepends the decision, so the agent reads it before the work', () => {
    // The whole reason an answered card goes back to Detected is that the
    // judgement is already made. An agent that meets the question first and
    // the answer last is an agent that can re-open it.
    const text = instructionForCard(decided());
    expect(text.indexOf('Use the cloud one.')).toBeLessThan(text.indexOf('Task:'));
  });

  it('names who decided, because an unattributed decision is a rumour', () => {
    expect(instructionForCard(decided())).toContain('zulfeekar');
  });

  it('says plainly that the decision is settled, not a suggestion', () => {
    expect(instructionForCard(decided())).toMatch(
      /already (been )?(made|decided)|do not re-?open/i,
    );
  });

  it('keeps the decision on its own paragraph, blank line and all', () => {
    // Same rule every other field here follows: a bare '\n' does not break a
    // line in the Markdown renderer a chat-based coding agent renders into.
    const lines = instructionForCard(decided()).split('\n');
    const taskLine = lines.findIndex((l) => l.startsWith('Task:'));
    expect(lines[taskLine - 1]).toBe('');
  });

  it('says nothing about a decision on a card that has none', () => {
    expect(instructionForCard(card())).not.toMatch(/Decision/i);
  });

  it('says nothing when the answer is blank rather than absent', () => {
    // Absent-not-empty, the rule the mapping already keeps — this is the
    // second line, so a row that arrives with an empty string still renders
    // no decision block rather than an empty one.
    expect(instructionForCard(card({ answer: '' }))).not.toMatch(/Decision/i);
  });
});
