# shadcn/ui as a consistency reference

**Status:** applied (2026-08)
**Scope:** `src/design/` only — tokens and primitives. No view redesigns.

## What this is, and what it is not

shadcn/ui is used here as a **conventions reference**, nothing more. It is not
installed, not depended on, not imported, and Tailwind is not introduced. This
app has its own design system (`src/design/styles/tokens.css` +
`src/design/primitives/*`), and that stays the source of truth.

**The palette is out of scope.** Every verdict below is on a non-colour axis:
control geometry, state treatment, spacing rhythm, radius, icon sizing, motion,
and form/dialog anatomy. Where a change touches a ring or a state, it reuses an
existing colour token (`--color-focus-ring`, `--color-danger`) and alters only
its *geometry and opacity*. No hue was added, removed, or retuned.

Reference facts were taken from the current `new-york-v4` registry
(`ui.shadcn.com/r/styles/new-york-v4/*.json`) and the shadcn docs, converted
from Tailwind classes to concrete values.

## Inventory

`src/design/primitives/` exports: `Button`, `IconButton`, `Icon`, `Field`,
`TextInput`, `TextArea`, `DisplayRow`, `Select`, `Slider`, `Tooltip`, `Menu`,
`StatusDot`, `Badge`, `IconTile`, `Kbd`, `Spinner`, `Progress`, `Panel` (+
`PanelHeader/Body/Footer/Section/Empty`), `useFloating`.

`Dialog` is **not** a primitive — it lives in `src/view/overlays/Dialog.tsx`
with its CSS in `overlays.css`. See "Deferred" below.

## Audit

| # | Axis | shadcn does | We did | Verdict |
|---|---|---|---|---|
| 1 | **Control height parity** | `button` default, `input`, `SelectTrigger` are all `h-9` (36px); `sm` is 32px on all three. One height per size, shared by every control class. | `btn` md 28px, `icon-btn` md 28px, but `input` and `select` 30px `min-height`. A button beside an input misaligned by 2px, in every inspector row and node body. | **Adopt** — one `--control-height-{sm,md,lg}` scale (24/28/32) consumed by button, icon-button, input and select. Our density is kept; only the disagreement is removed. |
| 2 | **Size variants on inputs** | Button has 8 size variants; input has one; select trigger has two driven by `data-size`. | Button/IconButton have sizes; `TextInput` and `Select` had **none**, so a control could not be made to match an `sm` button next to it. | **Adopt** — additive `size?: 'sm' \| 'md' \| 'lg'` on `TextInput`, `TextArea` and `Select`, driven by the same height scale. Default `md`, so no existing call site changes. |
| 3 | **Focus treatment** | One treatment everywhere: `focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50`, **no ring offset**, `outline-none` on the base. | **Two languages in one app.** Global `:focus-visible` gave a 2px opaque outline at 1px offset (buttons, menu items, links). `input`/`select` gave a border swap plus a 3px ring at 18% alpha. Same keyboard action, two different rings depending on what you landed on. | **Adopt** — one ring. `--focus-ring-width: 3px`, `--focus-ring-offset: 0`, and a single `--focus-ring-soft` colour-mix reused by the global `:focus-visible` outline *and* by the input/select `focus-within` box-shadow. Hue is the untouched `--color-focus-ring`; only width, offset and alpha changed. Offset 0 also stops the ring being clipped by the scrolling panels it sits inside. |
| 4 | **Invalid state** | `aria-invalid:border-destructive aria-invalid:ring-destructive/20` — a *weaker* ring than focus, so an errored field reads as errored even while focused. | `[data-invalid]` swapped the border to danger, but focusing it painted the ordinary blue focus ring straight over the error. | **Adopt, narrowed** — an errored control focuses to a danger-tinted ring instead of a blue one. Applied **only on focus**, so the idle appearance of an errored field is byte-identical to before. |
| 5 | **Disabled opacity** | Always `0.5`, on every component without exception. | Four different values: `btn` 0.45, `icon-btn` 0.35, `input` 0.7, `select` 0.7. | **Adopt** — one `--disabled-opacity: 0.5` token, used by all four. |
| 6 | **Disabled pointer-events** | `disabled:pointer-events-none` on button/tabs; `cursor-not-allowed` on input/select. | `cursor: not-allowed` from the reset; pointer events left live. | **Deliberately different** — we wrap disabled controls in `Tooltip`, which listens on the trigger. `pointer-events: none` would silently delete the explanation of *why* the control is disabled. We adopt `cursor: not-allowed` on the disabled select/input control and keep events live. |
| 7 | **Radius scale** | One `--radius` with multiplicative steps (`sm` ×0.6, `md` ×0.8, `lg` ×1, `xl` ×1.4); small controls get a proportionally smaller radius. | Fixed 3/5/7/9/12/16 ramp, and small controls already step down (`btn--sm` → `radius-sm`, `icon-btn--xs/sm` → `radius-sm`). | **Already consistent** — same principle, expressed as a hand-tuned ramp rather than a calc chain. No change. |
| 8 | **Badge shape** | `rounded-full` pill, no fixed height, intrinsic from `py-0.5`. | Fixed 18px height, `radius-sm`, rectangular. | **Deliberately different** — rectangular badges echo the node-card and `kbd` language on a dense canvas; pills would read as a second visual system. Kept. |
| 9 | **Icons inside controls** | `[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4` — a default that *yields* to an explicit override instead of fighting it, plus `size-3` on `xs`. | Nothing. Icon size was entirely the caller's choice, so a 16px glyph could land in a 24px `sm` button, and an unguarded svg could shrink or eat a click. | **Adopt** — `pointer-events: none` + `flex: none` on svgs inside buttons, selects, menu items and badges; and the yield-to-explicit convention ported as `svg:not([data-icon-size])`. `Icon` now stamps `data-icon-size` **only when the caller passed `size` explicitly**, so small controls auto-size their icons and every deliberate choice is preserved untouched. |
| 10 | **Transition scope** | `transition-[color,box-shadow]` on inputs/select/badge — deliberately excludes layout properties. `transition-all` on button. No duration class → 150ms `cubic-bezier(0.4,0,0.2,1)`. | `--transition-colors` = 120ms `--ease-out` over exactly `color, background-color, border-color, box-shadow`. | **Already consistent, and better** — we already scope to the four properties shadcn's input variant scopes to, and we do it from one token rather than per component. No change. |
| 11 | **Menu item transition** | n/a | `.menu__item` transitions `background-color` at `--duration-instant` (60ms) while every other control uses 120ms. | **Deliberately different** — a menu highlight tracks the pointer and must feel instant; a 120ms fade reads as lag when arrowing down a list. Kept, now documented. |
| 12 | **Form field anatomy** | Order Label → Control → Description → Message, `grid gap-2`. Error propagates three ways from one source: `data-error` on the label, `aria-invalid` on the control, and `aria-describedby` pointing at the description *and* the message. | Order and gap were right (label → control → hint/error, uniform 6px). But the hint and error were **rendered as anonymous spans** — no ids, no `aria-describedby`, no `aria-invalid` propagation. A screen reader announced the field and never the reason it was wrong. | **Adopt the wiring** — `Field` now mints ids for its hint and error and publishes them through a `FieldContext`; `TextInput`, `TextArea` and `Select` consume it and set `aria-describedby` / `aria-invalid` automatically. Purely additive: an explicit prop on the call site still wins. |
| 13 | **Hint + error together** | Description and message both render. | Error *replaces* hint. | **Deliberately different** — node-card bodies are height-constrained and sit on a canvas; swapping one line for another avoids a reflow that would move every node below it. Kept. |
| 14 | **Label recolour on error** | `data-[error=true]:text-destructive`. | Label colour is constant. | **Deferred** — it is a genuine improvement but it introduces the danger hue somewhere it does not currently appear, which is out of scope for this pass. The `data-error` hook is now present on the label element, so it is a one-line change whenever the owner wants it. |
| 15 | **Dialog padding rhythm** | Padding lives only on `DialogContent` (`p-6`), `gap-4` between header/body/footer, `gap-2` inside each. | Header 16/16/12, body 0/16/16 with `gap-4`, footer 12/16. Effectively one 16px gutter throughout with a 16px section gap. | **Already consistent** — the rhythm matches; ours distributes the padding per section because the body scrolls independently and must reach the edges to do so. No change. |
| 16 | **Dialog footer / border** | No borders; footer `flex-col-reverse` on mobile → `sm:flex-row sm:justify-end`. | `justify-content: flex-end`, plus a top border. | **Deliberately different** — the top border marks where a scrolling body ends, which shadcn does not need because its body does not scroll independently. No mobile breakpoint: this is a desktop canvas editor. Kept. |
| 17 | **Overlay** | Flat `bg-black/50`, fade only, no blur. | `rgba(9,12,17,0.45)`, fade only, no blur. | **Already consistent.** |
| 18 | **Motion vocabulary** | `fade-in-0 zoom-in-95` + a 2px directional slide; dialog `duration-200`, others 150ms. | `tooltip-in` (120ms, 2px rise + scale 0.98), `menu-in` (120ms, 3px + 0.985), `dialog-in` (180ms, 8px + 0.98), `fade-in` 120ms. | **Already consistent** — same grammar (fade + small scale + small directional offset), same ordering of durations (transient popovers fastest, modal slowest), and `prefers-reduced-motion` is already honoured globally. No change. |
| 19 | **Tooltip** | `px-3 py-1.5`, `text-xs`, `rounded-md`, `sideOffset 0`, `delayDuration 0`, arrow. | `4px/8px`, 12px text, `radius-sm`, no arrow. | **Already consistent** in kind; ours is tighter to match a dense canvas. No change. |
| 20 | **`data-slot` hook** | Every primitive carries `data-slot="button"` etc. as the v4 styling/targeting hook. | BEM class names (`.btn`, `.input__control`). | **Deliberately different** — BEM already provides the stable targeting hook `data-slot` exists to provide in a utility-class world. Adding a second one would be duplication of knowledge. |

**Counts: 7 adopt, 6 already-consistent, 6 deliberately-different, 1 deferred.**

## Missing primitives — noted, not built

- **Tabs.** shadcn has one; we have exactly one tab-like surface, the segmented
  run-view switcher in `AskPanel.css` (`.ask__views` / `.ask__view-tab`). One
  usage cannot diverge from itself, so extracting a primitive now would be
  speculation. Build it when a second surface needs it.
- **Dialog as a primitive.** `Dialog` is generic chrome living in
  `src/view/overlays/`, which is where `design/` says it should not be. Moving
  it is an import-churn refactor with no consistency payoff in this pass, and
  the brief forbids view redesigns. Recorded so it is not forgotten.
- **Checkbox / Switch / Popover** have no primitive, and no view currently
  hand-rolls a divergent version. Nothing to unify.

## What "no colour change" meant in practice

Three edits touch something a reader might call colour:

1. The focus ring's **alpha** moved to a single value used by both the global
   outline and the input ring — previously 100% (2px outline) and 18% (3px
   ring). The hue is `--color-focus-ring`, untouched.
2. Disabled **opacity** unified at 0.5 from 0.45/0.35/0.7/0.7.
3. An errored control focuses to a `--color-danger` ring rather than a blue
   one. Idle appearance unchanged.

All three are state geometry expressed through existing tokens. No ramp,
semantic colour, or theme value was edited, and `theme.css` was not touched.
