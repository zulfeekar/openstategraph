import { EdgeModel } from '@core/model/EdgeModel';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { NodeInit } from '@core/model/contracts/node';
import type { Workbench } from './Workbench';
import { NODE_TYPE } from '@nodes/index';
import { registerChinookNodes } from '@nodes/workflowScoped';

/**
 * The workflow the editor opens with: natural language to SQL over Chinook.
 *
 * Chosen over the previous Reddit example because it **actually works end to
 * end**. The Reddit tool node has no Python implementation, so the agent silently
 * lost its tools and answered a database question from parametric knowledge —
 * confidently, about global music revenue, having queried nothing. A demo whose
 * first answer is a hallucination teaches the wrong thing about the product.
 *
 * This one exercises the parts worth showing:
 *
 * - a **tool bus** with three tools converging on one port,
 * - a **grader** carrying the developer's own criterion, and
 * - the **revise loop** — `grader.revise` back to `agent.feedback`, the only
 *   cycle the port types permit.
 *
 * Built by writing straight to the model rather than through commands, so opening
 * the app leaves an empty undo stack: the first Cmd-Z should undo the *user's*
 * first edit, not dismantle the example.
 */
export function seedDemoWorkflow(workbench: Workbench): void {
  const { model, registry } = workbench;

  // This demo *is* the Chinook showcase, seeded straight to the model
  // before any document exists for the usual workflow-scoped registration
  // (`registerNodeTypesForRawDocument`) to inspect — so it has to ask for
  // the tools it uses explicitly, rather than being inferred from a
  // document that doesn't exist yet.
  registerChinookNodes(registry, workbench.engine.executors);

  const create = (typeId: string, init: NodeInit): AbstractNodeModel => {
    const definition = registry.nodeTypes.require(typeId);
    const node = definition.create(init) as AbstractNodeModel;
    model.addNode(node);
    return node;
  };

  model.transact(() => {
    const question = create(NODE_TYPE.textInput, {
      position: { x: 40, y: 180 },
      data: {
        prompt: 'Which music genre earned the most revenue? Give the top 3.',
      },
    });

    const skill = create(NODE_TYPE.markdownFile, {
      position: { x: 40, y: 460 },
      data: {
        filename: 'sql-analyst.md',
        instruction: [
          'You answer questions by querying the Chinook database.',
          'List the tables, read the schema of the ones you need — the foreign keys',
          'tell you how to join — then run a single SELECT. State the SQL you used.',
        ].join(' '),
      },
    });

    // Created before the agent so it renders behind it. 340 wide leaves the
    // 252px card an even gutter, and the height clears the notes above it.
    const frame = create(NODE_TYPE.group, {
      position: { x: 400, y: 20 },
      size: { width: 340, height: 470 },
      data: {
        title: '🗄️ Ask the database',
        notes: [
          '1. Open **Ask** in the toolbar',
          '2. Type a question about the music store',
          '3. The agent reads the schema, writes SQL, runs it',
          '4. The **grader** checks the answer cites real figures',
          '5. If not, it goes back for a revision',
          '',
          '💡 Needs the Python backend running — the browser never executes a workflow.',
        ].join('\n'),
      },
    });

    const agent = create(NODE_TYPE.agent, { position: { x: 444, y: 260 } });
    model.setNodeParent(agent.id, frame.id);

    // Three tools on one bus, which is the point: `tools` is uncapped, so the
    // agent gains a capability per link rather than per node type.
    const listTables = create(NODE_TYPE.chinookGetAllTables, {
      position: { x: 200, y: 640 },
    });
    const getSchema = create(NODE_TYPE.chinookGetSchema, {
      position: { x: 480, y: 640 },
    });
    const runSql = create(NODE_TYPE.chinookExecuteSql, {
      position: { x: 760, y: 640 },
    });

    const grader = create(NODE_TYPE.grader, {
      position: { x: 830, y: 200 },
      data: {
        // The developer's criterion, *added* to the built-in ones rather than
        // replacing them — the default, and the safe direction.
        criteria: '- Must name the genres and quote their revenue figures.',
        criteriaMode: 'extend',
        maxAttempts: 3,
      },
    });

    const output = create(NODE_TYPE.formattedOutput, {
      position: { x: 1180, y: 200 },
    });

    // Wired directly rather than through `controller.edges.connect`: the seed is
    // known-valid, and going through commands would fill the undo stack.
    const connect = (
      source: AbstractNodeModel,
      sourcePort: string,
      target: AbstractNodeModel,
      targetPort: string,
    ) => {
      model.addEdge(
        new EdgeModel({
          source: { nodeId: source.id, portId: sourcePort },
          target: { nodeId: target.id, portId: targetPort },
        }),
      );
    };

    connect(question, 'text', agent, 'prompt');
    connect(skill, 'skill', agent, 'skill');
    connect(listTables, 'tool', agent, 'tools');
    connect(getSchema, 'tool', agent, 'tools');
    connect(runSql, 'tool', agent, 'tools');
    connect(agent, 'result', grader, 'candidate');
    connect(grader, 'pass', output, 'result');
    // The loop. Legal only because `revise` is a `feedback` port and
    // `agent.feedback` is the one input that accepts it.
    connect(grader, 'revise', agent, 'feedback');

    model.setName('Chinook · natural language to SQL');
  });
}
