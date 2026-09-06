# Three self-hosted families, two subsets each — what the design system's type costs

**Status: in force from 2026-08-30.** Resolves `the-look-has-an-author-now`
ticket 05, and records the measurement ticket 05 asked for.

## The question, restated so it is the right one

The brief that charted this map asked whether the editor is subject to the
same Google-Fonts constraint as a published Claude Artifact. **It is not, and
the difference is not a loophole — it is a different product.**

The Google-Fonts-only exception is a property of the Artifact CSP, which blocks
external requests and excepts `fonts.googleapis.com` / `fonts.gstatic.com`
specifically. OpenStateGraph's editor is a Vite build shipped as package data
inside a Python wheel (`docs/decisions/framework-packaging.md`) and served by
`openstategraph serve` from the user's own machine. There is no CSP forcing a
choice here. The project made its own, independently and earlier: everything is
self-hosted, because a page that works offline once the wheel is installed has
no network call it can silently fail.

So the operative question is not *self-host or CDN*. It is:

> The design system names **three** families where this product loaded one.
> What does that cost, subsetted deliberately, against the 218,512 bytes of
> Inter it replaces?

## The measurement

Measured on built assets — `stat` on `dist/assets/*.woff2` after
`npm run build`, not a package's advertised size.

| | family | axis / weight | subsets | bytes |
| --- | --- | --- | --- | --- |
| before | Inter Variable | `wght` | latin, latin-ext, cyrillic, cyrillic-ext, greek, greek-ext, vietnamese | **218,512** |
| after | Archivo Variable | `wght` | latin, latin-ext | 67,536 |
| | IBM Plex Sans Variable | `wght` | latin, latin-ext | 76,676 |
| | IBM Plex Mono | 400 | latin, latin-ext | 28,056 |
| | | | | **172,268** |

**Three families for 46,244 bytes less than one**, a 21% reduction — because
the saving is in the subsets, not in the faces. The wheel moved with it:
`docs/wheel-footprint.json`, regenerated the same day, puts the built canvas at
1,566 KiB against 1,608 KiB.

## The three decisions behind that table

### 1. Two subsets, not seven

Dropped: cyrillic, cyrillic-ext, greek, greek-ext, vietnamese.

`docs/` and `README.md` state no internationalization commitment and the editor
ships no translations, so this removes no declared capability. It was never
chosen in the first place — it arrived with
`@import '@fontsource-variable/inter/index.css'`, which is one line that ships
everything the package has.

A browser only *downloads* the subsets a page needs; `unicode-range` sees to
that. But the **wheel carries all of them**, and the wheel is what a stranger
downloads before any browser has an opinion. That is the whole reason
`src/design/styles/fonts.css` spells out six `@font-face` rules by hand instead
of importing three stylesheets: a subset is now a reviewable diff. A future
non-Latin commitment adds them back, per family, in that file.

### 2. The weight axis, not the width axis

Archivo and IBM Plex Sans both publish variable releases with two axes. The
`standard` build carries `wght` **and** `wdth`; the `wght` build carries weight
alone. Nothing in this product sets `font-stretch`, and the difference is not
small — Archivo `standard` is 176,344 bytes for the same two subsets against
67,536 for `wght`. Taking `standard` would have made the headline number
"three families cost 60% more than one" for a capability nobody uses.

### 3. Mono ships one weight, and that has a visible edge

**IBM Plex Mono has no variable release.** `@fontsource-variable/ibm-plex-mono`
does not exist — the registry returns a 404 — only `@fontsource/ibm-plex-mono`
with static per-weight files. So every additional weight is another ~28 KB for
two subsets, and this is the one family where "load the weights you use" is a
real cost decision rather than a free one.

`--type-mono-sm` is the only role that sets this family together with a weight,
and it sets `--font-weight-regular`. The handful of sites that set
`font-family: var(--font-mono)` raw — `AskPanel.css`, `RichText.css`,
`PastRuns.css` — inherit whatever weight surrounds them, and where that is bold
the browser will synthesise it. A synthetic bold in a code span is a fair price
for not doubling a family; if it ever looks wrong, `600.css`'s two latin files
are 29,948 bytes and this paragraph is the place to record having spent them.

## Fallbacks are not decoration

Every family in `--osg-font-*` ends in a real stack — `'Helvetica Neue', Arial,
sans-serif` for the two sans, `ui-monospace, 'SF Mono', SFMono-Regular, Menlo,
Monaco, monospace` for the third. Two things land there routinely: text in a
dropped subset, and every character drawn in the moment before a `font-display:
swap` face arrives. A stack ending in `sans-serif` alone would make both of
those look like a bug.

## Inter is gone, and that is the point of the number above

Inter was the one loaded family and IBM Plex Sans has taken its job. Keeping it
in the stack behind Plex was considered — it is a better fallback for a dense UI
than Helvetica — and rejected: it would have meant shipping 218 KB of *fallback*
for a face that is already loaded, which is the largest possible price for the
smallest possible benefit. The dependency is removed from `package.json`, not
merely unimported.
