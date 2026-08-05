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
import { RuntimeClient, type RunResult } from '@core/runtime/RuntimeClient';
import { useController } from '@app/WorkbenchContext';
import './AskPanel.css';

/**
 * Ask the workflow a question, and see the answer.
 *
 * The whole point of this panel is that it sends **the document on the canvas**
 * to the runtime — not a server-side graph and not the browser's own engine. So
 * what a developer sees is what ran, and the per-node outputs coming back are the
 * evidence for that rather than a claim about it.
 *
 * Deliberately thin. It holds no credentials, builds no graph, and does not know
 * what LangGraph is; it serialises the document, posts it, and renders what comes
 * back (ticket 07).
 */
export function AskPanel() {
  const controller = useController();
  const [question, setQuestion] = useState('');
  const [running, setRunning] = useState(false);
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

    // Serialised through the same path as “export”, so the runtime receives
    // exactly the bytes that would be saved — no second representation.
    const document = JSON.parse(controller.document.exportJSON()) as unknown;
    const outcome = await client.run({ workflow: document, question: trimmed });

    if (outcome.ok) {
      setResult(outcome.value);
      // Show which nodes ran, on the canvas rather than only in this panel.
      controller.selectionActions.selectNodes(Object.keys(outcome.value.outputs));
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

        {result ? <Answer result={result} /> : null}
      </PanelBody>
    </Panel>
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
