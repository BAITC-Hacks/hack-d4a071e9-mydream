#!/usr/bin/env python3
"""Explainable analysis of the observed HackAlem transfer graph.

Roles describe patterns inside the July 2026, outgoing-only, four-hop extract.
They are not findings of misconduct or statements about unobserved transfers.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from time import perf_counter

# The demo can run after a local ``pip install --target track02/.deps``.
LOCAL_DEPS = Path(__file__).resolve().parent / ".deps"
if LOCAL_DEPS.is_dir():
    sys.path.insert(0, str(LOCAL_DEPS))

import duckdb
import networkx as nx
import numpy as np
import pandas as pd

from optional_analysis import build_optional_analysis


ROLES = {"consolidator", "transit", "distributor", "terminal", "coordinator", "peripheral"}
ROLE_WEIGHT = {
    "coordinator": 1.0,
    "consolidator": 0.95,
    "distributor": 0.9,
    "transit": 0.85,
    "terminal": 0.55,
    "peripheral": 0.15,
}
ROLE_COLUMNS = [
    "gid", "role", "role_score", "cluster_id", "priority_score", "evidence",
    "in_deg", "out_deg", "in_kzt", "out_kzt", "in_tx", "out_tx",
    "pagerank", "betweenness", "pass_through", "depth", "is_seed",
    "truncated_by_depth", "active_days", "data_quality",
    "continuation_rate", "continuation_support", "boundary_label",
]
# Depth-4 nodes without outgoing edges are compared with depth 1-3 nodes whose
# outgoing transfers the crawl did trace. The share of those reference nodes
# that sent money onward, per band of incoming operations, estimates whether
# the crawl cut the chain or the money really stopped.
CONTINUATION_BANDS = [(1, 1, "1 операция"), (2, 2, "2 операции"), (3, 5, "3–5 операций"), (6, None, "6+ операций")]
CONTINUATION_MIN_SUPPORT = 30
CONTINUATION_TERMINAL_MAX = 1 / 3
CONTINUATION_CONTINUES_MIN = 2 / 3
ROLE_CSV_COLUMNS = ["gid", "role", "role_score", "cluster_id", "priority_score", "evidence"]
CLUSTER_COLUMNS = ["cluster_id", "n_nodes", "n_seed", "sum_kzt_internal", "top_gids", "hypothesis"]
TOP_COLUMNS = ["rank", "gid", "role", "priority_score", "why"]


def load_data(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read parquet with DuckDB, avoiding a second Arrow dependency."""
    data_dir = Path(data_dir)
    frames = []
    for name in ("nodes", "edges", "transactions"):
        path = data_dir / f"{name}.parquet"
        if not path.is_file():
            raise FileNotFoundError(f"Missing input: {path}")
        frames.append(duckdb.read_parquet(str(path)).df())
    return tuple(frames)


def validate_data(nodes: pd.DataFrame, edges: pd.DataFrame, tx: pd.DataFrame) -> None:
    """Fail early when an input cannot support the stated evidence."""
    required = [
        (nodes, {"gid", "depth", "is_seed"}, "nodes"),
        (edges, {"src", "dst", "sum_kzt", "n_tx", "depth"}, "edges"),
        (tx, {"src", "dst", "date", "sum_kzt"}, "transactions"),
    ]
    for frame, columns, name in required:
        missing = columns - set(frame.columns)
        if missing:
            raise ValueError(f"{name} missing columns: {sorted(missing)}")
        if frame[list(columns)].isna().any().any():
            raise ValueError(f"{name} contains nulls in required columns")
    if nodes.gid.duplicated().any():
        raise ValueError("nodes contains duplicate gid")
    if edges.duplicated(["src", "dst"]).any():
        raise ValueError("edges contains duplicate directed pairs")
    gids = set(nodes.gid)
    if not set(edges.src).union(edges.dst).issubset(gids):
        raise ValueError("edge endpoint missing from nodes")
    if (edges.sum_kzt <= 0).any() or (edges.n_tx <= 0).any() or (tx.sum_kzt <= 0).any():
        raise ValueError("transfer amounts and counts must be positive")
    if ((nodes.depth == 0) != nodes.is_seed).any():
        raise ValueError("seed and depth=0 disagree")
    if not tx.empty:
        grouped = tx.groupby(["src", "dst"], as_index=False).agg(
            tx_amount=("sum_kzt", "sum"), tx_count=("sum_kzt", "size")
        )
        joined = edges.merge(grouped, on=["src", "dst"], how="outer", indicator=True)
        if not joined._merge.eq("both").all():
            raise ValueError("edge pairs and transaction pairs differ")
        if not np.allclose(joined.sum_kzt, joined.tx_amount, atol=0.01, rtol=1e-9):
            raise ValueError("edge sums and transaction sums differ")
        if not joined.n_tx.eq(joined.tx_count).all():
            raise ValueError("edge counts and transaction counts differ")


def build_graph(nodes: pd.DataFrame, edges: pd.DataFrame) -> nx.DiGraph:
    """Keep direction and monetary weights; include isolated seeds."""
    graph = nx.DiGraph()
    graph.add_nodes_from(int(gid) for gid in nodes.gid)
    for row in edges.itertuples(index=False):
        amount = float(row.sum_kzt)
        graph.add_edge(
            int(row.src), int(row.dst), sum_kzt=amount, n_tx=int(row.n_tx),
            distance=1.0 / math.log1p(amount),
        )
    return graph


def weighted_pagerank(graph: nx.DiGraph, iterations: int = 100) -> dict[int, float]:
    """Amount-weighted PageRank via power iteration, including isolates."""
    gids = list(graph.nodes)
    count = len(gids)
    if not count:
        return {}
    index = {gid: i for i, gid in enumerate(gids)}
    source = np.fromiter((index[u] for u, _ in graph.edges), dtype=int)
    dest = np.fromiter((index[v] for _, v in graph.edges), dtype=int)
    weight = np.fromiter((graph[u][v]["sum_kzt"] for u, v in graph.edges), dtype=float)
    total_out = np.bincount(source, weights=weight, minlength=count)
    transition = weight / total_out[source] if len(weight) else weight
    rank = np.full(count, 1.0 / count)
    damping = 0.85
    for _ in range(iterations):
        dangling = rank[total_out == 0].sum()
        updated = np.full(count, (1 - damping + damping * dangling) / count)
        if len(weight):
            np.add.at(updated, dest, damping * rank[source] * transition)
        if np.abs(updated - rank).sum() < 1e-10:
            rank = updated
            break
        rank = updated
    return dict(zip(gids, rank.tolist()))


def node_features(nodes: pd.DataFrame, tx: pd.DataFrame, graph: nx.DiGraph) -> pd.DataFrame:
    features = nodes[["gid", "depth", "is_seed"]].copy()
    measures = {
        "in_deg": dict(graph.in_degree()),
        "out_deg": dict(graph.out_degree()),
        "in_kzt": dict(graph.in_degree(weight="sum_kzt")),
        "out_kzt": dict(graph.out_degree(weight="sum_kzt")),
        "in_tx": dict(graph.in_degree(weight="n_tx")),
        "out_tx": dict(graph.out_degree(weight="n_tx")),
        "pagerank": weighted_pagerank(graph),
    }
    for name, values in measures.items():
        features[name] = features.gid.map(values).fillna(0)
    for name in ("in_deg", "out_deg", "in_tx", "out_tx"):
        features[name] = features[name].astype(int)

    # Shortest paths favor larger observed transfers. Sampling bounds runtime.
    sample_size = min(128, len(graph))
    bridge = nx.betweenness_centrality(
        graph, k=sample_size if sample_size < len(graph) else None,
        weight="distance", seed=42, normalized=True,
    ) if graph else {}
    features["betweenness"] = features.gid.map(bridge).fillna(0.0)
    dates = pd.concat([
        tx[["src", "date"]].rename(columns={"src": "gid"}),
        tx[["dst", "date"]].rename(columns={"dst": "gid"}),
    ], ignore_index=True)
    dates["date"] = pd.to_datetime(dates.date).dt.date
    active_days = dates.groupby("gid").date.nunique()
    features["active_days"] = features.gid.map(active_days).fillna(0).astype(int)
    features["pass_through"] = np.where(
        features.in_kzt > 0, features.out_kzt / features.in_kzt.replace(0, np.nan), 0.0
    )
    features["truncated_by_depth"] = (features.depth == 4) & (features.out_deg == 0)
    return features


def continuation_band(in_tx: int) -> str:
    for low, high, label in CONTINUATION_BANDS:
        if in_tx >= low and (high is None or in_tx <= high):
            return label
    return CONTINUATION_BANDS[0][2]


def continuation_reference(features: pd.DataFrame) -> dict[str, dict]:
    """Observed onward-transfer share of depth 1-3 recipients, per incoming band."""
    reference = features[features.depth.between(1, 3) & (features.in_deg > 0)]
    bands = reference.in_tx.astype(int).map(continuation_band)
    table = {}
    for _, _, label in CONTINUATION_BANDS:
        group = reference[bands == label]
        table[label] = {
            "band": label, "support": int(len(group)),
            "rate": round(float((group.out_deg > 0).mean()), 4) if len(group) else None,
        }
    return table


def boundary_assessment(features: pd.DataFrame, reference: dict[str, dict]) -> pd.DataFrame:
    """Label each depth-4 node without outgoing edges by its reference band."""
    rate = pd.Series([None] * len(features), index=features.index, dtype=object)
    support = pd.Series([None] * len(features), index=features.index, dtype=object)
    label = pd.Series([None] * len(features), index=features.index, dtype=object)
    for index in features.index[features.truncated_by_depth]:
        cell = reference[continuation_band(int(features.at[index, "in_tx"]))]
        rate[index], support[index] = cell["rate"], cell["support"]
        if cell["rate"] is None or cell["support"] < CONTINUATION_MIN_SUPPORT:
            label[index] = "uncertain"
        elif cell["rate"] <= CONTINUATION_TERMINAL_MAX:
            label[index] = "likely_terminal"
        elif cell["rate"] >= CONTINUATION_CONTINUES_MIN:
            label[index] = "likely_continues"
        else:
            label[index] = "uncertain"
    return pd.DataFrame({"continuation_rate": rate, "continuation_support": support, "boundary_label": label})


def role_hypothesis(row: pd.Series, bridge_cutoff: float, bridge_rank: float) -> tuple[str, float]:
    """Mutually exclusive, ordered graph-pattern rules."""
    in_deg, out_deg = int(row.in_deg), int(row.out_deg)
    if row.truncated_by_depth:
        if row.boundary_label == "likely_terminal":
            return "terminal", round(min(0.75, 0.45 + 0.4 * (1 - float(row.continuation_rate))), 6)
        return "peripheral", 0.4
    if in_deg == 0 and out_deg == 0:
        return "peripheral", 0.75
    if out_deg == 0 and in_deg > 0:
        return "terminal", min(0.92, 0.78 + 0.03 * min(int(row.in_tx), 4))
    if in_deg >= 2 and out_deg >= 2 and row.betweenness > 0 and row.betweenness >= bridge_cutoff:
        return "coordinator", min(0.98, 0.7 + 0.28 * bridge_rank)
    if in_deg >= 3 and out_deg >= 1 and in_deg >= 1.5 * out_deg:
        score = 0.67 + 0.035 * min(in_deg, 6) + 0.02 * min(int(row.active_days), 4)
        return "consolidator", min(0.96, score)
    if out_deg >= 3 and (bool(row.is_seed) or out_deg >= 1.5 * in_deg):
        score = 0.67 + 0.035 * min(out_deg, 6) + 0.02 * min(int(row.active_days), 4)
        return "distributor", min(0.96, score)
    if in_deg > 0 and out_deg > 0 and not row.is_seed and 0.5 <= row.pass_through <= 2:
        closeness = 1 - min(1.0, abs(math.log(max(row.pass_through, 1e-12))) / math.log(2))
        return "transit", min(0.94, 0.7 + 0.2 * closeness + 0.01 * min(int(row.active_days), 4))
    return "peripheral", 0.55


def evidence_text(row: pd.Series) -> str:
    """State the exact role rule, observed metrics, and observation limit."""
    rule = {
        "coordinator": "≥2 входа и выхода, посредничество в верхних 10%",
        "consolidator": "3 входа или больше, входящих ≥1,5× исходящих",
        "distributor": "≥3 выхода, seed или исходящих ≥1,5× входящих",
        "transit": "есть вход и выход, отношение сумм 0,5–2",
        "terminal": "есть вход, выхода нет в пределах обхода",
        "peripheral": "пороги других ролей не выполнены",
    }[row.role]
    if row.truncated_by_depth:
        verdict = {
            "likely_terminal": "вероятно конечный", "likely_continues": "вероятно продолжение",
        }.get(row.boundary_label, "продолжение неясно")
        if row.continuation_rate is None or row.continuation_support < CONTINUATION_MIN_SUPPORT:
            rule = f"глубина 4; мало сравнимых узлов колен 1–3 ({row.continuation_support}); {verdict}"
        else:
            rule = (f"глубина 4; {continuation_band(int(row.in_tx))}: дальше шли "
                    f"{100 * float(row.continuation_rate):.0f}% из {row.continuation_support} узлов колен 1–3; {verdict}")
    elif row.in_deg == 0 and row.out_deg == 0:
        rule = "наблюдаемых связей нет"
    facts = (
        f"вход {int(row.in_deg)} / {row.in_kzt:,.0f} KZT; "
        f"выход {int(row.out_deg)} / {row.out_kzt:,.0f} KZT; "
        f"операций {int(row.in_tx)}/{int(row.out_tx)}; дней {int(row.active_days)}"
    )
    limit = "; seed: вход неполон" if row.is_seed else ""
    return f"Правило: {rule}; {facts}{limit}"[:200]


def assign_clusters(graph: nx.DiGraph) -> dict[int, int]:
    """Louvain on an undirected projection, used only for grouping."""
    projection = nx.Graph()
    projection.add_nodes_from(graph.nodes)
    for src, dst, data in graph.edges(data=True):
        weight = math.log1p(data["sum_kzt"])
        if projection.has_edge(src, dst):
            projection[src][dst]["weight"] += weight
        else:
            projection.add_edge(src, dst, weight=weight)
    communities = nx.community.louvain_communities(projection, weight="weight", seed=42)
    communities.sort(key=lambda group: (-len(group), min(group)))
    return {gid: cluster_id for cluster_id, group in enumerate(communities) for gid in group}


def cluster_hypothesis(group: pd.DataFrame) -> str:
    counts = group.role.value_counts()
    if counts.get("coordinator", 0) and counts.get("consolidator", 0) and counts.get("distributor", 0):
        pattern = "Сбор, мост и рассылка"
    elif counts.get("consolidator", 0) and counts.get("distributor", 0):
        pattern = "Сбор и дальнейшая рассылка"
    elif counts.get("distributor", 0):
        pattern = "Веер исходящих переводов"
    elif counts.get("consolidator", 0):
        pattern = "Сходящиеся входящие переводы"
    elif counts.get("transit", 0):
        pattern = "Последовательные переводы"
    else:
        pattern = "Получатели и периферия выборки"
    return f"{pattern}; гипотеза по наблюдаемому графу, не вывод о нарушении"


def analyze(
    nodes: pd.DataFrame, edges: pd.DataFrame, tx: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """Run role, data-gap, and interpretable priority stages in that order."""
    validate_data(nodes, edges, tx)
    graph = build_graph(nodes, edges)
    roles = node_features(nodes, tx, graph)
    continuation = continuation_reference(roles)
    roles = pd.concat([roles, boundary_assessment(roles, continuation)], axis=1)
    bridge_rank = roles.betweenness.rank(pct=True)
    eligible = roles.loc[(roles.in_deg >= 2) & (roles.out_deg >= 2) & (roles.betweenness > 0), "betweenness"]
    bridge_cutoff = float(eligible.quantile(0.9)) if not eligible.empty else float("inf")
    hypotheses = [
        role_hypothesis(row, bridge_cutoff, float(bridge_rank.loc[i]))
        for i, row in roles.iterrows()
    ]
    roles["role"] = [item[0] for item in hypotheses]
    roles["role_score"] = [item[1] for item in hypotheses]

    # Critic stage: downweight limited observations without inventing missing flows.
    roles["data_quality"] = 1.0
    roles.loc[roles.is_seed, "data_quality"] *= 0.9
    roles.loc[roles.truncated_by_depth, "data_quality"] *= 0.55
    roles.loc[(roles.in_tx + roles.out_tx) <= 1, "data_quality"] *= 0.75
    roles.loc[(roles.in_deg + roles.out_deg) == 0, "data_quality"] = 0.2
    roles["evidence"] = roles.apply(evidence_text, axis=1)

    volume = np.log1p(roles.in_kzt + roles.out_kzt).rank(pct=True)
    degree = np.log1p(roles.in_deg + roles.out_deg).rank(pct=True)
    activity = ((roles.in_tx + roles.out_tx).rank(pct=True) + roles.active_days.rank(pct=True)) / 2
    role_value = roles.role_score * roles.role.map(ROLE_WEIGHT)
    priority_components = {
        "role": 0.30 * role_value,
        "volume": 0.25 * volume,
        "degree": 0.20 * degree,
        "bridge": 0.15 * bridge_rank,
        "activity": 0.10 * activity,
    }
    raw_priority = sum(priority_components.values())
    roles["priority_score"] = (raw_priority * roles.data_quality).clip(0, 1).round(6)
    roles["priority_factors"] = [
        {
            **{name: round(float(values.iloc[index]) * 100, 4)
               for name, values in priority_components.items()},
            "data_quality_penalty": round(
                float(raw_priority.iloc[index] * (1 - roles.data_quality.iloc[index])) * 100, 4
            ),
        }
        for index in range(len(roles))
    ]
    roles["role_score"] = roles.role_score.round(6)
    roles["data_quality"] = roles.data_quality.round(6)

    cluster_map = assign_clusters(graph)
    roles["cluster_id"] = roles.gid.map(cluster_map).astype(int)
    optional_by_gid, optional_network = build_optional_analysis(nodes, tx, graph, roles)
    factors_by_gid = dict(zip(roles.gid, roles.priority_factors))
    roles = roles[ROLE_COLUMNS].sort_values("gid").reset_index(drop=True)

    internal_amount = {}
    for edge in edges.itertuples(index=False):
        cluster_id = cluster_map[int(edge.src)]
        if cluster_id == cluster_map[int(edge.dst)]:
            internal_amount[cluster_id] = internal_amount.get(cluster_id, 0.0) + float(edge.sum_kzt)
    cluster_rows = []
    for cluster_id, group in roles.groupby("cluster_id", sort=True):
        leaders = group.sort_values(["priority_score", "gid"], ascending=[False, True]).head(5).gid
        cluster_rows.append({
            "cluster_id": int(cluster_id), "n_nodes": int(len(group)),
            "n_seed": int(group.is_seed.sum()),
            "sum_kzt_internal": round(internal_amount.get(int(cluster_id), 0.0), 2),
            "top_gids": ",".join(str(int(gid)) for gid in leaders),
            "hypothesis": cluster_hypothesis(group),
        })
    clusters = pd.DataFrame(cluster_rows, columns=CLUSTER_COLUMNS)

    top = roles.sort_values(["priority_score", "gid"], ascending=[False, True]).head(50).copy()
    top.insert(0, "rank", range(1, len(top) + 1))
    top["why"] = [
        (
            f"{row.evidence}; вклад: роль +{factors_by_gid[row.gid]['role']:.1f}, "
            f"оборот +{factors_by_gid[row.gid]['volume']:.1f}, "
            f"связи +{factors_by_gid[row.gid]['degree']:.1f}, "
            f"посредничество +{factors_by_gid[row.gid]['bridge']:.1f}, "
            f"активность +{factors_by_gid[row.gid]['activity']:.1f}; "
            f"вычет за неполноту −{factors_by_gid[row.gid]['data_quality_penalty']:.1f} п.п."
        )
        for row in top.itertuples(index=False)
    ]
    top = top[TOP_COLUMNS]

    node_columns = ROLE_COLUMNS
    # GIDs exceed IEEE-754's safe integer range; JSON uses strings so browser
    # graph joins cannot silently merge or round distinct client identifiers.
    network_nodes = roles[node_columns].copy()
    network_nodes["priority_factors"] = [factors_by_gid[value] for value in network_nodes.gid]
    network_nodes["optional"] = [optional_by_gid[int(value)] for value in network_nodes.gid]
    network_nodes["gid"] = network_nodes.gid.astype(str)
    for column in ("continuation_rate", "continuation_support", "boundary_label"):
        network_nodes[column] = pd.Series(
            [None if value is None or pd.isna(value) else value for value in network_nodes[column]],
            index=network_nodes.index, dtype=object,
        )
    network_edges = edges[["src", "dst", "sum_kzt", "n_tx", "depth"]].copy()
    network_edges["src"] = network_edges.src.astype(str)
    network_edges["dst"] = network_edges.dst.astype(str)
    network_top = top.copy()
    network_top["gid"] = network_top.gid.astype(str)
    network = {
        "nodes": network_nodes.to_dict("records"),
        "edges": network_edges.to_dict("records"),
        "clusters": clusters.to_dict("records"),
        "top": network_top.to_dict("records"),
        "optional": optional_network,
        "meta": {
            "n_nodes": int(len(nodes)), "n_edges": int(len(edges)),
            "n_transactions": int(len(tx)), "n_seeds": int(nodes.is_seed.sum()),
            "n_clusters": int(len(clusters)), "total_kzt": float(edges.sum_kzt.sum()),
            "n_depth4_censored": int(roles.truncated_by_depth.sum()),
            "boundary_labels": {
                label: int((roles.boundary_label == label).sum())
                for label in ("likely_terminal", "uncertain", "likely_continues")
            },
            "continuation_reference": list(continuation.values()),
            "continuation_thresholds": {
                "terminal_max": round(CONTINUATION_TERMINAL_MAX, 4),
                "continues_min": round(CONTINUATION_CONTINUES_MIN, 4),
                "min_support": CONTINUATION_MIN_SUPPORT,
            },
            "n_orphan_seeds": int(((roles.in_deg + roles.out_deg == 0) & roles.is_seed).sum()),
            "ranking_method": "Weighted interpretable graph metrics with observation-quality discount",
            "cluster_method": "Louvain on log-weighted undirected projection",
            "scope": "July 2026, outgoing-only crawl, >=5000 KZT, max depth 4",
            "runtime_sec": 0.0,
        },
    }
    return roles, clusters, top, network


def transaction_index(nodes: pd.DataFrame, tx: pd.DataFrame) -> dict[str, list[dict]]:
    """Index raw observed transfers by exact GID for the on-demand detail API."""
    indexed = {str(int(gid)): [] for gid in nodes.gid}
    for row in tx.itertuples(index=False):
        source, target = str(int(row.src)), str(int(row.dst))
        transfer = {
            "src": source, "dst": target,
            "date": pd.Timestamp(row.date).date().isoformat(),
            "sum_kzt": float(row.sum_kzt),
        }
        indexed[source].append({**transfer, "direction": "outgoing", "counterparty": target})
        if target != source:
            indexed[target].append({**transfer, "direction": "incoming", "counterparty": source})
    for rows in indexed.values():
        rows.sort(key=lambda transfer: (
            transfer["date"], transfer["src"], transfer["dst"], transfer["sum_kzt"]
        ))
    return indexed


def run_pipeline(data_dir: Path, out_dir: Path) -> dict:
    started = perf_counter()
    nodes, edges, tx = load_data(Path(data_dir))
    roles, clusters, top, network = analyze(nodes, edges, tx)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    roles[ROLE_CSV_COLUMNS].to_csv(out_dir / "nodes_roles.csv", index=False)
    clusters.to_csv(out_dir / "clusters.csv", index=False)
    top.to_csv(out_dir / "top_nodes.csv", index=False)
    network["meta"]["runtime_sec"] = round(perf_counter() - started, 3)
    (out_dir / "network.json").write_text(
        json.dumps(network, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
        encoding="utf-8",
    )
    (out_dir / "transactions_by_gid.json").write_text(
        json.dumps(transaction_index(nodes, tx), ensure_ascii=False, allow_nan=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return network["meta"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).resolve().parent
    parser.add_argument("--data", type=Path, default=here / "data")
    parser.add_argument("--out", type=Path, default=here / "out")
    args = parser.parse_args()
    meta = run_pipeline(args.data, args.out)
    print(f"Wrote {meta['n_nodes']} nodes, {meta['n_edges']} edges, "
          f"{meta['n_clusters']} clusters in {meta['runtime_sec']:.2f}s to {args.out}")


if __name__ == "__main__":
    main()
