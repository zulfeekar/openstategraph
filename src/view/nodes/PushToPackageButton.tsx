import { useCallback, useState } from 'react';
import { WorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import { getOpenSlug } from '@app/openWorkflow';
import { getOpenAddress } from '@app/openAddress';
import { isInstance } from '@core/model/MountAddress';
import { MountContext } from '@core/model/MountContext';
import { useController } from '@app/WorkbenchContext';
import type { NodeId } from '@core/model/contracts/node';
import type { FieldValue } from '@core/model/contracts/fields';
import { pushFieldToPackage, pushFieldMessage } from '@view/workflow/pushFieldToPackage';

/**
 * "Push to package" — beside `FieldRenderer`'s existing "overridden" revert,
 * `production-ready` ticket 17. The revert says *"go back to what the
 * package already says"*; this says the opposite thing a mount could never
 * say before: *"what I have here is right — put it in the package."*
 *
 * **Never labelled "save".** `pushFieldToPackage.ts`'s own docstring says
 * why: this changes every mount of the package, which is a materially
 * different act from an override, and "save" is already spent on the
 * instance-scoped write the toolbar's Save button performs here.
 *
 * There is no toast context this deep in the tree (`CompositionBody`'s
 * `OpenMount` states the same fact and takes the same way out) — so the
 * outcome, including the confirmation's instance count and any shadowing
 * warning, is reported in place rather than inventing plumbing to the
 * shell's `Toaster`.
 */
export function PushToPackageButton({
  nodeId,
  fieldKey,
  value,
}: {
  nodeId: NodeId;
  fieldKey: string;
  value: FieldValue;
}) {
  const controller = useController();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const push = useCallback(async () => {
    // The package **at the end of the chain** — never the mount's root.
    // `getOpenSlug()` already holds it: while an instance is on screen this
    // is the class it is of, resolved by the backend when the mount was
    // opened (`app/openAddress.ts`'s own docstring), so a mount several
    // levels deep needs no re-resolution here.
    const slug = getOpenSlug();
    if (!slug) {
      setMessage('This document has no package to push to yet — save it first.');
      return;
    }
    setBusy(true);
    setMessage(null);
    const client = new WorkflowFileClient();
    const outcome = await pushFieldToPackage(client, {
      slug,
      childNodeId: nodeId,
      key: fieldKey,
      value,
      // This mount's own host — dropped from the shadowing warning below,
      // since its override is cleared right after a successful push.
      excludeHost: getOpenAddress()?.root,
      confirm: (text) => window.confirm(text),
    });
    if (outcome.kind === 'pushed') {
      // The value just became the package default, so this instance no
      // longer says anything different — an override that agrees with the
      // package it narrows is not an override, it is stale bookkeeping the
      // "overridden" badge would keep claiming for no reason.
      //
      // But `ClearMountOverrideCommand` reverts to `MountContext`'s cached
      // `inheritedDocument` — fetched once, when the mount was opened — and
      // this push just changed what that document says. Clearing without
      // refreshing it first would show the *pre-push* package default for an
      // instant (a real defect this ticket's own browser pass caught: the
      // field visibly reverted to the old value, not the one just written),
      // so the baseline is re-fetched before the clear runs.
      const address = getOpenAddress();
      const mounts = controller.document.mountContext();
      if (address && isInstance(address) && mounts) {
        const mountId = address.mountPath[address.mountPath.length - 1] ?? '';
        const fresh = await client.loadMount(address, { inherited: true });
        controller.document.enterInstance(
          mountId,
          new MountContext(
            address,
            mounts.rootDocument,
            fresh.ok ? (fresh.value.document as Record<string, unknown>) : undefined,
          ),
        );
      }
      controller.nodes.clearOverride(nodeId, fieldKey);
    }
    setBusy(false);
    setMessage(pushFieldMessage(outcome));
  }, [controller, nodeId, fieldKey, value]);

  return (
    <>
      <button
        type="button"
        className="field__push"
        disabled={busy}
        title="Write this value into the package itself, so every mount that does not already override it picks up the change."
        onClick={() => void push()}
      >
        {busy ? 'Pushing…' : 'push to package'}
      </button>
      {/* `labelValue` is rendered inside a `<span>` (`Field.tsx`), so this
          stays inline-safe rather than nesting a block element in it —
          `white-space: pre-line` in the stylesheet is what turns the
          confirmation's blank-line-separated sentences into visible breaks. */}
      {message ? <span className="field__push-result">{message}</span> : null}
    </>
  );
}
