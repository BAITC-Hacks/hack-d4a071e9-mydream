"""Запись 3 CSV + features.parquet и валидация схемы (must-have M2, M4, M5)."""
from pathlib import Path

import pandas as pd

from . import config as C
from . import clusters, priority

NODE_COLS = ["gid", "role", "role_score", "cluster_id", "priority_score", "evidence"]
EXTRA_COLS = ["depth", "is_seed", "in_deg", "out_deg", "in_kzt", "out_kzt", "in_tx", "out_tx",
              "pass_through", "truncated", "n_seed_src", "betweenness", "pagerank_w", "lag_days",
              "fast_pass_share", "component_id", "in_cycle"]


def write(df: pd.DataFrame, edges: pd.DataFrame, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    nodes = df[NODE_COLS + EXTRA_COLS].sort_values("gid")
    nodes = nodes.round({"in_kzt": 2, "out_kzt": 2, "pass_through": 4, "betweenness": 6, "pagerank_w": 6, "fast_pass_share": 4})
    nodes.to_csv(out_dir / "nodes_roles.csv", index=False, encoding="utf-8")
    clusters.summarize(df, edges).to_csv(out_dir / "clusters.csv", index=False, encoding="utf-8")
    priority.top_nodes(df).to_csv(out_dir / "top_nodes.csv", index=False, encoding="utf-8")
    df.to_parquet(out_dir / "features.parquet", index=False)
    validate_outputs(out_dir)
    print(f"[export] записано в {out_dir}/")


def validate_outputs(out_dir: Path):
    n = pd.read_csv(out_dir / "nodes_roles.csv")
    assert len(n) == 2248, f"nodes_roles: {len(n)} строк"
    assert set(NODE_COLS) <= set(n.columns), "нет обязательных колонок"
    assert set(n.role) <= set(C.ROLES), f"неизвестные роли: {set(n.role) - set(C.ROLES)}"
    assert n.role_score.between(0, 1).all() and n.priority_score.between(0, 1).all()
    assert n.evidence.notna().all() and (n.evidence.str.len() > 0).all(), "пустой evidence"
    assert (n.evidence.str.len() <= C.EVIDENCE_MAX_LEN).all(), "evidence > 200"
    assert (n.cluster_id >= 0).all() and n.gid.is_unique
    c = pd.read_csv(out_dir / "clusters.csv")
    assert c.n_nodes.sum() == 2248 and c.hypothesis.notna().all()
    assert set(n.cluster_id) == set(c.cluster_id)
    t = pd.read_csv(out_dir / "top_nodes.csv")
    assert len(t) >= 20 and t.priority_score.is_monotonic_decreasing and t.why.notna().all()
    print("[check] nodes_roles 2248, clusters", len(c), ", top_nodes", len(t), "— OK")
