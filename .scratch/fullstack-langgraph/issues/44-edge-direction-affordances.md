Type: task
Status: open

## Question

Edges show no direction at rest: `FlowLink` has no arrowhead/marker of any
kind, and the one motion cue (`link-flow` dash animation) fires only from
the *local* preview engine (`CanvasStage.tsx:96`) — a Chat/backend run
animates nothing.

- Target-side arrowhead on `FlowLink`, themed via the existing CSS custom
  properties; stronger marker + midpoint chevron on hover/selection;
  selected edge shows source/target port emphasis.
- Drive `is-active` per-edge from the backend stream: AskPanel already knows
  the active node per `update` frame — light the edge(s) into it, keeping
  the ≥350ms minimum highlight chaining.
- Focused node: direction-aware port glow (inputs vs outputs distinct).
- Respect `prefers-reduced-motion` for the dash animation.
