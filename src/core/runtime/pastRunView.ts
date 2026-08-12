import type { PastRun, PastRunStep } from './RuntimeClient';

/**
 * How a past run reads on screen.
 *
 * Pure, and in `core/` rather than beside the component, for the reason every
 * other formatter here is: this is the part with rules — what counts as
 * identity, when a stamp is unreadable, which channels a person looks for
 * first — and rules deserve tests that need no DOM. The component is left
 * with markup.
 *
 * Nothing here re-executes anything. Every field was written while the run
 * happened; this module only chooses words for it.
 */

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/**
 * `2026-08-11T11:40:00Z` → `20 min ago`.
 *
 * An unparseable stamp is returned **verbatim**, never as "Invalid Date" and
 * never as a guess: the backend reads `ts` straight out of a checkpoint, and a
 * saver that writes some other format should show what it wrote rather than
 * have this function pretend to understand it.
 */
export function relativeTime(iso: string, now: number): string {
  if (!iso) return '';
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return iso;
  // Clamped at zero: a checkpoint stamped slightly ahead of this browser's
  // clock is skew, and "in 30 seconds" for something that already happened
  // reads as a bug in the history rather than in the clock.
  const age = Math.max(0, now - at);
  if (age < MINUTE) return 'just now';
  if (age < HOUR) return `${Math.floor(age / MINUTE)} min ago`;
  if (age < DAY) return `${Math.floor(age / HOUR)} h ago`;
  return `${Math.floor(age / DAY)} d ago`;
}

export interface RunDescription {
  readonly title: string;
  /** Who asked, when the run recorded it — empty when it recorded nobody. */
  readonly identity: string;
  readonly meta: string;
  readonly statusLabel: string;
}

export function describeRun(run: PastRun, now: number): RunDescription {
  const parts = [run.userEmail.trim(), run.sessionId.trim()].filter(Boolean);
  const when = relativeTime(run.updatedAt, now);
  const steps = `${run.steps} ${run.steps === 1 ? 'step' : 'steps'}`;
  return {
    title: run.question.trim() || '(no question recorded)',
    identity: parts.join(' · '),
    meta: when ? `${steps} · ${when}` : steps,
    // "waiting for you" rather than "paused": paused describes the server,
    // and the only thing a reader can act on is that it wants an answer.
    statusLabel: run.status === 'paused' ? 'waiting for you' : 'finished',
  };
}

/**
 * The channels a reader scans for first, in the order they scan for them.
 * Everything else follows alphabetically, exactly as the backend sorted it —
 * so an unknown channel from a future node type still appears, just later.
 */
const LEADING = ['question', 'answer', 'outputs', 'feedback', 'decisions'] as const;

/**
 * A channel that carries nothing, however it was serialised.
 *
 * `{}` and `[]` are what an untouched dict or list channel renders as, and a
 * graph has several: `outputs`, `decisions`, `subtasks`, `worker_results`.
 * Printing them makes a checkpoint eight lines of punctuation with the one
 * line that changed buried inside it.
 */
const BLANK = new Set(['', '{}', '[]']);

export function stepLines(step: PastRunStep): readonly { key: string; value: string }[] {
  const rank = (key: string) => {
    const index = LEADING.indexOf(key as (typeof LEADING)[number]);
    return index === -1 ? LEADING.length : index;
  };
  return Object.entries(step.values)
    .filter(([, value]) => !BLANK.has(value.trim()))
    .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b))
    .map(([key, value]) => ({ key, value }));
}

/**
 * `Step 3 · loop`.
 *
 * LangGraph numbers the checkpoint written before the first superstep `-1`;
 * calling that "Step -1" would invite the reader to work out what a negative
 * superstep is, when the answer is simply "the question, before anything ran".
 */
export function stepTitle(step: PastRunStep): string {
  const head = step.step < 0 ? 'Input' : `Step ${step.step}`;
  return step.source ? `${head} · ${step.source}` : head;
}
