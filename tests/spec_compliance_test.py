"""Organizer contract checks against the supplied AML data and fresh CLI outputs.

Run from the repository root:
    track02/.venv/Scripts/python.exe tests/spec_compliance_test.py

The CLI runs twice in temporary directories under the repository. Expectations
come from the organizer's dataset contract and raw transactions, not pipeline
helpers. No particular node role, cluster count, or ranking is prescribed.
"""

import json
import math
import os
import subprocess
import sys
import tempfile
import time
import unittest
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import duckdb
import networkx as nx
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "track02" / "data"
SCHEMAS = {
    "nodes_roles.csv": [
        "gid", "role", "role_score", "cluster_id", "priority_score", "evidence",
    ],
    "clusters.csv": [
        "cluster_id", "n_nodes", "n_seed", "sum_kzt_internal", "top_gids", "hypothesis",
    ],
    "top_nodes.csv": ["rank", "gid", "role", "priority_score", "why"],
}
ALLOWED_ROLES = {
    "consolidator", "transit", "distributor", "terminal", "coordinator", "peripheral",
}


class OrganizerComplianceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nodes = duckdb.read_parquet(str(DATA / "nodes.parquet")).df()
        cls.edges = duckdb.read_parquet(str(DATA / "edges.parquet")).df()
        cls.transactions = duckdb.read_parquet(str(DATA / "transactions.parquet")).df()
        cls.raw_gids = {str(gid) for gid in cls.nodes.gid}
        cls.seed_gids = {str(gid) for gid in cls.nodes.loc[cls.nodes.is_seed, "gid"]}
        cls.temp = tempfile.TemporaryDirectory(prefix="spec-compliance-", dir=ROOT)
        cls.addClassCleanup(cls.temp.cleanup)
        cls.output_dirs = [Path(cls.temp.name) / name for name in ("first", "second")]
        cls.runtimes = []
        for output, hash_seed in zip(cls.output_dirs, ("1", "73")):
            environment = os.environ.copy()
            environment["PYTHONHASHSEED"] = hash_seed
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            run_started = time.monotonic()
            result = subprocess.run(
                [sys.executable, str(ROOT / "track02" / "pipeline.py"),
                 "--data", str(DATA), "--out", str(output)],
                cwd=ROOT, env=environment, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=300, check=False,
            )
            cls.runtimes.append(time.monotonic() - run_started)
            if result.returncode:
                raise AssertionError(
                    f"Pipeline exited with {result.returncode}:\n"
                    f"{result.stdout[-4000:]}\n{result.stderr[-4000:]}"
                )
        # Preserve the literal CSV identifiers: parsing them as float can silently
        # round the organizer's 18-digit GIDs before a comparison is made.
        cls.outputs = {
            name: pd.read_csv(cls.output_dirs[0] / name, dtype="string")
            for name in SCHEMAS
        }
        cls.network = json.loads((cls.output_dirs[0] / "network.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        print("Full raw-Parquet CLI runs (seconds): " +
              ", ".join(f"{runtime:.3f}" for runtime in cls.runtimes), flush=True)

    def assert_exact_gids(self, values):
        self.assertFalse(values.isna().any(), "GIDs must not be missing")
        for value in values:
            self.assertRegex(value, r"^[0-9]+$", "GIDs must be literal decimal integers")
            self.assertEqual(value, str(int(value)), "GIDs must retain their canonical spelling")
            self.assertLessEqual(int(value), 2**63 - 1, "GIDs must fit signed int64")

    def assert_bounded_scores(self, values):
        for value in values:
            score = float(value)
            self.assertTrue(math.isfinite(score), "Scores must be finite")
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 1)

    def test_input_identity_counts_and_graph_endpoints(self):
        """Catch a substituted, truncated, duplicated, or ID-corrupted input."""
        self.assertEqual(len(self.nodes), 2248)
        self.assertEqual(len(self.edges), 3119)
        self.assertEqual(len(self.transactions), 4840)
        self.assertEqual(str(self.nodes.gid.dtype), "int64")
        self.assertTrue(self.nodes.gid.is_unique)
        self.assertFalse(self.nodes.isna().any().any())
        self.assertEqual(int(self.nodes.is_seed.sum()), 81)
        self.assertEqual(self.nodes.depth.value_counts().to_dict(),
                         {0: 81, 1: 472, 2: 462, 3: 789, 4: 444})
        self.assertEqual(set(self.nodes.loc[self.nodes.depth.eq(0), "gid"]),
                         set(self.nodes.loc[self.nodes.is_seed, "gid"]))
        for frame in (self.edges, self.transactions):
            self.assertFalse(frame.isna().any().any())
            for column in ("src", "dst"):
                self.assertEqual(str(frame[column].dtype), "int64")
                self.assertTrue(set(frame[column]).issubset(set(self.nodes.gid)))
        self.assertFalse(self.edges.duplicated(["src", "dst"]).any())

    def test_input_weak_components_keep_smaller_networks_and_isolated_seeds(self):
        """Catch a missing smaller component or isolate despite an intact main graph."""
        graph = nx.DiGraph()
        graph.add_nodes_from(self.nodes.gid)
        graph.add_edges_from(zip(self.edges.src, self.edges.dst))
        components = list(nx.weakly_connected_components(graph))
        linked = [component for component in components
                  if graph.subgraph(component).number_of_edges() > 0]
        isolated = {str(gid) for gid in nx.isolates(graph)}
        self.assertEqual(len(linked), 16)
        self.assertEqual(len(isolated), 19)
        self.assertTrue(isolated.issubset(self.seed_gids))
        self.assertEqual(sorted((len(component) for component in linked), reverse=True)[:2],
                         [1877, 270])

    def test_input_seed_observation_limits(self):
        """Catch accidental omission of isolated and receiver-only seeds."""
        senders = {str(gid) for gid in self.edges.src}
        receivers = {str(gid) for gid in self.edges.dst}
        self.assertEqual(len(self.seed_gids - senders - receivers), 19)
        self.assertEqual(len((self.seed_gids & receivers) - senders), 12)
        self.assertEqual(len(self.seed_gids - senders), 31)

    def test_input_transaction_period_threshold_and_total(self):
        """Catch transactions outside the supplied observation window or amount scope."""
        dates = pd.to_datetime(self.transactions.date)
        self.assertTrue(dates.ge(pd.Timestamp("2026-07-01")).all())
        self.assertTrue(dates.lt(pd.Timestamp("2026-08-01")).all())
        self.assertTrue(self.transactions.sum_kzt.ge(5000).all())
        self.assertAlmostEqual(float(self.transactions.sum_kzt.sum()), 365_890_012.01, delta=0.02)
        self.assertAlmostEqual(float(self.edges.sum_kzt.sum()), 365_890_012.01, delta=0.02)

    def test_input_edges_reconcile_with_raw_transactions(self):
        """Catch a reversed pair, missing transaction, or wrong aggregate."""
        raw = self.transactions.groupby(["src", "dst"]).sum_kzt.agg(["size", "sum"])
        edges = self.edges.set_index(["src", "dst"])
        self.assertEqual(set(raw.index), set(edges.index))
        self.assertEqual(int(self.edges.n_tx.sum()), 4840)
        for pair, transaction_group in raw.iterrows():
            self.assertEqual(int(edges.loc[pair, "n_tx"]), int(transaction_group["size"]))
            self.assertAlmostEqual(float(edges.loc[pair, "sum_kzt"]),
                                   float(transaction_group["sum"]), delta=0.02)

    def test_csv_schemas_and_required_values(self):
        """Catch removed, renamed, extra, empty, or null submission fields."""
        for name, columns in SCHEMAS.items():
            with self.subTest(file=name):
                frame = self.outputs[name]
                self.assertEqual(list(frame.columns), columns)
                self.assertGreater(len(frame), 0)
                self.assertFalse(frame.isna().any().any(), f"{name} contains missing values")
                for column in columns:
                    self.assertTrue(frame[column].str.strip().ne("").all(),
                                    f"{name}: {column} contains blank values")

    def test_node_roles_preserve_all_ids_and_have_bounded_explanations(self):
        """Catch node loss, float-rounded IDs, invalid labels, and unusable scores."""
        roles = self.outputs["nodes_roles.csv"]
        self.assert_exact_gids(roles.gid)
        self.assertTrue(roles.gid.is_unique)
        self.assertEqual(len(roles), 2248)
        self.assertEqual(set(roles.gid), self.raw_gids)
        self.assertTrue(set(roles.role).issubset(ALLOWED_ROLES))
        self.assertTrue(roles.cluster_id.str.fullmatch(r"-?[0-9]+").all())
        for column in ("role_score", "priority_score"):
            self.assert_bounded_scores(roles[column])
        self.assertTrue(roles.evidence.str.strip().str.len().between(1, 200).all())

    def test_clusters_cover_nodes_and_reconcile_raw_internal_flows(self):
        """Catch missing groups, wrong membership/seed counts, and external flows counted internally."""
        roles = self.outputs["nodes_roles.csv"]
        clusters = self.outputs["clusters.csv"]
        self.assertTrue(clusters.cluster_id.is_unique)
        self.assertEqual(set(clusters.cluster_id), set(roles.cluster_id))
        membership = dict(zip(roles.gid, roles.cluster_id))
        internal = defaultdict(Decimal)
        for tx in self.transactions.itertuples(index=False):
            source_cluster = membership[str(tx.src)]
            if source_cluster == membership[str(tx.dst)]:
                internal[source_cluster] += Decimal(str(tx.sum_kzt))
        for row in clusters.itertuples(index=False):
            with self.subTest(cluster=row.cluster_id):
                members = set(roles.loc[roles.cluster_id.eq(row.cluster_id), "gid"])
                self.assertRegex(row.n_nodes, r"^[0-9]+$")
                self.assertRegex(row.n_seed, r"^[0-9]+$")
                self.assertEqual(int(row.n_nodes), len(members))
                self.assertEqual(int(row.n_seed), len(members & self.seed_gids))
                self.assertGreater(len(members), 0)
                amount = Decimal(row.sum_kzt_internal)
                self.assertTrue(amount.is_finite())
                self.assertGreaterEqual(amount, 0)
                self.assertLessEqual(abs(amount - internal[row.cluster_id]), Decimal("0.02"))
                leaders = pd.Series(row.top_gids.split(","), dtype="string")
                self.assert_exact_gids(leaders)
                self.assertTrue(leaders.is_unique)
                self.assertTrue(set(leaders).issubset(members))
                self.assertTrue(row.hypothesis.strip())
        self.assertEqual(sum(int(value) for value in clusters.n_nodes), 2248)
        self.assertEqual(sum(int(value) for value in clusters.n_seed), 81)

    def test_top_nodes_are_valid_sorted_and_consistent_with_roles(self):
        """Catch too short a queue, duplicates, wrong ordering, or stale role/score copies."""
        top = self.outputs["top_nodes.csv"]
        roles = self.outputs["nodes_roles.csv"].set_index("gid")
        self.assertGreaterEqual(len(top), 20)
        self.assertLessEqual(len(top), len(roles))
        self.assert_exact_gids(top.gid)
        self.assertTrue(top.gid.is_unique)
        self.assertTrue(set(top.gid).issubset(self.raw_gids))
        self.assertEqual(top["rank"].tolist(), [str(rank) for rank in range(1, len(top) + 1)])
        self.assert_bounded_scores(top.priority_score)
        self.assertTrue(top.priority_score.astype(float).is_monotonic_decreasing)
        for row in top.itertuples(index=False):
            self.assertEqual(row.role, roles.loc[row.gid, "role"])
            self.assertEqual(Decimal(row.priority_score), Decimal(roles.loc[row.gid, "priority_score"]))
            self.assertTrue(row.why.strip())
        # A sorted subset alone is insufficient: higher-priority nodes must not
        # disappear from the review queue. Ties may be resolved in any order.
        excluded = roles.loc[~roles.index.isin(top.gid), "priority_score"].astype(float)
        if not excluded.empty:
            self.assertGreaterEqual(float(top.priority_score.iloc[-1]), float(excluded.max()))

    def test_boundary_terminal_evidence_acknowledges_incomplete_observation(self):
        """A depth-4 terminal hypothesis must carry uncertainty, not an observed full balance."""
        boundary = {str(gid) for gid in self.nodes.loc[self.nodes.depth.eq(4), "gid"]}
        roles = self.outputs["nodes_roles.csv"]
        terminals = roles.loc[roles.gid.isin(boundary) & roles.role.eq("terminal")]
        details = {node["gid"]: node for node in self.network["nodes"]}
        for row in terminals.itertuples(index=False):
            with self.subTest(gid=row.gid):
                node = details[row.gid]
                self.assertIs(node["truncated_by_depth"], True)
                self.assertGreaterEqual(node["continuation_support"], 30)
                self.assertGreaterEqual(node["continuation_rate"], 0)
                self.assertLessEqual(node["continuation_rate"], 1 / 3)
                self.assertGreater(node["data_quality"], 0)
                self.assertLess(node["data_quality"], 1)
                self.assertIn("вероятно", row.evidence.lower(),
                              "Depth-4 terminal must remain a reference-based hypothesis")

    def test_repeated_runs_are_byte_identical_and_finish_within_budget(self):
        """Catch nondeterminism across fresh processes and excessive end-to-end runtime."""
        for runtime in self.runtimes:
            self.assertLessEqual(runtime, 300)
        for name in SCHEMAS:
            with self.subTest(file=name):
                first = (self.output_dirs[0] / name).read_bytes()
                self.assertEqual(first, (self.output_dirs[1] / name).read_bytes())
                self.assertNotIn(b"\r\n", first, "Use stable LF newlines on every platform")

    def test_saved_deliverables_exist_and_match_fresh_outputs(self):
        """Catch missing or stale mandatory submission CSVs."""
        saved = ROOT / "deliverables"
        for name in SCHEMAS:
            with self.subTest(file=name):
                self.assertTrue((saved / name).is_file(), f"Missing deliverable: {name}")
                self.assertEqual((saved / name).read_bytes(),
                                 (self.output_dirs[0] / name).read_bytes(),
                                 f"Saved {name} differs from a fresh pipeline run")


if __name__ == "__main__":
    unittest.main(verbosity=2)
