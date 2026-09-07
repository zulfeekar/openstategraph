/**
 * The compiled Mermaid text, re-dressed for a 252px card.
 *
 * The backend hands back exactly what `draw_mermaid()` produced (ticket 54) —
 * sized for the full-screen `GraphPreview`, where a 14px label and generous
 * node padding read well. Dropped into a card body that same text renders a
 * diagram three times the card's width, and scaling the SVG down far enough to
 * fit turns every label into a grey smear.
 *
 * So the peek asks Mermaid to lay the graph out *small* rather than shrinking
 * a large one: a top-down flow (a card is tall and narrow, never wide), a
 * caption-sized font, tight padding. That is an `%%{init: ...}%%` directive,
 * which is part of the diagram source rather than a render option — hence a
 * pure text transform, testable without a browser.
 *
 * It is deliberately additive and idempotent-by-refusal: if the compiler ever
 * starts emitting its own front-matter or init directive, that is the
 * document's own intent and this leaves it alone rather than fighting it with
 * a second directive whose precedence is undefined.
 */

/** Layout hints for a card-sized peek. Kept here so the numbers are reviewable. */
const PEEK_INIT =
  '%%{init: {"theme":"neutral","flowchart":{"htmlLabels":false,"nodeSpacing":18,"rankSpacing":22,"padding":4},"themeVariables":{"fontSize":"9px"}} }%%';

/**
 * Prefix a compiled diagram with the peek's layout directive.
 *
 * Returns the text unchanged when it is empty, already carries an `%%{init}%%`
 * directive, or opens with YAML front-matter (`---`), since both of those are
 * the source's own configuration and must win.
 */
export function peekMermaid(text: string): string {
  const trimmed = text.trim();
  if (!trimmed) return trimmed;
  if (trimmed.startsWith('%%{')) return trimmed;
  if (trimmed.startsWith('---')) return trimmed;
  return `${PEEK_INIT}\n${trimmed}`;
}

/**
 * A stable DOM id for one peek render.
 *
 * Mermaid injects a `<style>` scoped to the id it is given and leaves a
 * temporary element behind under it, so two cards rendering the same slug with
 * the same id would collide — and a `Date.now()` id (what the full-screen
 * preview can afford, rendering once) would leak a new style block on every
 * re-render of a card that re-renders on every drag.
 */
export function peekDiagramId(slug: string, sequence: number): string {
  return `peek-${slug.replace(/[^a-zA-Z0-9_-]/g, '-')}-${sequence}`;
}
