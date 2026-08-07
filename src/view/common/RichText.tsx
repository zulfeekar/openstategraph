import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './RichText.css';

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
 */
export function RichText({ text, className }: { text: string; className?: string }) {
  return (
    <div className={className ? `rich-text ${className}` : 'rich-text'}>
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noreferrer noopener">
              {children}
            </a>
          ),
        }}
      >
        {text}
      </Markdown>
    </div>
  );
}
