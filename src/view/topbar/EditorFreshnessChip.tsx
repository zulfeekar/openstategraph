import { useEffect, useState } from 'react';
import { TriangleAlert } from 'lucide-react';
import { Icon } from '@design/primitives';
import { serverReadiness } from '@core/providers/serverReadiness';
import { staleEditorNotice } from './staleEditorNotice';

/**
 * The one place this product says anything about the bundle you are looking
 * at — `the-cost-of-one-more/16`.
 *
 * **No second poll and no second client.** `RuntimeHealthDot` already asks
 * `/api/health` every ten seconds through `probeServerReadiness`, and that
 * probe publishes into `serverReadiness`; this subscribes to the same store.
 * A component that fetched its own health would be a second timer answering
 * the same question, which is the shape `usePublishState` argues against for
 * the lifecycle badge.
 *
 * **It is beside the dot and not part of it.** The dot means *reachable*, and
 * `production-ready 60`'s question is *current*: a process can be perfectly
 * up while serving a month-old editor, and folding the second answer into the
 * first indicator would make one light mean two things and neither of them
 * precisely.
 *
 * All three states and the argument for what each renders are in
 * `staleEditorNotice.ts`, which is where the sentence is tested. This file is
 * the subscription and the markup.
 */
export function EditorFreshnessChip() {
  const [stale, setStale] = useState<boolean | null>(() => serverReadiness.editorStale());

  useEffect(() => serverReadiness.onChange(() => setStale(serverReadiness.editorStale())), []);

  const notice = staleEditorNotice(stale);
  if (notice === null) return null;

  return (
    <span className="topbar__stale" role="status" aria-label={notice.hint} title={notice.hint}>
      <Icon glyph={TriangleAlert} size="xs" />
      {notice.label}
    </span>
  );
}
