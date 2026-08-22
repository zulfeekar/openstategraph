/**
 * The editor's approval card and `/chat`'s approval box say the same sentence.
 *
 * `production-ready` 94. One judgement — the grader's verdict on a candidate
 * waiting for a person — reaches a reviewer through two doors, and until this
 * ticket the second door was a hand-written ternary in `chat.html` restating
 * the same four rules in JavaScript with no test of its own. `production-ready`
 * 92 added one clause and had to edit both files; the tripwire it left behind
 * (`TestEveryDoorSaysTheSameThing`) greps for a shared substring, and its
 * author said plainly that this is not a fix.
 *
 * It was not. Measured before the fix, the two spellings **had already
 * drifted**, on every input carrying surrounding whitespace:
 *
 * | `verdict` | `reason` | editor | `/chat` |
 * | --- | --- | --- | --- |
 * | `'   '` | `'x'` | *(nothing)* | `x` |
 * | `'pass'` | `'   '` | `The grader passed this.` | `The grader passed this —` + spaces |
 * | `'revise'` | `'  hedge  '` | trimmed | untrimmed |
 * | `' pass '` | `'ok'` | the pass sentence | the bare reason |
 *
 * The substring tripwire was green through all four.
 *
 * `chat.html` imports no bundled TypeScript on purpose, so the sentence is now
 * *generated* into it by `scripts/render_grader_verdict_line.py` — the same
 * relationship `docs/openapi.json` has with Pydantic. This test is the half a
 * byte-for-byte drift gate cannot do: it takes the JavaScript that the browser
 * actually runs, out of the page as shipped, and runs it beside the TypeScript
 * module over one table of cases. Editing one spelling and not the other turns
 * it red, and so does a generation nobody re-ran.
 */
import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { graderVerdictLine, type GraderApproval } from './graderVerdictLine';

const PAGE = new URL('../../../backend/openstategraph/api/static/chat.html', import.meta.url);

/** The generated function, lifted out of the page and made callable. */
function shippedInChatPage(): (approval: GraderApproval) => string {
  const page = readFileSync(PAGE, 'utf-8');
  const begin = page.indexOf('// GENERATED-BEGIN graderVerdictLine');
  const end = page.indexOf('// GENERATED-END graderVerdictLine');
  expect(begin, 'chat.html carries no generated block').toBeGreaterThan(-1);
  expect(end).toBeGreaterThan(begin);
  const source = page.slice(begin, end);
  expect(source).toContain('function graderVerdictLine(approval) {');
  // eslint-disable-next-line @typescript-eslint/no-implied-eval
  return new Function(`${source}\nreturn graderVerdictLine;`)() as (a: GraderApproval) => string;
}

/**
 * Every case the two doors could disagree on, including the four that they
 * actually did. Whitespace variants are not padding: the reason is a model's
 * own sentence and the verdict is parsed out of a model's reply, so leading
 * and trailing space is the ordinary case rather than the exotic one.
 */
const CASES: readonly GraderApproval[] = [
  { verdict: '', reason: '' },
  { verdict: '   ', reason: 'x' },
  { verdict: 'pass', reason: 'It commits to a date, with no hedging.' },
  { verdict: 'pass', reason: '' },
  { verdict: 'pass', reason: '   ' },
  { verdict: 'pass', reason: 'No reason given' },
  { verdict: ' pass ', reason: 'ok' },
  { verdict: 'revise', reason: "'if appropriate' is a hedge." },
  { verdict: 'revise', reason: '  hedge  ' },
  { verdict: 'revise', reason: '' },
  { verdict: 'revise', reason: 'The answer is empty.', check: 'empty' },
  { verdict: 'revise', reason: '', check: 'empty' },
  { verdict: 'revise', reason: 'Error: connection refused', check: 'error' },
  { verdict: 'pass', reason: 'The step budget ran out.', check: '' },
  { verdict: 'sideways', reason: ' something else happened ' },
  { verdict: 'sideways', reason: '' },
];

describe('the grader’s sentence has one spelling', () => {
  const inTheChatPage = shippedInChatPage();

  it.each(CASES)('reads the same on both doors: %o', (approval) => {
    expect(inTheChatPage(approval)).toBe(graderVerdictLine(approval));
  });

  it('is a table with something in it for every branch of the rules', () => {
    // Guards the test against itself: a table that lost its revise cases
    // would still pass every assertion above and check nothing.
    const rendered = CASES.map((c) => graderVerdictLine(c));
    expect(rendered).toContain('');
    expect(rendered.some((line) => line.startsWith('The grader passed this'))).toBe(true);
    expect(rendered.some((line) => line.includes('asked for a revision without a model call'))).toBe(
      true,
    );
    expect(rendered.some((line) => line === 'something else happened')).toBe(true);
  });
});
