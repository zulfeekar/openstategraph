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
    lines: 981,
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
      writing one more field of the same frame.

      **914 -> 922** (\`memory-and-replay/53\` and \`/55\`). Two branches on the
      same \`onEvent\` chain this module already owns. \`started\` calls the
      \`remember\` this file already had — every other call to it sits on a
      terminal path, so a run that dropped halfway took the conversation with
      it — and \`invoked\` moves the glow exactly as the \`progress\` branch
      three lines below it does, for the reason written there: it is one of the
      frames that arrive while a node is still working. Neither adds a reason to
      change; both are the transcript seam this entry has been asking somebody
      to take.

      **922 -> 905** (\`memory-and-replay/51\`), and this is the first time the
      number has gone *down*. The two run views left: the trace tree and the
      bars, the two-tab switch between them, and the Export button that belongs
      with the trace all moved to the run dock, which is a sibling of the whole
      stage rather than a section of a 300px chat column. What replaced them is
      six lines publishing the newest turn into \`runView\`.

      Seventeen lines is not the point and would not be worth a paragraph. What
      is worth one is that a **reason to change** came out with them: this entry
      has listed "the run's live state" among the things this module composes
      since it was written, and drawing a run is no longer one of them. The
      transcript seam it keeps asking somebody to take is still the next one,
      and it is now the only structural one left.

      **905 -> 907** (\`memory-and-replay/61\`). Two fields on the \`runView\`
      publish that 51 left behind: the thread the run reported, and what it
      spent. Both were already on this turn's \`result\` and neither had a reader
      anywhere in \`src/\` — the publish is the same effect handing on two more
      of a record it already holds, and the reason to change stays the one 51
      removed: this module is still not the thing that draws a run.

      Then **907 -> 920** (\`the-cost-of-one-more/20\`). Thirteen lines that make an
      arriving frame *queue* rather than commit: a buffer, a flush scheduled on
      the next animation frame with a timer behind it, and one line at the top
      of \`onEvent\` draining it before any event that is not an append. It
      bought a factor of **227** on a two-thousand-frame burst — 128.6 s of
      blocked main thread down to 0.57 s — and it is the reason ten and twenty
      thousand frames finish at all.

      No new reason to change, and this is the case worth stating rather than
      asserting: the queue is not a seventh thing this module composes, it is
      the same \`onEvent\` chain deciding *when* to write the state it already
      wrote. Both append branches got shorter; the length is in the paragraph
      explaining why an unpaced burst coalesces into one commit and a paced run
      does not, which is exactly the kind of line this ceiling does not charge
      for elsewhere and charges for here because a component's prose is code
      lines away from its JSX. The transcript seam is still the next one.

      **946 -> 964** (\`every-workflow-green/45\`). A second streamed-text
      buffer and the region that renders it: a reply a grader has still to
      judge, marked as one and unselectable, above the block that holds the
      settled stream. Eighteen lines, thirteen of them the region itself. The
      *rule* for when it shows is not among them — that is
      \`draftNotice.ts\`, beside the sentence it shows, for the reason
      \`settledThinking.ts\` was extracted: what goes wrong in a rule like this
      is invisible from the panel.

      **920 -> 946** (\`memory-and-replay/66\`). Two frames the stream has
      carried since \`55\` and this reader threw away: an \`invoked\` frame is a
      tool call's ask, a \`token\` frame with \`kind: 'tool'\` is its answer, and
      the wire's own contract says to pair them on \`callId\`. Nobody did, so
      the chart could not draw a tool call at all and the strip counted seven
      of something a reader had nowhere to click. Both branches already existed
      here and already read those frames; what is added is a \`queueRow\` in
      each, which is this module's one job — turn a frame into a row. No new
      reason to change, and the transcript seam is still the next one.

      **964 -> 969** (\`stable-beta-public/08\`) has no row of its own, and that
      is recorded rather than quietly absorbed into the next one: the number
      was bumped for the \`showsSteps\` import and the two-line \`hasPills\`
      fold, the resolution says so, and the row that should have said it here
      was not written. A number moved without its argument is the exact failure
      this table exists to prevent, so it is named where the next reader will
      look.

      **969 -> 973** (\`stable-beta-public/10\`). Four lines: the \`senderLabel\`
      import, and a \`.ask__reply\` wrapper carrying one \`.ask__sender\`
      paragraph around everything the workflow said back. The *rule* for what
      that label reads is not among them — it is \`senderLabel.ts\`, beside its
      own test, for the reason \`draftNotice.ts\` and \`settledThinking.ts\`
      were extracted. No new reason to change: this module already composed
      every block inside that wrapper, and the wrapper only says which side of
      a conversation they are on. The transcript seam is still the next one.

      **973 -> 977** (\`stable-beta-public/12\`). The composer moved out of
      \`PanelBody\` into \`PanelFooter\` so it stops inheriting the padded
      body's own left/right inset — a footer import, a longer opening tag
      (\`PanelFooter\` with two props instead of a bare \`<div>\`), and a
      four-line comment on the move recording the measured before-numbers and
      why \`PanelFooter\`'s own padding did not fit. No new reason to change:
      this is the same composer, moved one level up the tree. The transcript
      seam is still the next one.

      **977 -> 981** (\`stable-beta-public/15\`). Prettier's reformatting of two
      \`<RichText>\` tags that gained one class name: the answer bubble and the
      approval candidate now carry \`rich-text--narrow\`, so a table in a 187px
      bubble stacks instead of scrolling off the side. Four lines, no new
      behaviour and no new reason to change — the decision itself is CSS, in
      \`view/common/RichText.css\`, and which surfaces are narrow is the only
      part of it this module knows. The transcript seam is still the next one.`,
  },
  'core/runtime/RuntimeClient.ts': {
    lines: 900,
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
      making it.

      **649 -> 700** (\`memory-and-replay/53\`, \`/55\`, \`/56\`), and this is the
      entry's own argument arriving as a bill. Two frame kinds joined the
      published vocabulary — \`started\` and \`invoked\` — and \`usage\` joined the
      three terminal shapes; almost all fifty-one lines are **declared members
      of the union and their documentation**, which is precisely the practice
      the paragraph above says this measure charges for. The behaviour added is
      two \`else if\` branches in \`consumeFrame\` and one \`asRunUsage\` reader,
      and the physical count moved by more than the code count, which is the
      shape this number exists to distinguish from behaviour arriving.

      **700 -> 715** (\`the-cost-of-one-more/13\`). \`PastRunTruncation\` and its
      four documented members, plus an \`asTruncation\` reader of the same shape
      as \`asTokens\` beside it and one line in \`pastRun\`. The same bill again,
      and this time the entry's argument is load-bearing in the other direction
      too: the field existed on the wire, was documented, was published, and
      was mirrored by nobody for a day — so these fifteen lines are the
      practice working rather than the file drifting.

      **715 -> 717** (\`the-cost-of-one-more/14\`). \`ProviderStatus.defaultModel\`
      and its coercion in \`providers\` — the model a run gets when it names
      none, published on every provider row since the endpoint existed and read
      by nothing. One declared member and one line in a mapper, which is this
      entry's cheapest possible bill and the shape it exists to permit.

      **717 -> 723** (\`the-cost-of-one-more/16\`). \`RuntimeHealth\`, which is
      what \`health()\` used to return as an inline object literal in two
      places. Four of the six lines are the interface and its two members; the
      other two are the coercion that keeps \`editor_stale\` three-valued
      through the mirror, and they are the whole point of the ticket — the
      obvious \`=== true\` beside \`model_configured\` would have answered
      \`false\` for the wheel's \`null\` and made a claim the server declined to
      make. Declared members and a two-line reader: the same bill this entry
      has taken four times and the same shape.
      Then **728 -> 730** (\`every-workflow-green/45\`). \`draft\` on the
      \`token\` frame — whether a grader downstream has still to judge this
      reply. Two lines: the field and its parse. It is compiler knowledge and
      cannot be derived here, because the reply often streams from inside a
      mounted document judged by a grader no client has heard of.

      **730 -> 747** (\`kanban-patrol/19\`). \`kanbanCards()\` and the
      \`KanbanCardRow\` interface it returns — the board's read door onto
      \`GET /api/kanban/cards\`, same shape as \`providers()\` beside it: a thin
      method, a declared row type mirroring the wire, an \`Err\` on an
      unreachable backend rather than a false empty list. Seventeen lines,
      and the same bill this entry has taken every time: a declared member
      per wire field, and one line of actual behaviour.

      **747 -> 748** (\`kanban-patrol/25\`). One declared member,
      \`priority_reason\`, on \`KanbanCardRow\` — the plain-English why a
      classifier gave a card its priority, mirrored from the same route.

      **748 -> 760** (\`kanban-patrol/27\`). \`runPatrol()\` and the
      \`PatrolRunResult\` interface it returns — the door the board's own
      "Run Patrol" button now calls, replacing a placeholder toast. Same
      shape as every method beside it: a thin POST, a declared response
      type, an \`Err\` that reads the server's own \`detail\` message rather
      than inventing one.

      **760 -> 764** (\`kanban-patrol/17\`+\`21\`). Four declared members on
      \`KanbanCardRow\` — \`evidence_test_id\`, \`evidence_red_reason\`,
      \`evidence_green\`, \`evidence_commit\` — the evidence gate's own fields,
      mirrored from the same route. The same bill this entry has taken
      every time a field joins that response: one line per member, no new
      behaviour.

      Then **723 -> 728** (\`the-cost-of-one-more/17\`). \`PastRun.pause\` — what a
      parked run is waiting to be told — plus \`asPausePayload\`, a four-line
      reader beside \`asTokens\` and \`asTruncation\`. Same shape as the two
      bills above and the same argument: one declared member, one line in a
      mapper, and a guard that refuses an array because \`Object.entries\` would
      otherwise render one as numeric keys at a person. No behaviour — the
      judgement about what the payload *says* is \`pastRunView.pauseLines\`,
      which is where the rules in this seam belong.

      **764 -> 811** (\`kanban-patrol/07\`). The patrol became durable: three
      declared response shapes (\`PatrolStartedResult\`, \`PatrolStatus\`,
      \`PatrolStreamEvent\` — replacing \`PatrolRunResult\`, one member net
      gain) and two methods, \`patrolStatus()\` and \`watchPatrolEvents()\`.
      The first is \`kanbanCards()\`'s own shape, one GET and a coercion per
      field; the second is \`watchCatalogue()\`'s own shape, copied rather
      than re-derived — one \`EventSource\` subscription, one
      \`addEventListener\`, a parse that survives a bad frame. Both bills are
      the ones this entry has already argued for: declared members mirroring
      a wire shape, and a thin method wrapping one browser API this codebase
      already uses exactly once elsewhere. The constructor also grew an
      injected \`eventSourceImpl\`, the same seam \`WorkflowFileClient\`
      already carries, for the same reason: Vitest's node environment has no
      \`EventSource\`.

      **811 -> 821** (\`kanban-patrol/19\`). \`releaseCard()\`, the human's
      explicit press on a card the system has already flagged stale — a
      thin POST, same shape as \`runPatrol()\` beside it: one method, one
      \`fetch\`, an \`Err\` reading the backend's own \`detail\` on a refusal
      (the card was not actually stale) rather than inventing a second
      failure shape. Ten lines, no declared response type needed at all —
      the door answers \`{"ok": true}\` on success and nothing this class
      reads beyond the boolean \`Result\` already carries.

      **881 -> 895** (\`kanban-patrol/15\`, 2026-09-04). \`answerCard()\` and
      three declared members on \`KanbanCardRow\` — \`answer\`,
      \`answered_by\`, \`answered_at\`, the decision recorded on a Needs You
      card. Fourteen lines and the same bill this entry has taken every
      time: one line per mirrored wire field, and one method that is
      \`releaseCard()\`'s own shape — a POST, a JSON body, an \`Err\` reading
      the backend's own \`detail\` rather than a second failure shape
      invented here.

      **895 -> 900** (\`osg-agent-experience/25\`). Five declared members on
      \`KanbanCardRow\` — the brief a card filed from a conversation carries
      (\`story\`, \`done_when\`, \`blocked_by\`) and the model and effort to give a
      subagent that takes it. Five lines, no method and no behaviour at all:
      exactly the bill this entry's argument describes, one line per mirrored
      wire field, and the physical count moved by three times as much because
      each carries its documentation.

      **900 -> 909** (\`osg-agent-experience/36\`). \`KanbanStreamEvent\` — one
      declared member — and \`watchKanbanEvents\`, the fourth SSE door this
      client opens: an \`addEventListener\` for one event name, one field read,
      and a returned unsubscribe, the same nine lines of shape
      \`watchPatrolEvents\` beside it already has. Not a new kind of
      responsibility: the backend grew a stream because a card moved by
      another process was invisible until somebody pressed Refresh, and this
      is the client's one thin method per door.

      **909 -> 900** (\`osg-agent-experience/71\`), and it is the rarer
      direction: the file **shrank** because two doors stopped being doors.
      \`watchPatrolEvents\` and \`watchKanbanEvents\` no longer open sockets —
      they ask \`LiveEventStream\` for a subject on the one connection a tab
      holds — so the \`EventSource\` wiring, the \`addEventListener\` and the
      unsubscribe that closed a connection came out and a two-line delegation
      went in. Nothing was mirrored away: \`KanbanStreamEvent\` and
      \`PatrolStreamEvent\` are still parsed field for field here, which is what
      \`contractDrift.test.ts\` reads. Nine lines is what a browser's
      six-connections-per-origin budget cost this file, recorded rather than
      quietly pocketed.`,
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
