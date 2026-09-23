"""Загрузка parquet, проверка консистентности, сборка направленного графа."""
from pathlib import Path

import networkx as nx
import pandas as pd


def load(data_dir: Path):
    edges = pd.read_parquet(data_dir / "edges.parquet")
    nodes = pd.read_parquet(data_dir / "nodes.parquet")
    tx = pd.read_parquet(data_dir / "transactions.parquet")
    tx["date"] = pd.to_datetime(tx["date"])
    return edges, nodes, tx


def sanity_check(edges, nodes, tx):
    agg = tx.groupby(["src", "dst"]).agg(s=("sum_kzt", "sum")).reset_index()
    m = edges.merge(agg, on=["src", "dst"], how="outer", indicator=True)
    if not (m._merge == "both").all():
        raise ValueError("edges и transactions не сходятся по парам")
    in_edges = set(edges.src) | set(edges.dst)
    orphans = set(nodes.gid) - in_edges
    print(f"[load] узлов {len(nodes)}, рёбер {len(edges)}, транзакций {len(tx)}, "
          f"seed {int(nodes.is_seed.sum())}, без рёбер {len(orphans)}, "
          f"оборот {edges.sum_kzt.sum():,.0f} KZT")
    return orphans


def build_graph(edges) -> nx.DiGraph:
    G = nx.DiGraph()
    for r in edges.itertuples(index=False):
        G.add_edge(int(r.src), int(r.dst), sum_kzt=float(r.sum_kzt), n_tx=int(r.n_tx), depth=int(r.depth))
    return G
