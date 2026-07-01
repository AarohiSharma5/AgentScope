import { describe, expect, it } from "vitest";
import { layoutDag } from "./dagLayout.js";

describe("layoutDag", () => {
  it("returns empty layout for no nodes", () => {
    const out = layoutDag([], [], null);
    expect(out.nodes).toEqual([]);
    expect(out.edges).toEqual([]);
  });

  it("layers a sequential chain top-to-bottom", () => {
    const nodes = [{ id: "a" }, { id: "b" }, { id: "c" }];
    const edges = [
      { from: "a", to: "b", kind: "next" },
      { from: "b", to: "c", kind: "next" },
    ];
    const { nodes: laid } = layoutDag(nodes, edges, "a");
    const y = Object.fromEntries(laid.map((n) => [n.id, n.y]));
    expect(y.a).toBeLessThan(y.b);
    expect(y.b).toBeLessThan(y.c);
  });

  it("places parallel branches on the same layer", () => {
    const nodes = [
      { id: "fan", type: "parallel", branches: ["x", "y"] },
      { id: "x" },
      { id: "y" },
      { id: "merge" },
    ];
    const edges = [
      { from: "fan", to: "x", kind: "parallel" },
      { from: "fan", to: "y", kind: "parallel" },
      { from: "fan", to: "merge", kind: "next" },
      { from: "x", to: "merge", kind: "next" },
      { from: "y", to: "merge", kind: "next" },
    ];
    const { nodes: laid } = layoutDag(nodes, edges, "fan");
    const byId = Object.fromEntries(laid.map((n) => [n.id, n]));
    expect(byId.x.y).toBe(byId.y.y); // same layer (row)
    expect(byId.x.x).not.toBe(byId.y.x); // different columns
    expect(byId.merge.y).toBeGreaterThan(byId.x.y); // merge below branches
  });

  it("routes edges only between placed nodes", () => {
    const { edges } = layoutDag(
      [{ id: "a" }, { id: "b" }],
      [
        { from: "a", to: "b", kind: "next" },
        { from: "a", to: "ghost", kind: "next" },
      ],
      "a"
    );
    expect(edges).toHaveLength(1);
    expect(edges[0]).toMatchObject({ from: "a", to: "b" });
  });
});
