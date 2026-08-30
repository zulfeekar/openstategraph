import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { WorkflowFileClient, type PublishOutcome } from '@core/runtime/WorkflowFileClient';
import { getOpenAddress, subscribeOpenAddress } from '@app/openAddress';
import { getOpenSlug } from '@app/openWorkflow';
import { draftSavedAt } from '@app/workflowDrafts';
import { draftIsAhead } from '@app/staleDraft';
import { publishAffordance, type PublishAffordance } from './publishAffordance';

/**
 * The result of flipping the flag: the error to report, or the backend's own
 * publish answer for the toast to read.
 *
 * Two fields rather than a union so a caller cannot forget one branch: the
 * error is what to say when it failed, the outcome is what the sentence is
 * built from when it did not.
 */
export interface PublishFlip {
  readonly error: string | null;
  readonly outcome: PublishOutcome | null;
}

/**
 * Keeps the toolbar's lifecycle badge current — `ship-it` 39.
 *
 * The state itself is the backend's: `GET /api/workflows/{slug}/summary`
 * carries both halves this needs, `published` and `saved_at`, and asking by
 * name is what `workflowFileWatch` already established is the right question
 * about the open slug (a surface listing cannot answer it).
 *
 * **No second `/api/events` subscription and no second timer.** The editor
 * holds exactly one of each already, and a lifecycle badge is not worth a
 * third connection to reconnect and get the base URL wrong. So this refreshes
 * on the four moments that actually move the answer: the document opening, the
 * open slug changing, this tab returning to the foreground, and a publish this
 * editor performed. The gap left open is a *second tab* publishing while this
 * one sits idle and unfocused, which the focus refresh closes the moment
 * anybody looks.
 *
 * `published` starts and stays `null` until the backend answers, and
 * `publishAffordance` prints nothing for `null` rather than guessing — an
 * unreachable runtime must not make a published workflow read as a draft.
 */
export function usePublishState(): {
  readonly affordance: PublishAffordance;
  /**
   * The same answer, recomputed **now** — reading this browser's draft
   * timestamp at the moment of the call rather than at the last render.
   *
   * The gesture must use this one, and the reason was found in the browser
   * rather than in a test: `unsavedWork` is derived from the autosaved draft,
   * a drag writes that draft, and nothing re-renders the toolbar when it does.
   * So a memoised answer was computed *before* the edits it is supposed to
   * warn about and the confirm never fired once — the exact silent
   * ship-something-else this ticket exists to close, reintroduced by the fix
   * for it.
   */
  readonly affordanceNow: () => PublishAffordance;
  readonly slug: string | null;
  readonly refresh: () => void;
  readonly setPublished: (published: boolean) => Promise<PublishFlip>;
} {
  const clientRef = useRef<WorkflowFileClient | null>(null);
  if (!clientRef.current) clientRef.current = new WorkflowFileClient();

  const [slug, setSlug] = useState<string | null>(() => getOpenSlug());
  const [address, setAddress] = useState(() => getOpenAddress());
  const [published, setPublished] = useState<boolean | null>(null);
  /** What the backend last said the file's own timestamp was. */
  const [fileSavedAt, setFileSavedAt] = useState<string | null>(null);

  useEffect(
    () =>
      subscribeOpenAddress(() => {
        setSlug(getOpenSlug());
        setAddress(getOpenAddress());
        // The previous document's answer is not this one's, and showing it
        // for the moment before the fetch lands would be the guess this
        // module exists to refuse.
        setPublished(null);
        setFileSavedAt(null);
      }),
    [],
  );

  const refresh = useCallback(() => {
    const client = clientRef.current;
    const open = getOpenSlug();
    if (!client || open === null) return;
    void client.summary(open).then((outcome) => {
      if (!outcome.ok || outcome.value === null) return;
      if (getOpenSlug() !== open) return; // The document moved while we asked.
      setPublished(outcome.value.published);
      setFileSavedAt(outcome.value.savedAt);
    });
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh, slug]);

  useEffect(() => {
    const onFocus = () => refresh();
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [refresh]);

  const describe = useCallback(
    (): PublishAffordance =>
      publishAffordance({
        address,
        slug,
        published,
        // Read at call time, never cached: the draft moves on every drag and
        // nothing tells React about it.
        unsavedWork: slug === null ? false : draftIsAhead(draftSavedAt(slug), fileSavedAt),
      }),
    [address, slug, published, fileSavedAt],
  );

  const affordance = useMemo(() => describe(), [describe]);

  /**
   * Flip the flag. Returns the error to report, or the backend's own answer
   * on success — the toast itself is the caller's, from `consequences`, so
   * both surfaces that publish say the same sentence.
   *
   * The success case carries a `PublishOutcome` rather than nothing since
   * `the-cost-of-one-more/18`: the toast's routing clause is conditional on
   * the note the endpoint sends, and a hook that returned only `null` would
   * make this surface hardcode what the Workflows panel reads.
   */
  const flip = useCallback(async (next: boolean): Promise<PublishFlip> => {
    const client = clientRef.current;
    const open = getOpenSlug();
    if (!client || open === null)
      return { error: 'This workflow is not on disk yet.', outcome: null };
    const result = await client.setPublished(open, next);
    if (!result.ok) return { error: result.error, outcome: null };
    setPublished(next);
    return { error: null, outcome: result.value };
  }, []);

  return { affordance, affordanceNow: describe, slug, refresh, setPublished: flip };
}
