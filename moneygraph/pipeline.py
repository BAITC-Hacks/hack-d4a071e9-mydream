"""Оркестрация: load -> features -> clusters -> roles -> priority -> export."""
import time
from pathlib import Path


def run(data_dir: Path, out_dir: Path):
    from . import load, features, roles, clusters, priority, export
    t0 = time.time()
    edges, nodes, tx = load.load(data_dir)
    load.sanity_check(edges, nodes, tx)
    G = load.build_graph(edges)
    df = features.compute(G, nodes, edges, tx)
    df = clusters.assign(G, df)
    df = roles.assign(df, edges)
    df = priority.score(df)
    export.write(df, edges, out_dir)
    print(f"[done] {time.time() - t0:.1f} с")
