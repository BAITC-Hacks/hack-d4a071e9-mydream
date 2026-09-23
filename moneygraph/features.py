"""Метрики узлов: графовые (edges) и временные (transactions). Схема — DESIGN.md §3.2."""
import networkx as nx
import numpy as np
import pandas as pd

from . import config as C


def _graph_features(G: nx.DiGraph, nodes: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    df = nodes[["gid", "depth", "is_seed"]].copy()
    df["gid"] = df.gid.astype("int64")
    seeds = set(df[df.is_seed].gid)

    maps = {
        "in_deg": dict(G.in_degree()), "out_deg": dict(G.out_degree()),
        "in_kzt": dict(G.in_degree(weight="sum_kzt")), "out_kzt": dict(G.out_degree(weight="sum_kzt")),
        "in_tx": dict(G.in_degree(weight="n_tx")), "out_tx": dict(G.out_degree(weight="n_tx")),
        "pagerank_w": nx.pagerank(G, weight="sum_kzt"),
        "betweenness": nx.betweenness_centrality(G, normalized=True),
    }
    hubs, auths = nx.hits(G, max_iter=500)
    maps["hub"], maps["authority"] = hubs, auths
    for k, m in maps.items():
        df[k] = df.gid.map(m).fillna(0.0)
    for k in ("in_deg", "out_deg", "in_tx", "out_tx"):
        df[k] = df[k].astype(int)

    df["pass_through"] = np.where(df.in_kzt > 0, df.out_kzt / df.in_kzt.replace(0, np.nan), np.nan)
    df["truncated"] = (df.depth == 4) & (df.out_deg == 0)
    df["no_edges"] = (df.in_deg == 0) & (df.out_deg == 0)

    # seed-источники
    e_seed = edges[edges.src.isin(seeds)]
    df["n_seed_src"] = df.gid.map(e_seed.groupby("dst").src.nunique()).fillna(0).astype(int)
    seed_kzt = e_seed.groupby("dst").sum_kzt.sum()
    df["seed_kzt_share"] = np.where(df.in_kzt > 0, df.gid.map(seed_kzt).fillna(0) / df.in_kzt.replace(0, np.nan), 0.0)

    # концентрация входящих и средний чек
    max_src = edges.groupby("dst").sum_kzt.max()
    df["max_single_src_share"] = np.where(df.in_kzt > 0, df.gid.map(max_src).fillna(0) / df.in_kzt.replace(0, np.nan), 0.0)
    df["avg_in_tx"] = np.where(df.in_tx > 0, df.in_kzt / df.in_tx.replace(0, np.nan), 0.0)
    df["avg_out_tx"] = np.where(df.out_tx > 0, df.out_kzt / df.out_tx.replace(0, np.nan), 0.0)

    # компоненты
    comp = {}
    for i, c in enumerate(sorted(nx.weakly_connected_components(G), key=len, reverse=True)):
        for n in c:
            comp[n] = i
    df["component_id"] = df.gid.map(comp).fillna(-1).astype(int)
    sizes = df[df.component_id >= 0].component_id.value_counts()
    df["component_size"] = df.component_id.map(sizes).fillna(1).astype(int)

    # циклы (возвратные потоки)
    in_cycle = set()
    for cyc in nx.simple_cycles(G, length_bound=C.CYCLE_MAX_LEN):
        in_cycle.update(cyc)
    df["in_cycle"] = df.gid.isin(in_cycle)
    return df


def _time_features(df: pd.DataFrame, tx: pd.DataFrame) -> pd.DataFrame:
    fi = tx.groupby("dst").date.agg(in_first="min", in_last="max")
    fo = tx.groupby("src").date.agg(out_first="min", out_last="max")
    df = df.merge(fi, left_on="gid", right_index=True, how="left")
    df = df.merge(fo, left_on="gid", right_index=True, how="left")
    df["lag_days"] = (df.out_first - df.in_first).dt.days

    # доля исходящей суммы, ушедшей <= FAST_DAYS после первого прихода к этому узлу
    first_in = fi.in_first
    t = tx.merge(first_in.rename("first_in"), left_on="src", right_index=True, how="inner")
    fast = t[(t.date - t.first_in).dt.days.between(0, C.FAST_DAYS)].groupby("src").sum_kzt.sum()
    df["fast_pass_share"] = np.where(df.out_kzt > 0, df.gid.map(fast).fillna(0) / df.out_kzt.replace(0, np.nan), 0.0)

    days = pd.concat([tx[["src", "date"]].rename(columns={"src": "gid"}),
                      tx[["dst", "date"]].rename(columns={"dst": "gid"})]).groupby("gid").date.nunique()
    df["active_days"] = df.gid.map(days).fillna(0).astype(int)

    burst = tx.groupby(["src", "dst", "date"]).size().groupby(level=[0, 1]).max()
    b_src = burst.groupby(level=0).max()
    b_dst = burst.groupby(level=1).max()
    df["same_day_burst"] = np.maximum(df.gid.map(b_src).fillna(0), df.gid.map(b_dst).fillna(0)).astype(int)
    return df


def compute(G: nx.DiGraph, nodes: pd.DataFrame, edges: pd.DataFrame, tx: pd.DataFrame) -> pd.DataFrame:
    df = _graph_features(G, nodes, edges)
    df = _time_features(df, tx)
    print(f"[features] {df.shape[1]} колонок, betweenness>0 у {(df.betweenness > 0).sum()}, в циклах {df.in_cycle.sum()}")
    return df
