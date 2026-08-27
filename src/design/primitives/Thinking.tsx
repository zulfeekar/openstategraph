import { useEffect, useRef } from 'react';
import clsx from 'clsx';
import './Thinking.css';

/* ------------------------------------------------------------------ *
 * Thinking — the presentation of a step talking about itself.
 *
 * `launch-readiness/140`. The owner's words for what was wrong were "not a
 * text area but a beautiful thinking": the narration frames were arriving and
 * landing in something that read as a plain textarea. The raw material worked;
 * the presentation was missing.
 *
 * One primitive, three surfaces — the agent card on the canvas, the editor
 * chat, and the customer chat — because `design/` owns tokens and primitives
 * and three implementations of one idea is exactly the duplication of
 * *knowledge* CLAUDE.md's DRY rule forbids. The two shapes it takes are a
 * prop, not a fork: `ThinkingStack` (the stacked account, 420 px, scrolls) and
 * `ThinkingLine` (the one live line).
 *
 * There is no app logic here. It is handed strings and a flag; it decides
 * nothing about which strings, whose they are, or when they stop.
 * ------------------------------------------------------------------ */

/**
 * The tallest a stack may be, in pixels — a maximum, and the scroll is the
 * point.
 *
 * The number is the owner's, and it is load-bearing rather than taste: a card
 * on the canvas measures its own height and reports it to the paper adapter,
 * so an unbounded stack would resize the node and move the canvas under
 * somebody who is mid-sentence. Exported so the rule has one home and a test
 * can assert it rather than re-typing it.
 */
export const THINKING_MAX_HEIGHT = 420;

export interface ThinkingStackProps {
  /** Oldest first — the order the work happened in. */
  readonly lines: readonly string[];
  /**
   * Whether the last line is still the present tense.
   *
   * The distinction is the whole reason a finished stack is worth keeping:
   * live, the newest line is what is happening *now* and carries the pulse;
   * settled, every line is an account of what already happened and none of
   * them should look like activity. A finished stack that kept pulsing would
   * be the `paused`-dot defect again — a surface claiming work that is over.
   */
  readonly live?: boolean;
  /** Announced to assistive technology, e.g. the node's title. */
  readonly label?: string;
  readonly className?: string;
}

/**
 * The stacked account of what a step has been doing.
 *
 * Auto-scrolls to the newest line **only while live**, and only when the
 * reader has not scrolled away — reading back through what happened must not
 * be yanked to the bottom by the next frame.
 */
export function ThinkingStack({ lines, live = false, label, className }: ThinkingStackProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const pinned = useRef(true);

  useEffect(() => {
    const el = ref.current;
    if (!el || !live || !pinned.current) return;
    el.scrollTop = el.scrollHeight;
  }, [lines, live]);

  if (lines.length === 0) return null;

  return (
    <div
      ref={ref}
      className={clsx('thinking', live && 'thinking--live', className)}
      style={{ maxHeight: THINKING_MAX_HEIGHT }}
      // `polite` rather than `assertive`: a progress account must not
      // interrupt a screen-reader mid-sentence on every frame.
      role="log"
      aria-live="polite"
      aria-label={label ? `${label} — what it is doing` : 'What it is doing'}
      onScroll={(event) => {
        const el = event.currentTarget;
        pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
      }}
      // The card is draggable and the canvas pans on wheel; both would make
      // the panel unscrollable and unreadable, which is the whole point of a
      // maximum height.
      onWheel={(event) => event.stopPropagation()}
      onPointerDown={(event) => event.stopPropagation()}
    >
      {lines.map((line, index) => (
        <p
          // Index rather than the text: the same sentence can legitimately
          // appear twice in one account (a second query, a second lookup),
          // and this list is only ever appended to.
          key={index}
          className={clsx(
            'thinking__line',
            live && index === lines.length - 1 && 'thinking__line--now',
          )}
        >
          <span className="thinking__mark" aria-hidden="true" />
          <span className="thinking__text">{line}</span>
        </p>
      ))}
    </div>
  );
}

export interface ThinkingLineProps {
  /** The one line, or nothing. Renders nothing when empty. */
  readonly text: string | null | undefined;
  readonly className?: string;
}

/**
 * One neat live line — the chat's shape of the same idea.
 *
 * A chat thread already scrolls and already carries the answer; stacking the
 * whole account into it would bury the answer under the account of getting
 * there. So the chat gets the present tense only, and the card keeps the
 * history. Same marks, same rhythm, same tokens, so the two read as one
 * system rather than two features.
 */
export function ThinkingLine({ text, className }: ThinkingLineProps) {
  if (!text) return null;
  return (
    <p className={clsx('thinking-line', className)} role="status" aria-live="polite">
      <span className="thinking__mark" aria-hidden="true" />
      <span className="thinking__text">{text}</span>
    </p>
  );
}
