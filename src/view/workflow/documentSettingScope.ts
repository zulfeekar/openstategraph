import { isInstance, type MountAddress } from '@core/model/MountAddress';

/**
 * Whether the Workflow inspector's *Document* boxes may be typed in here.
 *
 * `workflow-gallery` 70. `MountEditScope` already refuses `RenameWorkflowCommand`
 * and `SetWorkflowSettingCommand` inside a mounted instance, and refuses them
 * correctly: a mount's own state is `data.overrides`, keyed by **child node id
 * → field key** (`docs/decisions/mount-overrides.md`), and a document's name
 * and settings belong to no node, so there is nowhere for them to be written.
 *
 * The refusal was honest and the surface was not. Drilling into
 * `delegate-by-mount/mount-sql` and typing produced: a box that accepted every
 * keystroke, *kept showing the typed text after blur*, a toolbar still reading
 * the real name, and a toast arriving afterwards to say it had not happened.
 * That is CLAUDE.md's "do not promise which is not possible", in a widget.
 *
 * ## Why a rule module rather than a flag in the component
 *
 * vitest runs `environment: 'node'`, so a React render cannot be asserted. The
 * decision therefore lives where it can be tested — the same reason
 * `stepBudget.ts` exists — and `Inspector.tsx` is left holding only the
 * wiring. It is also the shape the next document-level setting wants:
 * `organisms-first-class/34`'s cache policy and durability mode are refused by
 * exactly the same command and inherit this without a second rule.
 *
 * ## What this is deliberately not
 *
 * It is **not** a rule about a node's fields. Those stay editable inside a
 * mount — that is what an override *is* — so nothing here is reachable from
 * the node inspector, and no caller passes a node through it.
 */
export interface DocumentSettingScope {
  /** True when a document-level box must refuse the typing rather than the write. */
  readonly locked: boolean;
  /** The sentence shown beside the locked boxes; absent when nothing is locked. */
  readonly reason?: string;
}

/**
 * One sentence, and it points at a door rather than only closing one.
 *
 * `production-ready/81` praised the drill-in affordances for this — the
 * breadcrumb, **Save mount**, the palette naming the cycle it refuses — so
 * this is written to sit beside them and in the same voice as
 * `MountEditScope.refuse`, which a user may still see if a document setting
 * is changed by some other route.
 *
 * Two things it must not do. It must not name a **slug**: that is a name a
 * user never chose (CLAUDE.md), and the sentence is rendered in a panel where
 * the drill banner already says which mount this is. And it must not stop at
 * "no" — the setting genuinely exists somewhere, one level up, and the reader
 * is one click from it.
 */
export const DOCUMENT_LOCKED_IN_INSTANCE =
  "The package owns this. A mount can override a step's field values, not the " +
  "workflow's own name or settings — open the package to change it, and every " +
  'mount of it changes with you.';

/** The scope for the address currently displayed. `null` means nothing is open. */
export function documentSettingScope(address: MountAddress | null): DocumentSettingScope {
  if (address === null || !isInstance(address)) return { locked: false };
  return { locked: true, reason: DOCUMENT_LOCKED_IN_INSTANCE };
}
