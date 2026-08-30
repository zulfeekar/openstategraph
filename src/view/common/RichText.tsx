import { memo } from 'react';
import Markdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './RichText.css';

/**
 * How this app renders model- and user-authored Markdown. One owner.
 *
 * Exported because the node cards render Markdown *without* `RichText`'s
 * wrapper element — their `.prose` container is styled by the card, not by
 * `rich-text.css` — and before this existed they each restated
 * `remarkPlugins={[remarkGfm]}` and silently omitted the link rule below,
 * so a link in a model's answer navigated the whole editor away. The
 * plugin list and the components map are the security-relevant part; the
 * wrapper is not. Anything rendering Markdown spreads these.
 */
export const MARKDOWN_PLUGINS = [remarkGfm];

export const MARKDOWN_COMPONENTS: Components = {
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer noopener">
      {children}
    </a>
  ),
};

/**
 * Model output, rendered as Markdown — ticket 46.
 *
 * Every workflow in this repo produces Markdown tables (the SQL results, the
 * analytics reports), and a `<pre>` shows their raw pipes. This is the one
 * component that renders model-authored text anywhere in the app, so the
 * rules live in one place:
 *
 * - GFM (tables, strikethrough, task lists) via remark-gfm.
 * - **No raw HTML.** react-markdown skips HTML nodes by default; that
 *   default is the security boundary for model-authored content and must
 *   not be "fixed" with rehype-raw.
 * - Links open in a new tab and never carry the opener.
 *
 * **Memoised, and the memo is load-bearing rather than a micro-optimisation**
 * — `the-cost-of-one-more/20`. Parsing Markdown is not cheap: a CPU profile of
 * a 700-frame run through the real editor spent **56% of the whole burst**
 * inside `react-markdown`, most of it in `combineExtensions`/`syntaxExtension`,
 * i.e. rebuilding the micromark pipeline rather than reading the text. The run
 * trace renders one of these per step (`traceTree.tsx`), so an un-memoised
 * `RichText` re-parses every step's output on every commit, and a stream
 * commits once per frame — F parses of F rows, quadratic, measured at ×3.68
 * per doubling.
 *
 * The memo is safe by construction and that is why it is the fix rather than
 * a risk: both props are primitives, so the default shallow comparison is an
 * exact one. There is no object or callback here whose identity could go
 * stale, and nothing to keep in sync if one is added — adding one would make
 * the comparison wrong, which is what `richTextIsMemoised.test.ts` watches
 * for.
 */
export const RichText = memo(function RichText({
  text,
  className,
}: {
  text: string;
  className?: string;
}) {
  return (
    <div className={className ? `rich-text ${className}` : 'rich-text'}>
      <Markdown remarkPlugins={MARKDOWN_PLUGINS} components={MARKDOWN_COMPONENTS}>
        {text}
      </Markdown>
    </div>
  );
});
