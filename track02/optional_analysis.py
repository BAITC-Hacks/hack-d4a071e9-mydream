"""Deterministic extra graph signals from the provided anonymized extract only."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from itertools import islice
from statistics import median

import networkx as nx
import pandas as pd


def _temporal_and_splitting(tx: pd.DataFrame) -> dict[int, dict]:
    incoming = defaultdict(list)
    outgoing = defaultdict(list)
    activity = defaultdict(Counter)
    payers = defaultdict(lambda: defaultdict(set))
    pair_day = defaultdict(list)
    for row in tx.itertuples(index=False):
        source, target = int(row.src), int(row.dst)
        day = pd.Timestamp(row.date).date()
        outgoing[source].append(day)
        incoming[target].append(day)
        activity[source][day] += 1
        if source != target:
            activity[target][day] += 1
        payers[target][day].add(source)
        pair_day[(source, target, day)].append(float(row.sum_kzt))

    split_by_source = Counter()
    for (source, _, _), amounts in pair_day.items():
        if sum(5000 <= amount <= 25000 for amount in amounts) >= 3:
            split_by_source[source] += 1

    result = {}
    for gid in set(incoming) | set(outgoing):
        exit_days = sorted(outgoing[gid])
        transit = sum(
            any(day <= exit_day <= day + timedelta(days=2) for exit_day in exit_days)
            for day in incoming[gid]
        )
        daily = list(activity[gid].values())
        result[gid] = {
            "transit_2d_count": transit,
            "burst_days": sum(count >= 3 and count >= 2 * median(daily) for count in daily)
            if len(daily) >= 3 else 0,
            "synchronous_payers_days": sum(len(sources) >= 3 for sources in payers[gid].values()),
            "splitting_groups": split_by_source[gid],
        }
    return result


def _routes_and_cycles(graph: nx.DiGraph, tx: pd.DataFrame) -> tuple[list[dict], list[dict], bool]:
    pair_dates = defaultdict(set)
    for row in tx.itertuples(index=False):
        pair_dates[(int(row.src), int(row.dst))].add(pd.Timestamp(row.date).date())

    routes = []
    for middle in graph:
        for source in graph.predecessors(middle):
            for target in graph.successors(middle):
                if source == target or source == middle or target == middle:
                    continue
                common_days = pair_dates[(source, middle)] & pair_dates[(middle, target)]
                if len(common_days) >= 2:
                    routes.append({"path": [str(source), str(middle), str(target)],
                                   "matching_days": len(common_days)})
    routes.sort(key=lambda item: (-item["matching_days"], item["path"]))

    # Length and count bounds keep the optional stage safe on denser graphs.
    found = list(islice(nx.simple_cycles(graph, length_bound=4), 2001))
    cycles = [{"path": [str(gid) for gid in path]} for path in found[:2000] if len(path) >= 2]
    cycles.sort(key=lambda item: (len(item["path"]), item["path"]))
    return routes[:2000], cycles, len(found) > 2000


def _resilience(graph: nx.DiGraph, roles: pd.DataFrame) -> dict:
    undirected = graph.to_undirected()
    n_nodes = len(undirected)
    baseline_components = list(nx.connected_components(undirected)) if n_nodes else []
    baseline_largest = max(map(len, baseline_components), default=0)
    ranking = roles.sort_values(["priority_score", "gid"], ascending=[False, True]).gid.tolist()
    outcomes = []
    for count in (1, 5, 10):
        removed = ranking[:min(count, n_nodes)]
        remaining = undirected.copy()
        remaining.remove_nodes_from(removed)
        components = list(nx.connected_components(remaining)) if remaining else []
        largest = max(map(len, components), default=0)
        outcomes.append({
            "n": len(removed), "removed_gids": [str(gid) for gid in removed],
            "components": len(components), "largest_component": largest,
            "largest_share_pct": round(100 * largest / max(1, len(remaining)), 1),
        })
    return {
        "baseline_components": len(baseline_components),
        "baseline_largest": baseline_largest,
        "baseline_largest_share_pct": round(100 * baseline_largest / max(1, n_nodes), 1),
        "remove_top": outcomes,
        "method": "Слабые компоненты после удаления топ-1/5/10 по текущему приоритету; переводы не моделируются заново.",
    }


def build_optional_analysis(
    nodes: pd.DataFrame, tx: pd.DataFrame, graph: nx.DiGraph, roles: pd.DataFrame
) -> tuple[dict[int, dict], dict]:
    """Return per-node signals and network-wide route/fragmentation evidence."""
    temporal = _temporal_and_splitting(tx)
    routes, cycles, cycles_truncated = _routes_and_cycles(graph, tx)
    route_count = Counter(gid for route in routes for gid in map(int, route["path"]))
    cycle_count = Counter(gid for cycle in cycles for gid in map(int, cycle["path"]))
    peer_flags = defaultdict(list)
    for depth, group in roles.groupby("depth"):
        if len(group) < 30:
            continue
        for column, label in (("in_kzt", "входящий объём"), ("out_kzt", "исходящий объём"),
                              ("in_deg", "число отправителей"), ("out_deg", "число получателей")):
            values = group[column]
            cutoff = values.quantile(0.99)
            baseline = values.median()
            unusual = group[(values >= cutoff) & (values > 1.5 * baseline) & (values > 0)]
            for gid in unusual.gid:
                peer_flags[int(gid)].append(f"{label} в верхнем 1% колена {int(depth)}")

    by_gid = {}
    for row in roles.itertuples(index=False):
        gid = int(row.gid)
        item = temporal.get(gid, {
            "transit_2d_count": 0, "burst_days": 0,
            "synchronous_payers_days": 0, "splitting_groups": 0,
        }).copy()
        item["observation"] = "depth_limit" if row.truncated_by_depth else (
            "observed_terminal" if row.out_deg == 0 and row.in_deg > 0 else "observed"
        )
        item["route_count"] = route_count[gid]
        item["cycle_count"] = cycle_count[gid]
        item["peer_outliers"] = peer_flags[gid]
        by_gid[gid] = item
    global_signals = {
        "repeated_routes": routes, "cycles": cycles,
        "cycles_truncated": cycles_truncated,
        "resilience": _resilience(graph, roles),
        "method_limits": "Время известно только с точностью до дня; совпадение дат не доказывает прохождение тех же денег. Маршруты требуют совпадения обоих рёбер минимум в два разных дня; циклы ограничены длиной 2–4.",
    }
    return by_gid, global_signals
