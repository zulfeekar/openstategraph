import { describe, expect, it } from 'vitest';
import { DEV_RUNTIME_BASE_URL, describeRuntimeBase, resolveRuntimeBaseUrl } from './runtimeBaseUrl';

/**
 * The two modes, pinned.
 *
 * This is the bug the wheel made unavoidable: the bundle called
 * `http://localhost:8000` absolutely, so the moment the backend served the
 * editor on any other port — which `openstategraph serve` does routinely, and
 * always does under `--port 0` — every API call went to a port with nothing on
 * it. Same-origin is therefore the *default*, and the absolute URL is the
 * exception that only the cross-origin dev stack needs.
 */
describe('resolveRuntimeBaseUrl', () => {
  it('is same-origin relative in a production bundle', () => {
    // The wheel, Docker, `vite preview` — anywhere the backend itself serves
    // the built files. An empty base makes every request `/api/...`, which
    // follows the page to whatever host and port it was opened on.
    expect(resolveRuntimeBaseUrl({ dev: false })).toBe('');
  });

  it('is the explicit dev backend when Vite is serving the app', () => {
    // Vite on :5273 and uvicorn on :8000 are genuinely different origins, so
    // this mode keeps its absolute URL — and the backend keeps its CORS
    // allow-list for exactly these two origins.
    expect(resolveRuntimeBaseUrl({ dev: true })).toBe(DEV_RUNTIME_BASE_URL);
    expect(DEV_RUNTIME_BASE_URL).toBe('http://localhost:8000');
  });

  it('lets VITE_RUNTIME_BASE_URL override either mode', () => {
    expect(resolveRuntimeBaseUrl({ dev: true, configured: 'http://10.0.0.4:9000' })).toBe(
      'http://10.0.0.4:9000',
    );
    expect(resolveRuntimeBaseUrl({ dev: false, configured: 'http://10.0.0.4:9000' })).toBe(
      'http://10.0.0.4:9000',
    );
  });

  it('drops a trailing slash so callers can always append a rooted path', () => {
    expect(resolveRuntimeBaseUrl({ dev: false, configured: 'http://rt:9000/' })).toBe(
      'http://rt:9000',
    );
  });

  it('ignores a blank or whitespace-only override rather than emptying the base', () => {
    // `VITE_RUNTIME_BASE_URL=` in a .env file arrives as the empty string. In
    // dev that must not silently become same-origin, which would point the
    // editor at Vite's own port and 404 every API call.
    expect(resolveRuntimeBaseUrl({ dev: true, configured: '' })).toBe(DEV_RUNTIME_BASE_URL);
    expect(resolveRuntimeBaseUrl({ dev: true, configured: '   ' })).toBe(DEV_RUNTIME_BASE_URL);
  });

  it('describes the empty base in words, because "the runtime at " is not a message', () => {
    expect(describeRuntimeBase('')).toBe('this page’s own origin');
    expect(describeRuntimeBase('http://rt')).toBe('http://rt');
  });
});
