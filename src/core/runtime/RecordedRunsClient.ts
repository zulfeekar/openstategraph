import { Err, Ok, type Result } from '@core/kernel/Result';
import { describeFailure, type FetchLike, type RunUsage } from './RuntimeClient';
import { describeRuntimeBase, runtimeBaseUrl } from './runtimeBaseUrl';

/**
 * The local run store, read over HTTP — `memory-and-replay` 72.
 *
 * ## Why this is not `RuntimeClient.pastRuns`
 *
 * `pastRuns` reads `GET /api/threads`, which is the **checkpointer**: what
 * supersteps a run took, under whose identity, and which are paused. This
 * reads `GET /api/runs/recorded`, which is `runs.sqlite`: how a run's output
 * actually *arrived*, burst by burst, on the server's own clock.
 *
 * Only the second can drive a playhead, and that is the whole reason for a
 * second door rather than a widened first one. `52`'s transport moves between
 * offsets somebody measured, `47` is the ticket that measured them, and the
 * checkpointer has none of them — a superstep row says a node finished, never
 * when its first token left the model.
 *
 * ## Reads only, and structurally so
 *
 * Every method here is a `GET` against a store. Opening a recording calls no
 * model, opens no stream and touches no checkpoint — the lexicon's *replay*,
 * which is a profiler, and never its *re-run*, which is not built.
 *
 * ## A separate class, for the reason `McpRegistryClient` is one
 *
 * `RuntimeClient` is at the public-surface ceiling and its subject is a run
 * *in flight*. Two `GET`s onto a store is a second subject with a second
 * reason to change, and the pin in `contractDrift.test.ts` names this file so
 * the paths it builds are held to the published contract exactly as that
 * class's are.
 */

/** One contiguous burst of a stored run's output — `RecordedBurst` on the wire. */
export interface RecordedBurst {
  /**
   * The graph node whose output this is — inside an agent, LangGraph's own
   * `model` or `tools`, not the canvas node.
   */
  readonly node: string;
  /**
   * The canvas node the run said was working. `''` is *this recording did not
   * say* — a run stored before `memory-and-replay` 74 — and a bar built from
   * one of those falls back to `node`, which is the only name it has.
   */
  readonly activeNode: string;
  readonly namespace: readonly string[];
  /** `text` or `reasoning`. Two blocks are never one burst. */
  readonly block: string;
  /** Who produced it — `model`, `tool`. */
  readonly kind: string;
  /** The customer channel refused the text; the burst is kept so the stall shows. */
  readonly withheld: boolean;
  /** The server's own `elapsedMs` at the first and last chunk. **Measured.** */
  readonly firstMs: number;
  readonly lastMs: number;
  readonly chunks: number;
  readonly chars: number;
  readonly text: string;
  /** The recording ends here — not the run. */
  readonly capped: boolean;
}

/** One turn out of the store — `RecordedRun` on the wire. */
export interface RecordedRun {
  readonly at: string;
  readonly workflowSlug: string;
  readonly threadId: string;
  /**
   * The browser tab it was asked from. `''` is *this run had no sitting* — the
   * MCP and CLI doors mint none — never *one was lost*, which is why nothing
   * downstream may substitute the thread's name for it.
   */
  readonly sessionId: string;
  readonly question: string;
  readonly answer: string;
  readonly seconds: number;
  readonly attempts: number;
  readonly failed: boolean;
  /**
   * What it spent, one row per model — the same three answers `runCost`
   * already reads: a list is what it spent, `[]` is *no model was called*, and
   * `null` is *this reader was not told*, which is what a customer always is.
   */
  readonly usage: readonly RunUsage[] | null;
  /** Empty on a listing, which does not pay for it, and empty on a refusal. */
  readonly bursts: readonly RecordedBurst[];
}

export class RecordedRunsClient {
  constructor(
    private readonly baseUrl: string = runtimeBaseUrl(),
    private readonly fetchImpl: FetchLike = (url, init) => fetch(url, init),
  ) {}

  /**
   * Every recorded run, newest first and with no cadence attached.
   *
   * The order is the **server's**, and it is passed through untouched. It comes
   * off an index keyed on a derived UTC expression because `at` is local wall
   * clock with an offset and does not sort as text
   * (`the-cost-of-one-more/11`); re-sorting it here would put back exactly the
   * ordering that ticket removed.
   */
  async list(
    query: { workflowSlug?: string; limit?: number } = {},
  ): Promise<Result<readonly RecordedRun[], string>> {
    const params = new URLSearchParams();
    if (query.workflowSlug) params.set('workflow_slug', query.workflowSlug);
    if (query.limit != null) params.set('limit', String(query.limit));
    const suffix = params.size > 0 ? `?${params.toString()}` : '';

    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}/api/runs/recorded${suffix}`);
    } catch {
      return Err(this.unreachable());
    }
    if (!response.ok) return Err(await describeFailure(response));
    try {
      const payload = (await response.json()) as Record<string, unknown>;
      const rows = Array.isArray(payload['runs']) ? payload['runs'] : [];
      return Ok(rows.map(asRecordedRun));
    } catch {
      return Err('The runtime returned a response that was not valid JSON');
    }
  }

  /**
   * One conversation's turns, oldest first, each with its own recording.
   *
   * `audience=developer`, always, and not a parameter — the same sentence
   * `RuntimeClient.pastRun` writes and for the same reason: this client is the
   * **editor's**, and the editor is the workflow's author. The endpoint
   * defaults to `customer`, which is the right default for a door anyone may
   * build on and the wrong view for a panel whose whole content is which node
   * produced what. The server still caps it, so a deployment running as
   * `customer` answers as one whatever is asked.
   */
  async thread(threadId: string): Promise<Result<readonly RecordedRun[], string>> {
    let response: Response;
    try {
      response = await this.fetchImpl(
        `${this.baseUrl}/api/runs/recorded/${encodeURIComponent(threadId)}?audience=developer`,
      );
    } catch {
      return Err(this.unreachable());
    }
    if (!response.ok) return Err(await describeFailure(response));
    try {
      const payload = (await response.json()) as Record<string, unknown>;
      const rows = Array.isArray(payload['runs']) ? payload['runs'] : [];
      return Ok(rows.map(asRecordedRun));
    } catch {
      return Err('The runtime returned a response that was not valid JSON');
    }
  }

  private unreachable(): string {
    return `Could not reach the runtime at ${describeRuntimeBase(this.baseUrl)}. Is the backend running?`;
  }
}

/**
 * One row, read tolerantly.
 *
 * The repository's standing rule about a model's replies, applied to a
 * response: every field falls back to the shape's own default rather than
 * throwing, because a panel that refuses to list anything at all is worse to
 * meet than one row missing a number.
 */
function asRecordedRun(value: unknown): RecordedRun {
  const row = asRecord(value);
  const bursts = Array.isArray(row['bursts']) ? row['bursts'] : [];
  return {
    at: asText(row['at']),
    workflowSlug: asText(row['workflowSlug']),
    threadId: asText(row['threadId']),
    sessionId: asText(row['sessionId']),
    question: asText(row['question']),
    answer: asText(row['answer']),
    seconds: asCount(row['seconds']),
    attempts: asCount(row['attempts']),
    failed: row['failed'] === true,
    usage: Array.isArray(row['usage']) ? row['usage'].map(asUsage) : null,
    bursts: bursts.map(asRecordedBurst),
  };
}

function asRecordedBurst(value: unknown): RecordedBurst {
  const row = asRecord(value);
  const namespace = Array.isArray(row['namespace']) ? row['namespace'] : [];
  return {
    node: asText(row['node']),
    activeNode: asText(row['activeNode']),
    namespace: namespace.map(asText),
    block: asText(row['block']) || 'text',
    kind: asText(row['kind']),
    withheld: row['withheld'] === true,
    firstMs: asCount(row['firstMs']),
    lastMs: asCount(row['lastMs']),
    chunks: asCount(row['chunks']),
    chars: asCount(row['chars']),
    text: asText(row['text']),
    capped: row['capped'] === true,
  };
}

function asUsage(value: unknown): RunUsage {
  const row = asRecord(value);
  return {
    model: asText(row['model']),
    inputTokens: asCount(row['inputTokens']),
    outputTokens: asCount(row['outputTokens']),
    totalTokens: asCount(row['totalTokens']),
  };
}

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
const asText = (value: unknown): string => (typeof value === 'string' ? value : '');
const asCount = (value: unknown): number =>
  typeof value === 'number' && Number.isFinite(value) ? value : 0;
