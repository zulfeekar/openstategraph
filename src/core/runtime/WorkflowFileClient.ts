import { Err, Ok, type Result } from '@core/kernel/Result';

/**
 * File-backed workflow persistence (tickets 10/14/16).
 *
 * The browser cannot write to disk — the File System Access API is
 * Chromium-only and permission-gated, not a production answer (ticket 16's
 * own hard constraint) — so this, like `RuntimeClient`, only ever posts a
 * document and receives one back. `workflows/<slug>/workflow.json` on the
 * backend is the actual source of truth; this class holds no file handles
 * and knows nothing about the filesystem.
 *
 * Same shape as `RuntimeClient` on purpose: one class, `fetch` injected for
 * testability under Vitest's node environment, errors turned into a message
 * a developer can act on rather than a raw status code.
 */

/** A stable, filesystem-safe identity, derived once from a name and never
 * recomputed on a later rename — see `workflow_store.py`'s own docstring on
 * why the slug is frozen. Kept in lockstep with the backend's `slugify()`;
 * the backend is the enforcement point (a mismatched slug is a 422), this is
 * only what lets the frontend compute the *same* one client-side.
 */
export function slugify(name: string): string {
  const slug = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return slug || 'workflow';
}

export interface WorkflowSummary {
  readonly slug: string;
  readonly name: string;
  readonly savedAt: string;
  readonly nodeCount: number;
  readonly edgeCount: number;
}

export interface IWorkflowFileClient {
  list(): Promise<Result<readonly WorkflowSummary[], string>>;
  load(slug: string): Promise<Result<unknown, string>>;
  save(slug: string, name: string, document: unknown): Promise<Result<void, string>>;
  remove(slug: string): Promise<Result<void, string>>;
}

export type FetchLike = (url: string, init?: RequestInit) => Promise<Response>;

const DEFAULT_BASE = 'http://localhost:8000';

export class WorkflowFileClient implements IWorkflowFileClient {
  constructor(
    private readonly baseUrl: string = DEFAULT_BASE,
    private readonly fetchImpl: FetchLike = (url, init) => fetch(url, init),
  ) {}

  async list(): Promise<Result<readonly WorkflowSummary[], string>> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}/api/workflows`);
    } catch {
      return Err(`Could not reach the runtime at ${this.baseUrl}. Is the backend running?`);
    }
    if (!response.ok) return Err(await describeFailure(response));

    try {
      const payload = (await response.json()) as unknown[];
      return Ok(
        payload.map((entry) => {
          const record = entry as Record<string, unknown>;
          return {
            slug: asString(record['slug']),
            name: asString(record['name']),
            savedAt: asString(record['saved_at']),
            nodeCount: typeof record['node_count'] === 'number' ? record['node_count'] : 0,
            edgeCount: typeof record['edge_count'] === 'number' ? record['edge_count'] : 0,
          };
        }),
      );
    } catch {
      return Err('The runtime returned a response that was not valid JSON');
    }
  }

  async load(slug: string): Promise<Result<unknown, string>> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}/api/workflows/${encodeURIComponent(slug)}`);
    } catch {
      return Err(`Could not reach the runtime at ${this.baseUrl}. Is the backend running?`);
    }
    if (!response.ok) return Err(await describeFailure(response));

    try {
      const payload = (await response.json()) as { document?: unknown };
      return Ok(payload.document);
    } catch {
      return Err('The runtime returned a response that was not valid JSON');
    }
  }

  async save(slug: string, name: string, document: unknown): Promise<Result<void, string>> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}/api/workflows/${encodeURIComponent(slug)}`, {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ name, document }),
      });
    } catch {
      return Err(`Could not reach the runtime at ${this.baseUrl}. Is the backend running?`);
    }
    if (!response.ok) return Err(await describeFailure(response));
    return Ok(undefined);
  }

  async remove(slug: string): Promise<Result<void, string>> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}/api/workflows/${encodeURIComponent(slug)}`, {
        method: 'DELETE',
      });
    } catch {
      return Err(`Could not reach the runtime at ${this.baseUrl}. Is the backend running?`);
    }
    if (!response.ok) return Err(await describeFailure(response));
    return Ok(undefined);
  }
}

async function describeFailure(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === 'string' && payload.detail) return payload.detail;
  } catch {
    // fall through to the generic message below
  }
  if (response.status === 404) return 'That workflow does not exist on the backend.';
  return `The runtime returned ${response.status}`;
}

const asString = (value: unknown): string => (typeof value === 'string' ? value : '');
