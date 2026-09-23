"""Contract checks for the small, reproducible Money Graph demo input."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "track02"))

from pipeline import analyze, load_data, validate_data  # noqa: E402


class SyntheticDataTests(unittest.TestCase):
    def test_generated_graph_exercises_the_main_roles_and_crawl_limit(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "track02") as folder:
            data_dir = Path(folder)
            generator = ROOT / "track02" / "fixtures" / "generate.py"
            self.assertTrue(generator.is_file(), "reproducible fixture generator is missing")
            subprocess.run(
                [sys.executable, str(generator), "--out", str(data_dir)],
                check=True,
                capture_output=True,
                text=True,
            )
            nodes, edges, transactions = load_data(data_dir)
            validate_data(nodes, edges, transactions)
            roles, _, _, network = analyze(nodes, edges, transactions)

            self.assertEqual(len(nodes), 21)
            self.assertEqual(len(edges), 19)
            self.assertGreater(len(transactions), len(edges))
            self.assertEqual(nodes.is_seed.sum(), 6)
            self.assertTrue(transactions.date.astype(str).between("2026-07-01", "2026-07-31").all())
            self.assertTrue(transactions.sum_kzt.ge(5_000).all())

            by_gid = roles.set_index("gid")
            self.assertEqual(by_gid.loc[180000000000000001, "role"], "distributor")
            self.assertEqual(by_gid.loc[180000000000000104, "role"], "consolidator")
            self.assertEqual(by_gid.loc[180000000000000201, "role"], "transit")
            self.assertEqual(by_gid.loc[180000000000000202, "role"], "coordinator")
            self.assertEqual(by_gid.loc[180000000000000101, "role"], "terminal")
            self.assertEqual(by_gid.loc[180000000000000401, "role"], "peripheral")
            self.assertTrue(by_gid.loc[180000000000000401, "truncated_by_depth"])
            self.assertEqual(by_gid.loc[180000000000000005, "data_quality"], 0.2)
            self.assertTrue(all(isinstance(node["gid"], str) for node in network["nodes"]))


if __name__ == "__main__":
    unittest.main()
