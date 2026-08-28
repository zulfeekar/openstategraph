import { Err, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { ExecutionContext, INodeExecutor, PortOutputs } from '@core/execution/INodeExecutor';
import { CATEGORY, PORT } from '../vocabulary';

export const RESOLVE_SOURCE_TYPE = 'resolve.source';

export const FIELD_CATALOGUE = 'catalogue';
export const FIELD_QUANTITY = 'quantity';
export const FIELD_WHEN_UNDECIDED = 'whenUndecided';

/** Mirrors `openstategraph.sources.DEFAULT_WHEN_UNDECIDED`. */
export const DEFAULT_WHEN_UNDECIDED =
  'More than one system of record can answer this and none is declared the default. ' +
  'Say which ones are live and ask which is meant, rather than choosing one and ' +
  'presenting its figures as the figures.';

export class ResolveSourceNodeModel extends AbstractNodeModel {
  /** The package function this node asks, named as `function.<name>` names it. */
  get catalogue(): string {
    return this.getText(FIELD_CATALOGUE);
  }

  override get subtitle(): string {
    const catalogue = this.catalogue.trim();
    return catalogue ? `asks: ${catalogue}` : 'No source catalogue named yet.';
  }
}

/**
 * *Which store is answering this, and what else could have?* — before the model.
 *
 * `launch-readiness/150`, and the sibling of `resolve.vocabulary`
 * (`launch-readiness/135`). Vocabulary answers *what does this word mean
 * here*; this answers *which of the several stores that could answer this is
 * answering it*. Both are deterministic, both run before the model, and both
 * record what they did on the run's own rail.
 *
 * ## The complaint it exists for
 *
 * > *"the AI should state the assumptions on which source (or BAV) is being
 * > used, and guide the user to the fact that there are multiple sources… In
 * > the may number 1664 is given in the table. I do not understand where this
 * > number comes from."*
 *
 * Three of seven complaints in one round of user feedback were this failure,
 * and none of them was missing data: the balance lens carries a provider
 * dimension, and the outage store holds the quantity at several grains from
 * several systems of record — so two figures that disagree may both be right.
 * The defect is that the answer named neither.
 *
 * ## Why this is a step and not a tool, and not a prompt
 *
 * A source the model picks is a source that changes between runs, which is
 * the measurement that made `resolve.vocabulary` a step. And it is not a
 * sentence in a preamble: six prompt-level rules have been declined on this
 * project, and the live package's prompt already carries a rule of exactly
 * this shape that six runs ignored. The declaration is a node's output; the
 * disclosure is rendered by the run.
 *
 * ## The field that is not a nicety
 *
 * **A catalogue that declares no provider dimension and a catalogue with
 * exactly one source must not look the same.** One means *there is nothing to
 * choose*; the other means *we could not tell*. The node distinguishes five
 * such states by construction and offers no switch that turns the report off.
 *
 * ## Where it stops
 *
 * Several live sources and nothing settling which is `guardrails/06`'s
 * abstain — *a router that cannot tell should ask, not guess* — which is open
 * and unbuilt. So this node records **no** choice there, carries
 * `whenUndecided` downstream, and leaves that seam rather than inventing a
 * second way to ask. Nothing here routes: a resolver decides nothing.
 *
 * Compiles to `compile/node_runtime.py`'s `_resolve_source`.
 */
export const resolveSourceNode: INodeDefinition = defineNode(
  {
    id: RESOLVE_SOURCE_TYPE,
    category: CATEGORY.resolve,
    label: 'Resolve source',
    description:
      'Names which of the stores that could answer this question is answering it, before ' +
      'the model picks, and lists the alternatives it did not take. No model call.',
    iconId: 'node-format-report',
    accent: 'green',
    keywords: [
      'resolve',
      'source',
      'provider',
      'system of record',
      'lineage',
      'provenance',
      'alternatives',
      'default',
      'catalogue',
    ],
    defaultSize: { width: 276, height: 200 },
    fields: [
      {
        kind: 'text',
        key: FIELD_CATALOGUE,
        label: 'Catalogue',
        placeholder: 'balance_sources',
        hint:
          'The package function this node asks, named the way `function.<name>` names it. ' +
          'It is called once with the question and returns the systems of record that could ' +
          'answer it — a name is enough, and a row that marks itself the default settles ' +
          'which one is used.',
        defaultValue: '',
        required: true,
        onCard: true,
      },
      {
        kind: 'text',
        key: FIELD_QUANTITY,
        label: 'Figures',
        placeholder: 'Russian gasoline supply',
        hint:
          'What the figures are, in your words. “Which source?” is only answerable about ' +
          'something — the same warehouse answers supply from one system of record and ' +
          'outages from another — and this is the phrase the disclosure names.',
        defaultValue: '',
        onCard: false,
      },
      {
        kind: 'textarea',
        key: FIELD_WHEN_UNDECIDED,
        label: 'When nothing settles it',
        hint:
          'Carried downstream when several systems of record are live and none is named or ' +
          'default. The coverage report itself is not optional: a figure with no stated ' +
          'source reads exactly like a figure from the wrong one, which is the defect this ' +
          'node exists to close.',
        defaultValue: DEFAULT_WHEN_UNDECIDED,
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
        // One link: the step reads one upstream node's text, so a second edge
        // would be a coin toss rather than a fan-in.
        maxConnections: 1,
        description: 'The question whose system of record is settled.',
      },
      {
        id: 'result',
        direction: 'out',
        type: PORT.result,
        label: 'result',
        maxConnections: null,
        description: 'The question, plus which store answers it and which ones did not.',
      },
    ],
  },
  ResolveSourceNodeModel,
);

/**
 * Browser-preview executor — refuses, like the vocabulary resolver's.
 *
 * The catalogue is a package function in the Python runtime. A `standard`
 * node with no registered executor is silently skipped, and a run where no
 * catalogue was consulted must never look like a run where it was.
 */
export const resolveSourceExecutor: INodeExecutor = {
  id: RESOLVE_SOURCE_TYPE,
  execute(ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
    ctx.log('The catalogue is asked in the Python runtime, not the browser preview.');
    return Promise.resolve(
      Err(
        'This resolver calls a package function in the Python runtime. Use “Run” against ' +
          'the backend to see which source it settles on.',
      ),
    );
  },
};
