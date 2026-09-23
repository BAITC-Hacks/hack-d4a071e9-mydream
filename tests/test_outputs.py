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
