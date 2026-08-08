import { CANVAS } from '@design/tokens';
import { snapPoint, type Point } from '@core/kernel/geometry';
import { CompositeCommand } from '@core/commands/ICommand';
import {
  ConnectCommand,
  DisconnectCommand,
  SetEdgeLabelCommand,
  SpliceInsertCommand,
} from '@core/commands/edgeCommands';
import type { NodeTypeId } from '@core/model/contracts/node';
import type { PortRef } from '@core/model/contracts/ports';
import type { EdgeId } from '@core/model/contracts/workflow';
import type { ConnectionValidator } from '@core/validation/ConnectionValidator';
import { failed, OK, type ActionOutcome, type EditingContext, type IEdgeEditor } from './contracts';

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
    private readonly ctx: EditingContext,
    private readonly validator: ConnectionValidator,
  ) {}

  private get commands() {
    return this.ctx.commands;
  }

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

  /**
   * Ticket 25's splice-insert: drops `typeId` inline on an existing edge,
   * replacing it with two edges through the new node.
   *
   * Legal only if the new node's **default** ports (its first `in`, its
   * first `out`) are compatible with the edge's own endpoints — the same
   * "consumer's declared `accepts` list" check `typeCompatibilityRule`
   * makes for an ordinary drag-to-connect, applied here before anything is
   * created since the new node has no real id yet for the full
   * `ConnectionValidator` (which needs a live node to resolve ports from).
   */
  insertOnEdge(edgeId: EdgeId, typeId: NodeTypeId, at: Point): ActionOutcome {
    const edge = this.ctx.model.edge(edgeId);
    if (!edge) return failed('That link no longer exists');

    const definition = this.ctx.registry.nodeTypes.get(typeId);
    if (!definition) return failed(`Unknown node type "${typeId}"`);

    const previewPorts = definition.ports({});
    const inPort = previewPorts.find((p) => p.direction === 'in');
    const outPort = previewPorts.find((p) => p.direction === 'out');
    if (!inPort || !outPort) {
      return failed(`${definition.label} has no through-path — it can't sit inline on a link`);
    }

    const sourcePort = this.ctx.model.node(edge.source.nodeId)?.port(edge.source.portId);
    const targetPort = this.ctx.model.node(edge.target.nodeId)?.port(edge.target.portId);
    if (!sourcePort || !targetPort) return failed("Could not resolve this link's ports");

    const registry = this.ctx.registry;
    if (!registry.canConnectTypes(sourcePort.type, inPort.type)) {
      return failed(
        `${registry.portType(sourcePort.type).label} output can't feed ${definition.label}'s ${registry.portType(inPort.type).label} input`,
      );
    }
    if (!registry.canConnectTypes(outPort.type, targetPort.type)) {
      return failed(
        `${definition.label}'s ${registry.portType(outPort.type).label} output can't feed a ${registry.portType(targetPort.type).label} input`,
      );
    }

    const topLeft = {
      x: at.x - definition.defaultSize.width / 2,
      y: at.y - definition.defaultSize.height / 2,
    };
    const command = new SpliceInsertCommand(edgeId, definition, {
      position: snapPoint(topLeft, CANVAS.snapGrid),
    });
    this.commands.execute(command);
    return OK;
  }
}
