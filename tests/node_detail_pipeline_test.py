"""The detail export preserves every observed transfer and exact GID."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "track02"))

from pipeline import run_pipeline  # noqa: E402


class NodeDetailPipelineTests(unittest.TestCase):
    def test_full_node_export_keeps_large_ids_and_each_transaction(self):
        import duckdb

        first = 100000003115284099
        chosen = 100000003115284100
        last = 100000003115284101
        nodes = pd.DataFrame(
            [(first, 0, True), (chosen, 1, False), (last, 2, False)],
            columns=["gid", "depth", "is_seed"],
        )
        edges = pd.DataFrame(
            [(first, chosen, 23000, 2, 1), (chosen, last, 8000, 1, 2)],
            columns=["src", "dst", "sum_kzt", "n_tx", "depth"],
        )
        transactions = pd.DataFrame(
            [
                (first, chosen, pd.Timestamp("2026-07-05"), 11000),
                (first, chosen, pd.Timestamp("2026-07-06"), 12000),
                (chosen, last, pd.Timestamp("2026-07-07"), 8000),
            ],
            columns=["src", "dst", "date", "sum_kzt"],
        )

        with tempfile.TemporaryDirectory() as folder:
            data_dir = Path(folder) / "data"
            out_dir = Path(folder) / "out"
            data_dir.mkdir()
            for name, frame in (("nodes", nodes), ("edges", edges), ("transactions", transactions)):
                duckdb.from_df(frame).write_parquet(str(data_dir / f"{name}.parquet"))

            run_pipeline(data_dir, out_dir)

            network = json.loads((out_dir / "network.json").read_text(encoding="utf-8"))
            indexed = json.loads((out_dir / "transactions_by_gid.json").read_text(encoding="utf-8"))
            node = next(node for node in network["nodes"] if node["gid"] == str(chosen))
            self.assertTrue({"pagerank", "betweenness", "pass_through", "active_days"}.issubset(node))
            self.assertEqual(node["in_tx"], 2)
            self.assertEqual(node["out_tx"], 1)
            self.assertEqual([edge["depth"] for edge in network["edges"]], [1, 2])
            self.assertEqual(indexed[str(chosen)], [
                {"src": str(first), "dst": str(chosen), "date": "2026-07-05",
                 "sum_kzt": 11000.0, "direction": "incoming", "counterparty": str(first)},
                {"src": str(first), "dst": str(chosen), "date": "2026-07-06",
                 "sum_kzt": 12000.0, "direction": "incoming", "counterparty": str(first)},
                {"src": str(chosen), "dst": str(last), "date": "2026-07-07",
                 "sum_kzt": 8000.0, "direction": "outgoing", "counterparty": str(last)},
            ])
            self.assertEqual(len(indexed[str(first)]), 2)
            self.assertEqual(len(indexed[str(last)]), 1)


if __name__ == "__main__":
    unittest.main()
