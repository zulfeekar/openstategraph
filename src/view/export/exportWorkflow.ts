import { Err, Ok, type Result } from '@core/kernel/Result';
import { inflate, type Rect } from '@core/kernel/geometry';
import type { PaperController } from '@canvas/PaperController';
import type { WorkflowController } from '@controller/WorkflowController';

/** Triggers a browser download for a blob. */
export function download(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  // Revoking immediately can cancel the download in some browsers; a frame
  // is enough for the navigation to have been queued.
  requestAnimationFrame(() => URL.revokeObjectURL(url));
}

export function slugify(name: string): string {
  return (
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '') || 'workflow'
  );
}

export function exportJSON(controller: WorkflowController): void {
  const json = controller.document.exportJSON();
  download(
    new Blob([json], { type: 'application/json' }),
    `${slugify(controller.model.name)}.json`,
  );
}

/** Opens a file picker and loads the chosen workflow. */
export function importJSON(
  controller: WorkflowController,
  onDone: (outcome: { ok: boolean; message?: string }) => void,
): void {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'application/json,.json';
  input.addEventListener('change', () => {
    const file = input.files?.[0];
    if (!file) return;
    void file.text().then((text) => onDone(controller.document.importJSON(text)));
  });
  input.click();
}

/* ================================================================== *
 * Image export
 *
 * The commercial bundle ships a format plugin for this; the pieces below are
 * the open-source equivalent. The hard part is not the SVG — it is that node
 * bodies are HTML inside `foreignObject`, so the exported document has to
 * carry the stylesheets that lay them out. An SVG without them renders as
 * unstyled text in any external viewer.
 * ================================================================== */

/**
 * Collects the app's own CSS rules as a single stylesheet string.
 *
 * Only same-origin sheets can be read; a cross-origin one throws on
 * `cssRules` and is skipped. Everything this app ships is bundled and
 * same-origin, so in practice the result is complete.
 */
function collectStyles(): string {
  const chunks: string[] = [];
  for (const sheet of Array.from(document.styleSheets)) {
    try {
      for (const rule of Array.from(sheet.cssRules)) {
        // Font-face rules point at bundled URLs that won't resolve inside a
        // standalone file, so they are dropped and the fallback stack applies.
        if (rule instanceof CSSFontFaceRule) continue;
        chunks.push(rule.cssText);
      }
    } catch {
      // Cross-origin sheet — nothing readable here.
    }
  }
  return chunks.join('\n');
}

/**
 * Resolves the custom properties currently in force into literal values.
 *
 * Every colour in this app is a `var(--…)` reference resolved against the
 * root element. Outside the app that root doesn't exist, so the variables are
 * re-declared inline — which also captures the active theme, meaning a dark
 * mode export actually looks dark.
 */
function resolveRootVariables(): string {
  const computed = getComputedStyle(document.documentElement);
  const declarations: string[] = [];
  for (const property of Array.from(computed)) {
    if (!property.startsWith('--')) continue;
    const value = computed.getPropertyValue(property).trim();
    if (value) declarations.push(`${property}: ${value};`);
  }
  return `:root, svg { ${declarations.join(' ')} }`;
}

function contentBounds(paper: PaperController): Rect | null {
  const bounds = paper.contentBounds();
  return bounds ? inflate(bounds, 32) : null;
}

/** Serializes the paper as a standalone, self-contained SVG document. */
export function exportSVG(paper: PaperController): Result<string, string> {
  const source = paper.paper.svg;
  const bounds = contentBounds(paper);
  if (!bounds) return Err('There is nothing on the canvas to export');

  const clone = source.cloneNode(true) as SVGSVGElement;

  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  clone.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink');
  clone.setAttribute('width', String(Math.round(bounds.width)));
  clone.setAttribute('height', String(Math.round(bounds.height)));
  clone.setAttribute(
    'viewBox',
    `${bounds.x} ${bounds.y} ${bounds.width} ${bounds.height}`,
  );

  // The live paper carries the viewport's pan/zoom on its layers; the export
  // is framed by the viewBox instead, so that transform has to go.
  clone.querySelectorAll('.joint-layers').forEach((layer) => {
    layer.removeAttribute('transform');
  });
  // Interaction-only artefacts have no meaning in a static image.
  clone.querySelectorAll('.joint-tools, .joint-temporary-link').forEach((node) => node.remove());

  const style = document.createElementNS('http://www.w3.org/2000/svg', 'style');
  style.textContent = `${resolveRootVariables()}\n${collectStyles()}`;
  clone.insertBefore(style, clone.firstChild);

  // A solid backdrop: a transparent PNG of light-grey text on nothing is
  // unreadable wherever it lands.
  const background = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  background.setAttribute('x', String(bounds.x));
  background.setAttribute('y', String(bounds.y));
  background.setAttribute('width', String(bounds.width));
  background.setAttribute('height', String(bounds.height));
  background.setAttribute(
    'fill',
    getComputedStyle(document.documentElement).getPropertyValue('--color-bg-canvas').trim() ||
      '#ffffff',
  );
  clone.insertBefore(background, style.nextSibling);

  return Ok(new XMLSerializer().serializeToString(clone));
}

/**
 * Rasterises the exported SVG.
 *
 * Goes through an `Image` and a canvas. Browsers differ on whether they will
 * rasterise `foreignObject` content this way — Chromium does, WebKit
 * historically refuses — so a failure here is reported plainly rather than
 * producing a silently blank image. SVG export always works and is offered as
 * the fallback.
 */
export async function exportPNG(
  paper: PaperController,
  scale = 2,
): Promise<Result<Blob, string>> {
  const svg = exportSVG(paper);
  if (!svg.ok) return svg;

  const blob = new Blob([svg.value], { type: 'image/svg+xml;charset=utf-8' });
  const url = URL.createObjectURL(blob);

  try {
    const image = await loadImage(url);
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(image.width * scale);
    canvas.height = Math.round(image.height * scale);

    const context = canvas.getContext('2d');
    if (!context) return Err('This browser could not create a canvas');
    context.scale(scale, scale);
    context.drawImage(image, 0, 0);

    const png = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, 'image/png'),
    );
    return png ? Ok(png) : Err('The image could not be encoded');
  } catch {
    return Err(
      'This browser refused to rasterise the canvas. Export as SVG instead — it keeps full fidelity.',
    );
  } finally {
    URL.revokeObjectURL(url);
  }
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('SVG could not be loaded as an image'));
    image.src = url;
  });
}
