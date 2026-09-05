import { Err, Ok, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { ExecutionContext, INodeExecutor, PortOutputs } from '@core/execution/INodeExecutor';
import type { ProviderRegistry } from '@core/providers/ProviderRegistry';
import { CATEGORY, PORT } from '../vocabulary';

export const FORMAT_REPORT_TYPE = 'function.format_report';

const FIELD_REPORT_TITLE = 'reportTitle';
const DEFAULT_TITLE = 'Report';

export class FormatReportNodeModel extends AbstractNodeModel {
  /**
   * The report's Markdown heading. Named distinctly from the base class's
   * `title` (the card's own display title) — the two are unrelated
   * concepts that happen to share an obvious English word.
   */
  get reportTitle(): string {
    const value = this.getText(FIELD_REPORT_TITLE).trim();
    return value === '' ? DEFAULT_TITLE : value;
  }
}

/**
 * A **function**, not a tool: a deterministic graph step the compiler always
 * runs, with no model in the decision. Introduced alongside the Orchestrator
 * to keep "function" and "tool" as separate node types rather than one type
 * with a flag — `share_of_total`/`format_report` are functions,
 * `execute_sql` is a tool, and they must not be conflatable in the palette.
 *
 * Joins an orchestrator's worker results into one Markdown report, scoped to
 * the *current* plan's subtask ids only — a real bug (`backend/openstategraph`'s
 * `_format_report_function`) found that without this scoping, a revise loop's
 * replan silently blended a rejected attempt's stale results back in under
 * `worker_results`, since ids from every generation share one dict.
 *
 * Deterministic and side-effect-free, so unlike Router/Grader/Orchestrator/
 * Worker this one genuinely can run in the browser preview — it needs no
 * model and no LangGraph runtime, only whatever the mock provider already
 * produced upstream.
 */
/**
 * Deliberately has **no** model picker, unlike every other node in this
 * directory. Format Report is a *function* node: it joins worker results in
 * task-id order with no LLM call and therefore no variance, which is what
 * makes its output assertable byte-for-byte. Offering a model here would be
 * a control that changes nothing — the contract test
 * `test_no_node_offers_a_picker_the_compiler_ignores` refuses exactly that,
 * and refused this when it was added by reflex.
 *
 * It still takes the registry so the whole orchestrate family is built one
 * way; that costs nothing and keeps the registration site uniform.
 */
export function createFormatReportNode(_providers: ProviderRegistry): INodeDefinition {
  return defineNode(
    {
      id: FORMAT_REPORT_TYPE,
      category: CATEGORY.agent,
      label: 'Format Report',
      description: 'Joins worker results into one Markdown report.',
      iconId: 'node-format-report',
      accent: 'green',
      keywords: ['report', 'join', 'format', 'synthesize', 'function', 'markdown'],
      defaultSize: { width: 260, height: 180 },
      fields: [
        {
          kind: 'text',
          key: FIELD_REPORT_TITLE,
          label: 'Report title',
          placeholder: DEFAULT_TITLE,
          defaultValue: '',
          onCard: false,
        },
      ],
      ports: [
        {
          id: 'candidate',
          direction: 'in',
          type: PORT.result,
          label: 'candidate',
          required: true,
          // A bus since ticket 37: every worker archetype's `result` wires in,
          // and the join runs once after the fan-out's superstep completes.
          //
          // **`null` was measured against the runtime and kept**
          // (`osg-agent-experience/43`, which asked whether it should say 1).
          // These edges *sequence* the join; the value comes from
          // `worker_results` in graph state, so the number of them is the
          // number of workers and capping it at one would refuse the fan-out
          // this node exists for. `maxConnections` was never what could have
          // refused the fifteen guards that ticket found wired in here —
          // `sourceMustDeclare` below is, and it is asked by the canvas and
          // not yet by `validate`.
          maxConnections: null,
          // …and a bus for workers ONLY (production-ready ticket 31). These
          // edges sequence the join; they do not carry it. The compiled step
          // reads `worker_results`, which only a `Send`-dispatched worker
          // writes, so an agent wired here validated, compiled to a plain
          // `add_edge` and produced `_No results._` — the documented
          // "intuitive" parallelization shape that never worked
          // (`docs/patterns.md` §4). The capacity rule could not catch it
          // (three edges are legal) and neither could the type rule (a
          // worker's `result` and an agent's `result` are one type), so the
          // port states the requirement the runtime actually has.
          //
          // This is a refusal, not a fan-in: static fan-in is still unbuilt
          // (`production-ready/31`, open). Narrowed since, and the narrowing
          // is the part a reader needs: `_format_report_function` falls back
          // to the upstream `outputs` of every **static** `plan.edges` edge
          // into this node (`every-workflow-green/27`), so a plain fan-in is
          // partly served. A source whose edge compiles to a *conditional*
          // one — a guard's `pass`, a grader's `pass`, an approval's
          // `approved` — is not in `plan.edges` at all, so it arrives as
          // nothing and the join reports "No results". `_discovered_function`
          // reads `plan.conditional` for exactly that reason
          // (`launch-readiness/66`); this builder was left out of it.
          sourceMustDeclare: {
            portType: PORT.worker,
            refusal:
              'Format Report joins the worker_results a supervisor’s fan-out writes to graph ' +
              'state — its edges only sequence it, they carry nothing. Wire an Orchestrator ' +
              '→ Worker → this join; an agent wired straight in reports “No results”.',
          },
          description: 'Worker results to join into the report.',
        },
        {
          id: 'report',
          direction: 'out',
          type: PORT.result,
          label: 'report',
          description: 'The assembled Markdown report.',
        },
      ],
    },
    FormatReportNodeModel,
  );
}

/**
 * Runs for real in the browser preview.
 *
 * The compiled Python step scopes its join to the current generation's
 * subtask ids (`state["subtasks"]`), which the browser preview has no
 * equivalent of — there is no orchestrator generation here, only whatever
 * arrived on `candidate`. So this executor renders exactly what it is given,
 * which is the honest preview behaviour: it demonstrates the formatting, not
 * the fan-out/join semantics that only the compiled graph has.
 *
 * That difference used to be reachable, and a docstring is not a guard
 * (production-ready ticket 31): an agent wired into `candidate` rendered a
 * convincing joined document here and produced `_No results._` when compiled.
 * The port's `sourceMustDeclare` now makes that edge undrawable, so the only
 * source this executor can receive from is a worker — whose own preview
 * executor refuses, exactly as the fan-out it stands for cannot run in a
 * browser. The approximation is still an approximation; it is no longer one a
 * user can walk into.
 */
export const formatReportExecutor: INodeExecutor = {
  id: FORMAT_REPORT_TYPE,
  execute(ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
    const node = ctx.node as FormatReportNodeModel;
    const incoming = ctx.input<unknown>('candidate');

    if (incoming == null || incoming === '') {
      return Promise.resolve(Err('Nothing arrived on the candidate port'));
    }

    const body = typeof incoming === 'string' ? incoming : JSON.stringify(incoming, null, 2);
    const report = `# ${node.reportTitle}\n\n${body}`;
    ctx.log(`Formatted a ${report.length}-character report titled "${node.reportTitle}"`);
    return Promise.resolve(Ok({ report }));
  },
};
