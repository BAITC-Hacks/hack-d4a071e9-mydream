"""Кластеризация: Louvain на ненаправленной проекции (вес sum_kzt), малые компоненты — целиком."""
import networkx as nx
import pandas as pd

from . import config as C

HYPOTHESES = {
    "collect": "признаки сбора средств с {n_seed} seed в точку консолидации {gid}",
    "fanout": "веерное распределение от {gid} на {out_deg} получателей",
    "transit": "транзитная цепочка; точка назначения вне выборки",
    "small": "изолированный фрагмент ({n} узлов), данных недостаточно",
    "mixed": "смешанная структура: {roles}",
}


def assign(G: nx.DiGraph, df: pd.DataFrame) -> pd.DataFrame:
    UG = G.to_undirected()
    labels = {}
    next_id = 0
    for comp in sorted(nx.weakly_connected_components(G), key=lambda c: (-len(c), min(c))):
        if len(comp) < C.MIN_COMPONENT_FOR_LOUVAIN:
            for n in comp:
                labels[n] = next_id
            next_id += 1
            continue
        sub = UG.subgraph(comp)
        comms = nx.community.louvain_communities(sub, weight="sum_kzt", seed=C.LOUVAIN_SEED, resolution=C.LOUVAIN_RESOLUTION)
        for c in sorted(comms, key=lambda c: (-len(c), min(c))):
            for n in c:
                labels[n] = next_id
            next_id += 1
    df["cluster_id"] = df.gid.map(labels).fillna(-1).astype(int)
    # узлы без рёбер — каждый свой кластер
    mask = df.cluster_id < 0
    df.loc[mask, "cluster_id"] = range(next_id, next_id + mask.sum())
    print(f"[clusters] {df.cluster_id.nunique()} кластеров")
    return df


def summarize(df: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    """clusters.csv: одна строка на кластер. Требует колонок role и priority_score."""
    cl = df.set_index("gid").cluster_id
    e = edges.assign(c_src=edges.src.map(cl), c_dst=edges.dst.map(cl))
    internal = e[e.c_src == e.c_dst].groupby("c_src").sum_kzt.sum()
    rows = []
    for cid, g in df.groupby("cluster_id"):
        g = g.sort_values(["priority_score", "gid"], ascending=[False, True])
        top = g.head(5)
        roles = g.role.value_counts()
        n_seed = int(g.is_seed.sum())
        if len(g) < C.MIN_COMPONENT_FOR_LOUVAIN:
            hyp = HYPOTHESES["small"].format(n=len(g))
        elif roles.get("consolidator", 0) > 0 and n_seed >= 2:
            gid = g[g.role == "consolidator"].iloc[0].gid
            hyp = HYPOTHESES["collect"].format(n_seed=n_seed, gid=gid)
        elif roles.get("distributor", 0) > 0:
            d = g[g.role == "distributor"].iloc[0]
            hyp = HYPOTHESES["fanout"].format(gid=d.gid, out_deg=d.out_deg)
        elif roles.get("transit", 0) > 0 and roles.get("terminal", 0) == 0:
            hyp = HYPOTHESES["transit"]
        else:
            hyp = HYPOTHESES["mixed"].format(roles=", ".join(f"{r}:{n}" for r, n in roles.items() if r != "peripheral") or "только периферия")
        rows.append({
            "cluster_id": cid, "n_nodes": len(g), "n_seed": n_seed,
            "sum_kzt_internal": round(float(internal.get(cid, 0.0)), 2),
            "top_gids": ";".join(str(x) for x in top.gid), "hypothesis": hyp,
        })
    return pd.DataFrame(rows).sort_values("cluster_id")
