"""priority_score (DESIGN.md §3.5) и top_nodes."""
import pandas as pd

from . import config as C


def score(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    w = C.PRIORITY_WEIGHTS
    rank = lambda s: s.rank(pct=True, method="average")
    parts = {
        "in_kzt_rank": rank(df.in_kzt),
        "in_deg_rank": rank(df.in_deg),
        "betweenness_rank": rank(df.betweenness),
        "n_seed_src_norm": (df.n_seed_src / max(1, df.n_seed_src.max())).clip(0, 1),
        "pagerank_rank": rank(df.pagerank_w),
        "role_weight": df.role.map(C.ROLE_WEIGHT),
    }
    raw = sum(w[k] * parts[k] for k in w)
    raw = raw.where(~df.truncated, raw * C.TRUNCATED_PENALTY)
    raw = raw.where(~df.is_seed, raw * C.SEED_PENALTY)
    raw = raw.where(~df.no_edges, 0.0)
    df["priority_score"] = ((raw - raw.min()) / (raw.max() - raw.min())).round(4)
    # два главных вклада — для колонки why
    contrib = pd.DataFrame({k: w[k] * parts[k] for k in w})
    names = {"in_kzt_rank": "объём входящих", "in_deg_rank": "число плательщиков", "betweenness_rank": "посредничество",
             "n_seed_src_norm": "связь с seed", "pagerank_rank": "влияние (PageRank)", "role_weight": "роль"}
    # драйверы — по отклонению вклада от среднего по графу, иначе у всех одно и то же
    z = (contrib - contrib.mean()) / contrib.std().replace(0, 1)
    top2 = z.apply(lambda r: ", ".join(names[k] for k in r.nlargest(2).index), axis=1)
    df["priority_drivers"] = top2
    return df


def top_nodes(df: pd.DataFrame) -> pd.DataFrame:
    t = df.sort_values(["priority_score", "gid"], ascending=[False, True]).head(C.TOP_N).copy()
    t["rank"] = range(1, len(t) + 1)
    t["why"] = t.evidence + " | приоритет за: " + t.priority_drivers
    return t[["rank", "gid", "role", "priority_score", "why", "cluster_id", "role_score"]]
