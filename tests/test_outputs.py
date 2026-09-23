"""Механическая проверка must-have M2, M4, M5 и детерминизма."""
from pathlib import Path
import pandas as pd
import pytest

OUT = Path("output")
ROLES = {"consolidator", "transit", "distributor", "terminal", "coordinator", "peripheral"}


@pytest.fixture(scope="module")
def nodes():
    p = OUT / "nodes_roles.csv"
    if not p.exists():
        pytest.skip("run pipeline first")
    return pd.read_csv(p)


def test_m2_all_nodes_have_role(nodes):
    assert len(nodes) == 2248
    assert set(nodes.role) <= ROLES
    assert nodes.role_score.between(0, 1).all()
    assert nodes.priority_score.between(0, 1).all()
    assert nodes.evidence.notna().all() and (nodes.evidence.str.len() > 0).all()
    assert (nodes.evidence.str.len() <= 200).all()
    assert (nodes.cluster_id >= 0).all()


def test_m4_clusters():
    c = pd.read_csv(OUT / "clusters.csv")
    assert {"cluster_id", "n_nodes", "n_seed", "sum_kzt_internal", "top_gids", "hypothesis"} <= set(c.columns)
    assert c.n_nodes.sum() == 2248
    assert c.hypothesis.notna().all()


def test_m5_top_nodes():
    t = pd.read_csv(OUT / "top_nodes.csv")
    assert len(t) >= 20
    assert list(t["rank"]) == list(range(1, len(t) + 1))
    assert t.priority_score.is_monotonic_decreasing
    assert t.why.notna().all()


def test_truncated_not_terminal(nodes):
    if "truncated" in nodes.columns:
        assert not ((nodes.truncated) & (nodes.role == "terminal")).any()


def test_truncated_candidates(nodes):
    """Обрезанных различаем по профилю входящих, но роль не меняем."""
    t = nodes[nodes.truncated]
    passes = (t.in_kzt >= 500_000) | (t.in_deg >= 2)          # те же пороги, что у конечного получателя
    assert (t.truncated_candidate == passes).all()
    assert not nodes[~nodes.truncated].truncated_candidate.any()
    assert nodes.terminal_likeness.between(0, 1).all() and (nodes[~nodes.truncated].terminal_likeness == 0).all()
    assert (t.role == "peripheral").all()
    assert t[t.truncated_candidate].evidence.str.contains("запросить 5-е колено").all()


def test_bursts_and_resilience():
    b = pd.read_csv(OUT / "bursts.csv")
    assert set(b.kind) <= {"pair_day", "fan_in_day"} and len(b) > 0
    assert (b[b.kind == "pair_day"].n_tx >= 3).all() and (b[b.kind == "fan_in_day"].n_payers >= 4).all()
    r = pd.read_csv(OUT / "resilience.csv")
    assert {"priority", "in_kzt", "random"} == set(r.strategy)
    assert r[r.n_removed == 0].seed_flow_share.eq(1.0).all()
    for _, g in r.groupby("strategy"):          # удаление узлов не может увеличить поток
        assert g.sort_values("n_removed").seed_flow_share.is_monotonic_decreasing


def test_assistant_offline_fallback(monkeypatch):
    from moneygraph import assistant
    monkeypatch.setattr(assistant, "api_key", lambda: None)   # без ключа — только шаблон, сеть не нужна
    text, source, fx = assistant.answer("кто собирает деньги с 100000005264990100 и 100000004041163100", OUT, Path("data"))
    assert source == "rules" and fx["gids"] == [100000005264990100, 100000004041163100]
    assert "100000005382566100" in text and "гипотеза" in text
    text, source, fx = assistant.answer("без номеров", OUT, Path("data"))
    assert source == "rules" and not fx["gids"]
