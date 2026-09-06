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
 * **A decision, when the card carries one, comes first** — `kanban-patrol/15`.
 * An answered Needs You card returns to Detected precisely because the
 * judgement is settled, so the settled thing is the first thing read.
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
  const paragraphs: string[] = [];
  // `kanban-patrol/15`, decided 2026-09-04. An answered judgement returns to
  // Detected *because* the judgement is made, so the decision goes first —
  // an agent that meets the question before the answer is an agent that can
  // re-open it. Read for trimmed content, never mere presence: a row
  // carrying an empty answer renders no block at all, the same
  // absent-not-empty rule `priorityReason` already follows.
  if (card.answer?.trim()) {
    const decided = card.answeredBy ? ` (decided by ${card.answeredBy})` : '';
    paragraphs.push(
      `Decision${decided}: ${card.answer.trim()}\n` +
        'This judgement has already been made — work to it, do not re-open it.',
    );
  }
  paragraphs.push(`Task: ${card.id}`, `Title: ${card.title}`, `Context: ${card.secondary}`);
  if (card.priorityReason) {
    paragraphs.push(`Why this matters: ${card.priorityReason}`);
  }
  // `osg-agent-experience/25`. The brief an idea card carries, and it goes
  // **before** the test-first instruction rather than after it: what "done"
  // means is what the first failing test is written against, so an agent that
  // meets it below that instruction meets it after the decision it was
  // supposed to inform. Omitted entirely on a patrol card, which has none —
  // the same rule `priorityReason` follows on the line above, and the reason
  // it is a rule: an empty "Done when:" is worse than no line at all.
  if (card.story) {
    paragraphs.push(`Story: ${card.story}`);
  }
  if (card.doneWhen) {
    paragraphs.push(`Done when: ${card.doneWhen}`);
  }
  if (card.blockedBy?.length) {
    paragraphs.push(
      `Blocked by: ${card.blockedBy.join(', ')} — finish those first, or say why ` +
        'this can go ahead without them.',
    );
  }
  // Advisory, and said as advice. One line, both halves together: a model
  // named without an effort reads as a whole answer and is half of one.
  if (card.agentModel) {
    const effort = card.agentEffort ? `, ${card.agentEffort} effort` : '';
    paragraphs.push(`Suggested for this card: ${card.agentModel}${effort}.`);
  }
  paragraphs.push(
    'Work this test-first: write a failing test for the stated reason before ' +
      'any fix, then make it pass. Do not skip the red step.',
    // `kanban-patrol/08`. This agent is about to run workflows to reproduce
    // the defect, and every one of those runs lands in the same store the
    // patrol reads — unmarked, they come back as fresh findings and the
    // board files a card about the work done on this one. The reason is on
    // the line because an instruction with no reason is the first thing an
    // agent drops.
    `Any run you make while working this card must name this card as its ` +
      `sitting, or the next patrol reads it back as a new problem:\n` +
      `  openstategraph run <package> "<question>" --session-id card:${card.id}\n` +
      `(over MCP, pass session_id: "card:${card.id}" to run_workflow.)`,
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
