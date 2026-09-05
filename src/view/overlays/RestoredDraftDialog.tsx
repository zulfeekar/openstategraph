import { FileWarning } from 'lucide-react';
import { Button } from '@design/primitives';
import {
  RESTORED_DRAFT_KEEP,
  RESTORED_DRAFT_SUBTITLE,
  RESTORED_DRAFT_TAKE,
  RESTORED_DRAFT_TITLE,
  restoredDraftKeepHint,
  restoredDraftTakeHint,
} from '@view/workflow/restoredDraftChoiceCopy';
import { useRestoredDraftChoice } from '@view/workflow/useRestoredDraftChoice';
import { Dialog } from './Dialog';
import './overlays.css';

interface RestoredDraftDialogProps {
  /** The name the file on disk carries — what each door is about. */
  readonly fileName: string;
  readonly onKeepDraft: () => void;
  readonly onTakeFile: () => void;
  /** Escape and the backdrop — dismiss the question without answering it. */
  readonly onDefer: () => void;
}

/**
 * The choice a reload owes the user — `osg-agent-experience/68`.
 *
 * ## It is `ArrivalDialog`'s container, for the same four reasons
 *
 * `Dialog` owns Escape, a focus trap that wraps at both ends, a backdrop that
 * closes only on a press *and* release of its own, and a bounded scrolling
 * body. A second copy of those four decisions is the duplication this
 * repository keeps paying for, so what is left here is two buttons and the
 * sentence saying what each does.
 *
 * ## Escape is not one of the two answers, and must not be wired to either
 *
 * The obvious economy — pointing `onClose` at *keep my edits* so the dialog
 * has a default — would put a destructive choice on the Escape key: keeping
 * the draft records the baseline, and the next change then overwrites the
 * file. That is the ticket's own data loss, reachable by the one key people
 * press to make a dialog go away.
 *
 * So `onDefer` is a third outcome that writes nothing and decides nothing.
 * The tab stays in the state `ensureDiskBaseline` left it — draft on screen,
 * no baseline, autosave refusing — which is safe, is what the subtitle
 * promised, and raises the same question on the next reload. There is no
 * footer button for it, because a labelled third door would read as an answer.
 *
 * ## Neither button is `primary`
 *
 * Both destroy something. A primary weight on either would be the editor
 * recommending one, which is precisely the guess that produced the ticket —
 * the same call `diskConflictNotice` records for the save path, where it names
 * both doors and takes neither.
 */
export function RestoredDraftDialog({
  fileName,
  onKeepDraft,
  onTakeFile,
  onDefer,
}: RestoredDraftDialogProps) {
  return (
    <Dialog
      title={RESTORED_DRAFT_TITLE}
      subtitle={RESTORED_DRAFT_SUBTITLE}
      icon={FileWarning}
      onClose={onDefer}
      footer={
        <>
          <Button onClick={onTakeFile}>{RESTORED_DRAFT_TAKE}</Button>
          <Button onClick={onKeepDraft}>{RESTORED_DRAFT_KEEP}</Button>
        </>
      }
    >
      <p className="restored-draft__hint">{restoredDraftKeepHint(fileName)}</p>
      <p className="restored-draft__hint">{restoredDraftTakeHint(fileName)}</p>
    </Dialog>
  );
}

interface RestoredDraftChoicePromptProps {
  readonly notify: (message: string) => void;
}

/**
 * The dialog above, wired to the offer — and the only thing `AppShell` renders.
 *
 * Separate from the presentational component so the two can be exercised
 * apart, and mounted unconditionally so `AppShell` holds no state for a
 * question it does not raise: `ensureDiskBaseline` publishes the offer from
 * inside the autosave effect, and `useRestoredDraftChoice` subscribes. Renders
 * nothing at all on every ordinary page load, which is nearly all of them.
 */
export function RestoredDraftChoicePrompt({ notify }: RestoredDraftChoicePromptProps) {
  const choice = useRestoredDraftChoice(notify);
  if (choice.offer === null) return null;
  return (
    <RestoredDraftDialog
      fileName={choice.offer.fileName}
      onKeepDraft={choice.keepDraft}
      onTakeFile={choice.takeFile}
      onDefer={choice.defer}
    />
  );
}
