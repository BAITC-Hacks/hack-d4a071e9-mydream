"""Depth-4 boundary nodes are compared with traced depth 1-3 recipients."""

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "track02"))

from pipeline import CONTINUATION_MIN_SUPPORT, analyze  # noqa: E402


def reference_graph():
    """Traced depth 1-3 recipients with one incoming transfer: 18 of 58 forward.

    A depth-4 client with one incoming transfer therefore matches a band whose
    observed continuation share is 31%. A depth-4 client with seven incoming
    transfers matches a band with no reference support at all.
    """
    seed, forwarders, chain = 1, 8, [1001, 2001, 3001]
    depths = {seed: 0}
    pairs = []
    for index in range(40):
        client = 100 + index
        depths[client] = 1
        pairs.append((seed, client, 20_000))
        if index < forwarders:
            target = 500 + index
            depths[target] = 2
            pairs.append((client, target, 15_000))
    for depth, gid in enumerate(chain, start=1):
        depths[gid] = depth
    pairs += [(seed, 1001, 30_000), (1001, 2001, 30_000), (2001, 3001, 30_000)]
    depths[4001] = 4
    pairs.append((3001, 4001, 25_000))
    depths[4002] = 4
    busy_payers = [6001 + index for index in range(7)]
    for payer in busy_payers:
        depths[payer] = 3
        pairs += [(2001, payer, 10_000), (payer, 4002, 8_000)]
    nodes = pd.DataFrame(
        [(gid, depth, depth == 0) for gid, depth in depths.items()],
        columns=["gid", "depth", "is_seed"],
    )
    edges = pd.DataFrame(
        [(src, dst, amount, 1, max(1, depths[dst])) for src, dst, amount in pairs],
        columns=["src", "dst", "sum_kzt", "n_tx", "depth"],
    )
    tx = pd.DataFrame(
        [(src, dst, pd.Timestamp("2026-07-10"), amount) for src, dst, amount in pairs],
        columns=["src", "dst", "date", "sum_kzt"],
    )
    return nodes, edges, tx


class BoundaryAssessmentTests(unittest.TestCase):
    def test_depth_four_leaf_uses_reference_share_of_traced_recipients(self):
        nodes, edges, tx = reference_graph()
        roles, _, _, network = analyze(nodes, edges, tx)
        by_gid = roles.set_index("gid")

        leaf = by_gid.loc[4001]
        self.assertTrue(leaf.truncated_by_depth)
        self.assertEqual(leaf.boundary_label, "likely_terminal")
        self.assertGreaterEqual(leaf.continuation_support, CONTINUATION_MIN_SUPPORT)
        self.assertAlmostEqual(float(leaf.continuation_rate), 18 / 58, places=3)
        self.assertEqual(leaf.role, "terminal")
        self.assertLess(leaf.role_score, by_gid.loc[108, "role_score"])
        self.assertIn("глубина 4", leaf.evidence)
        self.assertIn("вероятно конечный", leaf.evidence)
        self.assertIn("узлов колен 1–3", leaf.evidence)

        busy = by_gid.loc[4002]
        self.assertTrue(busy.truncated_by_depth)
        self.assertEqual(busy.boundary_label, "uncertain")
        self.assertEqual(busy.role, "peripheral")
        self.assertIn("мало сравнимых", busy.evidence)

        self.assertTrue(by_gid.loc[~by_gid.truncated_by_depth, "boundary_label"].isna().all())
        self.assertEqual(network["meta"]["boundary_labels"]["likely_terminal"], 1)
        self.assertEqual(network["meta"]["boundary_labels"]["uncertain"], 1)
        bands = {item["band"]: item for item in network["meta"]["continuation_reference"]}
        self.assertEqual(bands["1 операция"]["support"], 58)
        self.assertTrue(all(item["boundary_label"] in (None, "likely_terminal", "uncertain", "likely_continues")
                            for item in network["nodes"]))


if __name__ == "__main__":
    unittest.main()
