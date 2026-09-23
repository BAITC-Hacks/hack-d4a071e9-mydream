// Only computed, anonymized graph facts are eligible for external assistant input.
const LIMITS = Object.freeze({ nodes: 60, edges: 160, sources: 20, recipients: 10, paths_per_kind: 5 });
const ROLES = new Set(['consolidator', 'transit', 'distributor', 'terminal', 'coordinator', 'peripheral']);
const NODE_NUMBERS = [
  'role_score', 'cluster_id', 'priority_score', 'in_deg', 'out_deg', 'in_kzt', 'out_kzt',
  'in_tx', 'out_tx', 'pagerank', 'betweenness', 'pass_through', 'depth', 'active_days', 'data_quality',
  'continuation_rate', 'continuation_support',
];
const BOUNDARY_LABELS = new Set(['likely_terminal', 'uncertain', 'likely_continues']);
const FACTORS = ['role', 'volume', 'degree', 'bridge', 'activity', 'data_quality_penalty'];
const OPTIONAL_NUMBERS = ['transit_2d_count', 'burst_days', 'synchronous_payers_days', 'splitting_groups', 'route_count', 'cycle_count'];
const validGid = (value) => typeof value === 'string' && /^\d{15,19}$/.test(value);
const edgeKey = (source, target) => `${source}:${target}`;
const numeric = (value) => typeof value === 'number' && Number.isFinite(value);
const priority = (node) => numeric(node?.priority_score) ? node.priority_score : 0;
const array = (value) => Array.isArray(value) ? value : [];

function copyNumbers(source, keys) {
  const result = {};
  for (const key of keys) if (numeric(source?.[key])) result[key] = source[key];
  return result;
}

function graphNode(node) {
  const result = { gid: node.gid, ...copyNumbers(node, NODE_NUMBERS) };
  if (ROLES.has(node.role)) result.role = node.role;
  if (BOUNDARY_LABELS.has(node.boundary_label)) result.boundary_label = node.boundary_label;
  if (typeof node.evidence === 'string') result.evidence = node.evidence.slice(0, 400);
  for (const key of ['is_seed', 'truncated_by_depth']) {
    if (typeof node[key] === 'boolean') result[key] = node[key];
  }
  if (node.priority_factors) result.priority_factors = copyNumbers(node.priority_factors, FACTORS);
  if (node.optional) {
    result.optional = copyNumbers(node.optional, OPTIONAL_NUMBERS);
    if (['depth_limit', 'observed_terminal', 'observed'].includes(node.optional.observation)) {
      result.optional.observation = node.optional.observation;
    }
    if (Array.isArray(node.optional.peer_outliers)) {
      result.optional.peer_outliers = node.optional.peer_outliers
        .filter((item) => typeof item === 'string').slice(0, 6).map((item) => item.slice(0, 160));
    }
  }
  return result;
}

function graphIndex(network) {
  const nodes = new Map();
  const edges = new Map();
  const outgoing = new Map();
  const incoming = new Map();
  for (const node of array(network?.nodes)) {
    if (node && validGid(node.gid)) nodes.set(node.gid, graphNode(node));
  }
  for (const edge of array(network?.edges)) {
    if (!edge || !nodes.has(edge.src) || !nodes.has(edge.dst)) continue;
    const key = edgeKey(edge.src, edge.dst);
    if (edges.has(key)) continue;
    const item = { src: edge.src, dst: edge.dst, ...copyNumbers(edge, ['sum_kzt', 'n_tx', 'depth']) };
    edges.set(key, item);
    if (!outgoing.has(item.src)) outgoing.set(item.src, []);
    if (!incoming.has(item.dst)) incoming.set(item.dst, []);
    outgoing.get(item.src).push(item);
    incoming.get(item.dst).push(item);
  }
  // Stable ordering makes equally short witness paths reproducible.
  for (const list of outgoing.values()) list.sort((a, b) => a.dst.localeCompare(b.dst));
  for (const list of incoming.values()) list.sort((a, b) => (b.sum_kzt || 0) - (a.sum_kzt || 0) || a.src.localeCompare(b.src));
  return { nodes, edges, outgoing, incoming };
}

function recipientCandidates(sources, graph) {
  const candidates = new Map();
  const sourceSet = new Set(sources);
  for (const source of sources) {
    const reached = new Map();
    const direct = graph.outgoing.get(source) || [];
    for (const edge of direct) if (edge.dst !== source) reached.set(edge.dst, [source, edge.dst]);
    for (const first of direct) {
      for (const second of graph.outgoing.get(first.dst) || []) {
        if (second.dst !== source && !reached.has(second.dst)) reached.set(second.dst, [source, first.dst, second.dst]);
      }
    }
    for (const [target, path] of reached) {
      if (sourceSet.has(target)) continue;
      if (!candidates.has(target)) candidates.set(target, { gid: target, witnesses: [], min_hops: 2 });
      const candidate = candidates.get(target);
      candidate.witnesses.push({ source, path });
      candidate.min_hops = Math.min(candidate.min_hops, path.length - 1);
    }
  }
  return [...candidates.values()]
    .filter((item) => sources.length === 1 || item.witnesses.length >= 2)
    .sort((a, b) => b.witnesses.length - a.witnesses.length || a.min_hops - b.min_hops ||
      priority(graph.nodes.get(b.gid)) - priority(graph.nodes.get(a.gid)) || a.gid.localeCompare(b.gid));
}

function validPatterns(items, graph, sources, cycle) {
  const selected = new Set(sources);
  return array(items).filter((item) => {
    const path = item?.path;
    if (!Array.isArray(path) || (cycle ? path.length < 2 || path.length > 4 : path.length !== 3)) return false;
    if (new Set(path).size !== path.length || path.some((gid) => !graph.nodes.has(gid))) return false;
    if (selected.size && !path.some((gid) => selected.has(gid))) return false;
    if (!path.slice(1).every((gid, index) => graph.edges.has(edgeKey(path[index], gid)))) return false;
    return !cycle || graph.edges.has(edgeKey(path.at(-1), path[0]));
  });
}

export function buildAssistantContext(question, network, selectedId = null) {
  const graph = graphIndex(network);
  const named = [...new Set(String(question ?? '').match(/(?<!\d)\d{15,19}(?!\d)/g) || [])];
  const unknown = named.filter((gid) => !graph.nodes.has(gid));
  const selected = !named.length && validGid(selectedId) ? selectedId : null;
  if (selected && !graph.nodes.has(selected)) unknown.push(selected);
  const allSources = named.length ? named.filter((gid) => graph.nodes.has(gid))
    : selected && graph.nodes.has(selected) ? [selected] : [];
  const sources = allSources.slice(0, LIMITS.sources);
  const unknownOnly = !sources.length && unknown.length > 0;
  const includedNodes = new Map();
  const includedEdges = new Map();
  let nodeLimitReached = false;
  let edgeLimitReached = false;
  const addNode = (gid) => {
    if (includedNodes.has(gid)) return true;
    if (!graph.nodes.has(gid)) return false;
    if (includedNodes.size >= LIMITS.nodes) { nodeLimitReached = true; return false; }
    includedNodes.set(gid, graph.nodes.get(gid));
    return true;
  };
  // Witness paths are admitted atomically, so no answer cites a broken path.
  const addPath = (path, cycle = false) => {
    const closed = cycle ? [...path, path[0]] : path;
    const pathEdges = closed.slice(1).map((gid, index) => graph.edges.get(edgeKey(closed[index], gid)));
    if (pathEdges.some((edge) => !edge)) return false;
    const newNodes = new Set(path.filter((gid) => !includedNodes.has(gid)));
    const newEdges = new Set(pathEdges.filter((edge) => !includedEdges.has(edgeKey(edge.src, edge.dst))).map((edge) => edgeKey(edge.src, edge.dst)));
    if (includedNodes.size + newNodes.size > LIMITS.nodes) { nodeLimitReached = true; return false; }
    if (includedEdges.size + newEdges.size > LIMITS.edges) { edgeLimitReached = true; return false; }
    for (const gid of path) addNode(gid);
    for (const edge of pathEdges) includedEdges.set(edgeKey(edge.src, edge.dst), edge);
    return true;
  };

  for (const gid of sources) addNode(gid);
  if (!sources.length && !unknownOnly) {
    [...graph.nodes.values()].sort((a, b) => priority(b) - priority(a) || a.gid.localeCompare(b.gid))
      .slice(0, 5).forEach((node) => addNode(node.gid));
  }
  const optional = { cycles: [], repeated_routes: [] };
  const questionText = String(question ?? '').toLocaleLowerCase('ru');
  const resilience = !unknownOnly && /устойчив|изъят|удал|распад/.test(questionText) ? network?.optional?.resilience : null;
  if (resilience) {
    optional.resilience = {
      ...copyNumbers(resilience, ['baseline_components', 'baseline_largest', 'baseline_largest_share_pct']),
      scope: 'full_observed_network',
      remove_top: array(resilience.remove_top).slice(0, 3).map((scenario) => {
        const removed = array(scenario.removed_gids).filter((gid) => graph.nodes.has(gid));
        const kept = removed.slice(0, 10).filter((gid) => addNode(gid));
        return { ...copyNumbers(scenario, ['n', 'components', 'largest_component', 'largest_share_pct']),
          removed_gids: kept, removed_gids_omitted: array(scenario.removed_gids).length - kept.length };
      }),
    };
    if (typeof resilience.method === 'string') optional.resilience.method = resilience.method.slice(0, 400);
  }
  const cycles = unknownOnly ? [] : validPatterns(network?.optional?.cycles, graph, sources, true);
  const routes = unknownOnly ? [] : validPatterns(network?.optional?.repeated_routes, graph, sources, false);
  const addPatterns = () => {
    for (const [items, key, cycle] of [[cycles, 'cycles', true], [routes, 'repeated_routes', false]]) {
      for (const item of items) {
        if (optional[key].length >= LIMITS.paths_per_kind) break;
        if (addPath(item.path, cycle)) optional[key].push({ path: [...item.path], ...copyNumbers(item, cycle ? [] : ['matching_days']) });
      }
    }
  };
  const patternsFirst = /цикл|возврат|маршрут|цепочк/.test(questionText);
  if (patternsFirst) addPatterns();

  const candidates = recipientCandidates(sources, graph);
  const commonRecipients = [];
  for (const candidate of candidates) {
    if (commonRecipients.length >= LIMITS.recipients) break;
    const witnesses = [];
    for (const witness of candidate.witnesses) {
      if (!addPath(witness.path)) continue;
      witnesses.push({ source: witness.source, path: witness.path,
        edges: witness.path.slice(1).map((target, index) => ({ src: witness.path[index], dst: target })) });
    }
    if (!witnesses.length) continue;
    commonRecipients.push({ gid: candidate.gid, coverage: candidate.witnesses.length, source_count: sources.length,
      min_hops: candidate.min_hops, witnesses, witnesses_truncated: witnesses.length < candidate.witnesses.length });
  }
  if (!patternsFirst) addPatterns();

  // Individual outgoing paths still matter when the requested sources have no
  // shared recipient. Sample strongest paths fairly before filling neighbors.
  const strongestOutgoing = (source) => [...(graph.outgoing.get(source) || [])]
    .sort((a, b) => (b.sum_kzt || 0) - (a.sum_kzt || 0) || a.dst.localeCompare(b.dst)).slice(0, 3);
  const firstHops = sources.map((source) => ({ source, edges: strongestOutgoing(source) }));
  for (let index = 0; index < 3; index += 1) {
    for (const item of firstHops) {
      const first = item.edges[index];
      if (first) addPath([item.source, first.dst]);
    }
  }
  for (const item of firstHops) {
    for (const first of item.edges.slice(0, 2)) {
      for (const second of strongestOutgoing(first.dst).slice(0, 2)) addPath([item.source, first.dst, second.dst]);
    }
  }

  const anchors = [...includedNodes.keys()];
  for (const target of anchors) {
    for (const edge of graph.incoming.get(target) || []) addPath([edge.src, edge.dst]);
  }
  // Include remaining observed edges between chosen nodes, within the edge budget.
  for (const source of [...includedNodes.keys()]) {
    for (const edge of graph.outgoing.get(source) || []) {
      if (includedNodes.has(edge.dst)) addPath([edge.src, edge.dst]);
    }
  }
  if (!unknownOnly && typeof network?.optional?.method_limits === 'string') {
    optional.method_limits = network.optional.method_limits.slice(0, 600);
  }
  optional.cycles_truncated = Boolean(network?.optional?.cycles_truncated) || optional.cycles.length < cycles.length;
  optional.repeated_routes_truncated = optional.repeated_routes.length < routes.length;

  return {
    nodes: [...includedNodes.values()], edges: [...includedEdges.values()], sources,
    unknown_gids: unknown, common_recipients: commonRecipients, optional,
    scope: {
      ...(typeof network?.meta?.scope === 'string' ? { dataset_scope: network.meta.scope.slice(0, 600) } : {}),
      selection: named.length ? 'named_gids' : selected ? 'selected_node' : 'network_overview',
      selected_node_used: Boolean(selected && sources.includes(selected)),
      source_count_total: allSources.length, sources_truncated: allSources.length > sources.length,
      network_nodes: graph.nodes.size, network_edges: graph.edges.size,
      nodes_sent: includedNodes.size, edges_sent: includedEdges.size,
      context_is_partial: includedNodes.size < graph.nodes.size || includedEdges.size < graph.edges.size,
      node_limit_reached: nodeLimitReached, edge_limit_reached: edgeLimitReached,
      recipient_hops: 2, candidates_total: candidates.length,
      recipients_truncated: commonRecipients.length < candidates.length,
      optional_available: Boolean(network?.optional), limits: LIMITS,
      limitation: 'Контекст — ограниченная часть наблюдаемой обезличенной сети. Покрытие кандидата рассчитано по выбранным исходным GID в полном локальном графе, пути показаны в пределах лимита. Связь по пути не доказывает движение тех же денег; роль и приоритет являются гипотезами, не вероятностью виновности.',
    },
  };
}
