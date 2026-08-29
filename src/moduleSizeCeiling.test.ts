import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';

/**
 * CLAUDE.md's module ceiling, on the TypeScript side.
 *
 * `backend/tests/test_module_size_ceiling.py` is the sibling and carries the
 * long argument: why length is measured at all, why in **code lines** rather
 * than physical ones, and why the recorded number is a ratchet rather than a
 * target. It is not repeated here. What matters on this side is that the rule
 * runs on both — `AskPanel.tsx` is the `src/` counterpart of
 * `node_runtime.py`, it has no split ticket at all, and a module measure
 * enforced in one language would be a third description of a rule that already
 * has two.
 *
 * The ceiling is 500 on both sides for the same reason the class ceiling is ten
 * on both sides: a rule with two numbers is two rules. It is the looser of the
 * two here — the median module under `src/` is 56 code lines against 101 in the
 * Python package, so 500 is nine medians rather than five — and that is
 * recorded rather than tuned away, because the honest cost of one number is
 * that it binds harder wherever files are smaller. At 400 this census would
 * name five modules instead of two; the next person who thinks the TypeScript
 * side is under-measured should reach for that number, not for a second rule.
 */
const CEILING = 500;

const SRC = fileURLToPath(new URL('.', import.meta.url));

/**
 * Physical lines carrying a token that is not a comment.
 *
 * Comments and JSDoc are trivia in the TypeScript AST rather than nodes, so
 * they fall out for free — which is the property the Python sibling has to work
 * for by subtracting docstrings, and the property that makes this measure safe
 * to apply to a repository that writes its reasoning down at length.
 *
 * A string literal *is* a node, so a multi-line prompt is charged for. Same
 * deliberate asymmetry as the Python side: prose about the code is free, content
 * inside it is not.
 */
export function codeLines(fileName: string, text: string): number {
  const source = ts.createSourceFile(fileName, text, ts.ScriptTarget.Latest, true);
  const lines = new Set<number>();
  const walk = (node: ts.Node): void => {
    if (node.getChildCount(source) === 0 && node.kind !== ts.SyntaxKind.EndOfFileToken) {
      // Whitespace-only JSX text is a leaf node and is not code.
      if (node.getText(source).trim() !== '') {
        const from = source.getLineAndCharacterOfPosition(node.getStart(source)).line;
        const to = source.getLineAndCharacterOfPosition(node.getEnd()).line;
        for (let line = from; line <= to; line += 1) lines.add(line);
      }
    }
    node.forEachChild(walk);
  };
  source.forEachChild(walk);
  return lines.size;
}

/**
 * Every module under `src/` longer than the ceiling — derived, never listed.
 *
 * Tests, specs and declaration files are skipped for the same reason the class
 * census skips them: they are not the app, and a test is allowed to be as long
 * as the argument it is making.
 */
function modulesOverTheCeiling(): Map<string, number> {
  const over = new Map<string, number>();
  for (const entry of readdirSync(SRC, { recursive: true, encoding: 'utf8' })) {
    const relative = entry.split('\\').join('/');
    if (!/\.tsx?$/.test(relative) || /\.(test|spec)\.tsx?$/.test(relative)) continue;
    if (relative.endsWith('.d.ts')) continue;
    const measured = codeLines(relative, readFileSync(SRC + relative, 'utf8'));
    if (measured > CEILING) over.set(relative, measured);
  }
  return over;
}

interface Recorded {
  /** Exact, in both directions. The number is a tripwire, not a goal. */
  readonly lines: number;
  /** What makes the number a decision rather than a file nobody has opened. */
  readonly reason: string;
}

const RECORDED: Readonly<Record<string, Recorded>> = {
  'view/ask/AskPanel.tsx': {
    lines: 914,
    reason: `The largest module under \`src/\` and the one the ticket named: the counterpart
      of \`node_runtime.py\` with no split ticket behind it at all. Eight hundred and
      eighty-nine code lines out of 2,237 physical — the rest is JSX structure, imports and
      the comments this repository writes on purpose.

      It is one surface with more than one reason to change, and the reasons are
      nameable, which is what makes this entry a debt rather than a decision. It
      composes the question box, the transcript, the run's live state, the
      grader verdict line, the spawned-node pills, the attempts line and the
      history drawer; several of those already have their own modules beside it
      (\`settledThinking\`, \`attemptsLine\`, \`doorHeadline\`,
      \`graderVerdictLine\`, \`moduleBrief\`, \`revealAdded\`), which is the
      evidence that the extraction pattern works here and simply has not been
      run far enough.

      The seam to take next is the transcript: it owns the message list, its
      scroll anchoring and the reveal of newly added nodes, and it reads none of
      the composer's state. That is a component, not a helper — which is why it
      has not happened yet, and why it is written down here instead of implied.
      Recorded at 908 so the next four hundred lines land as a red test.

      **908 -> 914** (\`memory-and-replay/50\`). The \`settled\` handler's
      one-line row update became a six-line object literal, because a closed
      spawn row now carries \`settledMs\` as well as \`outcome\` — the other end
      of a child lane's bar. No new reason to change: it is the same handler
      writing one more field of the same frame.`,
  },
  'core/runtime/RuntimeClient.ts': {
    lines: 649,
    reason: `The clearest case in either census of a long file that is not a design
      failure, and the reason this measure needs a recorded-exception mechanism
      rather than a bare number. Six hundred code lines against 1,682 physical,
      and the bulk of them are **type declarations**: CLAUDE.md records that this
      file "mirrors twelve types by hand" against Pydantic's published contract,
      deliberately, with \`docs/decisions/typescript-runtime-types.md\` carrying
      the argument for why a generator was rejected.

      Declared interface members are the cheapest lines in the repository to
      read and the most valuable to have — each one is a field of the run/stream
      seam, documented at its own declaration, pinned to \`docs/openapi.json\` by
      a drift test rather than by codegen. A measure that treats them like
      control flow is charging for exactly the practice CLAUDE.md asked for, and
      this entry says so rather than letting the number imply otherwise.

      The class behind them is thin on purpose — "the reason this class is so
      thin is that keeping it thin is the point": it posts a document and a
      question and receives an answer, builds no graph, executes nothing, stores
      no credentials. Splitting the type block into a \`runtimeContract.ts\`
      beside it is the available move and it buys a smaller file rather than a
      clearer one, since every consumer imports the types and the client
      together. The number is here to catch *behaviour* arriving, which would
      look like the code-line count moving without the physical count moving
      much.

      **647 -> 649** (\`the-boundary-nobody-checked/02\`). \`pastRun\` builds its
      query through \`URLSearchParams\` and names \`audience=developer\`, because
      \`GET /api/threads/{id}\` now defaults to a customer's view of a stored
      run. Two lines, and no behaviour: it is the same request, saying who is
      making it.`,
  },
};

describe('the module ceiling', () => {
  it('records every module over it, and only those', () => {
    const census = modulesOverTheCeiling();
    const recorded = new Set(Object.keys(RECORDED));

    const unrecorded = [...census].filter(([name]) => !recorded.has(name));
    const departed = [...recorded].filter((name) => !census.has(name));

    expect(
      unrecorded,
      `over the module ceiling and not recorded.\n` +
        `A module over ${CEILING} code lines is not automatically a defect, and this is ` +
        'not a request to delete anything. It is a request to say which of two things it is.\n' +
        '  - It has more than one reason to change: extract the second one into its own ' +
        'module beside it, the way settledThinking/attemptsLine/doorHeadline came out of ' +
        'AskPanel — or register the capability rather than editing the engine.\n' +
        '  - It is one thing that is genuinely this long: add it to RECORDED with the ' +
        'argument that makes the number a decision, naming the seam you considered and ' +
        'why it does not pay.\n' +
        'Raising CEILING is neither of those, and it is the move this file exists to make ' +
        'somebody argue for in public.',
    ).toEqual([]);

    expect(
      departed,
      'recorded but no longer over the ceiling — good news, delete the entry and its reasoning with it',
    ).toEqual([]);
  });

  it.each(Object.entries(RECORDED))('%s is exactly the length recorded for it', (name, entry) => {
    const census = modulesOverTheCeiling();

    expect(
      census.get(name),
      `${name} is ${census.get(name)} code lines, recorded as ${entry.lines}. ` +
        'Exact, not an upper bound: an exception with room to spare is how a ceiling ' +
        'becomes a floor. If it grew, ask whether what you added is this module\u2019s one ' +
        'reason to change; if it shrank, re-record the smaller number and say what came out.',
    ).toBe(entry.lines);
  });

  it.each(Object.entries(RECORDED))('%s carries a written reason', (_name, entry) => {
    // Length is a crude proxy for "somebody actually thought about this", and a
    // crude proxy beats none. Same threshold as both class censuses.
    expect(entry.reason.trim().length).toBeGreaterThan(400);
  });
});

describe('the measure measures what it claims', () => {
  it('does not charge for comments or JSDoc', () => {
    const source = '/**\n * One.\n *\n * Two.\n */\n// three\nexport const x = 1;\n';
    expect(codeLines('a.ts', source)).toBe(1);
  });

  it('charges for a string that is content rather than commentary', () => {
    expect(codeLines('a.ts', 'export const p = `One.\nTwo.\nThree.`;\n')).toBe(3);
  });

  it('sees JSX, which a statement count would not', () => {
    // The reason lines-of-code beat AST statements here: AskPanel's bulk is one
    // expression inside one `return`.
    const jsx =
      'export const V = () => (\n  <div>\n    <span>a</span>\n    <span>b</span>\n  </div>\n);\n';
    expect(codeLines('a.tsx', jsx)).toBeGreaterThan(4);
  });

  it('charges one for one added line of code', () => {
    const before = readFileSync(SRC + 'core/runtime/RuntimeClient.ts', 'utf8');
    expect(codeLines('RuntimeClient.ts', `${before}\nexport const sentinel = 1;\n`)).toBe(
      codeLines('RuntimeClient.ts', before) + 1,
    );
  });
});
