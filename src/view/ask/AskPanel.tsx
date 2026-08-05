import { useCallback, useMemo, useState } from 'react';
import { Send, TriangleAlert } from 'lucide-react';
import {
  Button,
  Field,
  Icon,
  Panel,
  PanelBody,
  PanelHeader,
  PanelSection,
  TextInput,
} from '@design/primitives';
import { RuntimeClient, type RunResult, type RunStreamEvent } from '@core/runtime/RuntimeClient';
import { useController } from '@app/WorkbenchContext';
import './AskPanel.css';

/** One row in the live "Activity" feed — a node that has started running. */
interface ActivityRow {
  readonly node: string;
  /** Distinguishes concurrently dispatched worker instances (ticket 27). */
  readonly taskId: string | null;
}

/**
 * Ask the workflow a question, and watch it run.
 *
 * The whole point of this panel is that it sends **the document on the canvas**
 * to the runtime — not a server-side graph and not the browser's own engine. So
 * what a developer sees is what ran, and the per-node outputs coming back are the
 * evidence for that rather than a claim about it.
 *
 * Streamed rather than a single blocking response, because ticket 27's sidebar
 * needs to show **which node is currently in charge** as the run happens — a
 * router's branch, a fan-out's dispatched workers, a revise loop's extra lap —
 * not only the outcome once everything has finished. The canvas highlight
 * follows the same feed: each `update` selects that node, live, so the running
 * workflow reads as motion across the graph rather than a spinner.
 *
 * Deliberately thin. It holds no credentials, builds no graph, and does not know
 * what LangGraph is; it serialises the document, posts it, and renders what
 * streams back (ticket 07).
 */
export function AskPanel() {
  const controller = useController();
  const [question, setQuestion] = useState('');
  const [running, setRunning] = useState(false);
  const [activity, setActivity] = useState<readonly ActivityRow[]>([]);
  const [result, setResult] = useState<RunResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // One client for the panel's lifetime; the base URL is a dev default until
  // configuration exists.
  const client = useMemo(() => new RuntimeClient(), []);

  const ask = useCallback(async () => {
    const trimmed = question.trim();
    if (trimmed === '' || running) return;

    setRunning(true);
    setError(null);
    setResult(null);
    setActivity([]);

    // Serialised through the same path as “export”, so the runtime receives
    // exactly the bytes that would be saved — no second representation.
    const document = JSON.parse(controller.document.exportJSON()) as unknown;
    const seen = new Set<string>();

    const onEvent = (event: RunStreamEvent) => {
      if (event.type !== 'update') return;
      // Highlight whichever node just acted — the "currently in charge" the
      // ticket asks for. A dispatched worker's `taskId` still selects the
      // one static Worker node on the canvas; there is nowhere else for a
      // runtime task instance to be shown (ticket 27's own finding: `Send`
      // creates tasks, never new canvas nodes).
      controller.selectionActions.selectNodes([event.node]);
      setActivity((rows) => [...rows, { node: event.node, taskId: event.taskId }]);
      seen.add(event.node);
    };

    const outcome = await client.runStream({ workflow: document, question: trimmed }, onEvent);

    if (outcome.ok) {
      setResult(outcome.value);
      // Once finished, show the whole path that ran rather than just the
      // last node the stream happened to touch.
      controller.selectionActions.selectNodes([...seen]);
    } else {
      setError(outcome.error);
    }
    setRunning(false);
  }, [client, controller, question, running]);

  return (
    <Panel side="right" className="ask" style={{ width: 'var(--layout-inspector-width)' }}>
      <PanelHeader bordered title="Ask" />
      <PanelBody>
        <PanelSection heading="Question">
          <Field label="Natural language">
            <TextInput
              value={question}
              placeholder="Which genre earned the most revenue?"
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                // Enter runs it. A question is one line, so a newline would be
                // less useful than the shortcut.
                if (event.key === 'Enter' && !event.shiftKey) void ask();
              }}
            />
          </Field>
          <Button
            variant="primary"
            icon={<Icon glyph={Send} size="sm" />}
            disabled={running || question.trim() === ''}
            onClick={() => void ask()}
          >
            {running ? 'Running…' : 'Ask the workflow'}
          </Button>
        </PanelSection>

        {error ? (
          <PanelSection heading="Could not run">
            <p className="ask__error">
              <Icon glyph={TriangleAlert} size="sm" />
              {error}
            </p>
          </PanelSection>
        ) : null}

        {running || (activity.length > 0 && !result) ? <Activity rows={activity} /> : null}

        {result ? <Answer result={result} /> : null}
      </PanelBody>
    </Panel>
  );
}

/**
 * The live feed: which node just acted, in order, as the stream reports it.
 *
 * This is what makes a fan-out visible — three dispatched worker rows with
 * distinct `taskId`s appear one at a time as `Send` schedules them, rather
 * than a single spinner that gives no sense a fan-out happened at all.
 */
function Activity({ rows }: { rows: readonly ActivityRow[] }) {
  return (
    <PanelSection heading="Activity">
      {rows.length === 0 ? <p className="ask__meta">Waiting for the first node to run…</p> : null}
      {rows.map((row, index) => (
        <div key={`${row.node}-${row.taskId ?? index}`} className="ask__activity-row">
          <span className="ask__activity-node">{row.node.replace(/^node:/, '')}</span>
          {row.taskId ? <span className="ask__activity-task">{row.taskId}</span> : null}
        </div>
      ))}
    </PanelSection>
  );
}

function Answer({ result }: { result: RunResult }) {
  const decisions = Object.entries(result.decisions);

  return (
    <>
      <PanelSection heading="Answer">
        <pre className="ask__answer">{result.answer || '_No answer was produced._'}</pre>
      </PanelSection>

      {result.attempts > 1 ? (
        <PanelSection heading="Revisions">
          {/* Surfaced because a silent retry hides real cost and real quality
              signal — two attempts means the grader rejected the first. */}
          <p className="ask__meta">{result.attempts} attempts before the grader passed it.</p>
        </PanelSection>
      ) : null}

      {decisions.length > 0 ? (
        <PanelSection heading="Path taken">
          {decisions.map(([nodeId, branch]) => (
            <div key={nodeId} className="ask__decision">
              <span className="ask__decision-node">{nodeId.replace(/^node:/, '')}</span>
              <span className="ask__decision-branch">{branch}</span>
            </div>
          ))}
        </PanelSection>
      ) : null}

      {result.warnings.length > 0 ? (
        <PanelSection heading="Warnings">
          {result.warnings.map((warning) => (
            <p key={warning} className="ask__meta">
              {warning}
            </p>
          ))}
        </PanelSection>
      ) : null}
    </>
  );
}
