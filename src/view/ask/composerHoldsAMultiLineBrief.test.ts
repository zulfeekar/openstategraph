import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { moduleBrief } from './moduleBrief';

/**
 * The composer has to be able to *hold* what the "build one" card puts in it
 * (`every-workflow-green` 40).
 *
 * `moduleBrief()` returns twelve lines joined with `\n`, and its own spec is
 * green — but the value went into a single-line `<input>`, and the HTML value
 * sanitisation algorithm strips CR and LF from an input's value. So the
 * developer got one 909-character run-on line: `provides it.What`,
 * `SlackBefore`, `logicThen`. Nothing errored and nothing reported the loss.
 *
 * That defeats the card's entire justification — *it seeds, it does not send*
 * (ticket 34). The developer is meant to **read and edit** the brief, because
 * the four questions are about their own business logic, and the five shape
 * clauses are the contract a generated module is checked against
 * (`generated_module_contract.CLAUSES`). None of that survives one line.
 *
 * ## Why this test reads the source
 *
 * The loss is in the *element type*, and vitest runs `environment: 'node'`
 * here with no jsdom, so there is no DOM in which to observe a sanitised
 * value. The pin is therefore on the source, in the same idiom as
 * `publicSurfaceCeiling.test.ts` and `lexicon.test.ts`: a control that cannot
 * hold a newline is a red test rather than something a reader notices in a
 * screenshot months later. The browser pass is what verifies the fix; this is
 * what stops it being undone.
 */
const SOURCE = readFileSync(new URL('./AskPanel.tsx', import.meta.url), 'utf8');

/** The composer's own JSX element, not another control in the same file. */
function composerElement(): string {
  const start = SOURCE.indexOf('className="ask__composer-input"');
  expect(start).toBeGreaterThan(-1);
  const open = SOURCE.lastIndexOf('<', start);
  return SOURCE.slice(open, SOURCE.indexOf('/>', start) + 2);
}

describe('the Ask composer', () => {
  it('is a multi-line control, so a seeded brief keeps its lines', () => {
    const element = composerElement();
    expect(element).toContain('<TextArea');
    // The single-line control the brief was lost in. Named, so restoring it
    // fails here rather than silently flattening the next brief.
    expect(element).not.toContain('<TextInput');
  });

  it('leaves Shift+Enter to the control, and still sends on Enter alone', () => {
    const element = composerElement();
    // Enter sends: unchanged, and the same answer `/chat`'s textarea composer
    // already ships (`api/static/chat.html`). Shift+Enter must reach the
    // textarea rather than being swallowed, which is how a newline is typed.
    expect(element).toMatch(/event\.key === 'Enter' && !event\.shiftKey/);
    expect(element).toMatch(/preventDefault\(\)/);
  });

  it('has more lines to hold than a single-line control can carry', () => {
    // Guards the premise rather than restating the fix: if the brief ever
    // becomes one line, this test should be reconsidered rather than kept
    // passing by accident.
    const brief = moduleBrief('Need tool to send messages to Slack', 'classifier-router-qa');
    expect(brief.split('\n').length).toBeGreaterThan(10);
  });
});
