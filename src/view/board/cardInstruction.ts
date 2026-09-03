import type { BoardCard } from './patrolBoardModel';

/**
 * "Copy instruction" — the self-contained text `kanban-patrol/19` puts on
 * the clipboard. Pasteable into any coding agent with nothing installed: no
 * skill, no MCP connection, no CLI. Built from fields the board already has
 * for real, never a plausible-looking invention.
 *
 * **`priorityReason` is the evidence, and it must be here.** Caught live —
 * `Context: workflows · gap` told an agent nothing about what actually
 * happened; the classifier's own reason ("asked the same table 4 times")
 * is the one sentence that makes this actionable rather than a bare label
 * pair. Its absence is a fact too: no reason given is different from a
 * blank line, so this never prints an empty "Why:" — it omits the field
 * entirely, same rule this feature applies everywhere else an optional
 * field is missing rather than empty.
 *
 * The last line is the whole point of a card: it tells the reader how to
 * report progress back, so a coding agent that reads this text (rather than
 * having the skill installed to read the row live) still knows what closes
 * the loop.
 */
export function instructionForCard(card: BoardCard): string {
  // Every field on its own **paragraph** — a blank line between each, not a
  // bare '\n'. A single newline does not force a break in the Markdown
  // renderer the realistic paste destination (a chat-based coding agent)
  // uses, only a blank line does — caught live: a pasted copy ran two
  // fields together with no space between them at all.
  const paragraphs = [`Task: ${card.id}`, `Title: ${card.title}`, `Context: ${card.secondary}`];
  if (card.priorityReason) {
    paragraphs.push(`Why this matters: ${card.priorityReason}`);
  }
  paragraphs.push(
    'Work this test-first: write a failing test for the stated reason before ' +
      'any fix, then make it pass. Do not skip the red step.',
    [
      'Report progress as you go, from this repository:',
      `  openstategraph kanban attend ${card.id} --actor <your name>`,
      `  openstategraph kanban stage ${card.id} red --actor <your name>`,
      `  openstategraph kanban stage ${card.id} green --actor <your name>`,
      `  openstategraph kanban stage ${card.id} finished --actor <your name>`,
    ].join('\n'),
  );
  return paragraphs.join('\n\n');
}
