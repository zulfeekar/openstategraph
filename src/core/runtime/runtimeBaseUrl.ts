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
 * **A third mode: mounted under a host application's path.** A service that
 * embeds this product mounts it at a prefix of its own choosing — `/osg`, or
 * anything else — and then `/api/runs` is not our path at all, it is the
 * host's, and the host answers 404. The prefix cannot be baked into the
 * bundle: one wheel is mounted at different paths by different hosts. So the
 * server states it in the served document, as `<base href>`, and this function
 * reads it back. That single tag also settles the assets, which is why the
 * build emits relative asset URLs.
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
  /**
   * `document.baseURI` — the absolute URL of the document's `<base href>`,
   * or of the document itself when there is no such tag. Its path is the
   * prefix the server mounted us at.
   */
  readonly baseHref?: string | undefined;
}

/**
 * The path prefix a `<base href>` names, with no trailing slash — `''` at the
 * origin root, which is what every other mode already returns.
 *
 * Unparseable input is `''` rather than a throw: this is the value every API
 * call is built from, and a base that prefixes garbage onto `/api` fails
 * later and further away than one that is simply absent.
 */
export function mountPrefix(baseHref: string): string {
  try {
    return new URL(baseHref).pathname.replace(/\/+$/, '');
  } catch {
    return '';
  }
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
  if (env.dev) return DEV_RUNTIME_BASE_URL;
  return mountPrefix(env.baseHref ?? '');
}

/** The resolved base for this bundle. */
export function runtimeBaseUrl(): string {
  const env = import.meta.env as { DEV?: boolean; VITE_RUNTIME_BASE_URL?: string };
  // `document` is absent under vitest's `node` environment, which is why the
  // decision above takes the value rather than reading it.
  const baseHref = typeof document === 'undefined' ? undefined : document.baseURI;
  return resolveRuntimeBaseUrl({
    dev: env.DEV,
    configured: env.VITE_RUNTIME_BASE_URL,
    baseHref,
  });
}

/**
 * The base, said out loud in an error message. `''` is correct as a URL prefix
 * and useless in a sentence — "Could not reach the runtime at ." tells nobody
 * anything.
 */
export function describeRuntimeBase(base: string): string {
  return base === '' ? 'this page’s own origin' : base;
}
