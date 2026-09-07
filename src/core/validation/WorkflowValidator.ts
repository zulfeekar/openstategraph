import { Registry, type IIdentifiable } from '@core/kernel/Registry';
import type { ModelRegistry } from '@core/model/ModelRegistry';
import type { WorkflowModel } from '@core/model/WorkflowModel';
import { validateFields } from '@core/model/contracts/fields';
import { cyclicMembers } from '@core/model/topology';
import type { NodeId } from '@core/model/contracts/node';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';

export type DiagnosticSeverity = 'error' | 'warning' | 'info';

export interface Diagnostic {
  readonly code: string;
  readonly severity: DiagnosticSeverity;
  readonly message: string;
  /** Node the problem is attached to, when it has one. */
  readonly nodeId?: NodeId;
  /** Field key within that node, when the problem is a specific input. */
  readonly fieldKey?: string;
}

export interface WorkflowRuleContext {
  readonly model: WorkflowModel;
  readonly registry: ModelRegistry;
}

export interface IWorkflowRule extends IIdentifiable {
  readonly id: string;
  check(ctx: WorkflowRuleContext): readonly Diagnostic[];
}

/**
 * Whole-graph checks, run before a workflow executes and continuously to
 * drive per-node status dots.
 *
 * Separate from `ConnectionValidator`, which answers a local question
 * about one prospective link. This answers "is the document runnable",
 * which is a different lifecycle and a different set of rules.
 */
export class WorkflowValidator {
  readonly rules = new Registry<IWorkflowRule>('workflowRules');

  constructor(
    private readonly model: WorkflowModel,
    private readonly registry: ModelRegistry,
  ) {}

  validate(): readonly Diagnostic[] {
    const ctx: WorkflowRuleContext = { model: this.model, registry: this.registry };
    const diagnostics: Diagnostic[] = [];
    for (const rule of this.rules.list()) {
      try {
        diagnostics.push(...rule.check(ctx));
      } catch (error) {
        // A broken rule must not block a run; report it as a diagnostic.
        diagnostics.push({
          code: 'rule-failed',
          severity: 'warning',
          message: `Validation rule "${rule.id}" failed: ${String(error)}`,
        });
      }
    }
    return diagnostics;
  }

  /** Diagnostics grouped by node, for rendering status on the cards. */
  byNode(): Map<NodeId, Diagnostic[]> {
    const grouped = new Map<NodeId, Diagnostic[]>();
    for (const diagnostic of this.validate()) {
      if (!diagnostic.nodeId) continue;
      const bucket = grouped.get(diagnostic.nodeId);
      if (bucket) bucket.push(diagnostic);
      else grouped.set(diagnostic.nodeId, [diagnostic]);
    }
    return grouped;
  }

  get isRunnable(): boolean {
    return !this.validate().some((d) => d.severity === 'error');
  }
}

/* ================================================================== *
 * Default rules
 * ================================================================== */

/** Every port marked `required` must be wired. */
export const requiredInputsRule: IWorkflowRule = {
  id: 'required-inputs',
  check({ model }) {
    const diagnostics: Diagnostic[] = [];
    for (const node of model.nodes()) {
      if (node.kind !== 'standard') continue;
      for (const port of node.ports) {
        if (port.direction !== 'in' || !port.required) continue;
        const connected = model.edgesInto({ nodeId: node.id, portId: port.id }).length > 0;
        if (!connected) {
          diagnostics.push({
            code: 'required-input-missing',
            severity: 'error',
            nodeId: node.id,
            message: `${node.title} needs a "${port.label}" input`,
          });
        }
      }
    }
    return diagnostics;
  },
};

/** Field-level validators declared in each node type's schema. */
export const fieldValidationRule: IWorkflowRule = {
  id: 'fields',
  check({ model }) {
    const diagnostics: Diagnostic[] = [];
    for (const node of model.nodes()) {
      const errors = validateFields(node.definition.fields, node.data);
      for (const [fieldKey, message] of Object.entries(errors)) {
        diagnostics.push({
          code: 'field-invalid',
          severity: 'error',
          nodeId: node.id,
          fieldKey,
          message: `${node.title}: ${message}`,
        });
      }
    }
    return diagnostics;
  },
};

/**
 * Cycles.
 *
 * `ConnectionValidator` already refuses to draw one, but a document can
 * arrive cyclic from an import or a hand-edited file, so the runnable check
 * cannot assume acyclicity.
 *
 * Not every cycle is the same *kind* of problem. CLAUDE.md's own rule: "a
 * cycle must contain at least one conditional edge — an all-static cycle
 * can never terminate." A grader's `revise` port looping back to its own
 * agent is exactly the valid case — the same node also has a `pass` port
 * that escapes the cycle, so the loop terminates the moment the grader
 * passes. That shape is legitimate for the backend LangGraph compiler,
 * just unrunnable by this engine's local, sequential DAG preview.
 *
 * A cycle with **no** escaping edge at all — every node in it only ever
 * feeds back into the cycle, never out — is the other case: an accidental,
 * genuinely infinite loop, which is a real bug regardless of which engine
 * runs it. Flagging both identically as `error` made a legitimate,
 * intentional revise loop (in a graph that runs correctly through the
 * backend) look exactly as broken as one that can never produce an answer
 * on any engine. Only the second kind should block a static "is this
 * runnable" check; the first is a `warning` — noteworthy, not broken.
 */
export const acyclicGraphRule: IWorkflowRule = {
  id: 'acyclic-graph',
  check({ model }) {
    const { cycle: blocked } = model.topologicalOrder();
    if (!blocked || blocked.length === 0) return [];

    // `topologicalOrder()`'s `cycle` is Kahn's leftover set: every node
    // whose in-degree never reached zero. That over-includes anything
    // merely *downstream* of a cycle (blocked because its dependency never
    // finished), not only the cycle's own members — found by this rule's
    // own escape check misfiring: a node three hops past the actual loop,
    // with no edge back into anything, still landed in that set and made
    // the escape look absent. A node is truly *in* the cycle only if a
    // path exists from it back to itself using edges between other members
    // of the leftover set.
    //
    // Answered for the whole set in **one** pass rather than one traversal
    // per member. The over-inclusion above is deliberate and stays; what
    // was wrong was the price of narrowing it, O(V·(V+E)) exactly when a
    // cycle exists — and a cycle is a feature here, not an accident (the
    // audit of 2026-08-15 measured 48 ms on 800 nodes, inside the render
    // that every node drag causes). `cyclicMembers` is Tarjan: a node is on
    // a cycle iff its SCC has more than one member, or it has a self-edge.
    // Same membership, same order, same messages — pinned by this rule's
    // existing cases and by `acyclicGraphRule.scaling.test.ts`.
    const candidates = new Set(blocked);
    const inCycle = cyclicMembers(candidates, (nodeId) =>
      model
        .edgesOf(nodeId)
        .filter((edge) => edge.source.nodeId === nodeId)
        .map((edge) => edge.target.nodeId),
    );
    const cycle = blocked.filter((nodeId) => inCycle.has(nodeId));
    const hasEscape = cycle.some((nodeId) =>
      model
        .edgesOf(nodeId)
        .some((edge) => edge.source.nodeId === nodeId && !inCycle.has(edge.target.nodeId)),
    );

    if (hasEscape) {
      // ONE notice per loop, not one per member (found during ticket 42's
      // UI check: a 7-node revise loop produced 7 identical warnings, which
      // reads as 7 problems). Anchored to the first member so clicking it
      // still lands somewhere real; the message names the loop's size.
      const first = cycle[0];
      if (first === undefined) return [];
      const titles = cycle.map((nodeId) => model.node(nodeId)?.title ?? nodeId);
      const shown = titles.slice(0, 3).join(', ') + (titles.length > 3 ? ', …' : '');
      return [
        {
          code: 'escapable-loop',
          // `info`, not `warning`. A revision loop with a way out is a
          // *correct* graph — it is precisely the shape the palette's
          // "Revision loop" assembly exists to create — so amber here makes
          // the product warn about its own recommended affordance, and a
          // warning on the happy path is how people learn to ignore warnings.
          //
          // The sentence itself stays, because it is genuinely worth knowing:
          // the in-canvas preview is a sequential DAG walk and a cycle has no
          // topological order, so only that engine cannot follow it. That is
          // a fact about the preview, not a defect in the graph — which is
          // exactly what `info` means and `warning` does not.
          severity: 'info' as const,
          nodeId: first,
          // Describes what Run will do, rather than instructing the user to
          // do something instead (ticket 22). The old wording — "use Chat to
          // run it, not the canvas preview" — told people to go elsewhere
          // for a thing the button already does: pressing Run on
          // `chinook-assistant` opens the Ask panel, streams the loop
          // through the backend and finishes ("2 attempts before the grader
          // passed it"). Only the in-canvas *preview* engine, a sequential
          // DAG walk, cannot follow a cycle, and that is a fact about the
          // preview, not an instruction to the reader.
          message: `This workflow contains a revision loop (${titles.length} nodes: ${shown}) — Run streams it through the backend, which handles loops; only the in-canvas step preview cannot follow one`,
        },
      ];
    }
    return cycle.map((nodeId) => {
      const title = model.node(nodeId)?.title ?? nodeId;
      return {
        code: 'cycle',
        severity: 'error' as const,
        nodeId,
        message: `${title} is part of a loop with no way out — this can never finish`,
      };
    });
  },
};

/**
 * A graph with no terminal node produces nothing observable.
 *
 * "Terminal" means unwired downstream, not "has zero declared out-ports" —
 * found live: `AgentNode`, `RouterNode` and `GraderNode` all statically
 * declare a `result`/branch out-port regardless of whether anything is
 * connected to it, so a workflow that legitimately ends in one of them
 * without a separate `Output` node (the backend compiler supports this
 * fine — `_agent`/`_format_report_function` write `answer` directly) was
 * flagged "nothing consumes the result" even though the run produces a real
 * answer. Only `output.formatted` has literally zero out-ports; checking
 * port *descriptors* instead of actual edges made every other node type a
 * false positive.
 */
export const hasOutputRule: IWorkflowRule = {
  id: 'has-output',
  check({ model }) {
    const executable = model.nodes().filter((node) => node.kind === 'standard');
    if (executable.length === 0) return [];
    const hasSink = executable.some((node) => {
      const outPorts = node.ports.filter((p) => p.direction === 'out');
      if (outPorts.length === 0) return true;
      return outPorts.every(
        (port) => model.edgesFrom({ nodeId: node.id, portId: port.id }).length === 0,
      );
    });
    return hasSink
      ? []
      : [
          {
            code: 'no-output',
            severity: 'warning',
            message: 'Nothing consumes the result — add an output node',
          },
        ];
  },
};

/**
 * Names, on *this* workflow, every node this build cannot render.
 *
 * The only warning before this was a generic amber note in the palette
 * sidebar counting tools with no editor card. It named a *class* of tools; it
 * never said "the workflow you are looking at right now contains one", which
 * is the only form of the fact anyone can act on.
 *
 * **A warning, not an error, and the distinction is now honest.** It was
 * proposed as an error while the node was being silently deleted — at that
 * point the document really was being damaged. The serializer now preserves
 * it (`serialization/UnknownNode.ts`) and the backend compiles it to a
 * passthrough, so the workflow still loads, still saves byte-identically and
 * still runs. Marking it an error would make `isRunnable` false and block Run
 * on a workflow that works, which is a different bug wearing this one's
 * clothes. The node cannot be *edited* here, and that is exactly what this
 * says.
 */
export const unknownNodeTypeRule: IWorkflowRule = {
  id: 'unknown-node-type',
  check({ model, registry }) {
    const diagnostics: Diagnostic[] = [];
    for (const node of model.nodes()) {
      if (registry.nodeTypes.get(node.type) != null) continue;
      diagnostics.push({
        code: 'unknown-node-type',
        severity: 'warning',
        nodeId: node.id,
        message:
          `"${node.id}" has no editor card for its type "${node.type}" — ` +
          'it is preserved exactly as saved and still runs, but it cannot be edited here.',
      });
    }
    return diagnostics;
  },
};

/** Nodes wired to nothing at all will never run — unless their capability
 * binds without wiring, which `bindsWithoutWiring` is how a type says. */
export const orphanNodeRule: IWorkflowRule = {
  id: 'orphan-nodes',
  check({ model }) {
    const executable = model.nodes().filter((node) => node.kind === 'standard');
    // A lone node on a fresh canvas is normal, not a warning.
    if (executable.length < 2) return [];
    return executable
      .filter(
        (node) =>
          node.ports.length > 0 &&
          model.edgesOf(node.id).length === 0 &&
          // A type that binds ambiently is doing its job unwired, so saying it
          // "isn't connected to anything" describes the graph and misdescribes
          // the run (ticket 09). Read off the definition, never a list here.
          !node.definition.bindsWithoutWiring,
      )
      .map((node) => ({
        code: 'orphan-node',
        severity: 'info' as const,
        nodeId: node.id,
        message: `${node.title} isn't connected to anything`,
      }));
  },
};

/**
 * At most one worker per orchestrator may claim "Default worker".
 *
 * Ticket 37's hybrid routing sends unlabelled/unrecognised subtasks to the
 * default archetype. Two claims is not a broken document — the compiler
 * deterministically takes the first wired claimant — but the second card's
 * toggle is silently inert, which is exactly the kind of thing a developer
 * should be told rather than left to discover from dispatch behaviour.
 */
export const singleDefaultWorkerRule: IWorkflowRule = {
  id: 'single-default-worker',
  check({ model }) {
    const diagnostics: Diagnostic[] = [];
    for (const node of model.nodes()) {
      if (node.type !== 'orchestrate.supervisor') continue;
      const claimants = model
        .edgesFrom({ nodeId: node.id, portId: 'workers' })
        .map((edge) => model.node(edge.target.nodeId))
        // A type predicate, not a `!` at each use: the guard and the narrowing
        // are the same statement, so they cannot drift apart.
        .filter(
          (worker): worker is AbstractNodeModel =>
            worker != null && worker.data['default'] === true,
        );
      if (claimants.length < 2) continue;
      for (const worker of claimants) {
        diagnostics.push({
          code: 'multiple-default-workers',
          severity: 'warning',
          nodeId: worker.id,
          message: `${worker.title}: more than one worker claims "Default worker" — only the first wired one takes effect`,
        });
      }
    }
    return diagnostics;
  },
};

/**
 * The node type whose template ships with blanks, and the key its body lives
 * under.
 *
 * Two literals rather than an import: `core/` depends on no node module — the
 * dependency runs the other way, and `singleDefaultWorkerRule` above already
 * names `orchestrate.supervisor` the same way. `port_specs.json` is what pins
 * the spelling against the catalogue, in both languages.
 */
const SKILL_TYPE = 'input.skill';
const SKILL_BODY_KEY = 'instruction';

/** The marker a Skill's template leaves where a developer must write. */
const PLACEHOLDER = /\{\{([^}]+)\}\}/g;

/** Every `{{blank}}` still unfilled in `text`, in the order they appear. */
export function unfilledPlaceholders(text: string): string[] {
  return [...text.matchAll(PLACEHOLDER)].map((match) => match[1]?.trim() ?? '');
}

/**
 * A Skill still carrying the blanks its template shipped with.
 *
 * Passing one through means `{{the first rule}}` reaches a model as an
 * instruction; deleting it means a half-written skill runs as if it were
 * finished. Neither failure announces itself, so it is an error — but a
 * *diagnostic* error, raised here rather than inside `skillExecutor` where it
 * only ever surfaced once a run had already started. A half-written document
 * is exactly what this registry exists to show before the run button.
 */
export const skillBlanksRule: IWorkflowRule = {
  id: 'skill-blanks',
  check({ model }) {
    const diagnostics: Diagnostic[] = [];
    for (const node of model.nodes()) {
      if (node.type !== SKILL_TYPE) continue;
      const body = node.data[SKILL_BODY_KEY];
      const blanks = unfilledPlaceholders(typeof body === 'string' ? body : '');
      if (blanks.length === 0) continue;
      diagnostics.push({
        code: 'skill-unfilled-blank',
        severity: 'error',
        nodeId: node.id,
        fieldKey: SKILL_BODY_KEY,
        message: `${node.title} still has ${blanks.length} blank(s) to fill: ${blanks.join('; ')}`,
      });
    }
    return diagnostics;
  },
};

/**
 * The entry node type, and the field its prompt lives in.
 *
 * Literals, like `SKILL_TYPE` and `singleDefaultWorkerRule`'s
 * `orchestrate.supervisor` above: `core/` depends on no node module, the
 * dependency runs the other way, and `port_specs.json` pins the spelling
 * against the catalogue in both languages.
 */
const ENTRY_TYPE = 'input.text';
const ENTRY_PROMPT = 'prompt';

/**
 * An entry prompt left blank is where the question comes in, not a defect.
 *
 * Ticket 22, found on the shipped examples. `concierge` and
 * `workflow-architect` both opened with a red Diagnostics error —
 * `Text Input: Enter a prompt for the agent` — on documents that answer
 * correctly through Chat, refuse unanswerable questions honestly and carry
 * conversation memory across turns. The rule was simply wrong: these are
 * chat-driven workflows, the field is *supposed* to be empty, and the
 * backend's `_input` node reads `state["question"] or configured` exactly so
 * that a saved workflow answers **this** run rather than replaying whatever
 * was typed when it was saved.
 *
 * The cost of getting this wrong is not cosmetic. A red error on a working
 * flagship example trains a first-time developer to ignore the one panel
 * that exists to be believed — and `isRunnable` is computed from `error`
 * severity, so a false error is one refactor away from blocking a run on a
 * workflow that works.
 *
 * So this replaces the field validator rather than downgrading it, and says
 * the true thing instead: the question will arrive at run time. `info`,
 * because the Diagnostics badge counts errors — a document in a normal state
 * must not raise the count.
 *
 * **It is deliberately not silent.** A blank field with no explanation is
 * the other failure: a developer who meant to type a prompt and did not gets
 * told where the text is expected to come from, and a developer who meant it
 * gets a sentence confirming they are right.
 */
export const entryQuestionRule: IWorkflowRule = {
  id: 'entry-question',
  check({ model }) {
    const diagnostics: Diagnostic[] = [];
    for (const node of model.nodes()) {
      if (node.type !== ENTRY_TYPE) continue;
      const prompt = node.data[ENTRY_PROMPT];
      if (typeof prompt === 'string' && prompt.trim() !== '') continue;
      diagnostics.push({
        code: 'entry-supplied-at-run-time',
        severity: 'info',
        nodeId: node.id,
        fieldKey: ENTRY_PROMPT,
        message:
          `${node.title} has no prompt, so this workflow takes its question at run time — ` +
          'Chat and the Ask panel supply it. Type one here to give Run something to send.',
      });
    }
    return diagnostics;
  },
};

export const DEFAULT_WORKFLOW_RULES: readonly IWorkflowRule[] = [
  requiredInputsRule,
  fieldValidationRule,
  entryQuestionRule,
  acyclicGraphRule,
  hasOutputRule,
  orphanNodeRule,
  singleDefaultWorkerRule,
  skillBlanksRule,
  unknownNodeTypeRule,
];
