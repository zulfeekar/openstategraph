import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * consistency-sweep ticket 10 — *"subgraph" is not a word this product says.*
 *
 * CLAUDE.md's portability rule 4 is "do not leak LangGraph type names into
 * `workflow.json` or into `core/`", and the settled lexicon gives the user
 * **mount**, **instance** and **workflow node**. The word had reached four
 * surfaces anyway: the self-mount refusal (twice in one sentence), the
 * drill-in breadcrumb, the compiled-graph preview's hint, and a run
 * timeline's lane tooltip.
 *
 * It was also *false*. This compiler emits no LangGraph subgraph — a mount is
 * a closure over the child's `invoke()` (production-ready 37) — so the preview
 * promising "subgraphs expanded" described something that never happens.
 *
 * **What this does and does not forbid.** `workflow.subgraph` stays: it is the
 * node **type id**, it is in every shipped `workflow.json`, and renaming it is
 * a migration this ticket declined (`docs/decisions/mount-type-name.md`). So
 * are the wire enum `kind: 'subgraph'` and the identifiers built from them.
 * What is forbidden is the word inside a **string a person reads** — which is
 * exactly what a scan of quoted text can see and a grep for the bare word
 * cannot.
 */
const HERE = fileURLToPath(new URL('.', import.meta.url));

/** Text inside single quotes, double quotes or backticks. */
const LITERALS =
  /'([^'\\\n]*(?:\\.[^'\\\n]*)*)'|"([^"\\\n]*(?:\\.[^"\\\n]*)*)"|`([^`\\]*(?:\\.[^`\\]*)*)`/g;

/**
 * The identifiers this is *not* about. A literal is exempt when the word is
 * part of one of these rather than part of a sentence.
 */
const NOT_PROSE = [
  'workflow.subgraph', // the node type id — kept, with a recorded decision
  'subgraphExecutor',
  'node-subgraph', // an icon name
  'SubgraphNode',
  'subgraph-', // a minted node id in a fixture
];

function sourceFiles(directory: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) found.push(...sourceFiles(path));
    else if (/\.tsx?$/.test(entry.name) && !entry.name.includes('.test.')) found.push(path);
  }
  return found;
}

/**
 * Comments out, code in.
 *
 * This file is *about* the word, and so are the docstrings recording why each
 * surface stopped using it — `compositionSummary.ts` quotes the old union
 * `CompositionKind = 'team' | 'subgraph'` to say what it replaced. A guard
 * that forbade explaining the history would be a guard that deletes its own
 * reasons.
 */
function code(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|\s)\/\/[^\n]*/g, '$1');
}

function offendingLiterals(path: string): string[] {
  const source = code(readFileSync(path, 'utf8'));
  const offences: string[] = [];
  for (const match of source.matchAll(LITERALS)) {
    const text = match[1] ?? match[2] ?? match[3] ?? '';
    if (!/subgraph/i.test(text)) continue;
    if (NOT_PROSE.some((allowed) => text.includes(allowed))) continue;
    // A one-word literal is an identifier, a key or an enum member, not a
    // sentence. The defect is the word inside prose.
    if (!/\s/.test(text.trim())) continue;
    offences.push(`${path}: ${text.trim()}`);
  }
  return offences;
}

describe('the word a user never reads', () => {
  it('says "mount", never "subgraph", in every string the view renders', () => {
    const offences = sourceFiles(join(HERE)).flatMap(offendingLiterals);

    expect(offences, `"subgraph" reached a user-facing string:\n${offences.join('\n')}`).toEqual(
      [],
    );
  });

  it('says "mount" in the sentences core/ hands the view', () => {
    // `mountCycleRule` lives in core and its output is rendered verbatim by
    // three surfaces — the mount field, the palette row and its hover text —
    // so core is where this leak was widest.
    const offences = sourceFiles(join(HERE, '..', 'core')).flatMap(offendingLiterals);

    expect(offences, `"subgraph" reached a user-facing string:\n${offences.join('\n')}`).toEqual(
      [],
    );
  });
});
