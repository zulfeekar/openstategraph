Type: task
Status: open

## Question

Layout is horizontal-only in three layers: `AutoLayout` hardcodes
`rankDir:'LR'` (its option type already admits 'TB'); `sideOf()` defaults
in→left / out→right; `NodeCard` computes a left/right port's y from an HTML
footer row. No preferences store exists (only `theme` persists).

- `FlowDirection = 'horizontal' | 'vertical'` + `resolvePortSide(port, flow)`
  in core, with `axis?: 'flow' | 'cross'` on `IPortDescriptor`: flow ports go
  left/right (horizontal) or top/bottom (vertical); cross ports (tool bus,
  worker bus — today's hardcoded side:'top'/'bottom') go perpendicular.
  Explicit `side` still wins.
- `PreferencesStore` (framework-free, EventBus + injectable storage,
  `dyflow.*` key convention) as a Workbench collaborator; workflow-level
  override via ticket 36's settings.
- `NodeCard` vertical mode: flow ports render as a horizontal strip (inputs
  above header, outputs below footer); measurement derives a top/bottom
  port's x from its row centre — today every input would stack at width/2.
- TopBar toggle beside Arrange; arrange passes the matching rankDir;
  keyboard binding in the one binding table; persisted; live re-layout on
  switch is a single undoable transaction.
