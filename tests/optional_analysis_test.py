"""Checks that optional signals use observed transfers and preserve graph boundaries."""

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "track02"))

from pipeline import analyze  # noqa: E402


class OptionalAnalysisTests(unittest.TestCase):
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
