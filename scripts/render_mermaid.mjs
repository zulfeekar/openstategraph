#!/usr/bin/env node
// Render Mermaid text to inline SVG, entirely on this machine.
//
// Reads {"<key>": "<mermaid source>", ...} on stdin, writes {"<key>": "<svg>"}
// on stdout. The renderer is the mermaid build this repository already vendors
// (node_modules/mermaid/dist/mermaid.min.js, MIT) loaded from disk into a
// Playwright chromium page — no CDN, no network, and nothing about the graph
// ever leaves the machine, which is the same rule that makes the backend call
// draw_mermaid() instead of draw_mermaid_png().
//
// Colours come out as sentinels and are rewritten to the site's CSS custom
// properties by the caller, so a build-time SVG still follows the reader's
// light/dark theme.
//
// Used by scripts/build_gallery_diagrams.py; not part of the shipped package.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { chromium } from 'playwright';

const here = dirname(fileURLToPath(import.meta.url));
const MERMAID = resolve(here, '..', 'node_modules', 'mermaid', 'dist', 'mermaid.min.js');

// Sentinels the caller swaps for hsl(var(--token)). Chosen so they cannot
// collide with anything mermaid emits of its own accord.
const THEME_VARIABLES = {
  fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
  fontSize: '14px',
  background: '#fe0001',
  primaryColor: '#fe0002',
  primaryBorderColor: '#fe0003',
  primaryTextColor: '#fe0004',
  lineColor: '#fe0005',
  textColor: '#fe0004',
  mainBkg: '#fe0002',
  nodeBorder: '#fe0003',
  edgeLabelBackground: '#fe0001',
  clusterBkg: '#fe0001',
  clusterBorder: '#fe0003',
};

const stdin = readFileSync(0, 'utf8');
const sources = JSON.parse(stdin);

const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto('about:blank');
// Fail loudly rather than silently rendering a degraded diagram if anything
// ever tries to reach the network.
page.on('request', (req) => {
  if (!req.url().startsWith('data:') && req.url() !== 'about:blank') {
    console.error(`refusing network request: ${req.url()}`);
    process.exitCode = 1;
  }
});
await page.addScriptTag({ path: MERMAID });

const out = {};
for (const [key, source] of Object.entries(sources)) {
  const id = `d${key.replace(/[^a-zA-Z0-9]/g, '-')}`;
  out[key] = await page.evaluate(
    async ({ id, source, themeVariables }) => {
      window.mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        theme: 'base',
        themeVariables,
        // htmlLabels stays on: LangGraph writes edge labels as `&nbsp;revise&nbsp;`,
        // and the SVG-text path renders that entity literally.
        flowchart: { htmlLabels: true, useMaxWidth: true, padding: 8 },
      });
      const { svg } = await window.mermaid.render(id, source);
      return svg;
    },
    { id, source, themeVariables: THEME_VARIABLES },
  );
}

await browser.close();
process.stdout.write(JSON.stringify(out));
