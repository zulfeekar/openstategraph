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
