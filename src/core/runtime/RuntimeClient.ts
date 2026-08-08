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
  /**
   * The open workflow's slug, when known. The backend layers that
   * workflow's own `tools/` over its defaults, so a document can bind the
   * tools that live beside it. Optional — a run without it still works.
   */
  readonly workflowSlug?: string;
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

/**
 * A run paused at a `human.approval` node instead of finishing.
 *
 * `threadId` is the only thing `resume()` needs to continue this exact run —
 * LangGraph resumes by replaying the same checkpointed thread, not by
 * resending the original request.
 */
export interface RunInterrupted {
  readonly interrupted: true;
  readonly threadId: string;
  readonly message: string;
  readonly candidate: string;
}

/** What a stream settles into: a finished run, or one waiting on a human. */
export type RunOutcome = RunResult | RunInterrupted;

export interface ResumeRequest {
  readonly threadId: string;
  readonly workflow: unknown;
  readonly decision: 'approve' | 'reject';
  readonly feedback?: string;
  readonly model?: string;
  readonly recursionLimit?: number;
  /** Same as `RunRequest.workflowSlug`: a resume must bind the same tool
   * set as the run it resumes. The backend's `ResumeRequest` declares this
   * field explicitly (it forbids unknown keys). */
  readonly workflowSlug?: string;
}

/**
 * One frame of `/api/runs/stream`'s Server-Sent-Events feed.
 *
 * `node`/`namespace`/`taskId` mirror the backend's own finding (verified
 * live against LangGraph): a `namespace` alone cannot tell two concurrently
 * `Send`-dispatched instances of the *same* worker node apart, because a
 * `Send` task shares its parent's checkpoint namespace rather than getting
 * its own — unlike an actual nested subgraph. `taskId` is what a Worker
 * node's dispatched instances carry instead, and is `null` for every other
 * node type.
 */
export type RunStreamEvent =
  | {
      readonly type: 'update';
      readonly node: string;
      readonly namespace: readonly string[];
      readonly taskId: string | null;
      /** True for steps inside a node's own compiled loop (model calls,
       * tool executions, middleware hooks) — trace-tree children, never
       * flat-feed rows. */
      readonly internal: boolean;
      readonly output: string | null;
    }
  | {
      readonly type: 'token';
      readonly node: string;
      readonly namespace: readonly string[];
      readonly content: string;
    }
  | { readonly type: 'error'; readonly detail: string };

export interface IRuntimeClient {
  run(request: RunRequest): Promise<Result<RunResult, string>>;
  /**
   * Runs the same request, but calls `onEvent` as each node acts — what lets
   * the canvas highlight whichever node is currently in charge instead of
   * only learning the outcome once the whole run has finished.
   *
   * Resolves to a `RunInterrupted` rather than a `RunResult` if the run
   * pauses at a `human.approval` node — `resume()` continues it from there.
   */
  runStream(
    request: RunRequest,
    onEvent: (event: RunStreamEvent) => void,
  ): Promise<Result<RunOutcome, string>>;
  /** Continues a paused run with a human's decision. Same outcome shape as `runStream` — a resumed run can itself pause again at a later approval node. */
  resume(
    request: ResumeRequest,
    onEvent: (event: RunStreamEvent) => void,
  ): Promise<Result<RunOutcome, string>>;
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
      ...(request.workflowSlug ? { workflow_slug: request.workflowSlug } : {}),
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

  async runStream(
    request: RunRequest,
    onEvent: (event: RunStreamEvent) => void,
  ): Promise<Result<RunOutcome, string>> {
    const body = {
      workflow: request.workflow,
      question: request.question,
      ...(request.model ? { model: request.model } : {}),
      ...(request.recursionLimit != null ? { recursion_limit: request.recursionLimit } : {}),
      ...(request.workflowSlug ? { workflow_slug: request.workflowSlug } : {}),
    };
    return this.streamFrom(`${this.baseUrl}/api/runs/stream`, body, onEvent);
  }

  async resume(
    request: ResumeRequest,
    onEvent: (event: RunStreamEvent) => void,
  ): Promise<Result<RunOutcome, string>> {
    const body = {
      thread_id: request.threadId,
      workflow: request.workflow,
      decision: request.decision,
      ...(request.feedback ? { feedback: request.feedback } : {}),
      ...(request.model ? { model: request.model } : {}),
      ...(request.recursionLimit != null ? { recursion_limit: request.recursionLimit } : {}),
      ...(request.workflowSlug ? { workflow_slug: request.workflowSlug } : {}),
    };
    return this.streamFrom(`${this.baseUrl}/api/runs/resume`, body, onEvent);
  }

  private async streamFrom(
    url: string,
    body: unknown,
    onEvent: (event: RunStreamEvent) => void,
  ): Promise<Result<RunOutcome, string>> {
    let response: Response;
    try {
      response = await this.fetchImpl(url, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      });
    } catch {
      return Err(`Could not reach the runtime at ${this.baseUrl}. Is the backend running?`);
    }

    if (!response.ok) return Err(await describeFailure(response));
    if (!response.body) return Err('The runtime did not stream a response body.');

    // SSE, not JSON: frames arrive as `event: <name>\ndata: <json>\n\n`, and
    // a frame can straddle two chunk boundaries, so this buffers text and
    // only parses complete frames (split on the blank-line terminator).
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let outcome: RunOutcome | null = null;
    let failure: string | null = null;

    const consumeFrame = (frame: string): void => {
      let eventName = '';
      let dataLine = '';
      for (const line of frame.split('\n')) {
        if (line.startsWith('event: ')) eventName = line.slice('event: '.length);
        else if (line.startsWith('data: ')) dataLine = line.slice('data: '.length);
      }
      if (eventName === '' || dataLine === '') return;

      let payload: Record<string, unknown>;
      try {
        payload = JSON.parse(dataLine) as Record<string, unknown>;
      } catch {
        return;
      }

      if (eventName === 'update') {
        onEvent({
          type: 'update',
          node: asString(payload['node']),
          namespace: Array.isArray(payload['namespace']) ? payload['namespace'].map(asString) : [],
          taskId: typeof payload['taskId'] === 'string' ? payload['taskId'] : null,
          internal: payload['internal'] === true,
          output: typeof payload['output'] === 'string' ? payload['output'] : null,
        });
      } else if (eventName === 'token') {
        onEvent({
          type: 'token',
          node: asString(payload['node']),
          namespace: Array.isArray(payload['namespace']) ? payload['namespace'].map(asString) : [],
          content: asString(payload['content']),
        });
      } else if (eventName === 'error') {
        failure = asString(payload['detail']) || 'The workflow failed while streaming.';
        onEvent({ type: 'error', detail: failure });
      } else if (eventName === 'interrupt') {
        outcome = {
          interrupted: true,
          threadId: asString(payload['threadId']),
          message: asString(payload['message']),
          candidate: asString(payload['candidate']),
        };
      } else if (eventName === 'done') {
        outcome = {
          answer: asString(payload['answer']),
          decisions: asRecord(payload['decisions']),
          outputs: asRecord(payload['outputs']),
          attempts: typeof payload['attempts'] === 'number' ? payload['attempts'] : 0,
          mermaid: asString(payload['mermaid']),
          warnings: Array.isArray(payload['warnings']) ? payload['warnings'].map(asString) : [],
        };
      }
    };

    for (;;) {
      const { value, done: streamDone } = await reader.read();
      if (streamDone) break;
      buffer += decoder.decode(value, { stream: true });

      let boundary = buffer.indexOf('\n\n');
      while (boundary !== -1) {
        consumeFrame(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf('\n\n');
      }
    }

    if (failure) return Err(failure);
    if (outcome) return Ok(outcome);
    return Err('The runtime closed the stream without reporting a result.');
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
