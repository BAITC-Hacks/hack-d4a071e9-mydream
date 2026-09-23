"""Дополнительные расчёты для UI: дробление (bursts.csv) и устойчивость сети (resilience.csv).
Не меняют роли, приоритеты и 3 основных CSV — только читают df после priority."""
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd

from . import config as C


def bursts(tx: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """Признаки дробления: много переводов одной паре за день и сбор с многих плательщиков за день."""
    role = df.set_index("gid").role
    cluster = df.set_index("gid").cluster_id

    p = (tx.groupby(["src", "dst", "date"]).sum_kzt
         .agg(n_tx="size", sum_kzt="sum", max_kzt="max").reset_index())
    p = p[p.n_tx >= C.BURST_MIN_TX].assign(kind="pair_day", n_payers=1)
    p["note"] = [f"{_plural(n, 'перевод', 'перевода', 'переводов')} за день от {s} к {d}: {v:,.0f} KZT, крупнейший {m:,.0f}"
                 for n, s, d, v, m in zip(p.n_tx, p.src, p.dst, p.sum_kzt, p.max_kzt)]

    f = (tx.groupby(["dst", "date"])
         .agg(n_payers=("src", "nunique"), n_tx=("src", "size"), sum_kzt=("sum_kzt", "sum"), max_kzt=("sum_kzt", "max"))
         .reset_index())
    f = f[f.n_payers >= C.BURST_MIN_PAYERS].assign(kind="fan_in_day", src=pd.NA)
    f["note"] = [f"{_plural(k, 'плательщик', 'разных плательщика', 'разных плательщиков')} за день перевели {d}: "
                 f"{_plural(n, 'перевод', 'перевода', 'переводов')}, {v:,.0f} KZT"
                 for k, d, n, v in zip(f.n_payers, f.dst, f.n_tx, f.sum_kzt)]

    out = pd.concat([p, f], ignore_index=True)
    out["src"] = out.src.astype("Int64")
    out["date"] = pd.to_datetime(out.date).dt.strftime("%Y-%m-%d")
    out["src_role"] = out.src.map(role)
    out["dst_role"] = out.dst.map(role)
    out["dst_cluster"] = out.dst.map(cluster).astype("Int64")
    cols = ["kind", "date", "src", "dst", "n_tx", "n_payers", "sum_kzt", "max_kzt",
            "src_role", "dst_role", "dst_cluster", "note"]
    return (out[cols].sort_values(["sum_kzt", "kind", "date", "dst", "src"], ascending=[False, True, True, True, True])
            .reset_index(drop=True))


def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


class _Net:
    """Списки смежности для быстрых повторных обходов (сотни замеров за доли секунды)."""

    def __init__(self, G: nx.DiGraph, seeds: set, n_total: int):
        self.nodes = list(G.nodes)
        self.succ = {n: list(G.successors(n)) for n in self.nodes}
        self.und = {n: list(set(G.successors(n)) | set(G.predecessors(n))) for n in self.nodes}
        self.edges = [(u, v, d["sum_kzt"]) for u, v, d in G.edges(data=True)]
        self.seeds = [s for s in seeds if s in G]
        self.n_total = n_total
        self.base_flow = self._flow(set()) or 1.0

    def _flow(self, removed: set) -> float:
        reach, stack = set(), [s for s in self.seeds if s not in removed]
        while stack:
            n = stack.pop()
            if n in reach:
                continue
            reach.add(n)
            stack.extend(m for m in self.succ[n] if m not in removed and m not in reach)
        return sum(w for u, v, w in self.edges if u in reach and v not in removed)

    def _lcc(self, removed: set) -> int:
        seen, best = set(removed), 0
        for start in self.nodes:
            if start in seen:
                continue
            size, stack = 0, [start]
            seen.add(start)
            while stack:
                n = stack.pop()
                size += 1
                for m in self.und[n]:
                    if m not in seen:
                        seen.add(m)
                        stack.append(m)
            best = max(best, size)
        return best

    def measure(self, removed: set):
        return self._lcc(removed) / self.n_total, self._flow(removed) / self.base_flow


def resilience(G: nx.DiGraph, df: pd.DataFrame) -> pd.DataFrame:
    """Насколько распадается сеть, если убрать N узлов. Seed не удаляем — они уже известны следствию;
    вопрос в том, каких ещё неизвестных участников отрабатывать первыми."""
    seeds = set(df[df.is_seed].gid)
    cand = df[~df.is_seed & df.gid.isin(G.nodes)]
    orders = {
        "priority": cand.sort_values(["priority_score", "gid"], ascending=[False, True]).gid.tolist(),
        "in_kzt": cand.sort_values(["in_kzt", "gid"], ascending=[False, True]).gid.tolist(),
    }
    net = _Net(G, seeds, len(df))

    rows = []
    for name, order in orders.items():
        for k in C.RESILIENCE_STEPS:
            lcc, flow = net.measure(set(order[:k]))
            rows.append((name, k, lcc, flow))
    rng = np.random.default_rng(C.RESILIENCE_SEED)
    pool = cand.gid.to_numpy()
    runs = [rng.permutation(pool) for _ in range(C.RESILIENCE_RANDOM_RUNS)]
    for k in C.RESILIENCE_STEPS:
        m = [net.measure(set(r[:k])) for r in runs]
        rows.append(("random", k, float(np.mean([x[0] for x in m])), float(np.mean([x[1] for x in m]))))

    out = pd.DataFrame(rows, columns=["strategy", "n_removed", "lcc_share", "seed_flow_share"])
    return out.round({"lcc_share": 4, "seed_flow_share": 4})


def write(G: nx.DiGraph, df: pd.DataFrame, tx: pd.DataFrame, out_dir: Path):
    b = bursts(tx, df)
    b.to_csv(out_dir / "bursts.csv", index=False, encoding="utf-8")
    r = resilience(G, df)
    r.to_csv(out_dir / "resilience.csv", index=False, encoding="utf-8")
    top = r[(r.strategy == "priority") & (r.n_removed == C.TOP_N)]
    msg = f", после удаления топ-{C.TOP_N} поток от seed {top.seed_flow_share.iloc[0]:.0%}" if len(top) else ""
    print(f"[extras] дробление: {(b.kind == 'pair_day').sum()} пар-дней, {(b.kind == 'fan_in_day').sum()} сборов за день{msg}")
