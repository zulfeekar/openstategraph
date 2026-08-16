import { Err, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { ExecutionContext, INodeExecutor, PortOutputs } from '@core/execution/INodeExecutor';
import { CATEGORY, PORT } from '../vocabulary';
import { OVERRIDES_FIELD } from './overridesField';
import { workflowCatalogue } from '@core/runtime/workflowCatalogue';
import { mountAncestry } from '@core/runtime/mountAncestry';
import { mountCycleRefusal } from '@core/validation/mountCycleRule';

export const SUBGRAPH_TYPE = 'workflow.subgraph';

const FIELD_WORKFLOW = 'workflow';
const FIELD_OUTCOME = 'outcome';

/**
 * Another workflow, run as one node of this one — ticket 34.
 *
 * This is the composition mechanism CLAUDE.md's vocabulary promises
 * ("workflow composition = subgraphs"): the backend compiles the referenced
 * workflow's own document and invokes it with an explicit state mapping —
 * this node's input text becomes the child's question, and only the child's
 * final answer flows back out. The child never sees this workflow's other
 * state, mirroring the subagent-isolation rule: it receives a task and
 * reports a result.
 *
 * The reference is the child's **slug** — data, never code — so the document
 * stays serialisable and vendor-neutral. Because the slug is all the card
 * would otherwise show, a registered card body
 * (`view/nodes/CompositionBody`) annotates it with a census of the
 * referenced document — node-type counts in the palette's own vocabulary,
 * derived by the pure `summarizeComposition`. That census says "loops until
 * its grader passes" when — and only when — the child's own grader routes
 * `revise`, so the claim is earned from the document rather than asserted by
 * the card. A workflow that (transitively) includes itself is refused by the
 * compiler at build time with the chain spelled out.
 *
 * **This is the only mount.** `team.workflow` was a second node type that
 * compiled through this very builder with no branch and identical ports; what
 * made it look different was a glyph, an `outcome` field that turned out to be
 * documentation, and that same earned census note. None of those is a kind of
 * node, so schema v3 collapsed it into this one — a Team was a Workflow whose
 * mounted document happens to contain a revision loop (production-ready
 * ticket 16). `MIGRATIONS[2]` rewrites the old id.
 */
export class SubgraphNodeModel extends AbstractNodeModel {
  /** The referenced workflow's slug, e.g. `chinook-assistant`. */
  get workflowSlug(): string {
    return this.getText(FIELD_WORKFLOW);
  }
}

export const subgraphNode: INodeDefinition = defineNode(
  {
    id: SUBGRAPH_TYPE,
    category: CATEGORY.compose,
    label: 'Workflow',
    // Isolation is the thing a reader cannot guess and the thing that decides
    // whether this is the right node: the child sees a task and reports a
    // result, never this graph's state, messages or tools. "Runs another
    // workflow as a single step" said none of that (ticket 02).
    description:
      'Another workflow, run as one isolated step — task in, answer out. It brings its own state, tools and knowledge, and by reference: change the original and every mount of it changes.',
    iconId: 'node-subgraph',
    accent: 'violet',
    keywords: ['subgraph', 'workflow', 'compose', 'nest', 'call', 'reuse'],
    defaultSize: { width: 252, height: 150 },
    fields: [
      {
        // A combobox, not a text box and not a listbox (ticket 05). It was
        // free text: nothing populated it, nothing validated it, and nothing
        // told a developer what existed — so a typo produced a mount that
        // resolved to nothing, and the catalogue was discoverable only by
        // already knowing it.
        //
        // Not a listbox, decided rather than defaulted: mounting a package you
        // have not built yet is a real way to work — sketch the parent, then
        // go and build the child — and a listbox outlaws that order. The
        // suggestions keep a typo off the *normal* path, which is what was
        // asked for.
        kind: 'combobox',
        key: FIELD_WORKFLOW,
        label: 'Workflow slug',
        placeholder: 'e.g. chinook-assistant',
        defaultValue: '',
        mono: true,
        emptyHint: 'No saved workflows yet — save one, and it appears here.',
        // A package already above this document says so **in the list**, before
        // it is picked, rather than only after — ticket 42's "unavailable
        // rather than merely punished", in the only form a native `<datalist>`
        // can carry: a suffix on the label.
        //
        // Not `disabled`. The flag exists on `FieldOption` and `select` honours
        // it, but a datalist is a *suggestion* source — a disabled option is
        // dropped from the suggestions, not greyed in them — so marking the
        // ancestor disabled would delete the one entry a reader is looking for
        // and say nothing about why. Greying a gesture needs a surface that can
        // grey: that is the Packages palette (ticket 11, landed), where the row
        // renders greyed and non-draggable carrying this same refusal. It asks
        // `mountCycleRefusal` with `mountAncestry()` through
        // `view/palette/packageRows.ts` rather than comparing slugs again, so
        // the two surfaces cannot drift.
        // Which store answers this field's question, so the control redraws
        // when a package is saved or deleted. Declared here rather than
        // hardcoded in `FieldRenderer`, which is what let a second live
        // combobox exist at all (mcp-connect ticket 07).
        subscribe: (notify: () => void) => workflowCatalogue.onChange(notify),
        options: () => {
          const above = new Set(mountAncestry());
          return workflowCatalogue.list().map((choice) => ({
            value: choice.slug,
            label: above.has(choice.slug)
              ? `${choice.name} · ${choice.slug} — would include itself`
              : `${choice.name} · ${choice.slug}`,
          }));
        },
        // Refused at **pick time**, in the compiler's own sentence — ticket 42.
        // The server refuses self-inclusion twice already (`_subgraph`'s
        // ancestry chain, `mount_resolution`'s visited chain) and stays the
        // authority; this only reports the same verdict before a save rather
        // than after a failed compile. Declared on the schema rather than in a
        // panel so the card and the inspector both get it from one place —
        // and it is the ancestry, not just this slug, because drilling in means
        // the cycle you would create need not involve the document on screen.
        validate: (value: string) => mountCycleRefusal(value, mountAncestry()),
      },
      {
        kind: 'textarea',
        key: FIELD_OUTCOME,
        label: 'Expected outcome (documentation)',
        // Inherited from the collapsed `team.workflow`, and kept precisely so
        // its migration would not have to destroy prose a person wrote.
        //
        // It does not reach the compiler, and the copy says so: enforcement
        // is a property of the *child package's* grader criteria, not of this
        // mount. Claiming otherwise was ticket 03's defect — a surface
        // presenting a machine-owned promise as configuration.
        placeholder: 'What this workflow is expected to deliver, in your words.',
        minRows: 3,
        maxRows: 8,
        hint: 'Shown on the card so a reader knows what this mount is for. It does not constrain the run — enforcement lives in the mounted workflow’s own grader criteria, and the card says so when that grader is missing or never revises.',
        defaultValue: '',
        onCard: true,
      },
      OVERRIDES_FIELD,
    ],
    ports: [
      {
        id: 'input',
        direction: 'in',
        type: PORT.result,
        label: 'input',
        required: true,
        description: 'Becomes the child workflow’s question.',
      },
      {
        id: 'result',
        direction: 'out',
        type: PORT.result,
        label: 'result',
        description: 'The child workflow’s final answer.',
      },
    ],
  },
  SubgraphNodeModel,
);

/**
 * Refuses honestly in the browser preview: a child workflow's tools and
 * models live behind the backend, and pretending to run it here would
 * produce exactly the plausible-but-empty result this codebase treats as
 * worse than an error. Same stance as Orchestrator/Worker.
 */
export const subgraphExecutor: INodeExecutor = {
  id: SUBGRAPH_TYPE,

  async execute(ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
    const node = ctx.node as SubgraphNodeModel;
    const target = node.workflowSlug.trim() || '(none selected)';
    return Err(
      `The Workflow node runs "${target}" on the backend — use Chat to execute this graph.`,
    );
  },
};
