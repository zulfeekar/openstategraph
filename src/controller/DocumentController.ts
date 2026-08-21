import type { CommandStack } from '@core/commands/CommandStack';
import type { WorkflowModel } from '@core/model/WorkflowModel';
import type { WorkflowSerializer } from '@core/serialization/WorkflowSerializer';
import type { Diagnostic, WorkflowValidator } from '@core/validation/WorkflowValidator';
import { RenameWorkflowCommand, SetWorkflowSettingCommand } from '@core/commands/edgeCommands';
import type { MountEditScope } from '@core/commands/editScope';
import type { MountContext } from '@core/model/MountContext';
import { failed, OK, type ActionOutcome, type IDocumentController } from './contracts';
import type { SelectionModel } from './SelectionModel';

/**
 * The document as a whole — validate, import, export, clear, rename.
 *
 * Grouped because these are the operations that act on the *file* rather than
 * on anything in it, and they share a rule the per-node operations do not:
 * **replacing the document clears history.** Undoing across a document boundary
 * would be meaningless, so `importJSON` and `clear` drop the stack.
 */
export class DocumentController implements IDocumentController {
  constructor(
    private readonly model: WorkflowModel,
    private readonly commands: CommandStack,
    private readonly selection: SelectionModel,
    private readonly serializer: WorkflowSerializer,
    private readonly validator: WorkflowValidator,
    private readonly scope?: MountEditScope,
  ) {}

  diagnostics(): readonly Diagnostic[] {
    return this.validator.validate();
  }

  exportJSON(): string {
    return this.serializer.toJSONString(this.model);
  }

  /**
   * Replaces the document from JSON.
   *
   * Warnings are surfaced rather than swallowed: a load that dropped an unknown
   * node or a dangling link succeeded, but the user needs to know it was not
   * byte-for-byte what they opened.
   */
  importJSON(text: string): ActionOutcome {
    const result = this.serializer.loadFromText(this.model, text);
    if (!result.ok) return failed(result.error);
    this.commands.clear();
    const { warnings } = result.value;
    return warnings.length > 0 ? { ok: true, message: warnings.join('; ') } : OK;
  }

  clear(): void {
    this.model.clear();
    this.commands.clear();
    this.selection.clear();
  }

  setName(name: string): void {
    // Undoable, unlike the rest of this class — renaming is an edit to the
    // document's content, not a replacement of it.
    this.commands.execute(new RenameWorkflowCommand(name));
  }

  /**
   * Sets one workflow-level setting, or removes it when `value` is
   * `undefined` — `workflow-gallery` 58.
   *
   * Undoable for the same reason `setName` is: this edits the document's
   * content rather than replacing the document. Generic in the key so the
   * graph-assembly siblings in `organisms-first-class/34` land here without a
   * tenth member; the *meaning* of each key belongs to its own surface, which
   * is where the step budget's window and wording live
   * (`view/workflow/stepBudget.ts`).
   */
  setSetting(key: string, value: unknown): void {
    this.commands.execute(new SetWorkflowSettingCommand(key, value));
  }

  enterInstance(mountId: string, mounts?: MountContext): void {
    this.scope?.enterInstance(mountId, mounts);
  }

  leaveInstance(): void {
    this.scope?.leaveInstance();
  }

  mountContext(): MountContext | undefined {
    return this.scope?.mounts;
  }
}
