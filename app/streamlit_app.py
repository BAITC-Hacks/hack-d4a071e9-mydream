"""Экран просмотра «Граф денег». Читает только output/ и data/ — ничего не пересчитывает.
Запуск: streamlit run app/streamlit_app.py
"""
import sys
from pathlib import Path

import networkx as nx
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from pyvis.network import Network

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from moneygraph import config as C  # noqa: E402
from moneygraph.assistant import answer  # noqa: E402
from moneygraph.explain import explain, ROLE_RU, RULE_TEXT  # noqa: E402

OUT, DATA = ROOT / "output", ROOT / "data"
COLORS = {"coordinator": "#d62728", "consolidator": "#ff7f0e", "distributor": "#9467bd",
          "transit": "#1f77b4", "terminal": "#2ca02c", "peripheral": "#bdbdbd"}
CLUSTER_PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b",
                   "#e377c2", "#17becf", "#bcbd22", "#7f7f7f", "#393b79", "#ad494a"]

st.set_page_config(page_title="Граф денег", layout="wide")


def ru(text) -> str:
    """Коды ролей в тексте из CSV (гипотезы кластеров) → русские названия; сами CSV не меняются."""
    text = str(text)
    for code, name in ROLE_RU.items():
        text = text.replace(code, name)
    return text


@st.cache_data
def load():
    if not (OUT / "features.parquet").exists():
        return (None,) * 8
    f = pd.read_parquet(OUT / "features.parquet")
    e = pd.read_parquet(DATA / "edges.parquet")
    c = pd.read_csv(OUT / "clusters.csv")
    t = pd.read_csv(OUT / "top_nodes.csv")
    G = nx.from_pandas_edgelist(e, "src", "dst", ["sum_kzt", "n_tx"], create_using=nx.DiGraph)
    b = (pd.read_csv(OUT / "bursts.csv", dtype={"src": "Int64", "dst": "Int64"})  # gid без потери цифр
         if (OUT / "bursts.csv").exists() else None)
    rs = pd.read_csv(OUT / "resilience.csv") if (OUT / "resilience.csv").exists() else None
    n_tx = len(pd.read_parquet(DATA / "transactions.parquet", columns=["sum_kzt"]))
    return f, e, c, t, G, b, rs, n_tx


res = load()
if res[0] is None:
    st.error("Нет output/features.parquet — запустите `python -m moneygraph run`")
    st.stop()
feat, edges, clusters, top, G, bursts, resil, n_tx = res
feat = feat.set_index("gid", drop=False)

st.title("Граф денег — структура сети по транзакциям")
st.caption("Все выводы — гипотезы для проверки аналитиком. Роли присвоены правилами с порогами — "
           "см. вкладку «Правила ролей»; LLM роли не присваивает.")
tab_node, tab_rules, tab_burst, tab_res, tab_ai, tab_scheme, tab_demo = st.tabs(
    ["Узел", "Правила ролей", "Дробление", "Устойчивость", "Ассистент", "Схема решения", "Демо"])

# ---------------- sidebar: выбор узла ----------------
with st.sidebar:
    st.header("Поиск")
    q = st.text_input("gid", value=str(top.gid.iloc[0]))
    hops = st.slider("Окрестность, колен", 1, 3, 2)
    max_nodes = st.slider("Макс. узлов на схеме", 30, 400, 150, step=10)
    color_by = st.radio("Цвет узлов на схеме", ["роль", "кластер"], horizontal=True)
    st.markdown("**Легенда**")
    if color_by == "роль":
        for r, col in COLORS.items():
            st.markdown(f"<span style='color:{col}'>■</span> {ROLE_RU[r]}", unsafe_allow_html=True)
    else:
        st.markdown("цвет = номер кластера; кластеры окрестности перечислены под схемой")
    st.markdown("◆ — seed; толщина стрелки — сумма")


def neighborhood(g, center, k, limit):
    nodes = {center}
    frontier = {center}
    for _ in range(k):
        nxt = set()
        for n in frontier:
            if n in g:
                nxt |= set(g.predecessors(n)) | set(g.successors(n))
        nxt -= nodes
        if len(nodes) + len(nxt) > limit:
            # берём самых приоритетных
            nxt = set(sorted(nxt, key=lambda x: -feat.priority_score.get(x, 0))[: max(0, limit - len(nodes))])
            nodes |= nxt
            break
        nodes |= nxt
        frontier = nxt
    return g.subgraph(nodes)


def render_node():
    try:
        gid = int(q.strip())
    except ValueError:
        st.warning("Введите числовой gid"); return
    if gid not in feat.index:
        st.warning(f"gid {gid} не найден"); return
    row = feat.loc[gid]

    # ---------------- карточка ----------------
    c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 1, 1])
    c1.metric("Роль", ROLE_RU[row.role]); c2.metric("Уверенность", f"{row.role_score:.2f}")
    c3.metric("Приоритет", f"{row.priority_score:.2f}"); c4.metric("Кластер", int(row.cluster_id))
    c5.metric("Колено", f"{int(row.depth)}{' (seed)' if row.is_seed else ''}")
    st.code(explain(gid, OUT), language=None)

    # ---------------- схема ----------------

    sub = neighborhood(G, gid, hops, max_nodes)
    net = Network(height="620px", width="100%", directed=True, bgcolor="#ffffff", font_color="#222", cdn_resources="in_line")
    net.set_options("""{"physics":{"solver":"forceAtlas2Based","stabilization":{"iterations":150}},
     "edges":{"arrows":{"to":{"enabled":true,"scaleFactor":0.6}},"smooth":false}}""")
    for n in sub.nodes:
        r = feat.loc[n] if n in feat.index else None
        role = r.role if r is not None else "peripheral"
        title = (f"{n}\n{ROLE_RU[role]} / приоритет {r.priority_score:.2f}\n{r.evidence}" if r is not None else str(n))
        color = (COLORS[role] if color_by == "роль" or r is None
                 else CLUSTER_PALETTE[int(r.cluster_id) % len(CLUSTER_PALETTE)])
        net.add_node(int(n), label=str(n)[-6:], title=title, color=color,
                     shape="diamond" if (r is not None and r.is_seed) else "dot",
                     size=28 if n == gid else 12 + (8 * r.priority_score if r is not None else 0),
                     borderWidth=4 if n == gid else 1)
    mx = max((d["sum_kzt"] for _, _, d in sub.edges(data=True)), default=1)
    for u, v, d in sub.edges(data=True):
        net.add_edge(int(u), int(v), value=1 + 6 * d["sum_kzt"] / mx, title=f"{d['sum_kzt']:,.0f} KZT, {d['n_tx']} tx")
    st.subheader(f"Окрестность {gid}: {sub.number_of_nodes()} узлов, {sub.number_of_edges()} рёбер")
    components.html(net.generate_html(), height=640, scrolling=False)
    if color_by == "кластер":
        hyp = clusters.set_index("cluster_id").hypothesis
        in_view = feat.loc[[n for n in sub.nodes if n in feat.index]].cluster_id.value_counts()
        st.markdown("  \n".join(
            f"<span style='color:{CLUSTER_PALETTE[int(c) % len(CLUSTER_PALETTE)]}'>■</span> кластер {int(c)} — "
            f"{k} узл. на схеме; {ru(hyp.get(c, ''))}" for c, k in in_view.items()), unsafe_allow_html=True)

    # ---------------- связи ----------------
    l, r_ = st.columns(2)
    with l:
        st.markdown("**Входящие**")
        st.dataframe(edges[edges.dst == gid].sort_values("sum_kzt", ascending=False)
                     .assign(role=lambda d: d.src.map(feat.role).map(ROLE_RU))[["src", "role", "sum_kzt", "n_tx"]]
                     .rename(columns={"src": "плательщик", "role": "роль", "sum_kzt": "сумма, KZT", "n_tx": "переводов"}),
                     hide_index=True, width="stretch")
    with r_:
        st.markdown("**Исходящие**")
        st.dataframe(edges[edges.src == gid].sort_values("sum_kzt", ascending=False)
                     .assign(role=lambda d: d.dst.map(feat.role).map(ROLE_RU))[["dst", "role", "sum_kzt", "n_tx"]]
                     .rename(columns={"dst": "получатель", "role": "роль", "sum_kzt": "сумма, KZT", "n_tx": "переводов"}),
                     hide_index=True, width="stretch")

    # ---------------- топ-лист и кластеры ----------------
    st.subheader("Топ приоритетов")
    role_f = st.multiselect("Роль", list(COLORS), default=list(COLORS), format_func=ROLE_RU.get)
    st.dataframe(top[top.role.isin(role_f)].assign(role=lambda d: d.role.map(ROLE_RU)).rename(columns={
        "rank": "место", "role": "роль", "priority_score": "приоритет", "why": "почему",
        "cluster_id": "кластер", "role_score": "уверенность"}), hide_index=True, width="stretch")

    st.subheader("Кластеры")
    st.dataframe(clusters.sort_values("n_nodes", ascending=False).assign(hypothesis=lambda d: d.hypothesis.map(ru))
                 .rename(columns={"cluster_id": "кластер", "n_nodes": "узлов", "n_seed": "seed",
                                  "sum_kzt_internal": "внутренний оборот, KZT", "top_gids": "топ-5 gid",
                                  "hypothesis": "гипотеза"}), hide_index=True, width="stretch")

    st.subheader("Распределение ролей")
    st.bar_chart(feat.role.map(ROLE_RU).value_counts(), horizontal=True)


with tab_node:
    render_node()

# ---------------- правила ролей ----------------
with tab_rules:
    st.subheader("Роли присвоены правилами с порогами")
    st.markdown("Правила проверяются по порядку, первое сработавшее задаёт роль. Все пороги — в "
                "`moneygraph/config.py`; эта таблица строится из них же, поэтому не расходится с расчётом.")
    counts = feat.role.value_counts()
    example = feat.reset_index(drop=True).sort_values(["priority_score", "gid"], ascending=[False, True]).groupby("role").gid.first()
    order = ["coordinator", "consolidator", "distributor", "transit", "terminal", "peripheral"]
    st.dataframe(pd.DataFrame({
        "№": range(1, len(order) + 1),
        "Роль": [ROLE_RU[r] for r in order],
        "Код в CSV": order,
        "Правило и порог": [RULE_TEXT[r] for r in order],
        "Узлов": [int(counts.get(r, 0)) for r in order],
        "Пример (макс. приоритет)": [str(example.get(r, "")) for r in order],
    }), hide_index=True, width="stretch")
    st.markdown(
        "**Ограничения правил.** seed не бывает точкой консолидации, транзитом и конечным получателем: "
        "входящие seed занижены выгрузкой. Узел, обрезанный 4-м коленом (`truncated`), никогда не конечный "
        "получатель — его исходящие неизвестны. "
        "`role_score` 0–1 — насколько превышен порог своего правила; у периферии всегда "
        f"{C.PERIPHERAL_SCORE}. В CSV роли записаны кодами из словаря ТЗ (колонка «Код в CSV»).")
    st.markdown("**Приоритет** — взвешенная сумма рангов, нормированная 0–1:")
    st.code(" + ".join(f"{w:.2f}·{k}" for k, w in C.PRIORITY_WEIGHTS.items())
            + f"\n× {C.TRUNCATED_PENALTY} для обрезанных, × {C.SEED_PENALTY} для seed (уже известны следствию)",
            language=None)

    st.subheader("Обрезанные 4-м коленом: как различаем")
    tr = feat[feat.truncated]
    ref_n = int((~feat.is_seed & (feat.out_deg == 0) & (feat.depth < 4) & (feat.in_deg > 0)).sum())
    cand = tr[tr.truncated_candidate]
    st.markdown(
        f"У {len(tr)} узлов на 4-м колене нет исходящих, потому что обход на них закончился — это не доказывает, "
        "что деньги осели. Поэтому такие узлы **никогда не получают роль конечного получателя** и остаются "
        "периферией. Но различаем их по профилю входящих:\n"
        f"- сравниваем с {ref_n} **подтверждёнными стоками** — узлами на коленах 1–3 без исходящих "
        "(обход шёл дальше них, значит отсутствие исходящих — факт);\n"
        f"- **кандидат в конечные получатели** — обрезанный узел, который проходит тот же порог, что и правило "
        f"конечного получателя: получил ≥ {C.TERM_MIN_IN_KZT:,} KZT или от ≥ {C.TERM_MIN_IN_DEG} плательщиков;\n"
        "- **похожесть** 0–1 — среднее двух процентилей среди подтверждённых стоков: по сумме входящих и по числу "
        "плательщиков.\n\n"
        f"Кандидатов **{len(cand)}** из {len(tr)}. По ним следующий шаг аналитика — запросить переводы "
        "5-го колена: только так можно подтвердить или снять гипотезу «деньги осели здесь».")
    st.dataframe(cand.reset_index(drop=True).sort_values(["terminal_likeness", "gid"], ascending=[False, True])
                 [["gid", "in_kzt", "in_deg", "terminal_likeness", "cluster_id"]]
                 .rename(columns={"in_kzt": "получил, KZT", "in_deg": "плательщиков",
                                  "terminal_likeness": "похожесть", "cluster_id": "кластер"})
                 .astype({"gid": "string"}), hide_index=True, width="stretch")

# ---------------- дробление ----------------
with tab_burst:
    st.subheader("Признаки дробления")
    if bursts is None:
        st.info("Нет output/bursts.csv — запустите `python -m moneygraph run`")
    else:
        st.markdown(
            f"- **Одна пара, один день:** ≥{C.BURST_MIN_TX} переводов от одного отправителя одному получателю за день.\n"
            f"- **Сбор за день:** ≥{C.BURST_MIN_PAYERS} разных плательщиков переводят одному получателю в один день.\n\n"
            "Это признак для проверки, не вывод: так же выглядят зарплатные дни и сборы на общие покупки.")
        m1, m2, m3 = st.columns(3)
        m1.metric("Пар-дней с дроблением", int((bursts.kind == "pair_day").sum()))
        m2.metric("Сборов за день", int((bursts.kind == "fan_in_day").sum()))
        m3.metric("Сумма эпизодов, KZT", f"{bursts.sum_kzt.sum():,.0f}")
        kinds = {"pair_day": "одна пара, один день", "fan_in_day": "сбор за день"}
        pick = st.multiselect("Тип", list(kinds), default=list(kinds), format_func=kinds.get)
        view = bursts[bursts.kind.isin(pick)].assign(kind=lambda d: d.kind.map(kinds),
                                                     src_role=lambda d: d.src_role.map(ROLE_RU),
                                                     dst_role=lambda d: d.dst_role.map(ROLE_RU))
        st.dataframe(view.astype({"src": "string", "dst": "string"})
                     .fillna({"src": "несколько", "src_role": "—"}).rename(columns={
            "kind": "тип", "date": "дата", "src": "отправитель", "dst": "получатель", "n_tx": "переводов",
            "n_payers": "плательщиков", "sum_kzt": "сумма, KZT", "max_kzt": "крупнейший, KZT",
            "src_role": "роль отправителя", "dst_role": "роль получателя", "dst_cluster": "кластер получателя",
            "note": "описание"}), hide_index=True, width="stretch")
        st.caption("gid из таблицы можно вставить в поиск слева — откроется его окрестность на вкладке «Узел».")

# ---------------- устойчивость ----------------
with tab_res:
    st.subheader("Устойчивость сети: что будет, если отработать топ-N узлов")
    if resil is None:
        st.info("Нет output/resilience.csv — запустите `python -m moneygraph run`")
    else:
        names = {"priority": "наш приоритет", "in_kzt": "по объёму входящих", "random": "случайно (среднее)"}
        pv = resil.assign(strategy=resil.strategy.map(names))
        at = lambda strat, k, col: float(resil[(resil.strategy == strat) & (resil.n_removed == k)][col].iloc[0])
        k = C.TOP_N if C.TOP_N in set(resil.n_removed) else int(resil.n_removed.max())
        a, b_, c = st.columns(3)
        a.metric(f"Поток от seed после топ-{k} по приоритету", f"{at('priority', k, 'seed_flow_share'):.0%}",
                 f"{at('priority', k, 'seed_flow_share') - 1:.0%}")
        b_.metric(f"… по объёму входящих", f"{at('in_kzt', k, 'seed_flow_share'):.0%}",
                  f"{at('in_kzt', k, 'seed_flow_share') - 1:.0%}")
        c.metric(f"… {k} случайных узлов", f"{at('random', k, 'seed_flow_share'):.0%}",
                 f"{at('random', k, 'seed_flow_share') - 1:.0%}")
        l1, l2 = st.columns(2)
        with l1:
            st.markdown("**Доля суммы, достижимой от seed**")
            st.line_chart(pv.pivot(index="n_removed", columns="strategy", values="seed_flow_share"))
        with l2:
            st.markdown("**Крупнейшая связная часть, доля узлов**")
            st.line_chart(pv.pivot(index="n_removed", columns="strategy", values="lcc_share"))
        st.markdown(
            "Seed не удаляем — они уже известны. Меряем, сколько денег от seed всё ещё может дойти до получателей, "
            "если заблокировать N неизвестных узлов. Чем круче падает линия, тем точнее список приоритетов "
            f"указывает на узлы, которые держат сеть. Случайная стратегия — среднее по {C.RESILIENCE_RANDOM_RUNS} "
            f"прогонам (seed {C.RESILIENCE_SEED}).")
        st.dataframe(pv, hide_index=True, width="stretch")

# ---------------- ассистент ----------------
seed_set = set(feat[feat.is_seed].gid)
_by_dst = edges[edges.src.isin(seed_set)].groupby("dst").src.nunique()
_hub = int(_by_dst.sort_values(ascending=False).index[0]) if len(_by_dst) else None
_five = sorted(edges[(edges.dst == _hub) & edges.src.isin(seed_set)].src.unique())[:5] if _hub else []
EXAMPLE_Q = "Кто собирает деньги с этих пятерых: " + ", ".join(str(g) for g in _five)


@st.cache_data(show_spinner=False)
def ask(question: str):
    return answer(question, OUT, DATA)


with tab_ai:
    st.subheader("Ассистент аналитика")
    st.markdown(
        "Вставьте gid в вопрос. Кандидатов (общих получателей и плательщиков) находит код по графу; "
        "языковая модель OpenAI только пересказывает эти факты. Без ключа или без интернета ответ "
        "собирается по шаблону из тех же фактов — демо не зависит от сети.")
    question = st.text_area("Вопрос", value=EXAMPLE_Q, height=90)
    if st.button("Спросить", type="primary"):
        with st.spinner("Собираю факты…"):
            text, source, fx = ask(question)
        st.markdown(text.replace("\n", "  \n"))  # переносы строк как в CLI
        st.caption(f"Источник ответа: {source}")
        with st.expander("Факты, переданные модели"):
            from moneygraph.assistant import facts_text
            st.code(facts_text(fx), language=None)

# ---------------- схема решения ----------------
with tab_scheme:
    st.subheader("Схема решения")
    rc = feat.role.value_counts()
    steps = [
        ("Данные", f"{len(feat):,} узлов, {len(edges):,} рёбер, {n_tx:,} транзакций, {int(feat.is_seed.sum())} seed, "
                   "обход до 4-го колена"),
        ("Метрики", "степени и суммы, доля пропуска, лаг и скорость пересылки, betweenness, PageRank, HITS, "
                    "циклы, дробление за день"),
        ("Роли", "6 правил с порогами из config.py: " + ", ".join(f"{ROLE_RU[r]} {int(rc.get(r, 0))}" for r in
                 ["coordinator", "consolidator", "distributor", "transit", "terminal", "peripheral"])),
        ("Кластеры и приоритет", f"Louvain (seed {C.LOUVAIN_SEED}): {len(clusters)} кластеров; приоритет — "
                                 f"взвешенные ранги, топ-{C.TOP_N} с объяснением «почему»"),
        ("Интерфейс", "3 CSV + explain за минуту, экран Streamlit, ассистент, офлайн-запуск без установки"),
    ]
    boxes = "".join(
        f"<div class='mg-step'><div class='mg-n'>{i}</div><div class='mg-t'>{t}</div><div class='mg-d'>{d}</div></div>"
        + ("<div class='mg-arrow'>→</div>" if i < len(steps) else "")
        for i, (t, d) in enumerate(steps, 1))
    st.markdown(
        "<style>.mg-flow{display:flex;flex-wrap:wrap;align-items:stretch;gap:6px;margin-bottom:12px}"
        ".mg-step{flex:1 1 130px;border:1px solid rgba(128,128,128,.45);border-radius:10px;padding:12px;"
        "background:rgba(128,128,128,.08)}.mg-n{font-size:12px;opacity:.7}.mg-t{font-weight:700;margin:2px 0 6px}"
        ".mg-d{font-size:14px;line-height:1.35}.mg-arrow{align-self:center;font-size:22px;opacity:.6}"
        "@media(max-width:700px){.mg-arrow{transform:rotate(90deg);flex-basis:100%;text-align:center}}</style>"
        f"<div class='mg-flow'>{boxes}</div>", unsafe_allow_html=True)
    st.markdown(
        "**Принципы.** Роли — только правила с порогами (объяснимо, детерминированно, без обучающей разметки). "
        "LLM — только в ассистенте, поверх готовых фактов. Экран и `explain` читают `output/` и ничего не "
        "пересчитывают. Все выводы — гипотезы для проверки аналитиком.")

# ---------------- демо ----------------
with tab_demo:
    st.subheader("Сценарий демо на 5 минут")
    cons = top[top.role == "consolidator"].iloc[0] if (top.role == "consolidator").any() else top.iloc[0]
    coord = feat[feat.role == "coordinator"].reset_index(drop=True).sort_values(["priority_score", "gid"], ascending=[False, True])
    trunc = feat[feat.truncated].reset_index(drop=True).sort_values(["in_kzt", "gid"], ascending=[False, True])
    b0 = bursts.iloc[0] if bursts is not None and len(bursts) else None
    flow = (float(resil[(resil.strategy == "priority") & (resil.n_removed == C.TOP_N)].seed_flow_share.iloc[0])
            if resil is not None and ((resil.strategy == "priority") & (resil.n_removed == C.TOP_N)).any() else None)
    plan = [
        ("0:00–0:30", "Задача и данные", f"{len(feat):,} узлов, {int(feat.is_seed.sum())} seed. Вкладка «Схема решения»."),
        ("0:30–1:00", "Живой прогон", "`run_offline.bat run` — ≈4 с, 3 CSV, проверка схемы OK."),
        ("1:00–2:00", "Топ-1: точка консолидации", f"gid **{cons.gid}** в поиск → схема окрестности, крупнейшие плательщики."),
    ]
    if len(coord):
        cr = coord.iloc[0]
        plan.append(("2:00–2:40", "Координатор", f"gid **{cr.gid}**: связывает {int(cr.n_adj_clusters)} кластеров, "
                     f"посредничество #{int(cr.bt_rank)} — почему это не распределитель."))
    if len(trunc):
        plan.append(("2:40–3:10", "Ловушка данных", f"gid **{trunc.iloc[0].gid}** с 4-го колена: получил "
                     f"{trunc.iloc[0].in_kzt:,.0f} KZT, но не конечный получатель — исходящие неизвестны. "
                     f"Различаем: {int(feat.truncated_candidate.sum())} обрезанных похожи на конечных получателей "
                     "(вкладка «Правила ролей») — по ним запросить 5-е колено."))
    plan.append(("3:10–3:50", "Дробление и устойчивость",
                 (f"крупнейший эпизод: {b0.note}. " if b0 is not None else "")
                 + (f"Топ-{C.TOP_N} по приоритету отсекают {1 - flow:.0%} потока от seed." if flow is not None else "")))
    plan.append(("3:50–4:30", "Ассистент", "вопрос «кто собирает деньги с этих пятерых» (заготовлен на вкладке)."))
    plan.append(("4:30–5:00", "Вопросы жюри", "жюри называет любой gid → вкладка «Узел» или `explain <gid>`."))
    st.markdown("\n".join(f"- **{t}** · {step} — {what}" for t, step, what in plan))

    st.markdown("**Чек-лист репетиции** (отметки живут до перезагрузки страницы)")
    for item in ["Прогон уложился в 5:00 по секундомеру", "gid из сценария скопированы в заметки",
                 "Вкладки открываются без ошибок на ноутбуке для демо", "Проверен ответ ассистента (LLM или шаблон)",
                 "Каждый член команды знает свой шаг", "Готовы ответы на вопросы ниже"]:
        st.checkbox(item, key=f"rehearsal_{item}")

    with st.expander("Вероятные вопросы жюри и короткие ответы"):
        st.markdown(
            "- **Почему правила, а не ML?** Нет разметки — точность не измерить; правила объяснимы за минуту и "
            "детерминированы.\n"
            "- **Откуда пороги?** Из разведки данных, все в `config.py`; таблица на вкладке «Правила ролей».\n"
            "- **Почему seed не консолидатор?** Их входящие занижены выгрузкой; зато ассистент показывает seed, "
            "которые собирают деньги с других seed.\n"
            "- **Как проверить, что приоритет полезен?** Вкладка «Устойчивость»: топ по приоритету режет поток от "
            "seed сильнее, чем топ по объёму или случайный выбор.\n"
            "- **Что с 1 млн узлов?** README, раздел «Масштабирование».\n"
            "- **Где LLM?** Только в ассистенте и только поверх готовых фактов; роли присваивают правила.")
