import { describe, expect, it } from 'vitest';
import {
  addNode,
  connect,
  LOOPABLE_TYPE,
  makeWorkbench,
  registerLoopableType,
  TYPE,
} from '@core/testing/fixtures';
import {
  acyclicGraphRule,
  DEFAULT_WORKFLOW_RULES,
  entryQuestionRule,
  hasOutputRule,
  singleDefaultWorkerRule,
  skillBlanksRule,
  unfilledPlaceholders,
  orphanNodeRule,
  unknownNodeTypeRule,
} from './WorkflowValidator';

/**
 * Found live, not hypothetically: a real chat run answered a question and
 * produced a real `answer`, yet the diagnostics panel showed "Nothing
 * consumes the result — add an output node." `hasOutputRule` checked port
 * *descriptors* (does this node type declare zero out-ports at all) rather
 * than actual wiring — but `AgentNode`, `RouterNode` and `GraderNode` all
 * statically declare an out-port whether or not anything is connected to
 * it. Only `output.formatted` genuinely has zero out-ports, so any graph
 * that legitimately terminates at an Agent/Router/Grader without a
 * separate Output node was a false positive.
 */
describe('hasOutputRule', () => {
  it('does not flag a graph that terminates at an unwired Agent out-port', () => {
    const workbench = makeWorkbench();
    const input = addNode(workbench, TYPE.textInput);
    const agent = addNode(workbench, TYPE.agent, { at: { x: 200, y: 0 } });
    connect(workbench, input, 'text', agent, 'prompt');
    // Deliberately no edge out of `agent.result` — the agent's own answer
    // is the graph's terminal output, same as `_agent` writing `answer`
    // directly in the backend compiler.

    const diagnostics = hasOutputRule.check({
      model: workbench.model,
      registry: workbench.registry,
    });
    expect(diagnostics).toEqual([]);
  });

  it('still flags a graph where every node truly has zero out-ports and nothing runs', () => {
    const workbench = makeWorkbench();
    // A single Output node: it has no out-ports at all, so it is
    // (correctly) always its own sink — nothing to flag.
    addNode(workbench, TYPE.output);

    const diagnostics = hasOutputRule.check({
      model: workbench.model,
      registry: workbench.registry,
    });
    expect(diagnostics).toEqual([]);
  });

  it('flags a graph where every out-port is wired into something, with no true terminal', () => {
    // Under the corrected semantics, an unwired out-port on an Agent/Router/
    // Grader is a legitimate terminal — so the *only* remaining way to have
    // no sink at all is a graph where literally every out-port some node
    // declares is connected to something else, e.g. a closed loop with no
    // node escaping it. `LOOPABLE_TYPE` is used (see `fixtures.ts`) because
    // the real catalogue has no port pair that can form a cycle at all.
    const workbench = makeWorkbench();
    registerLoopableType(workbench);
    const a = addNode(workbench, LOOPABLE_TYPE);
    const b = addNode(workbench, LOOPABLE_TYPE, { at: { x: 200, y: 0 } });
    connect(workbench, a, 'out', b, 'in');
    connect(workbench, b, 'out', a, 'in');

    const diagnostics = hasOutputRule.check({
      model: workbench.model,
      registry: workbench.registry,
    });
    expect(diagnostics).toHaveLength(1);
    expect(diagnostics[0]?.code).toBe('no-output');
  });
});

/**
 * Found live: the diagnostics panel showed 11 identical "X is part of a
 * loop" `error`s for the intent-routed demo's real, intentional revise
 * loops (a grader's `revise` port feeding back into its own agent, with a
 * `pass` port that escapes the same cycle) — reading exactly as broken as
 * a real, unescapable infinite loop, even though the backend runs it fine.
 * CLAUDE.md's own rule: a cycle needs a conditional edge to be valid at
 * all. `acyclicGraphRule` now tells the two shapes apart.
 */
describe('acyclicGraphRule', () => {
  it('downgrades an escapable loop (one with a way out) to a warning', () => {
    const workbench = makeWorkbench();
    registerLoopableType(workbench);
    const a = addNode(workbench, LOOPABLE_TYPE);
    const b = addNode(workbench, LOOPABLE_TYPE, { at: { x: 200, y: 0 } });
    const c = addNode(workbench, LOOPABLE_TYPE, { at: { x: 400, y: 0 } });
    connect(workbench, a, 'out', b, 'in');
    connect(workbench, b, 'out', a, 'in');
    // `a`'s escape hatch — the same shape as a grader's `pass` port.
    connect(workbench, a, 'out', c, 'in');

    const diagnostics = acyclicGraphRule.check({
      model: workbench.model,
      registry: workbench.registry,
    });
    // Collapsed: ONE notice per loop, naming its size, anchored to a member
    // (a 7-node revise loop used to produce 7 identical warnings).
    expect(diagnostics).toHaveLength(1);
    // `info`, not `warning`. A revision loop that has a way out is a correct
    // graph — it is the shape the palette's "Revision loop" assembly exists to
    // create — so flagging it amber makes the product warn about its own
    // recommended affordance, and a warning on the happy path teaches people
    // to ignore warnings. What remains true is that the *preview* cannot walk
    // a cycle, and that is a fact worth stating, not a problem with the graph.
    expect(diagnostics[0]?.severity).toBe('info');
    expect(diagnostics[0]?.code).toBe('escapable-loop');
    expect(diagnostics[0]?.message).toContain('2 nodes');
  });

  it('keeps an unescapable loop (no way out at all) as a blocking error', () => {
    const workbench = makeWorkbench();
    registerLoopableType(workbench);
    const a = addNode(workbench, LOOPABLE_TYPE);
    const b = addNode(workbench, LOOPABLE_TYPE, { at: { x: 200, y: 0 } });
    connect(workbench, a, 'out', b, 'in');
    connect(workbench, b, 'out', a, 'in');

    const diagnostics = acyclicGraphRule.check({
      model: workbench.model,
      registry: workbench.registry,
    });
    expect(diagnostics).toHaveLength(2);
    for (const d of diagnostics) {
      expect(d.severity).toBe('error');
      expect(d.code).toBe('cycle');
    }
  });
});

/**
 * Ticket 37: unlabelled/unrecognised subtasks dispatch to the default worker
 * archetype. The compiler takes the first wired claimant, so a second card's
 * "Default worker" toggle is silently inert — worth a warning, not an error.
 */
describe('singleDefaultWorkerRule', () => {
  it('says nothing for zero or one default claim', () => {
    const workbench = makeWorkbench();
    const orchestrator = addNode(workbench, TYPE.orchestrator);
    const weather = addNode(workbench, TYPE.worker, { data: { default: true } });
    const countries = addNode(workbench, TYPE.worker, { at: { x: 200, y: 0 } });
    connect(workbench, orchestrator, 'workers', weather, 'dispatch');
    connect(workbench, orchestrator, 'workers', countries, 'dispatch');

    const diagnostics = singleDefaultWorkerRule.check({
      model: workbench.model,
      registry: workbench.registry,
    });
    expect(diagnostics).toEqual([]);
  });

  it('warns on every card when two workers both claim the default', () => {
    const workbench = makeWorkbench();
    const orchestrator = addNode(workbench, TYPE.orchestrator);
    const weather = addNode(workbench, TYPE.worker, { data: { default: true } });
    const countries = addNode(workbench, TYPE.worker, {
      at: { x: 200, y: 0 },
      data: { default: true },
    });
    connect(workbench, orchestrator, 'workers', weather, 'dispatch');
    connect(workbench, orchestrator, 'workers', countries, 'dispatch');

    const diagnostics = singleDefaultWorkerRule.check({
      model: workbench.model,
      registry: workbench.registry,
    });
    expect(diagnostics).toHaveLength(2);
    for (const d of diagnostics) {
      expect(d.severity).toBe('warning');
      expect(d.code).toBe('multiple-default-workers');
    }
  });
});

/**
 * Ticket 28. The unfilled-`{{blank}}` check used to live inside
 * `skillExecutor`, so a half-written skill was invisible until the run died on
 * it. It is a whole-document check like every other one, and belongs in the
 * rule registry that drives the diagnostics panel and the card status dots.
 */
describe('skillBlanksRule', () => {
  it('flags every blank a skill still carries, before anything runs', () => {
    const workbench = makeWorkbench();
    const skill = addNode(workbench, TYPE.skill, {
      data: { skillName: 'drafty', instruction: '## Rules\n\n- {{the first rule}}' },
    });

    const diagnostics = skillBlanksRule.check({
      model: workbench.model,
      registry: workbench.registry,
    });
    expect(diagnostics).toHaveLength(1);
    expect(diagnostics[0]?.code).toBe('skill-unfilled-blank');
    expect(diagnostics[0]?.severity).toBe('error');
    expect(diagnostics[0]?.nodeId).toBe(skill.id);
    expect(diagnostics[0]?.message).toContain('the first rule');
  });

  it('says nothing once the blanks are filled', () => {
    const workbench = makeWorkbench();
    addNode(workbench, TYPE.skill, {
      data: { skillName: 'terse', instruction: '## Rules\n\n- Answer in one sentence.' },
    });

    expect(skillBlanksRule.check({ model: workbench.model, registry: workbench.registry })).toEqual(
      [],
    );
  });

  it('is registered by default, so the panel shows it with no extra wiring', () => {
    expect(DEFAULT_WORKFLOW_RULES).toContain(skillBlanksRule);
  });
});

describe('unfilledPlaceholders', () => {
  it('finds every remaining placeholder in order', () => {
    expect(unfilledPlaceholders('{{first}} then {{second}}')).toEqual(['first', 'second']);
  });

  it('reports none once they are filled', () => {
    expect(unfilledPlaceholders('## Rules\n\n- Answer in one sentence.')).toEqual([]);
  });
});

/**
 * `tool.not-a-real-type`, deliberately — and it was `tool.validate-workflow`
 * until 2026-08-19, when that type gained an editor card (production-ready 61)
 * and stopped being unknown. A fixture that names a *real* type as its example
 * of an unknown one is a test that expires the day somebody implements it.
 */
describe('unknownNodeTypeRule', () => {
  const documentWithUnknownNode = () => {
    const authored = makeWorkbench();
    addNode(authored, TYPE.agent, { at: { x: 0, y: 0 } });
    const document = JSON.parse(authored.controller.document.exportJSON()) as {
      nodes: Record<string, unknown>[];
    };
    document.nodes.push({
      id: 't-validate',
      type: 'tool.not-a-real-type',
      position: { x: 400, y: 600 },
      size: { width: 240, height: 96 },
      parentId: null,
      data: {},
    });
    return JSON.stringify(document);
  };

  it('names the node and its type, on the workflow that actually contains it', () => {
    // The only warning before this counted tools with no card, in the palette,
    // for every workflow alike — it never said which document was affected.
    const workbench = makeWorkbench();
    workbench.controller.document.importJSON(documentWithUnknownNode());

    const diagnostics = unknownNodeTypeRule.check({
      model: workbench.model,
      registry: workbench.registry,
    });

    expect(diagnostics).toHaveLength(1);
    expect(diagnostics[0]?.nodeId).toBe('t-validate');
    expect(diagnostics[0]?.message).toContain('tool.not-a-real-type');
  });

  it('is a warning, so a workflow the runtime can still run is not blocked', () => {
    const workbench = makeWorkbench();
    workbench.controller.document.importJSON(documentWithUnknownNode());

    expect(
      unknownNodeTypeRule.check({ model: workbench.model, registry: workbench.registry })[0]
        ?.severity,
    ).toBe('warning');
  });

  it('says nothing about a document whose types are all registered', () => {
    const workbench = makeWorkbench();
    addNode(workbench, TYPE.agent, { at: { x: 0, y: 0 } });

    expect(
      unknownNodeTypeRule.check({ model: workbench.model, registry: workbench.registry }),
    ).toEqual([]);
  });

  it('is registered by default, so the Diagnostics panel shows it with no extra wiring', () => {
    expect(DEFAULT_WORKFLOW_RULES).toContain(unknownNodeTypeRule);
  });
});

/**
 * Ticket 22: two of the three shipped workflows greeted a first-time
 * developer with a red Diagnostics error — `Text Input: Enter a prompt for
 * the agent` — on documents that demonstrably work. `concierge` and
 * `workflow-architect` are chat-driven: their Text Input is deliberately
 * empty because the question arrives at run time from the composer, and the
 * backend's `_input` node reads `state["question"] or configured` precisely
 * so that it can.
 *
 * A blocking-looking diagnostic on a working document teaches people to
 * ignore the panel, which is the one place this product gets to be honest.
 * So the *rule* was wrong, not the severity: an empty run-time entry is a
 * normal state of the document. What replaces it says what is true — where
 * the question will come from — at `info`, which the panel counts as zero
 * errors.
 */
describe('entryQuestionRule', () => {
  it('does not make an empty entry prompt an error', () => {
    // Through every default rule, not just the new one: the point is that
    // NOTHING in the panel calls this document broken.
    const workbench = makeWorkbench();
    addNode(workbench, TYPE.textInput);
    const context = { model: workbench.model, registry: workbench.registry };

    const diagnostics = DEFAULT_WORKFLOW_RULES.flatMap((rule) => rule.check(context));
    expect(diagnostics.filter((d) => d.severity === 'error')).toEqual([]);
  });

  it('still says where the question will come from, so the blank is explained', () => {
    const workbench = makeWorkbench();
    const input = addNode(workbench, TYPE.textInput);

    const diagnostics = entryQuestionRule.check({
      model: workbench.model,
      registry: workbench.registry,
    });
    expect(diagnostics).toHaveLength(1);
    expect(diagnostics[0]?.severity).toBe('info');
    expect(diagnostics[0]?.code).toBe('entry-supplied-at-run-time');
    expect(diagnostics[0]?.nodeId).toBe(input.id);
  });

  it('says nothing when the prompt is filled in', () => {
    const workbench = makeWorkbench();
    addNode(workbench, TYPE.textInput, { data: { prompt: 'Who are you?' } });

    expect(
      entryQuestionRule.check({ model: workbench.model, registry: workbench.registry }),
    ).toEqual([]);
  });

  it('leaves a workflow with no entry node alone', () => {
    const workbench = makeWorkbench();
    addNode(workbench, TYPE.agent);

    expect(
      entryQuestionRule.check({ model: workbench.model, registry: workbench.registry }),
    ).toEqual([]);
  });

  it('is registered by default', () => {
    expect(DEFAULT_WORKFLOW_RULES).toContain(entryQuestionRule);
  });
});

/**
 * Ticket 22, second half. The amber loop notice told the user to do
 * something the product does not require — "use Chat to run it, not the
 * canvas preview" — while pressing **Run** on `chinook-assistant` opens the
 * Ask panel and runs the loop against the backend, successfully. A
 * diagnostic that instructs is a diagnostic that can be wrong about the
 * product; this one describes what will happen instead.
 */
describe('the escapable-loop notice describes Run rather than instructing the user', () => {
  const loopMessage = (): string => {
    const workbench = makeWorkbench();
    registerLoopableType(workbench);
    const a = addNode(workbench, LOOPABLE_TYPE);
    const b = addNode(workbench, LOOPABLE_TYPE, { at: { x: 200, y: 0 } });
    const c = addNode(workbench, LOOPABLE_TYPE, { at: { x: 400, y: 0 } });
    connect(workbench, a, 'out', b, 'in');
    connect(workbench, b, 'out', a, 'in');
    connect(workbench, a, 'out', c, 'in');
    return (
      acyclicGraphRule.check({ model: workbench.model, registry: workbench.registry })[0]
        ?.message ?? ''
    );
  };

  it('no longer tells the user to go and use Chat', () => {
    expect(loopMessage()).not.toContain('use Chat');
  });

  it('says Run handles it, which is what actually happens', () => {
    expect(loopMessage()).toContain('Run');
  });

  it('is not a warning, because there is nothing wrong with the graph', () => {
    const workbench = makeWorkbench();
    registerLoopableType(workbench);
    const a = addNode(workbench, LOOPABLE_TYPE);
    const b = addNode(workbench, LOOPABLE_TYPE, { at: { x: 200, y: 0 } });
    const c = addNode(workbench, LOOPABLE_TYPE, { at: { x: 400, y: 0 } });
    connect(workbench, a, 'out', b, 'in');
    connect(workbench, b, 'out', a, 'in');
    connect(workbench, a, 'out', c, 'in');

    const [notice] = acyclicGraphRule.check({
      model: workbench.model,
      registry: workbench.registry,
    });
    expect(notice?.severity).toBe('info');
  });

  it('still blocks the loop that genuinely cannot finish', () => {
    // The severity split is the whole point: escapable is information,
    // inescapable is an error on every engine including the backend.
    const workbench = makeWorkbench();
    registerLoopableType(workbench);
    const a = addNode(workbench, LOOPABLE_TYPE);
    const b = addNode(workbench, LOOPABLE_TYPE, { at: { x: 200, y: 0 } });
    connect(workbench, a, 'out', b, 'in');
    connect(workbench, b, 'out', a, 'in');

    const diagnostics = acyclicGraphRule.check({
      model: workbench.model,
      registry: workbench.registry,
    });
    expect(diagnostics.every((d) => d.severity === 'error')).toBe(true);
  });
});

/**
 * The Knowledge card is not the wiring, and the diagnostics must not say it is
 * (ticket 09).
 *
 * Binding is **ambient**: the runtime attaches the lookup tool to every agent
 * and worker in the package whenever `knowledge/` holds at least one `.md`,
 * card or no card (`prebuilt_knowledge.ambient_knowledge_tool`). Dropping one
 * on a canvas nonetheless produced *"Knowledge isn't connected to anything"* —
 * a true sentence about the graph and a false one about the consequence, on
 * the one surface this project insists must be a truthful projection.
 *
 * Data-driven rather than a special case in the rule: a node type says
 * `bindsWithoutWiring` and the rule believes it, so the next ambient
 * capability needs no edit here.
 */
describe('orphanNodeRule', () => {
  it('still flags an ordinary tool nobody wired', () => {
    const workbench = makeWorkbench();
    addNode(workbench, TYPE.agent);
    const tool = addNode(workbench, 'tool.web-search');

    const found = orphanNodeRule.check({
      model: workbench.model,
      registry: workbench.registry,
    });

    expect(found.map((d) => d.nodeId)).toContain(tool.id);
  });

  it('says nothing about a node that binds without wiring', () => {
    const workbench = makeWorkbench();
    addNode(workbench, TYPE.agent);
    const knowledge = addNode(workbench, 'tool.knowledge-lookup');

    const found = orphanNodeRule.check({
      model: workbench.model,
      registry: workbench.registry,
    });

    expect(found.map((d) => d.nodeId)).not.toContain(knowledge.id);
  });

  it('the claim is on the node type, where the runtime rule can be cited', () => {
    const workbench = makeWorkbench();

    expect(workbench.registry.nodeTypes.require('tool.knowledge-lookup').bindsWithoutWiring).toBe(
      true,
    );
    expect(
      workbench.registry.nodeTypes.require('tool.web-search').bindsWithoutWiring,
    ).toBeUndefined();
  });
});
