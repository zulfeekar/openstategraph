/**
 * A skill port takes as many skills as the compiler composes — launch-readiness/72.
 *
 * The two layers disagreed, and only one of them was right. `SKILL_PORT`
 * declared no `maxConnections`, so it inherited the input default of one, and
 * `capacityRule` refused a second edge onto an agent's `skill` port. The
 * Python compiler had never agreed: `skill` is a binding port type, every
 * binding edge appends to `plan.skill_bindings[dst]`, and `_wired_skill`
 * joins the whole list with newlines. Many skills per node is what it does.
 *
 * The disagreement was invisible until somebody needed the shape. Building a
 * lens layer for a real package (launch-readiness/69) meant wiring twelve
 * Markdown files — seven per-table lenses, an index, and four cross-cutting
 * method files — into one agent. The canvas could not draw it. Hand-editing
 * the document could, and the compiler accepted and composed all twelve
 * without an error, a warning, or a truncation.
 *
 * That is the worst shape for a limit to take: enforced where a developer
 * works, absent where the work actually happens. A limit worth having is
 * enforced in both places; one worth nothing is enforced in neither. This
 * one was worth nothing, and it cost a developer the editor.
 *
 * `tools` on the same node has always been unbounded, and a bus of skills is
 * the same idea — which is the argument for fixing the catalogue rather than
 * teaching the compiler to reject the twelfth file.
 */

import { describe, expect, it } from 'vitest';

import { readFileSync } from 'node:fs';

import { SKILL_PORT, SKILL_PORT_ID } from './skillLayer';

describe('the skill port', () => {
  it('is declared unbounded, not left to the single-connection input default', () => {
    // `null` is the spelling, never `Infinity`: a non-finite number does not
    // survive JSON, and `JSON.stringify(Infinity)` is the string "null"
    // anyway — so the value would round-trip into this one silently.
    expect(SKILL_PORT.maxConnections).toBe(null);
  });

  it('says so in the generated catalogue the compiler ships', () => {
    // The declaration above is TypeScript; `port_specs.json` is what the
    // Python side and the installed wheel actually read. A fix that stops at
    // the source leaves the two disagreeing again, one regeneration later —
    // which is the whole defect, not a smaller version of it.
    const specs = JSON.parse(
      readFileSync('backend/openstategraph/compile/port_specs.json', 'utf8'),
    ) as {
      node_types: { type: string; ports: { id: string; max_connections: number | null }[] }[];
    };

    const withSkill = specs.node_types.filter((type) =>
      type.ports.some((port) => port.id === SKILL_PORT_ID),
    );

    // Guards the guard: a renamed port would make every assertion below pass
    // by matching nothing.
    expect(withSkill.length).toBeGreaterThan(0);

    for (const type of withSkill) {
      const port = type.ports.find((p) => p.id === SKILL_PORT_ID);
      expect(
        port?.max_connections,
        `${type.type}'s skill port must accept as many skills as the compiler composes`,
      ).toBe(null);
    }
  });
});
