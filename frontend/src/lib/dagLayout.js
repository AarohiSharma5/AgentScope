// Pure layered layout for a workflow DAG. No React / DOM dependencies so it can
// be unit-tested and reused. Assigns each node a layer via BFS from the entry
// node (following edges), then positions layers top-to-bottom and centers the
// nodes within each layer.

export const NODE_W = 150;
export const NODE_H = 50;
const H_GAP = 40;
const V_GAP = 90;
const PAD = 28;

export function layoutDag(nodes = [], edges = [], entry = null) {
  if (!nodes.length) {
    return { nodes: [], edges: [], width: 0, height: 0 };
  }

  const byId = new Map(nodes.map((n) => [n.id, n]));
  const adjacency = new Map(nodes.map((n) => [n.id, []]));
  edges.forEach((e) => {
    if (adjacency.has(e.from)) adjacency.get(e.from).push(e.to);
  });

  // BFS layering from the entry node (fall back to the first node).
  const layer = new Map();
  const start = entry && byId.has(entry) ? entry : nodes[0].id;
  const queue = [[start, 0]];
  layer.set(start, 0);
  while (queue.length) {
    const [id, depth] = queue.shift();
    for (const next of adjacency.get(id) || []) {
      const candidate = depth + 1;
      if (!layer.has(next) || candidate > layer.get(next)) {
        layer.set(next, candidate);
        queue.push([next, candidate]);
      }
    }
  }

  // Any nodes unreachable from entry go into a trailing layer.
  let maxLayer = 0;
  layer.forEach((v) => (maxLayer = Math.max(maxLayer, v)));
  nodes.forEach((n) => {
    if (!layer.has(n.id)) layer.set(n.id, maxLayer + 1);
  });

  // Group node ids by layer, preserving input order within a layer.
  const layers = [];
  nodes.forEach((n) => {
    const li = layer.get(n.id);
    (layers[li] = layers[li] || []).push(n.id);
  });

  const rowWidth = (row) => row.length * NODE_W + (row.length - 1) * H_GAP;
  const maxRowWidth = Math.max(...layers.filter(Boolean).map(rowWidth), NODE_W);

  const positioned = [];
  layers.forEach((row, li) => {
    if (!row) return;
    const startX = PAD + (maxRowWidth - rowWidth(row)) / 2;
    const y = PAD + li * (NODE_H + V_GAP);
    row.forEach((id, i) => {
      const x = startX + i * (NODE_W + H_GAP);
      positioned.push({ ...byId.get(id), x, y, w: NODE_W, h: NODE_H });
    });
  });

  const posById = new Map(positioned.map((p) => [p.id, p]));
  const routed = edges
    .filter((e) => posById.has(e.from) && posById.has(e.to))
    .map((e) => {
      const s = posById.get(e.from);
      const t = posById.get(e.to);
      return {
        ...e,
        x1: s.x + s.w / 2,
        y1: s.y + s.h,
        x2: t.x + t.w / 2,
        y2: t.y,
      };
    });

  const numLayers = layers.filter(Boolean).length;
  return {
    nodes: positioned,
    edges: routed,
    width: maxRowWidth + PAD * 2,
    height: PAD * 2 + numLayers * NODE_H + (numLayers - 1) * V_GAP,
  };
}
