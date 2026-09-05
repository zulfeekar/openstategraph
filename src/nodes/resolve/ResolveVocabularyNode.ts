import { Err, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { ExecutionContext, INodeExecutor, PortOutputs } from '@core/execution/INodeExecutor';
import { CATEGORY, PORT } from '../vocabulary';

export const RESOLVE_VOCABULARY_TYPE = 'resolve.vocabulary';

export const FIELD_SOURCE = 'source';
export const FIELD_MAX_ENTRIES = 'maxEntries';
export const FIELD_WHEN_UNCOVERED = 'whenUncovered';

/** Mirrors `openstategraph.vocabulary.DEFAULT_MAX_ENTRIES`. */
export const DEFAULT_MAX_ENTRIES = 12;

/** Mirrors `openstategraph.vocabulary.DEFAULT_WHEN_UNCOVERED`. */
export const DEFAULT_WHEN_UNCOVERED =
  'Nothing in this vocabulary names the term. Say which axis you chose and that ' +
  'nothing declared it, rather than treating the term as unambiguous.';

export class ResolveVocabularyNodeModel extends AbstractNodeModel {
  /** The package function this node searches, named as `function.<name>` names it. */
  get source(): string {
    return this.getText(FIELD_SOURCE);
  }

  override get subtitle(): string {
    const source = this.source.trim();
    return source ? `looks up: ${source}` : 'No vocabulary source named yet.';
  }
}

/**
 * *What is this word called here?* — answered before the model, every run.
 *
 * `launch-readiness/135`. This capability shipped first as one package's
 * private function, wired by hand-editing `workflow.json`: it could not be
 * placed on a canvas, configured, or seen. Lifting it into a node type is the
 * platform's own rule rather than a new idea — *extend by registering, never
 * by editing the engine* — and `core/` is untouched by it.
 *
 * ## Why this is a step and not a tool
 *
 * **Vocabulary must not be a choice.** When the model picked which source
 * told it what "persian gulf" meant, it picked differently on every run — one
 * correct answer, one refusal built on an invented 81-port country set, one
 * correct refusal, from the same question. A resolver is a *step*, and steps
 * run; a tool is *picked*. Method — *how do I query this domain?* — is the
 * opposite case and stays on the tools bus, where choosing is the point.
 *
 * ## Vocabulary only, deliberately
 *
 * Measured on 2026-08-27: the index behind the original function described 10
 * tables against the 38 its domain's lenses name, an overlap of three. Its
 * glossary rows are a different kind of fact — *"users may say: MEG, Middle
 * East Gulf, Arabian Gulf, Persian Gulf"* — true regardless of which store
 * holds the rows, which is why they port where a table description does not.
 * So this node resolves words. Table discovery stays a tool.
 *
 * ## The field that is not a nicety
 *
 * **A prefetch that finds nothing looks exactly like a term that is not
 * ambiguous.** That is the shape behind six defects on this map, and it is
 * why the node reports what it *covered* and not only what it found — a
 * source that declares its inventory yields a conclusive *not covered*, one
 * that does not yields *silence here proves nothing*, and a failed search is
 * neither. `whenUncovered` is the sentence the run carries downstream in the
 * first two cases; it is a default worth editing, never a switch that turns
 * the coverage report off.
 *
 * Compiles to `compile/node_runtime.py`'s `_resolve_vocabulary`, which does
 * the searching concurrently and merges by rank — never by arrival
 * (`launch-readiness/130`, where the deciding entry reached the model only
 * when its search won a thread race).
 */
export const resolveVocabularyNode: INodeDefinition = defineNode(
  {
    id: RESOLVE_VOCABULARY_TYPE,
    category: CATEGORY.resolve,
    label: 'Resolve vocabulary',
    description:
      'Looks up what the question’s words mean in this domain before the model runs, and ' +
      'reports what it covered as well as what it found. No model call.',
    iconId: 'node-format-report',
    accent: 'green',
    keywords: [
      'resolve',
      'vocabulary',
      'glossary',
      'synonym',
      'alias',
      'term',
      'prefetch',
      'lookup',
      'canonical',
    ],
    defaultSize: { width: 276, height: 200 },
    fields: [
      {
        kind: 'text',
        key: FIELD_SOURCE,
        label: 'Source',
        placeholder: 'glossary_index',
        hint:
          'The package function this node searches, named the way `function.<name>` names ' +
          'it. It is called as `fn(phrase)`, once per derived phrase, concurrently, and ' +
          'returns the entries ' +
          'it holds for that phrase. Give it a `coverage` attribute and this node can say ' +
          'a term is genuinely uncovered instead of merely unmatched.',
        defaultValue: '',
        required: true,
        onCard: true,
      },
      {
        kind: 'slider',
        key: FIELD_MAX_ENTRIES,
        label: 'Entries kept',
        hint:
          'How many entries survive to the model after ranking. The ranking always runs ' +
          'first — the cap never decides which axis the model sees.',
        defaultValue: DEFAULT_MAX_ENTRIES,
        min: 1,
        max: 24,
        step: 1,
        onCard: false,
        format: (value) => `· ${value} ${value === 1 ? 'entry' : 'entries'}`,
      },
      {
        kind: 'textarea',
        key: FIELD_WHEN_UNCOVERED,
        label: 'When nothing is covered',
        hint:
          'Carried downstream when the lookup covered nothing. The coverage report itself ' +
          'is not optional: silence would read exactly like a term that is not ambiguous, ' +
          'which is the defect this node exists to close.',
        defaultValue: DEFAULT_WHEN_UNCOVERED,
        minRows: 3,
        maxRows: 8,
        onCard: false,
      },
    ],
    ports: [
      {
        id: 'question',
        direction: 'in',
        type: PORT.result,
        label: 'question',
        required: true,
        // One link: the resolver reads one upstream node's text, so a second
        // edge would be a coin toss rather than a fan-in.
        maxConnections: 1,
        description: 'The question whose words are resolved.',
      },
      {
        id: 'result',
        direction: 'out',
        type: PORT.result,
        label: 'result',
        maxConnections: null,
        description: 'The question, plus what this vocabulary named and what it covered.',
      },
    ],
  },
  ResolveVocabularyNodeModel,
);

/**
 * Browser-preview executor — refuses, like the Guard's and the Grader's.
 *
 * The lookup runs in the Python runtime against a package function. A
 * `standard` node with no registered executor is silently skipped, and a run
 * where no vocabulary was consulted must never look like a run where it was.
 */
export const resolveVocabularyExecutor: INodeExecutor = {
  id: RESOLVE_VOCABULARY_TYPE,
  execute(ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
    ctx.log('The lookup runs in the Python runtime, not the browser preview.');
    return Promise.resolve(
      Err(
        'This resolver calls a package function in the Python runtime. Use “Run” against ' +
          'the backend to see what it resolves.',
      ),
    );
  },
};
