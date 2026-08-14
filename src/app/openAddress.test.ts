import { beforeEach, describe, expect, it } from 'vitest';
import { formatMountAddress, parseMountAddress } from '@core/model/MountAddress';
import { CURRENT_SLUG_KEY } from './workflowFileWatch';
import {
  OPEN_ADDRESS_KEY,
  getOpenAddress,
  readAddressFromSearch,
  resolveAddressRequest,
  setOpenAddress,
  urlWithAddress,
} from './openAddress';

/**
 * The address half of ticket 42 — `?w=concierge/wf-music` names one *instance*
 * of a mounted workflow, where `?w=concierge` still names a document.
 *
 * The rule this file exists to hold is the storage split, and it is the one
 * that would break six unrelated panels if it were got wrong.
 * `CURRENT_SLUG_KEY` is read raw by the Ask panel, the SQL schema body, the
 * knowledge body, the palette, the mount card and the file watch, and every one
 * of them substitutes it into `/api/workflows/{slug}/…`. Those questions —
 * capabilities, schema, knowledge, tools — are questions about the **package**,
 * so that key keeps meaning the class slug of whatever is on screen. The
 * instance address lives in its own key, and only code that knows what an
 * instance is ever reads it.
 */
const address = (raw: string) => parseMountAddress(raw)!;

describe('readAddressFromSearch', () => {
  it('reads a bare slug as a class address', () => {
    expect(readAddressFromSearch('?w=chinook-assistant')).toEqual(address('chinook-assistant'));
  });

  it('reads a mount path as an instance address', () => {
    expect(readAddressFromSearch('?w=concierge/wf-music')).toEqual(address('concierge/wf-music'));
  });

  it('is null when there is no parameter, or it is blank', () => {
    // Preserved from the slug-only behaviour: a bare `?w=` is a broken link,
    // not a workflow named "".
    expect(readAddressFromSearch('')).toBeNull();
    expect(readAddressFromSearch('?theme=dark')).toBeNull();
    expect(readAddressFromSearch('?w=')).toBeNull();
    expect(readAddressFromSearch('?w=%20')).toBeNull();
  });

  it('is null for an address that cannot be parsed, rather than a repair', () => {
    // A repaired address opens the *wrong instance* silently. See
    // `MountAddress` — this is the same refusal, one layer up.
    expect(readAddressFromSearch('?w=concierge//wf-music')).toBeNull();
    expect(readAddressFromSearch('?w=concierge/..')).toBeNull();
  });
});

describe('urlWithAddress', () => {
  it('writes a class address exactly as the slug form did', () => {
    // Byte-identical to the old output, so no existing link changes shape.
    expect(urlWithAddress('http://localhost:5273/', address('my-workflow'))).toBe(
      '/?w=my-workflow',
    );
  });

  it('percent-encodes the separator, as the standard serializer does', () => {
    // `URLSearchParams` escapes `/` in a value. Left alone deliberately:
    // hand-building the query string to keep it pretty would mean
    // reimplementing the parameter-preserving behaviour the test below pins,
    // and `%2F` round-trips exactly. What matters is that reading it back
    // yields the same address, which `readAddressFromSearch` covers.
    expect(urlWithAddress('http://localhost:5273/', address('concierge/wf-music'))).toBe(
      '/?w=concierge%2Fwf-music',
    );
    expect(readAddressFromSearch('?w=concierge%2Fwf-music')).toEqual(address('concierge/wf-music'));
  });

  it('preserves every other parameter and the hash', () => {
    expect(urlWithAddress('http://x/?theme=dark#node-1', address('concierge/wf-music'))).toBe(
      '/?theme=dark&w=concierge%2Fwf-music#node-1',
    );
  });

  it('removes the parameter for a document with no address', () => {
    expect(urlWithAddress('http://localhost:5273/?w=old', null)).toBe('/');
  });
});

describe('setOpenAddress — the storage split', () => {
  // The suite runs in `node` on purpose (see `vite.config.ts`), so storage is
  // stubbed rather than shimmed with a whole DOM: the behaviour under test is
  // *which key gets which value*, and that needs a Map, not a browser.
  beforeEach(() => {
    const cells = new Map<string, string>();
    (globalThis as { sessionStorage?: unknown }).sessionStorage = {
      getItem: (key: string) => cells.get(key) ?? null,
      setItem: (key: string, value: string) => void cells.set(key, value),
      removeItem: (key: string) => void cells.delete(key),
      clear: () => cells.clear(),
    };
  });

  it('stores the class slug where every existing reader looks for it', () => {
    // `concierge/wf-music` displays the `chinook-assistant` package, so the
    // palette, knowledge and SQL panels must ask about `chinook-assistant`.
    setOpenAddress(address('concierge/wf-music'), 'chinook-assistant');
    expect(sessionStorage.getItem(CURRENT_SLUG_KEY)).toBe('chinook-assistant');
  });

  it('stores the instance address separately', () => {
    setOpenAddress(address('concierge/wf-music'), 'chinook-assistant');
    expect(sessionStorage.getItem(OPEN_ADDRESS_KEY)).toBe('concierge/wf-music');
    expect(formatMountAddress(getOpenAddress()!)).toBe('concierge/wf-music');
  });

  it('leaves a class address with both keys agreeing', () => {
    setOpenAddress(address('concierge'), 'concierge');
    expect(sessionStorage.getItem(CURRENT_SLUG_KEY)).toBe('concierge');
    expect(sessionStorage.getItem(OPEN_ADDRESS_KEY)).toBe('concierge');
  });
});

describe('resolveAddressRequest', () => {
  it('restores a reload of the address already open', () => {
    // The unsaved-edits rule, unchanged: refetching over this tab's autosave
    // would discard work on every reload.
    expect(
      resolveAddressRequest({
        urlAddress: address('concierge/wf-music'),
        openAddress: address('concierge/wf-music'),
      }),
    ).toEqual({ action: 'restore' });
  });

  it('fetches when the URL names a different instance of the same package', () => {
    // The test a slug-only implementation passes by accident. `wf-music` and
    // `wf-other` are both `chinook-assistant`; comparing slugs would call this
    // a reload and show the wrong instance's overrides.
    expect(
      resolveAddressRequest({
        urlAddress: address('concierge/wf-other'),
        openAddress: address('concierge/wf-music'),
      }),
    ).toEqual({ action: 'fetch', address: address('concierge/wf-other') });
  });

  it('fetches when the URL names an instance and a class is open', () => {
    expect(
      resolveAddressRequest({
        urlAddress: address('concierge/wf-music'),
        openAddress: address('chinook-assistant'),
      }),
    ).toEqual({ action: 'fetch', address: address('concierge/wf-music') });
  });

  it('restores when there is no address in the URL at all', () => {
    expect(resolveAddressRequest({ urlAddress: null, openAddress: address('concierge') })).toEqual({
      action: 'restore',
    });
  });

  it('still honours an old bookmark naming a bare slug', () => {
    // Links already in someone's browser must keep working, unchanged.
    expect(
      resolveAddressRequest({ urlAddress: address('chinook-assistant'), openAddress: null }),
    ).toEqual({ action: 'fetch', address: address('chinook-assistant') });
  });
});
