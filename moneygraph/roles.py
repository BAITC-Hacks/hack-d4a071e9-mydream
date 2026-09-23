"""Правила ролей (DESIGN.md §3.3). Порядок: coordinator → consolidator → distributor → transit → terminal → peripheral.
Каждое правило возвращает (сработало, role_score, evidence) из одних и тех же чисел."""
import numpy as np
import pandas as pd

from . import config as C


def _score(value, threshold):
    """Превышение порога, нормированное 0..1."""
    if threshold <= 0:
        return 1.0
    return float(min(1.0, max(0.0, (value - threshold) / threshold)))


def _cut(s: str) -> str:
    return s if len(s) <= C.EVIDENCE_MAX_LEN else s[: C.EVIDENCE_MAX_LEN - 1] + "…"


def _pt(x):
    return "n/a" if pd.isna(x) else f"{x:.0%}"


def rule_coordinator(r, ctx):
    if r.is_seed or r.in_deg < C.COORD_MIN_IN or r.out_deg < C.COORD_MIN_OUT:
        return None
    if r.betweenness < ctx["bt_cut"] or r.n_adj_clusters < C.COORD_MIN_CLUSTERS:
        return None
    sc = 0.5 * _score(r.betweenness, ctx["bt_cut"]) + 0.5 * min(1.0, r.n_adj_clusters / 4)
    ev = (f"связывает {r.n_adj_clusters} кластера; посредничество топ-{r.bt_rank} из {ctx['n']}; "
          f"получает от {r.in_deg}, отправляет {r.out_deg}; пропуск {_pt(r.pass_through)}")
    return "coordinator", sc, ev


def rule_consolidator(r, ctx):
    if r.is_seed:
        return None
    holds = pd.isna(r.pass_through) or r.pass_through < C.CONS_MAX_PASS or r.out_deg == 0
    if r.in_deg >= C.CONS_MIN_IN_DEG and holds:
        sc = 0.7 * _score(r.in_deg, C.CONS_MIN_IN_DEG) + 0.3 * (1 - min(1.0, 0 if pd.isna(r.pass_through) else r.pass_through / C.CONS_MAX_PASS))
        sc = max(sc, 0.3)
    elif r.n_seed_src >= C.CONS_SEED_MIN_SRC and (pd.isna(r.pass_through) or r.pass_through < C.CONS_SEED_MAX_PASS):
        sc = max(0.3, 0.6 * min(1.0, r.n_seed_src / 4))
    else:
        return None
    ev = (f"получает от {r.in_deg} плательщиков ({r.in_kzt:,.0f} KZT, из них {r.n_seed_src} seed), "
          f"отдаёт дальше {_pt(r.pass_through) if r.out_deg else '0%'}")
    return "consolidator", sc, ev


def rule_distributor(r, ctx):
    if r.out_deg >= C.DIST_MIN_OUT_DEG and r.out_deg >= C.DIST_OUT_IN_RATIO * max(r.in_deg, 1):
        sc = max(0.3, _score(r.out_deg, C.DIST_MIN_OUT_DEG))
        ev = (f"рассылает {r.out_deg} получателям {r.out_kzt:,.0f} KZT, средний перевод {r.avg_out_tx:,.0f}; "
              f"получает от {r.in_deg}" + ("; seed" if r.is_seed else ""))
        return "distributor", sc, ev
    return None


def rule_transit(r, ctx):
    if r.is_seed or r.in_deg < 1 or r.out_deg < 1 or pd.isna(r.pass_through):
        return None
    if not (C.TRANSIT_PASS_LO <= r.pass_through <= C.TRANSIT_PASS_HI):
        return None
    if pd.isna(r.lag_days) or r.lag_days < 0 or r.fast_pass_share < C.TRANSIT_MIN_FAST_SHARE:
        return None
    sc = max(0.3, 0.5 * (1 - abs(r.pass_through - 1) / 0.3) + 0.5 * r.fast_pass_share)
    ev = (f"получил {r.in_kzt:,.0f}, отправил {r.out_kzt:,.0f} ({_pt(r.pass_through)}); "
          f"{r.fast_pass_share:.0%} ушло в течение {C.FAST_DAYS} дней после прихода")
    return "transit", sc, ev


def rule_terminal(r, ctx):
    if r.is_seed or r.out_deg != 0 or r.depth >= 4 or r.in_deg == 0:
        return None
    if r.in_kzt >= C.TERM_MIN_IN_KZT or r.in_deg >= C.TERM_MIN_IN_DEG:
        sc = max(0.3, max(_score(r.in_kzt, C.TERM_MIN_IN_KZT), _score(r.in_deg, C.TERM_MIN_IN_DEG)))
        ev = (f"получил {r.in_kzt:,.0f} KZT от {r.in_deg} плательщиков ({r.in_tx} переводов), исходящих нет; "
              f"колено {r.depth}, обходом не обрезан")
        return "terminal", sc, ev
    return None


def rule_peripheral(r, ctx):
    if r.no_edges:
        ev = "seed без переводов ≥5 000 KZT в выборке; входящие вне выборки" if r.is_seed else "нет рёбер в выборке"
    elif r.truncated:
        ev = (f"обход остановлен на 4-м колене: получил {r.in_kzt:,.0f} от {r.in_deg}; "
              f"исходящие неизвестны, сток не подтверждён")
    elif r.is_seed:
        ev = (f"seed: отправляет {r.out_deg} получателям {r.out_kzt:,.0f}; входящие занижены выгрузкой, "
              f"пропуск не интерпретируется")
    else:
        ev = (f"получает от {r.in_deg} ({r.in_kzt:,.0f}), отправляет {r.out_deg} ({r.out_kzt:,.0f}); "
              f"ниже порогов ролей")
    return "peripheral", C.PERIPHERAL_SCORE, ev


RULES = [rule_coordinator, rule_consolidator, rule_distributor, rule_transit, rule_terminal, rule_peripheral]


def _adjacent_clusters(df: pd.DataFrame, edges: pd.DataFrame) -> pd.Series:
    cl = df.set_index("gid").cluster_id
    e = pd.concat([
        edges[["src", "dst"]].rename(columns={"src": "gid", "dst": "other"}),
        edges[["dst", "src"]].rename(columns={"dst": "gid", "src": "other"}),
    ])
    e["oc"] = e.other.map(cl)
    e["own"] = e.gid.map(cl)
    return e.groupby("gid").oc.nunique()


def assign(df: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["n_adj_clusters"] = df.gid.map(_adjacent_clusters(df, edges)).fillna(0).astype(int)
    df["bt_rank"] = df.betweenness.rank(ascending=False, method="min").astype(int)
    ctx = {
        "n": len(df),
        "bt_cut": float(df.betweenness[df.betweenness > 0].quantile(1 - C.COORD_BETWEENNESS_TOP_SHARE)),
    }
    roles, scores, evs = [], [], []
    for r in df.itertuples(index=False):
        for rule in RULES:
            res = rule(r, ctx)
            if res:
                break
        roles.append(res[0]); scores.append(round(res[1], 4)); evs.append(_cut(res[2]))
    df["role"], df["role_score"], df["evidence"] = roles, scores, evs
    print("[roles]", dict(df.role.value_counts()))
    return df
