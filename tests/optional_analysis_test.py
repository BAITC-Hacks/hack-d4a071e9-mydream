"""Checks that optional signals use observed transfers and preserve graph boundaries."""

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "track02"))

from pipeline import analyze  # noqa: E402
from optional_analysis import _temporal_and_splitting  # noqa: E402


class OptionalAnalysisTests(unittest.TestCase):
    def test_small_transfer_group_survives_a_large_transfer_on_the_same_day(self):
        tx = pd.DataFrame([
            (1, 2, "2026-07-01", amount)
            for amount in (6000, 7000, 8000, 100000)
        ], columns=["src", "dst", "date", "sum_kzt"])

        signals = _temporal_and_splitting(tx)

        self.assertEqual(signals[1]["splitting_groups"], 1)
        self.assertEqual(signals[2]["splitting_groups"], 0)

    def test_small_transfers_are_counted_within_one_recipient_and_day(self):
        tx = pd.DataFrame([
            (1, 2, "2026-07-01", 5000),
            (1, 2, "2026-07-01", 25000),
            (1, 2, "2026-07-01", 25001),
            (1, 3, "2026-07-01", 6000),
            (1, 2, "2026-07-02", 6000),
        ], columns=["src", "dst", "date", "sum_kzt"])

        self.assertEqual(_temporal_and_splitting(tx)[1]["splitting_groups"], 0)

    def test_transit_window_includes_day_two_but_not_day_three_or_earlier(self):
        tx = pd.DataFrame([
            (1, 2, "2026-07-01", 10000), (2, 3, "2026-07-03", 10000),
            (4, 5, "2026-07-01", 10000), (5, 6, "2026-07-04", 10000),
            (7, 8, "2026-07-05", 10000), (8, 9, "2026-07-05", 10000),
            (10, 11, "2026-07-04", 10000), (11, 12, "2026-07-03", 10000),
        ], columns=["src", "dst", "date", "sum_kzt"])

        signals = _temporal_and_splitting(tx)

        self.assertEqual(signals[2]["transit_2d_count"], 1)
        self.assertEqual(signals[5]["transit_2d_count"], 0)
        self.assertEqual(signals[8]["transit_2d_count"], 1)
        self.assertEqual(signals[11]["transit_2d_count"], 0)

    def test_burst_uses_at_least_three_active_days(self):
        tx = pd.DataFrame([
            (1, 2, "2026-07-01", 10000),
            (1, 3, "2026-07-02", 10000),
            (1, 2, "2026-07-03", 10000),
            (1, 2, "2026-07-03", 10000),
            (1, 2, "2026-07-03", 10000),
        ], columns=["src", "dst", "date", "sum_kzt"])

        signals = _temporal_and_splitting(tx)

        self.assertEqual(signals[1]["burst_days"], 1)
        self.assertEqual(signals[2]["burst_days"], 0)

    def test_synchronous_payers_require_three_distinct_senders(self):
        tx = pd.DataFrame([
            (source, target, "2026-07-01", 10000)
            for source, target in [(1, 9), (1, 9), (2, 9), (3, 9),
                                   (1, 10), (1, 10), (2, 10)]
        ], columns=["src", "dst", "date", "sum_kzt"])

        signals = _temporal_and_splitting(tx)

        self.assertEqual(signals[9]["synchronous_payers_days"], 1)
        self.assertEqual(signals[10]["synchronous_payers_days"], 0)

    def test_depth_profile_needs_thirty_peers_and_flags_the_large_recipient(self):
        for recipient_count in (29, 30):
            with self.subTest(recipient_count=recipient_count):
                recipients = list(range(2, recipient_count + 2))
                large_recipient = recipients[-1]
                nodes = pd.DataFrame(
                    [(1, 0, True)] + [(gid, 1, False) for gid in recipients],
                    columns=["gid", "depth", "is_seed"],
                )
                tx = pd.DataFrame([
                    (1, gid, "2026-07-01", 2000000 if gid == large_recipient else 10000)
                    for gid in recipients
                ], columns=["src", "dst", "date", "sum_kzt"])
                edges = tx.groupby(["src", "dst"], as_index=False).agg(
                    sum_kzt=("sum_kzt", "sum"), n_tx=("sum_kzt", "size")
                )
                edges["depth"] = 1

                _, _, _, network = analyze(nodes, edges, tx)
                details = {item["gid"]: item["optional"] for item in network["nodes"]}

                expected = ["входящий объём в верхнем 1% колена 1"] if recipient_count == 30 else []
                self.assertEqual(details[str(large_recipient)]["peer_outliers"], expected)
                self.assertTrue(all(not details[str(gid)]["peer_outliers"]
                                    for gid in recipients[:-1]))

    def test_removing_the_top_star_hub_separates_all_leaves(self):
        nodes = pd.DataFrame(
            [(1, 0, True)] + [(gid, 1, False) for gid in range(2, 7)],
            columns=["gid", "depth", "is_seed"],
        )
        tx = pd.DataFrame([
            (1, gid, "2026-07-01", 10000) for gid in range(2, 7)
        ], columns=["src", "dst", "date", "sum_kzt"])
        edges = tx.groupby(["src", "dst"], as_index=False).agg(
            sum_kzt=("sum_kzt", "sum"), n_tx=("sum_kzt", "size")
        )
        edges["depth"] = 1

        _, _, _, network = analyze(nodes, edges, tx)
        resilience = network["optional"]["resilience"]

        self.assertEqual(resilience["baseline_components"], 1)
        self.assertEqual(resilience["baseline_largest"], 6)
        self.assertEqual(resilience["remove_top"][0], {
            "n": 1, "removed_gids": ["1"], "components": 5,
            "largest_component": 1, "largest_share_pct": 20.0,
        })

    def test_temporal_routes_cycles_and_resilience_are_explained(self):
        gids = list(range(1, 10))
        nodes = pd.DataFrame({
            "gid": gids, "depth": [0, 1, 2, 3, 4, 0, 1, 1, 1],
            "is_seed": [True, False, False, False, False, True, False, False, False],
        })
        transfers = [
            (1, 2, "2026-07-01", 10000), (1, 2, "2026-07-02", 10000),
            (2, 3, "2026-07-01", 10000), (2, 3, "2026-07-02", 10000),
            (3, 1, "2026-07-03", 5000),
            (6, 2, "2026-07-01", 10000), (7, 2, "2026-07-01", 10000),
            (8, 9, "2026-07-04", 6000), (8, 9, "2026-07-04", 7000),
            (8, 9, "2026-07-04", 8000),
            (3, 4, "2026-07-04", 10000), (4, 5, "2026-07-04", 10000),
        ]
        tx = pd.DataFrame(transfers, columns=["src", "dst", "date", "sum_kzt"])
        tx["date"] = pd.to_datetime(tx.date)
        edges = tx.groupby(["src", "dst"], as_index=False).agg(
            sum_kzt=("sum_kzt", "sum"), n_tx=("sum_kzt", "size")
        )
        edges["depth"] = 1

        roles, _, _, network = analyze(nodes, edges, tx)
        details = {item["gid"]: item["optional"] for item in network["nodes"]}
        self.assertGreaterEqual(details["2"]["transit_2d_count"], 1)
        self.assertEqual(details["1"]["transit_2d_count"], 0)
        self.assertGreaterEqual(details["2"]["synchronous_payers_days"], 1)
        self.assertTrue(any(route["path"] == ["1", "2", "3"]
                            for route in network["optional"]["repeated_routes"]))
        self.assertTrue(any(set(cycle["path"]) == {"1", "2", "3"}
                            for cycle in network["optional"]["cycles"]))
        self.assertEqual(details["8"]["splitting_groups"], 1)
        self.assertEqual(details["8"]["burst_days"], 0)
        self.assertEqual(details["5"]["observation"], "depth_limit")
        self.assertIn("remove_top", network["optional"]["resilience"])
        self.assertEqual(len(network["optional"]["resilience"]["remove_top"]), 3)
        self.assertEqual(len(roles), len(gids))


if __name__ == "__main__":
    unittest.main()
