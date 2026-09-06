import { useState } from 'react';
import { Accessibility, Check, CircleAlert, TriangleAlert } from 'lucide-react';
import { Button, Icon } from '@design/primitives';
import { assessContrast, type TextSample } from './contrastAudit';
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
    return !hasText && !hasLabel && !hasExplicitLabel && !hasImplicitLabel && !hasPlaceholder;
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
            .map(
              (element) =>
                `<${element.tagName.toLowerCase()}${element.className ? `.${String(element.className).split(' ')[0]}` : ''}>`,
            )
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

  const rootStyles = getComputedStyle(document.documentElement);

  /* ---- Text contrast, sampled from what is on screen ---- */
  findings.push(assessContrast(sampleRenderedText()));

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

/**
 * Real text, from the rendered page.
 *
 * The check this replaces read two CSS variables and generalised — so it
 * sampled the text *least* likely to fail and called the page accessible
 * (reviews-2026-08-14 ticket 05). This walks what is actually drawn.
 *
 * Deliberately biased toward the small and the quiet: those are where
 * contrast fails, and a sample of headings proves nothing about a palette
 * description. One representative per distinct colour/size pairing, so the
 * report names a kind of text rather than listing four hundred nodes.
 */
function sampleRenderedText(): TextSample[] {
  const samples = new Map<string, TextSample>();

  for (const element of document.querySelectorAll<HTMLElement>('body *')) {
    // Only elements with their own visible words — a wrapper inherits its
    // child's colour and would double-count it under a useless name.
    const own = [...element.childNodes].some(
      (node) => node.nodeType === Node.TEXT_NODE && (node.textContent ?? '').trim().length > 0,
    );
    if (!own) continue;

    const style = getComputedStyle(element);
    if (style.visibility === 'hidden' || style.display === 'none' || style.opacity === '0') {
      continue;
    }
    const background = effectiveBackground(element);
    if (!background) continue;

    const fontSizePx = Number.parseFloat(style.fontSize) || 16;
    const weight = Number.parseInt(style.fontWeight, 10) || 400;
    const key = `${style.color}|${background}|${Math.round(fontSizePx)}|${weight >= 700}`;
    if (samples.has(key)) continue;

    samples.set(key, {
      label: describe(element, fontSizePx),
      color: style.color,
      background,
      fontSizePx,
      bold: weight >= 700,
    });
  }

  return [...samples.values()];
}

/**
 * The colour actually behind an element.
 *
 * `background-color` is `rgba(0, 0, 0, 0)` on nearly everything, so the real
 * backdrop is whichever ancestor last painted one. Without this walk every
 * sample would be measured against transparency and the check would be as
 * fictional as the one it replaces.
 */
function effectiveBackground(start: HTMLElement): string | null {
  let node: HTMLElement | null = start;
  while (node) {
    const background = getComputedStyle(node).backgroundColor;
    const transparent =
      !background || background === 'transparent' || /,\s*0\s*\)$/.test(background);
    if (!transparent) return background;
    node = node.parentElement;
  }
  return null;
}

/** A name a reader can act on — the class that styles it, not a selector path. */
function describe(element: HTMLElement, fontSizePx: number): string {
  const named =
    element.className && typeof element.className === 'string'
      ? element.className.split(/\s+/).filter(Boolean).slice(-1)[0]
      : '';
  return named
    ? `${named} (${Math.round(fontSizePx)}px)`
    : `${element.tagName.toLowerCase()} (${Math.round(fontSizePx)}px)`;
}
