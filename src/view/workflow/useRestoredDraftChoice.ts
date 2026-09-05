import { useCallback, useSyncExternalStore } from 'react';
import { useWorkbench } from '@app/WorkbenchContext';
import { rememberDiskDocument } from '@app/diskAutosave';
import {
  clearRestoredDraftChoice,
  pendingRestoredDraftChoice,
  subscribeRestoredDraftChoice,
  type RestoredDraftOffer,
} from '@app/restoredDraftConflict';
import { registerNodeTypesForRawDocument } from '@nodes/workflowScoped';
import { restoredDraftKeptTheDraft, restoredDraftTookTheFile } from './restoredDraftChoiceCopy';

export interface RestoredDraftChoice {
  /** The offer awaiting an answer, or `null` when there is none. */
  readonly offer: RestoredDraftOffer | null;
  readonly keepDraft: () => void;
  readonly takeFile: () => void;
  /** Escape and the backdrop: write nothing, decide nothing, ask again later. */
  readonly defer: () => void;
}

/**
 * The two doors a reload's conflict opens — `osg-agent-experience/68`.
 *
 * ## Both answers are the *same* call, and that is the point
 *
 * `rememberDiskDocument` is what each one ends in, because the baseline is a
 * statement about the file and not about the choice: after either answer the
 * editor knows what `workflow.json` holds, and disk autosave's ordinary
 * comparison decides the rest. *Take the file* imports it first, so the
 * comparison finds nothing to write; *keep my edits* does not, so the
 * comparison finds the draft and writes it — deliberately, quoting the digest
 * `ensureDiskBaseline` adopted, which is what puts this path behind the same
 * 409 guard as every other write rather than beside it.
 *
 * There is no second conflict mechanism here, and there must not be one. The
 * ticket's own finding was that the restore path bypassed the guard; a private
 * copy of it would be that finding rebuilt in a new place.
 *
 * ## Node types are registered before the import
 *
 * The same ordering requirement every import path in this repository carries:
 * a workflow-scoped type must exist before `fromJSON` runs, or every node of
 * that type is silently skipped. *Take the file* is a real import of a real
 * document and is not exempt from it.
 */
export function useRestoredDraftChoice(notify: (message: string) => void): RestoredDraftChoice {
  const workbench = useWorkbench();
  const offer = useSyncExternalStore(subscribeRestoredDraftChoice, pendingRestoredDraftChoice);

  const keepDraft = useCallback(() => {
    if (!offer) return;
    // The baseline is the **file**, not the draft: it is what disk holds, and
    // recording the draft here would tell autosave the two already agree and
    // quietly strand the edits the user just chose to keep.
    rememberDiskDocument(offer.slug, offer.fileName, offer.file, workbench.serializer);
    clearRestoredDraftChoice();
    notify(restoredDraftKeptTheDraft(offer.fileName));
  }, [offer, workbench, notify]);

  const takeFile = useCallback(() => {
    if (!offer) return;
    registerNodeTypesForRawDocument(offer.file, workbench.registry, workbench.engine.executors);
    workbench.controller.document.importJSON(JSON.stringify(offer.file));
    // After the import, so the baseline describes what is now on screen and the
    // first change after this is the user's rather than this one.
    rememberDiskDocument(offer.slug, offer.fileName, offer.file, workbench.serializer);
    clearRestoredDraftChoice();
    notify(restoredDraftTookTheFile(offer.fileName));
  }, [offer, workbench, notify]);

  // No baseline is recorded, so autosave goes on refusing and the file keeps
  // what it has. Deliberately not an answer.
  const defer = useCallback(() => clearRestoredDraftChoice(), []);

  return { offer, keepDraft, takeFile, defer };
}
