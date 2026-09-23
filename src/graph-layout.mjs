const number = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
const id = (value) => String(value ?? '');

export function clusterGrid(clusters, width, height) {
  const ordered = [...clusters].sort((a, b) => number(b.n_nodes) - number(a.n_nodes) || number(a.cluster_id) - number(b.cluster_id));
  if (!ordered.length) return [];
  const columns = Math.min(ordered.length, Math.max(1, Math.floor((width - 32) / 42)));
  const rows = Math.ceil(ordered.length / columns);
  const horizontalGap = (width - 32) / columns;
  const verticalGap = (height - 40) / rows;
  return ordered.map((cluster, index) => ({
    cluster,
    clusterId: id(cluster.cluster_id),
    x: 16 + (index % columns + .5) * horizontalGap,
    y: 20 + (Math.floor(index / columns) + .5) * verticalGap,
    radius: Math.min(10, 6 + Math.log1p(number(cluster.n_nodes)) * .65),
  }));
}

export function selectClusterNodes(nodes, selectedId, maxPerDepth = 18) {
  const selected = id(selectedId);
  const result = [];
  for (let depth = 0; depth <= 4; depth++) {
    const layer = nodes.filter((node) => Math.max(0, Math.min(4, number(node.depth))) === depth)
      .sort((a, b) => number(b.priority_score) - number(a.priority_score) || id(a.gid).localeCompare(id(b.gid)));
    const visible = layer.slice(0, maxPerDepth);
    const chosen = layer.find((node) => id(node.gid) === selected);
    if (chosen && !visible.includes(chosen)) visible[visible.length - 1] = chosen;
    result.push(...visible);
  }
  return result;
}

export function layoutByDepth(nodes, width, height) {
  const points = [];
  for (let depth = 0; depth <= 4; depth++) {
    const layer = nodes.filter((node) => Math.max(0, Math.min(4, number(node.depth))) === depth);
    layer.forEach((node, row) => points.push({
      id: id(node.gid), node,
      x: 40 + depth * (width - 80) / 4,
      y: 30 + (row + .5) * (height - 60) / layer.length,
    }));
  }
  return points;
}

export function selectEgoEdges(incoming, outgoing, width) {
  const limit = width < 600 ? 24 : 36;
  function strongest(edges, neighbor) {
    const sorted = [...edges].sort((a, b) => number(b.sum_kzt) - number(a.sum_kzt));
    const seen = new Set();
    return sorted.filter((edge) => {
      const value = id(edge[neighbor]);
      if (seen.has(value)) return false;
      seen.add(value);
      return true;
    }).slice(0, limit);
  }
  return { incoming: strongest(incoming, 'src'), outgoing: strongest(outgoing, 'dst') };
}