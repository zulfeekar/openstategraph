import { Err, Ok, type Result } from '@core/kernel/Result';

/**
 * The editor's only route to a runtime.
 *
 * Lives in `core/` because it is framework-free: no React, no JointJS, and
 * `fetch` is injected so it runs under Vitest's node environment like everything
 * else here.
 *
 * The contract it enforces is ticket 07's: the browser **posts a document and a
 * question**, and receives an answer. It holds no provider credentials, and it
 * never builds or executes a graph — that is the backend's job, and the reason
 * this class is so thin is that keeping it thin is the point.
 */

export interface RunRequest {
  /** A `workflow.json` document, exactly as the serializer emits it. */
  readonly workflow: unknown;
  readonly question: string;
  /** Provider-prefixed, e.g. `ollama:gpt-oss:120b-cloud`. Server picks if absent. */
  readonly model?: string;
  /** Superstep budget — **not** an iteration count. */
  readonly recursionLimit?: number;
}

export interface RunResult {
  readonly answer: string;
  /** node id → branch taken, so the canvas can highlight the path that ran. */
  readonly decisions: Readonly<Record<string, string>>;
  /** node id → that node's output, for per-node inspection. */
  readonly outputs: Readonly<Record<string, string>>;
  readonly attempts: number;
  /** Mermaid text of the graph that actually compiled. */
  readonly mermaid: string;
  readonly warnings: readonly string[];
}

export interface IRuntimeClient {
  run(request: RunRequest): Promise<Result<RunResult, string>>;
  health(): Promise<Result<{ modelConfigured: boolean }, string>>;
}

/** Injected so tests need no server and no network. */
export type FetchLike = (url: string, init?: RequestInit) => Promise<Response>;

const DEFAULT_BASE = 'http://localhost:8000';

export class RuntimeClient implements IRuntimeClient {
  constructor(
    private readonly baseUrl: string = DEFAULT_BASE,
    private readonly fetchImpl: FetchLike = (url, init) => fetch(url, init),
  ) {}

  async run(request: RunRequest): Promise<Result<RunResult, string>> {
    const body = {
      workflow: request.workflow,
      question: request.question,
      ...(request.model ? { model: request.model } : {}),
      ...(request.recursionLimit != null ? { recursion_limit: request.recursionLimit } : {}),
    };

    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}/api/runs`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      });
    } catch {
      // The single most likely failure in development, so it gets the message
      // that actually helps rather than a bare "Failed to fetch".
      return Err(`Could not reach the runtime at ${this.baseUrl}. Is the backend running?`);
    }

    if (!response.ok) return Err(await describeFailure(response));

    try {
      const payload = (await response.json()) as Record<string, unknown>;
      return Ok({
        answer: asString(payload['answer']),
        decisions: asRecord(payload['decisions']),
        outputs: asRecord(payload['outputs']),
        attempts: typeof payload['attempts'] === 'number' ? payload['attempts'] : 0,
        mermaid: asString(payload['mermaid']),
        warnings: Array.isArray(payload['warnings']) ? payload['warnings'].map(asString) : [],
      });
    } catch {
      return Err('The runtime returned a response that was not valid JSON');
    }
  }

  async health(): Promise<Result<{ modelConfigured: boolean }, string>> {
    try {
      const response = await this.fetchImpl(`${this.baseUrl}/api/health`);
      if (!response.ok) return Err(`Runtime is unhealthy (${response.status})`);
      const payload = (await response.json()) as Record<string, unknown>;
      return Ok({ modelConfigured: payload['model_configured'] === true });
    } catch {
      return Err('Runtime is not reachable');
    }
  }
}

/**
 * Turns an error status into something a developer can act on.
 *
 * Each of these is a distinct, likely situation with a distinct fix, so
 * collapsing them into one message would waste the information the server sent.
 */
async function describeFailure(response: Response): Promise<string> {
  const detail = await readDetail(response);
  if (response.status === 503) {
    return detail || 'No model is configured on the runtime.';
  }
  if (response.status === 422) {
    return detail || 'The runtime rejected the workflow or question as invalid.';
  }
  if (response.status === 502) {
    if (detail === '') return 'The workflow failed while running.';
    // A provider's own 5xx is transient far more often than it is a bug in the
    // workflow — observed once from Ollama cloud on a request that succeeded on
    // the next attempt. Saying "try again" is more useful than surfacing a raw
    // `ResponseError: Internal Server Error` and implying the workflow is broken.
    if (/\b5\d\d\b|internal server error/i.test(detail)) {
      return `The model provider returned an error — this is usually transient, so try again. (${detail})`;
    }
    return detail;
  }
  return detail || `The runtime returned ${response.status}`;
}

async function readDetail(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    const detail = payload.detail;
    if (typeof detail === 'string') return detail;
    // FastAPI's 422 detail is an array of field errors; summarise rather than
    // dumping the structure into a toast.
    if (Array.isArray(detail)) {
      return detail
        .map((item) => (item as { msg?: string }).msg ?? '')
        .filter(Boolean)
        .join('; ');
    }
    return '';
  } catch {
    return '';
  }
}

const asString = (value: unknown): string => (typeof value === 'string' ? value : '');

const asRecord = (value: unknown): Record<string, string> => {
  if (typeof value !== 'object' || value === null) return {};
  const out: Record<string, string> = {};
  for (const [key, item] of Object.entries(value)) out[key] = asString(item);
  return out;
};
