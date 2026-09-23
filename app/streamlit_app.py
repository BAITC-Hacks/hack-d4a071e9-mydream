"""Экран просмотра «Граф денег». Читает только output/ и data/edges.parquet — ничего не пересчитывает.
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
from moneygraph.explain import explain, ROLE_RU  # noqa: E402

OUT, DATA = ROOT / "output", ROOT / "data"
COLORS = {"coordinator": "#d62728", "consolidator": "#ff7f0e", "distributor": "#9467bd",
          "transit": "#1f77b4", "terminal": "#2ca02c", "peripheral": "#bdbdbd"}

st.set_page_config(page_title="Граф денег", layout="wide")


@st.cache_data
def load():
    if not (OUT / "features.parquet").exists():
        return None, None, None, None
    f = pd.read_parquet(OUT / "features.parquet")
    e = pd.read_parquet(DATA / "edges.parquet")
    c = pd.read_csv(OUT / "clusters.csv")
    t = pd.read_csv(OUT / "top_nodes.csv")
    G = nx.from_pandas_edgelist(e, "src", "dst", ["sum_kzt", "n_tx"], create_using=nx.DiGraph)
    return f, e, c, t, G


res = load()
if res[0] is None:
    st.error("Нет output/features.parquet — запустите `python -m moneygraph run`")
    st.stop()
feat, edges, clusters, top, G = res
feat = feat.set_index("gid", drop=False)

st.title("Граф денег — структура сети по транзакциям")
st.caption("Все выводы — гипотезы для проверки аналитиком. Роли присвоены правилами с порогами (см. README).")

# ---------------- sidebar: выбор узла ----------------
with st.sidebar:
    st.header("Поиск")
    q = st.text_input("gid", value=str(top.gid.iloc[0]))
    hops = st.slider("Окрестность, колен", 1, 3, 2)
    max_nodes = st.slider("Макс. узлов на схеме", 30, 400, 150, step=10)
    st.markdown("**Легенда**")
    for r, col in COLORS.items():
        st.markdown(f"<span style='color:{col}'>■</span> {r} — {ROLE_RU[r]}", unsafe_allow_html=True)
    st.markdown("◆ — seed; толщина стрелки — сумма")

try:
    gid = int(q.strip())
except ValueError:
    st.warning("Введите числовой gid"); st.stop()
if gid not in feat.index:
    st.warning(f"gid {gid} не найден"); st.stop()
row = feat.loc[gid]

# ---------------- карточка ----------------
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Роль", row.role); c2.metric("Уверенность", f"{row.role_score:.2f}")
c3.metric("Приоритет", f"{row.priority_score:.2f}"); c4.metric("Кластер", int(row.cluster_id))
c5.metric("Колено", f"{int(row.depth)}{' (seed)' if row.is_seed else ''}")
st.code(explain(gid, OUT), language=None)

# ---------------- схема ----------------
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


sub = neighborhood(G, gid, hops, max_nodes)
net = Network(height="620px", width="100%", directed=True, bgcolor="#ffffff", font_color="#222", cdn_resources="in_line")
net.set_options("""{"physics":{"solver":"forceAtlas2Based","stabilization":{"iterations":150}},
 "edges":{"arrows":{"to":{"enabled":true,"scaleFactor":0.6}},"smooth":false}}""")
for n in sub.nodes:
    r = feat.loc[n] if n in feat.index else None
    role = r.role if r is not None else "peripheral"
    title = (f"{n}\n{role} / приоритет {r.priority_score:.2f}\n{r.evidence}" if r is not None else str(n))
    net.add_node(int(n), label=str(n)[-6:], title=title, color=COLORS[role],
                 shape="diamond" if (r is not None and r.is_seed) else "dot",
                 size=28 if n == gid else 12 + (8 * r.priority_score if r is not None else 0),
                 borderWidth=4 if n == gid else 1)
mx = max((d["sum_kzt"] for _, _, d in sub.edges(data=True)), default=1)
for u, v, d in sub.edges(data=True):
    net.add_edge(int(u), int(v), value=1 + 6 * d["sum_kzt"] / mx, title=f"{d['sum_kzt']:,.0f} KZT, {d['n_tx']} tx")
st.subheader(f"Окрестность {gid}: {sub.number_of_nodes()} узлов, {sub.number_of_edges()} рёбер")
components.html(net.generate_html(), height=640, scrolling=False)

# ---------------- связи ----------------
l, r_ = st.columns(2)
with l:
    st.markdown("**Входящие**")
    st.dataframe(edges[edges.dst == gid].sort_values("sum_kzt", ascending=False)
                 .assign(role=lambda d: d.src.map(feat.role))[["src", "role", "sum_kzt", "n_tx"]],
                 hide_index=True, width="stretch")
with r_:
    st.markdown("**Исходящие**")
    st.dataframe(edges[edges.src == gid].sort_values("sum_kzt", ascending=False)
                 .assign(role=lambda d: d.dst.map(feat.role))[["dst", "role", "sum_kzt", "n_tx"]],
                 hide_index=True, width="stretch")

# ---------------- топ-лист и кластеры ----------------
st.subheader("Топ приоритетов")
role_f = st.multiselect("Роль", list(COLORS), default=list(COLORS))
st.dataframe(top[top.role.isin(role_f)], hide_index=True, width="stretch")

st.subheader("Кластеры")
st.dataframe(clusters.sort_values("n_nodes", ascending=False), hide_index=True, width="stretch")

st.subheader("Распределение ролей")
st.bar_chart(feat.role.value_counts())
