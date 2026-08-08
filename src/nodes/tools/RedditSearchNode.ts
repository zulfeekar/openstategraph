import { Ok, type Result } from '@core/kernel/Result';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { ExecutionContext, INodeExecutor, IToolExecutor } from '@core/execution/INodeExecutor';
import type { ToolSpec } from '@core/providers/ILLMProvider';
import { AbstractToolNodeModel, createToolExecutor, defineToolNode } from './AbstractToolNode';

const FIELD_SUBREDDIT = 'subreddit';
const FIELD_LIMIT = 'topicLimit';

export class RedditSearchNodeModel extends AbstractToolNodeModel {
  get subreddit(): string {
    return this.getText(FIELD_SUBREDDIT)
      .replace(/^\/?r\//, '')
      .trim();
  }

  get limit(): number {
    return this.getNumber(FIELD_LIMIT, 10);
  }
}

export const redditSearchNode: INodeDefinition = defineToolNode(
  {
    id: 'tool.reddit-search',
    label: 'Search Reddit',
    description: 'Finds trending posts in a subreddit.',
    iconId: 'node-reddit',
    accent: 'orange',
    keywords: ['reddit', 'search', 'trending', 'social', 'community'],
    defaultSize: { width: 252, height: 190 },
    fields: [
      {
        kind: 'text',
        key: FIELD_SUBREDDIT,
        label: 'Subreddit',
        prefix: 'r/',
        placeholder: 'reactjs',
        defaultValue: 'reactjs',
        validate: (value) => (value.trim().length === 0 ? 'Name the subreddit to search' : null),
      },
      {
        kind: 'slider',
        key: FIELD_LIMIT,
        label: 'Topic limit',
        min: 1,
        max: 25,
        step: 1,
        defaultValue: 10,
        format: (value) => `· ${value}`,
      },
    ],
  },
  RedditSearchNodeModel,
);

/* ------------------------------------------------------------------ *
 * Sample data.
 *
 * Reddit's JSON endpoints reject browser origins, so the tool tries the
 * network first and falls back to this. The fallback is *labelled* in its
 * payload and in the run log — a tool that quietly returns invented data as
 * if it were live is far worse than one that says it is offline.
 *
 * r/reactjs is seeded to match the reference workflow so the shipped demo
 * reproduces exactly; anything else is generated from the subreddit name.
 * ------------------------------------------------------------------ */

const SEEDED: Record<string, { title: string; signal: string }[]> = {
  reactjs: [
    { title: 'React Compiler is stable', signal: '4.2k' },
    { title: 'Server Components in production', signal: '3.8k' },
    { title: 'Suspense + transitions', signal: '2.9k' },
    { title: 'The signals debate', signal: '2.4k' },
    { title: 'Testing hooks without a DOM', signal: '1.9k' },
    { title: 'Migrating off Redux in 2026', signal: '1.6k' },
    { title: 'Why we dropped CSS-in-JS', signal: '1.4k' },
    { title: 'RSC data-loading patterns', signal: '1.1k' },
    { title: 'View Transitions API in React', signal: '980' },
    { title: 'Bundle size after React 19', signal: '870' },
  ],
};

const TOPIC_SHAPES = [
  'State management in {sub}',
  'What changed in {sub} this month',
  'Common {sub} mistakes',
  'Tooling roundup for {sub}',
  'Performance tips for {sub}',
  'Migration guide: {sub}',
  'Testing strategies in {sub}',
  '{sub} in production: a retrospective',
  'Why {sub} beginners get stuck',
  'The future of {sub}',
];

interface RedditRow {
  title: string;
  signal: string;
}

/** Stable hash, so a given subreddit always yields the same sample rows. */
function hash(text: string): number {
  let value = 0;
  for (let i = 0; i < text.length; i += 1) {
    value = (value * 31 + text.charCodeAt(i)) | 0;
  }
  return Math.abs(value);
}

function sampleRows(subreddit: string, limit: number): RedditRow[] {
  const seeded = SEEDED[subreddit.toLowerCase()];
  if (seeded) return seeded.slice(0, limit);

  const seed = hash(subreddit);
  return Array.from({ length: Math.min(limit, TOPIC_SHAPES.length) }, (_, index) => {
    const shape = TOPIC_SHAPES[(seed + index) % TOPIC_SHAPES.length] ?? '{sub} discussion';
    const score = 400 + ((seed * (index + 7)) % 4200);
    return {
      title: shape.replace('{sub}', subreddit),
      signal: score >= 1000 ? `${(score / 1000).toFixed(1)}k` : String(score),
    };
  });
}

interface RedditListing {
  data?: { children?: { data?: { title?: string; score?: number } }[] };
}

async function fetchLive(
  subreddit: string,
  limit: number,
  signal: AbortSignal,
): Promise<RedditRow[] | null> {
  try {
    const response = await fetch(
      `https://www.reddit.com/r/${encodeURIComponent(subreddit)}/hot.json?limit=${limit}`,
      { signal },
    );
    if (!response.ok) return null;
    const payload = (await response.json()) as RedditListing;
    const rows = (payload.data?.children ?? [])
      .map((child) => child.data)
      .filter((post): post is { title: string; score?: number } => typeof post?.title === 'string')
      .map((post) => ({
        title: post.title,
        signal:
          post.score != null && post.score >= 1000
            ? `${(post.score / 1000).toFixed(1)}k`
            : String(post.score ?? '—'),
      }));
    return rows.length > 0 ? rows : null;
  } catch {
    // CORS rejection, offline, or an aborted run — all mean "use samples".
    return null;
  }
}

const redditTool: IToolExecutor = {
  describeTool(node: AbstractNodeModel): ToolSpec {
    const tool = node as RedditSearchNodeModel;
    return {
      name: 'search_reddit',
      description:
        'Find the currently trending posts in a subreddit. Returns a JSON list of titles with an engagement signal for each.',
      parameters: {
        type: 'object',
        properties: {
          subreddit: {
            type: 'string',
            description: 'Subreddit name without the r/ prefix.',
            default: tool.subreddit,
          },
          limit: {
            type: 'integer',
            description: 'How many posts to return.',
            default: tool.limit,
          },
        },
        required: ['subreddit'],
        additionalProperties: false,
      },
    };
  },

  async invokeTool(
    node: AbstractNodeModel,
    args: Record<string, unknown>,
    ctx: ExecutionContext,
  ): Promise<Result<string, string>> {
    const tool = node as RedditSearchNodeModel;
    // The node's own configuration is the fallback, so a model that omits an
    // argument still gets the subreddit the user picked on the card.
    const subreddit =
      (typeof args['subreddit'] === 'string' && args['subreddit'].trim()) || tool.subreddit;
    const requested = typeof args['limit'] === 'number' ? args['limit'] : tool.limit;
    const limit = Math.max(1, Math.min(25, Math.round(requested)));

    if (!subreddit) return Ok(JSON.stringify({ error: 'No subreddit given' }));

    const live = await fetchLive(subreddit, limit, ctx.signal);
    const rows = live ?? sampleRows(subreddit, limit);
    const source = live ? 'live' : 'sample';

    ctx.log(
      live
        ? `Fetched ${rows.length} live posts from r/${subreddit}`
        : `r/${subreddit} unreachable from the browser — returning ${rows.length} sample posts`,
    );

    return Ok(
      JSON.stringify(
        {
          source: `r/${subreddit}`,
          dataset: source,
          ...(live ? {} : { note: 'Sample data — Reddit blocks browser-origin requests.' }),
          items: rows,
        },
        null,
        2,
      ),
    );
  },
};

export const redditSearchExecutor: INodeExecutor = createToolExecutor(
  redditSearchNode.id,
  redditTool,
);
