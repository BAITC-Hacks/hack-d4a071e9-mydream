"""Behavior tests for the local track 02 graph pipeline."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "track02"))

from pipeline import analyze, run_pipeline  # noqa: E402


def small_graph():
    # 1 fans out; 7 collects from three sources then forwards; 20 bridges
    # two incoming and two outgoing paths. 3 is a censored depth-4 leaf.
    node_depths = {
        1: 0, 2: 1, 3: 4, 4: 1, 5: 2, 6: 0,
        7: 1, 8: 0, 9: 0, 10: 0, 11: 2,
        20: 2, 21: 1, 22: 1, 23: 3, 24: 3,
    }
    nodes = pd.DataFrame(
        [(gid, depth, depth == 0) for gid, depth in node_depths.items()],
        columns=["gid", "depth", "is_seed"],
    )
    pairs = [
        (1, 2, 100_000), (1, 3, 50_000), (1, 4, 100_000),
        (4, 5, 100_000),
        (8, 7, 40_000), (9, 7, 40_000), (10, 7, 40_000),
        (7, 11, 110_000),
        (21, 20, 70_000), (22, 20, 70_000),
        (20, 23, 70_000), (20, 24, 70_000),
    ]
    edges = pd.DataFrame(
        [(src, dst, amount, 1, 1) for src, dst, amount in pairs],
        columns=["src", "dst", "sum_kzt", "n_tx", "depth"],
    )
    tx = pd.DataFrame(
        [(src, dst, pd.Timestamp("2026-07-05"), amount)
         for src, dst, amount in pairs],
        columns=["src", "dst", "date", "sum_kzt"],
    )
    return nodes, edges, tx


class PipelineAnalysisTests(unittest.TestCase):
    def test_directed_roles_respect_censoring_seed_and_orphan(self):
        nodes, edges, tx = small_graph()
        roles, clusters, top, network = analyze(nodes, edges, tx)
        by_gid = roles.set_index("gid")

        self.assertEqual(by_gid.loc[1, "role"], "distributor")
        self.assertEqual(by_gid.loc[4, "role"], "transit")
        self.assertEqual(by_gid.loc[7, "role"], "consolidator")
        self.assertEqual(by_gid.loc[2, "role"], "terminal")
        self.assertEqual(by_gid.loc[3, "role"], "peripheral")
        self.assertEqual(by_gid.loc[6, "role"], "peripheral")
        self.assertIn("глубина 4", by_gid.loc[3, "evidence"].lower())
        self.assertIn("вход", by_gid.loc[1, "evidence"].lower())
        self.assertEqual(int(by_gid.loc[6, "in_deg"]), 0)
        self.assertEqual(int(by_gid.loc[6, "out_deg"]), 0)
        self.assertEqual(set(roles.gid), set(nodes.gid))
        self.assertTrue(roles.role_score.between(0, 1).all())
        self.assertTrue(roles.priority_score.between(0, 1).all())
        self.assertTrue(roles.evidence.str.len().le(200).all())
        self.assertTrue(roles.evidence.str.startswith("Правило:").all())
        self.assertIn("3 вход", by_gid.loc[7, "evidence"])
        self.assertEqual(sum(cluster["n_nodes"] for cluster in network["clusters"]), len(nodes))
        self.assertEqual(len(network["edges"]), len(edges))
        self.assertEqual(len(top), len(nodes))
        self.assertTrue(top["why"].str.contains("вклад: роль").all())
        self.assertTrue(top["why"].str.contains("вычет за неполноту").all())
        for item in network["nodes"]:
            factors = item["priority_factors"]
            self.assertNotIn("anomaly", factors)
            positive = sum(factors[name] for name in (
                "role", "volume", "degree", "bridge", "activity"
            ))
            self.assertAlmostEqual(
                positive - factors["data_quality_penalty"],
                item["priority_score"] * 100,
                delta=0.02,
            )
        self.assertGreater(
            next(item for item in network["nodes"] if item["is_seed"])["priority_factors"]["data_quality_penalty"],
            0,
        )
        self.assertEqual({node["gid"] for node in network["nodes"]}, {str(gid) for gid in nodes.gid})
        self.assertTrue(all(isinstance(edge["src"], str) and isinstance(edge["dst"], str)
                            for edge in network["edges"]))
        self.assertTrue(all(isinstance(node["gid"], str) for node in network["top"]))

    def test_run_writes_contract_files_from_raw_parquet(self):
        import duckdb

        nodes, edges, tx = small_graph()
        with tempfile.TemporaryDirectory() as folder:
            data_dir = Path(folder) / "data"
            out_dir = Path(folder) / "out"
            data_dir.mkdir()
            for name, frame in [("nodes", nodes), ("edges", edges), ("transactions", tx)]:
                duckdb.from_df(frame).write_parquet(str(data_dir / f"{name}.parquet"))

            run_pipeline(data_dir, out_dir)

            roles = pd.read_csv(out_dir / "nodes_roles.csv")
            clusters = pd.read_csv(out_dir / "clusters.csv")
            top = pd.read_csv(out_dir / "top_nodes.csv")
            network = json.loads((out_dir / "network.json").read_text(encoding="utf-8"))
            self.assertEqual(len(roles), len(nodes))
            self.assertFalse(roles[["role", "role_score", "cluster_id", "priority_score", "evidence"]].isna().any().any())
            self.assertGreater(len(clusters), 0)
            self.assertEqual(len(top), len(nodes))
            self.assertEqual(top["rank"].tolist(), list(range(1, len(nodes) + 1)))
            self.assertTrue(top.priority_score.is_monotonic_decreasing)
            self.assertEqual(network["meta"]["n_nodes"], len(nodes))
            self.assertEqual(network["meta"]["n_edges"], len(edges))
            self.assertEqual(network["meta"]["n_transactions"], len(tx))
            self.assertIn("runtime_sec", network["meta"])
            required_node = {"gid", "role", "role_score", "priority_score", "cluster_id",
                             "is_seed", "depth", "in_deg", "out_deg", "in_kzt", "out_kzt", "evidence"}
            self.assertTrue(required_node.issubset(network["nodes"][0]))
            self.assertEqual(set(network["edges"][0]), {"src", "dst", "sum_kzt", "n_tx", "depth"})


if __name__ == "__main__":
    unittest.main()
