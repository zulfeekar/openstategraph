import { Ok, type Result } from '@core/kernel/Result';
import {
  AbstractLLMProvider,
  type CompletionRequest,
  type CompletionResult,
  type ModelDescriptor,
} from './ILLMProvider';

/**
 * Offline provider — the default, so the editor is fully explorable with
 * no credentials.
 *
 * It is a *simulator*, not a stub: it runs the same two-phase agent loop a
 * real model does (request a tool, then answer from the tool's result), so
 * the canvas exercises the real execution path — tool ports light up, the
 * token counter moves, the output node renders a genuine table. A stub that
 * returned canned text on the first call would leave the interesting half of
 * the engine untested.
 *
 * Deterministic by construction: the same graph always produces the same
 * run, which is what makes the seeded demo reproducible and the executor
 * unit-testable.
 */
export class MockProvider extends AbstractLLMProvider {
  readonly id = 'mock';
  readonly label = 'Mock · Offline';
  readonly requiresApiKey = false;
  /**
   * The simulator does not reason, and says so rather than leaving it open.
   * Empty is a *certainty* here, not an absence: this provider's replies are
   * assembled by code in this file, so there is no depth to ask for.
   */
  override readonly reasoningEffortLevels = [] as const;

  readonly models: readonly ModelDescriptor[] = [
    {
      id: 'mock-offline',
      label: 'Mock · Offline',
      providerId: 'mock',
      contextWindow: 128_000,
      maxOutputTokens: 8_192,
      supportsTools: true,
    },
  ];

  /** Simulated latency per turn, in ms. Zero in tests. */
  constructor(private readonly latencyMs = 420) {
    super();
  }

  async complete(request: CompletionRequest): Promise<Result<CompletionResult, string>> {
    await this.delay(request.signal);

    const { system, messages } = this.splitSystem(request);
    const alreadyCalledTool = messages.some((message) => message.role === 'tool');
    const tools = request.tools ?? [];

    // Phase 1: tools are available and none has run yet — ask for one.
    if (tools.length > 0 && !alreadyCalledTool) {
      const tool = tools[0];
      if (tool) {
        return Ok({
          text: '',
          toolCalls: [
            {
              id: `mock-call-${tools.length}`,
              name: tool.name,
              arguments: this.inventArguments(tool.parameters),
            },
          ],
          usage: this.usageFor(request, 24),
          stopReason: 'tool_use',
          reasoning: `The ${tool.name} tool can answer this directly — calling it before drafting.`,
        });
      }
    }

    // Phase 2: compose an answer from whatever the tool returned.
    const toolOutput = messages.filter((message) => message.role === 'tool').at(-1)?.content ?? '';
    const prompt = messages.filter((message) => message.role === 'user').at(-1)?.content ?? '';
    const text = this.compose({ prompt, system, toolOutput });

    return Ok({
      text,
      toolCalls: [],
      usage: this.usageFor(request, Math.ceil(text.length / 4)),
      stopReason: 'end_turn',
      reasoning: 'Tool results are sufficient; formatting them as requested.',
    });
  }

  /**
   * Builds arguments from the tool's own schema rather than a hardcoded
   * map, so a newly registered tool works with the mock immediately.
   */
  private inventArguments(schema: {
    properties: Record<string, unknown>;
  }): Record<string, unknown> {
    const args: Record<string, unknown> = {};
    for (const [key, raw] of Object.entries(schema.properties)) {
      const spec = raw as { type?: string; default?: unknown; enum?: unknown[] };
      if (spec.default !== undefined) {
        args[key] = spec.default;
        continue;
      }
      if (Array.isArray(spec.enum) && spec.enum.length > 0) {
        args[key] = spec.enum[0];
        continue;
      }
      switch (spec.type) {
        case 'number':
        case 'integer':
          args[key] = 10;
          break;
        case 'boolean':
          args[key] = true;
          break;
        default:
          args[key] = '';
      }
    }
    return args;
  }

  /**
   * Renders the tool's JSON rows as a Markdown table.
   *
   * Falls back to prose when the payload isn't tabular, because the output
   * node has to look right for any tool, not just the seeded one.
   */
  private compose({
    prompt,
    system,
    toolOutput,
  }: {
    prompt: string;
    system: string | undefined;
    toolOutput: string;
  }): string {
    const rows = this.parseRows(toolOutput);
    const wantsTable = /table/i.test(system ?? '') || rows.length > 0;

    if (rows.length > 0 && wantsTable) {
      const heading = this.headingFor(toolOutput);
      const lines = [
        `## ${heading}`,
        '',
        '| # | Topic | Signal |',
        '| --- | --- | --- |',
        ...rows.map((row, index) => `| ${index + 1} | ${row.title} | ${row.signal} |`),
        '',
        `_${rows.length} item${rows.length === 1 ? '' : 's'} · mock data, no network calls made._`,
      ];
      return lines.join('\n');
    }

    if (toolOutput) {
      return [
        '## Summary',
        '',
        prompt ? `**Request:** ${truncate(prompt, 160)}` : '',
        '',
        toolOutput.trim(),
      ]
        .filter(Boolean)
        .join('\n');
    }

    return [
      '## Summary',
      '',
      prompt
        ? `Responding to: ${truncate(prompt, 200)}`
        : 'No prompt was connected, so there is nothing to answer.',
      '',
      '_Running with mock data. Add an API key to use a real model._',
    ].join('\n');
  }

  private parseRows(toolOutput: string): { title: string; signal: string }[] {
    if (!toolOutput.trim().startsWith('{') && !toolOutput.trim().startsWith('[')) return [];
    try {
      const parsed = JSON.parse(toolOutput) as unknown;
      const items = Array.isArray(parsed)
        ? parsed
        : ((parsed as { items?: unknown[] }).items ?? []);
      return items
        .filter(
          (item): item is Record<string, unknown> => typeof item === 'object' && item !== null,
        )
        .map((item) => ({
          title: String(item['title'] ?? item['name'] ?? item['topic'] ?? 'Untitled'),
          signal: String(item['signal'] ?? item['score'] ?? item['count'] ?? '—'),
        }));
    } catch {
      return [];
    }
  }

  private headingFor(toolOutput: string): string {
    const match = /"(?:source|subreddit|origin)"\s*:\s*"([^"]+)"/.exec(toolOutput);
    return match?.[1] ? `Trending in ${match[1]}` : 'Findings';
  }

  /** Rough but stable token accounting, so the counter behaves plausibly. */
  private usageFor(request: CompletionRequest, outputTokens: number) {
    const inputTokens = request.messages.reduce(
      (total, message) => total + Math.ceil(message.content.length / 4),
      0,
    );
    const capped = Math.min(outputTokens, request.maxTokens);
    return { inputTokens, outputTokens: capped, totalTokens: inputTokens + capped };
  }

  private delay(signal: AbortSignal | undefined): Promise<void> {
    if (this.latencyMs <= 0) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(resolve, this.latencyMs);
      signal?.addEventListener(
        'abort',
        () => {
          clearTimeout(timer);
          reject(new DOMException('Aborted', 'AbortError'));
        },
        { once: true },
      );
    });
  }
}

function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}
