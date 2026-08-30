/**
 * What the toolbar says about the editor bundle it is running inside —
 * **`the-cost-of-one-more/16`**.
 *
 * `openstategraph serve` hosts the API *and* the built editor from `dist/`,
 * same origin: one `pip install`, one process, one port. That is the product,
 * and it carries one trap that only exists on that side. Edit `src/`, reload
 * the served page, and you are looking at whatever `npm run build` last
 * produced. `production-ready 60` built the detector
 * (`backend/openstategraph/editor_freshness.py`) and published the answer on
 * `GET /api/health`; nothing in the editor read it, so **a fix that is in the
 * tree, is not on the screen, and looks like a fix that did not work** had no
 * signal at all.
 *
 * ## The three states, and what each one renders
 *
 * | `editor_stale` | Means | Renders |
 * | --- | --- | --- |
 * | `true` | the served bundle predates `src/` | the warning below |
 * | `false` | it does not | **nothing** |
 * | `null` | the question does not apply | **nothing** |
 *
 * **The last two rows are the decision, not an oversight.** The recurring
 * defect here is a health surface that shows *fine* when it means *could not
 * tell*, and the way this refuses it is by having no *fine* to show: there is
 * no state in which this module reports the bundle current. `52`'s standard —
 * an unmeasured value renders `—` and never `0`, because a dash says nobody
 * measured this — governs a **readout**, which owns a slot and must fill it
 * with something. This is a **warning**, which owns no slot: a permanent chip
 * in a toolbar reading `—` would be a fifth thing to parse on every glance in
 * exchange for a fact nobody asked. Saying nothing shows no measurement,
 * which is what the third state means; `null` and `false` share an output
 * without sharing a claim.
 *
 * ## It is not audience-gated, and does not need to be
 *
 * A stale bundle is a developer condition and this is a developer surface, by
 * construction rather than by a flag. The audience boundary this product draws
 * (`backend/openstategraph/api/audience.py`, `compile/state.py`'s
 * `CUSTOMER_VISIBLE`) is a **run-state redaction seam** — it decides which
 * keys of a running graph reach which channel — and `editor_stale` is not run
 * state. The customer surface is `chat.html`, which calls `/api/runs/stream`
 * and never `/api/health`; the editor asks for `audience: 'developer'` on
 * every run it makes. So gating this would be a switch with one position.
 *
 * ## Its own module, and pure
 *
 * The same reason `runIntent` and `publishAffordance` are: copy that matters
 * is copy worth a test, and a sentence built inline in a component is a
 * sentence nothing can hold to its promise.
 */
export interface StaleEditorNotice {
  /** The chip's word — short, because it sits in a toolbar. */
  readonly label: string;
  /** The whole sentence, as the chip's tooltip and its accessible name. */
  readonly hint: string;
}

/**
 * The notice for one health answer, or `null` when there is nothing to say.
 *
 * The sentence is the **editor's own**, not the backend's forwarded. That
 * comes free here — only the boolean is on the wire, and
 * `editor_freshness.STALE_EDITOR_WARNING` never leaves the server — but it is
 * the rule either way (`13`, and `18` after it): a message addressed to an API
 * caller put in front of somebody looking at a page tells them to do something
 * this page does not do.
 */
export function staleEditorNotice(editorStale: boolean | null): StaleEditorNotice | null {
  if (editorStale !== true) return null;
  return {
    label: 'Editor is stale',
    hint:
      'This page is running an editor bundle that was built before your last change to src/. ' +
      'Run `npm run build` and reload, or open the editor on the dev server, which rebuilds ' +
      'as you type.',
  };
}
