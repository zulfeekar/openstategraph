/**
 * What the tools returned during a turn — the record, and the one way it is
 * shown (ticket 02).
 *
 * **The defect this closes.** LangGraph's `messages` stream carries a node's
 * messages, not only its model tokens, so every tool result rode the same
 * frames as the model's prose and was concatenated into one `thinking` string.
 * Two things followed, both observed on a real Chinook run: the eleven-row
 * table from `list_all_tables` was glued to the tail of the model's sentence,
 * so once the turn settled and the blob was rendered as Markdown the table
 * collapsed onto a single wrapped line; and reasoning and results competed for
 * one 160px scroll region, so the longer the result, the less of it was
 * reachable.
 *
 * **One renderer, not two.** `list_all_tables` and `get_table_schema` return
 * different shapes — a Markdown table of row counts, and columns/PK/foreign
 * keys — but the chat trace knows only one fact about either: *a tool returned
 * this text*. Splitting on shape would put Chinook-specific knowledge in the
 * chat panel and would need a third renderer for the next tool. The knowledge
 * that is genuinely shared, and is therefore declared once here, is what a
 * bounded tool result looks like: attributed to its tool, whitespace
 * preserved, and scrollable rather than clipped or unbounded. The *shapes*
 * stay different and are simply shown as they arrived.
 */
/** One completed tool call's returned text. */
export interface ToolResult {
  /** The `tool_call_id` this answers — the fold's identity, not shown. */
  readonly callId: string;
  /** The tool as the model named it. */
  readonly tool: string;
  readonly text: string;
}

export interface ToolChunk {
  readonly toolName: string;
  readonly toolCallId: string;
  readonly content: string;
}

/**
 * Folds one streamed tool frame into the turn's results.
 *
 * Pure and non-mutating, so a turn's record can be rebuilt from its frames.
 */
export function appendToolChunk(
  results: readonly ToolResult[],
  chunk: ToolChunk,
): readonly ToolResult[] {
  const last = results[results.length - 1];
  // A missing id means the backend predates the tagging; coalescing onto the
  // previous entry is the best available guess, and beats one card per
  // fragment. With an id present, identity is exact — which is what keeps two
  // consecutive reads by the same tool from merging into one.
  const continues =
    last && (chunk.toolCallId ? last.callId === chunk.toolCallId : !chunk.toolCallId);
  if (continues) {
    return [...results.slice(0, -1), { ...last, text: last.text + chunk.content }];
  }
  return [
    ...results,
    { callId: chunk.toolCallId, tool: chunk.toolName || 'tool', text: chunk.content },
  ];
}

/**
 * Every tool result of one turn, each in its own bounded scroll region.
 *
 * `<pre>` rather than the Markdown renderer used for the model's prose: a tool
 * returns a fixed-width artefact whose line breaks are the content. Reflowing
 * it as prose is exactly the bug above.
 */
export function ToolResults({ results }: { results: readonly ToolResult[] }) {
  if (results.length === 0) return null;
  return (
    <div className="ask__tools">
      {results.map((result, index) => (
        <details key={`${result.callId}-${index}`} className="ask__tool" open>
          <summary className="ask__tool-name">{result.tool}</summary>
          <pre className="ask__tool-body">{result.text}</pre>
        </details>
      ))}
    </div>
  );
}
