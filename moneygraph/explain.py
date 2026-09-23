"""explain(gid): объяснение роли за минуту — для CLI, UI и демо."""
from pathlib import Path

import pandas as pd

from . import config as C

ROLE_RU = {"consolidator": "точка консолидации", "transit": "транзит", "distributor": "распределитель",
           "terminal": "конечный получатель", "coordinator": "координатор", "peripheral": "периферия"}

RULE_TEXT = {
    "coordinator": f"in≥{C.COORD_MIN_IN}, out≥{C.COORD_MIN_OUT}, посредничество в топ-{C.COORD_BETWEENNESS_TOP_SHARE:.0%}, связан с ≥{C.COORD_MIN_CLUSTERS} кластерами",
    "consolidator": f"in_deg≥{C.CONS_MIN_IN_DEG} и пропуск<{C.CONS_MAX_PASS:.0%} (или ≥{C.CONS_SEED_MIN_SRC} seed-плательщиков и пропуск<{C.CONS_SEED_MAX_PASS:.0%})",
    "distributor": f"out_deg≥{C.DIST_MIN_OUT_DEG} и out_deg≥{C.DIST_OUT_IN_RATIO:g}×in_deg",
    "transit": f"пропуск {C.TRANSIT_PASS_LO:.0%}–{C.TRANSIT_PASS_HI:.0%}, ≥{C.TRANSIT_MIN_FAST_SHARE:.0%} суммы ушло ≤{C.FAST_DAYS} дней после прихода",
    "terminal": f"исходящих нет, колено<4, получил ≥{C.TERM_MIN_IN_KZT:,} KZT или от ≥{C.TERM_MIN_IN_DEG} плательщиков",
    "peripheral": "ни одно правило выше не сработало",
}


def explain(gid: int, out_dir: Path = Path("output")) -> str:
    df = pd.read_parquet(out_dir / "features.parquet")
    e = pd.read_parquet(Path("data") / "edges.parquet") if (Path("data") / "edges.parquet").exists() else None
    row = df[df.gid == gid]
    if row.empty:
        return f"gid {gid} не найден"
    r = row.iloc[0]
    lines = [
        f"gid {gid}: роль — {ROLE_RU[r.role].upper()}, уверенность {r.role_score:.2f}, приоритет {r.priority_score:.2f}, кластер {r.cluster_id}",
        f"Правило: {RULE_TEXT[r.role]}",
        f"Факты: {r.evidence}",
        f"Метрики: in {r.in_deg}/{r.in_kzt:,.0f} KZT, out {r.out_deg}/{r.out_kzt:,.0f} KZT, пропуск "
        f"{'n/a' if pd.isna(r.pass_through) else f'{r.pass_through:.0%}'}, seed-плательщиков {r.n_seed_src}, "
        f"колено {r.depth}{', SEED' if r.is_seed else ''}{', ОБРЕЗАН' if r.truncated else ''}, "
        f"посредничество #{r.bt_rank}, в цикле: {'да' if r.in_cycle else 'нет'}",
        f"Приоритет за: {r.priority_drivers}",
    ]
    if e is not None:
        top_in = e[e.dst == gid].nlargest(3, "sum_kzt")
        top_out = e[e.src == gid].nlargest(3, "sum_kzt")
        if len(top_in):
            lines.append("Крупнейшие плательщики: " + "; ".join(f"{s} → {v:,.0f}" for s, v in zip(top_in.src, top_in.sum_kzt)))
        if len(top_out):
            lines.append("Крупнейшие получатели: " + "; ".join(f"{d} ← {v:,.0f}" for d, v in zip(top_out.dst, top_out.sum_kzt)))
    lines.append("Вывод — гипотеза для проверки аналитиком, не утверждение.")
    return "\n".join(lines)
