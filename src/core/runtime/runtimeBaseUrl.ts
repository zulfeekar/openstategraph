/**
 * Where the editor's HTTP calls go — resolved once, here, for every client.
 *
 * **The default is same-origin.** The built bundle used to name
 * `http://localhost:8000` absolutely, which was true of exactly one deployment
 * (Docker, published on port 8000) and false of the one that matters now:
 * `openstategraph serve` picks a free port when 8000 is taken, and `--port 0`
 * never lands on 8000 at all. An absolute base means the page loads and every
 * request inside it dies — the worst failure shape there is, because the app
 * looks fine.
 *
 * An empty base makes every request path-relative (`/api/runs`), so the API
 * follows the page to whatever host and port it was actually opened on. The
 * backend serves both from one origin (`api/editor_assets.py`), so there is no
 * CORS boundary to cross.
 *
 * **The dev stack is the exception, and it stays explicit.** Vite serves the
 * editor on :5273 and uvicorn runs on :8000 — genuinely different origins,
 * which is why `ALLOWED_ORIGINS` in `api/main.py` names exactly those two. So
 * a dev build keeps the absolute URL, and `VITE_RUNTIME_BASE_URL` overrides
 * either mode for anyone running the two halves somewhere else again — set it
 * in `.env.development.local`, which Vite loads in dev mode only. Not
 * `.env.local`: Vite loads that one in every mode, including `vitest`'s, so a
 * value there reaches the tests that pin the default below and fails them on
 * a file nobody touched (`the-cost-of-one-more/23`).
 *
 * Framework-free by construction: the Vite-specific `import.meta.env` lookup
 * is confined to `runtimeBaseUrl()`, and the decision itself is a pure
 * function of its arguments.
 */

/** Where `scripts/dev.sh` puts uvicorn. */
export const DEV_RUNTIME_BASE_URL = 'http://localhost:8000';

export interface RuntimeBaseUrlEnv {
  /** Vite's `import.meta.env.DEV` — true only under the dev server. */
  readonly dev?: boolean | undefined;
  /** `VITE_RUNTIME_BASE_URL`, when someone runs the halves apart. */
  readonly configured?: string | undefined;
}

/**
 * Explicit configuration wins; otherwise dev is cross-origin and everything
 * else is same-origin. Returns a base with no trailing slash, so every caller
 * can append a rooted path (`${base}/api/...`) and get the right thing in both
 * modes — `''` + `/api/runs` is a relative request, which is the point.
 */
export function resolveRuntimeBaseUrl(env: RuntimeBaseUrlEnv): string {
  const configured = env.configured?.trim();
  if (configured) return configured.replace(/\/+$/, '');
  return env.dev ? DEV_RUNTIME_BASE_URL : '';
}

/** The resolved base for this bundle. */
export function runtimeBaseUrl(): string {
  const env = import.meta.env as { DEV?: boolean; VITE_RUNTIME_BASE_URL?: string };
  return resolveRuntimeBaseUrl({ dev: env.DEV, configured: env.VITE_RUNTIME_BASE_URL });
}

/**
 * The base, said out loud in an error message. `''` is correct as a URL prefix
 * and useless in a sentence — "Could not reach the runtime at ." tells nobody
 * anything.
 */
export function describeRuntimeBase(base: string): string {
  return base === '' ? 'this page’s own origin' : base;
}
