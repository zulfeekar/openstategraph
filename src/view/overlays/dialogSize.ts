/**
 * How wide a `Dialog` is — `kanban-patrol/06`.
 *
 * A plain module rather than a `clsx(...)` expression inside `Dialog.tsx`,
 * because the thing worth pinning is a **decision** (the default does not
 * move) and the suite runs in `node` on purpose (`vite.config.ts`). A pure
 * function can be executed; a JSX line can only be read back as text, and a
 * rule about text is a rule about whatever prettier last did to it.
 */

/**
 * The two sizes, in the order they were added.
 *
 * `default` is `min(520px, 100%)` — the width `CredentialsDialog`,
 * `McpServersDialog`, `ArrivalDialog`, `AccessibilityCheck` and
 * `KnowledgeBody` were all laid out against. `large` is 90% of the viewport in
 * both dimensions, which is the board's requirement and nobody else's.
 */
export const DIALOG_SIZES = ['default', 'large'] as const;

export type DialogSize = (typeof DIALOG_SIZES)[number];

/**
 * The panel's class list.
 *
 * The default adds **nothing**, which is what makes it the default: an
 * existing caller renders the same single class it rendered before this
 * variant existed, so there is no cascade to re-check and no width to
 * re-measure. `aDialogSizeIsOptInOnly.test.ts` is the ratchet.
 */
export function dialogClassName(size: DialogSize): string {
  return size === 'default' ? 'dialog' : `dialog dialog--${size}`;
}
