import { Err, Ok, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import type {
  ExecutionContext,
  INodeExecutor,
  PortOutputs,
} from '@core/execution/INodeExecutor';
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
 * the *current* plan's subtask ids only — a real bug (`backend/dyflow`'s
 * `_format_report_function`) found that without this scoping, a revise loop's
 * replan silently blended a rejected attempt's stale results back in under
 * `worker_results`, since ids from every generation share one dict.
 *
 * Deterministic and side-effect-free, so unlike Router/Grader/Orchestrator/
 * Worker this one genuinely can run in the browser preview — it needs no
 * model and no LangGraph runtime, only whatever the mock provider already
 * produced upstream.
 */
export const formatReportNode: INodeDefinition = defineNode(
  {
    id: FORMAT_REPORT_TYPE,
    category: CATEGORY.output,
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

/**
 * Runs for real in the browser preview.
 *
 * The compiled Python step scopes its join to the current generation's
 * subtask ids (`state["subtasks"]`), which the browser preview has no
 * equivalent of — there is no orchestrator generation here, only whatever
 * arrived on `candidate`. So this executor renders exactly what it is given,
 * which is the honest preview behaviour: it demonstrates the formatting, not
 * the fan-out/join semantics that only the compiled graph has.
 */
export const formatReportExecutor: INodeExecutor = {
  id: formatReportNode.id,
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
