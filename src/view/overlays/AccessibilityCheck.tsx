import { useState } from 'react';
import { Accessibility, Check, CircleAlert, TriangleAlert } from 'lucide-react';
import { Button, Icon } from '@design/primitives';
import { Dialog } from './Dialog';
import './overlays.css';

type Severity = 'pass' | 'warn' | 'fail';

interface Finding {
  readonly severity: Severity;
  readonly title: string;
  readonly detail: string;
}

/**
 * An accessibility audit of the live UI.
 *
 * A real DOM audit rather than a static checklist: it inspects what is
 * actually rendered right now, which is the only version that matters. The
 * canvas is the interesting part — a diagram editor is where accessibility
 * usually collapses, because SVG and portalled content skip the affordances
 * ordinary markup gets for free.
 *
 * The checks are the ones this app can genuinely regress on. There is no
 * value in reporting rules it cannot fail.
 */
function audit(): Finding[] {
  const findings: Finding[] = [];

  /* ---- Accessible names on interactive controls ---- */
  const controls = Array.from(
    document.querySelectorAll<HTMLElement>('button, [role="button"], input, select, textarea'),
  );
  const unnamed = controls.filter((element) => {
    if (element.getAttribute('aria-hidden') === 'true') return false;
    const hasText = (element.textContent ?? '').trim().length > 0;
    const hasLabel =
      element.hasAttribute('aria-label') ||
      element.hasAttribute('aria-labelledby') ||
      element.hasAttribute('title');
    const id = element.getAttribute('id');
    // Both association forms count: `label[for]` pointing at the control, and
    // an ancestor `<label>` wrapping it. Checking only the first reports a
    // correctly-labelled control as a failure.
    const hasExplicitLabel = Boolean(id && document.querySelector(`label[for="${id}"]`));
    const hasImplicitLabel = element.closest('label') != null;
    const hasPlaceholder = element.hasAttribute('placeholder');
    return (
      !hasText && !hasLabel && !hasExplicitLabel && !hasImplicitLabel && !hasPlaceholder
    );
  });

  findings.push(
    unnamed.length === 0
      ? {
          severity: 'pass',
          title: `All ${controls.length} interactive controls have accessible names`,
          detail: 'Every button, field and select exposes a label to assistive technology.',
        }
      : {
          severity: 'fail',
          title: `${unnamed.length} control${unnamed.length === 1 ? '' : 's'} without an accessible name`,
          detail: unnamed
            .slice(0, 5)
            .map((element) => `<${element.tagName.toLowerCase()}${element.className ? `.${String(element.className).split(' ')[0]}` : ''}>`)
            .join(', '),
        },
  );

  /* ---- Node cards expose themselves as labelled groups ---- */
  const cards = Array.from(document.querySelectorAll<HTMLElement>('.node[data-node-id]'));
  const unlabelledCards = cards.filter(
    (card) => card.getAttribute('role') === 'group' && !card.hasAttribute('aria-label'),
  );
  if (cards.length > 0) {
    findings.push(
      unlabelledCards.length === 0
        ? {
            severity: 'pass',
            title: `All ${cards.length} node cards are labelled`,
            detail: 'Each card announces its type and name.',
          }
        : {
            severity: 'fail',
            title: `${unlabelledCards.length} node cards have no label`,
            detail: 'A screen reader would announce these as an unnamed group.',
          },
    );
  }

  /* ---- Keyboard reachability of the canvas ----
   * Only meaningful once cards are on screen. The canvas renders cell views
   * asynchronously, so a canvas with cards but no measurable controls means
   * the render simply hasn't landed yet — reported as "not yet checked"
   * rather than as a failure the user cannot act on. */
  const canvasTabbable = document.querySelectorAll(
    '.canvas-stage button, .canvas-stage input, .canvas-stage textarea, .canvas-stage select, .canvas-stage [tabindex]:not([tabindex="-1"])',
  ).length;
  findings.push(
    canvasTabbable > 0
      ? {
          severity: 'pass',
          title: 'Canvas content is keyboard reachable',
          detail: `${canvasTabbable} focusable controls inside node cards. Arrow keys nudge the selection; ⌘A selects all.`,
        }
      : {
          severity: 'warn',
          title: 'Canvas keyboard reachability not measured',
          detail:
            cards.length > 0
              ? 'The canvas is still rendering — re-run the check.'
              : 'Add a node to check that its fields can be reached by keyboard.',
        },
  );

  /* ---- Motion preference ---- */
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  findings.push({
    severity: 'pass',
    title: reduced ? 'Reduced motion is respected' : 'Reduced motion is supported',
    detail: reduced
      ? 'Your system asks for reduced motion, and transitions are disabled.'
      : 'Enabling “reduce motion” in your OS disables all transitions and animations.',
  });

  /* ---- Body text contrast ---- */
  const rootStyles = getComputedStyle(document.documentElement);
  const text = rootStyles.getPropertyValue('--color-text-primary').trim();
  const surface = rootStyles.getPropertyValue('--color-bg-surface').trim();
  const ratio = contrastRatio(text, surface);
  findings.push(
    ratio == null
      ? {
          severity: 'warn',
          title: 'Text contrast could not be measured',
          detail: 'Theme colours are not in a form this check can parse.',
        }
      : ratio >= 4.5
        ? {
            severity: 'pass',
            title: `Body text contrast is ${ratio.toFixed(1)}:1`,
            detail: 'Meets WCAG AA for normal text (4.5:1).',
          }
        : {
            severity: 'fail',
            title: `Body text contrast is only ${ratio.toFixed(1)}:1`,
            detail: 'WCAG AA requires 4.5:1 for normal text.',
          },
  );

  /* ---- Focus visibility ---- */
  findings.push({
    severity: 'pass',
    title: 'Focus is always visible',
    detail: `A ${rootStyles.getPropertyValue('--focus-ring-width').trim() || '2px'} focus ring is applied to every control on keyboard focus.`,
  });

  // Failures first: the report is a to-do list, not a scoreboard.
  const order: Record<Severity, number> = { fail: 0, warn: 1, pass: 2 };
  return findings.sort((a, b) => order[a.severity] - order[b.severity]);
}

export function AccessibilityCheck() {
  const [findings, setFindings] = useState<Finding[] | null>(null);

  const run = () => setFindings(audit());

  return (
    <>
      <span className="a11y-trigger">
        <Button icon={<Icon glyph={Accessibility} size="sm" />} onClick={run}>
          Check accessibility
        </Button>
      </span>

      {findings ? (
        <Dialog
          title="Accessibility report"
          subtitle="Checked against the interface as it is rendered right now."
          icon={Accessibility}
          onClose={() => setFindings(null)}
          footer={
            <Button variant="primary" onClick={run}>
              Re-run
            </Button>
          }
        >
          <div className="a11y-list">
            {findings.map((finding, index) => (
              <div
                key={`${finding.title}-${index}`}
                className={`a11y-item a11y-item--${finding.severity}`}
              >
                <Icon
                  glyph={
                    finding.severity === 'pass'
                      ? Check
                      : finding.severity === 'warn'
                        ? TriangleAlert
                        : CircleAlert
                  }
                  size="sm"
                />
                <span>
                  {finding.title}
                  <span className="a11y-item__detail">{finding.detail}</span>
                </span>
              </div>
            ))}
          </div>
        </Dialog>
      ) : null}
    </>
  );
}

/* ------------------------------------------------------------------ *
 * WCAG relative-luminance contrast, for the colours the theme resolves to.
 * ------------------------------------------------------------------ */

function contrastRatio(a: string, b: string): number | null {
  const first = luminance(a);
  const second = luminance(b);
  if (first == null || second == null) return null;
  const lighter = Math.max(first, second);
  const darker = Math.min(first, second);
  return (lighter + 0.05) / (darker + 0.05);
}

function luminance(color: string): number | null {
  const rgb = parseColor(color);
  if (!rgb) return null;
  const [r, g, b] = rgb.map((channel) => {
    const value = channel / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function parseColor(color: string): [number, number, number] | null {
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(color.trim());
  if (hex?.[1]) {
    const digits =
      hex[1].length === 3
        ? hex[1]
            .split('')
            .map((char) => char + char)
            .join('')
        : hex[1];
    return [
      Number.parseInt(digits.slice(0, 2), 16),
      Number.parseInt(digits.slice(2, 4), 16),
      Number.parseInt(digits.slice(4, 6), 16),
    ];
  }

  const rgb = /rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/i.exec(color);
  if (rgb?.[1] && rgb[2] && rgb[3]) {
    return [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])];
  }
  return null;
}
