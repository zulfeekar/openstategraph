import { CompositeCommand } from '@core/commands/ICommand';
import type { CommandStack } from '@core/commands/CommandStack';
import {
  ConnectCommand,
  DisconnectCommand,
  SetEdgeLabelCommand,
} from '@core/commands/edgeCommands';
import type { PortRef } from '@core/model/contracts/ports';
import type { EdgeId } from '@core/model/contracts/workflow';
import type { ConnectionValidator } from '@core/validation/ConnectionValidator';
import { failed, OK, type ActionOutcome, type IEdgeEditor } from './contracts';

/**
 * Connecting and disconnecting ports.
 *
 * Owns one non-obvious behaviour: a link dropped on a full single-slot input
 * *replaces* the incumbent rather than being rejected, and the removal plus the
 * new link go into **one transaction** so a single undo restores the previous
 * wiring exactly. Splitting them would leave an undo that disconnects without
 * reconnecting.
 */
export class EdgeEditor implements IEdgeEditor {
  constructor(
    private readonly commands: CommandStack,
    private readonly validator: ConnectionValidator,
  ) {}

  /** Asked by the canvas on every pointer move while drawing a link. */
  canConnect(source: PortRef, target: PortRef): boolean {
    return this.validator.canConnect(source, target);
  }

  connect(source: PortRef, target: PortRef): ActionOutcome {
    const verdict = this.validator.validate(source, target);
    if (!verdict.ok) return failed(verdict.reason);

    const connect = new ConnectCommand(source, target);
    if (verdict.replaces.length > 0) {
      this.commands.execute(
        CompositeCommand.of('Reconnect', [new DisconnectCommand(verdict.replaces), connect]),
      );
    } else {
      this.commands.execute(connect);
    }
    return OK;
  }

  disconnect(edgeIds: readonly EdgeId[]): ActionOutcome {
    if (edgeIds.length === 0) return OK;
    this.commands.execute(new DisconnectCommand(edgeIds));
    return OK;
  }

  setLabel(edgeId: EdgeId, label: string | null): void {
    this.commands.execute(new SetEdgeLabelCommand(edgeId, label));
  }
}
