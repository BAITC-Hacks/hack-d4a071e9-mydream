#!/usr/bin/env python3
"""Write a deterministic, synthetic transfer graph for checking Money Graph."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd


BASE = 180000000000000000
DEPTHS = {
    1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0,
    101: 1, 102: 1, 103: 1, 104: 1, 105: 1, 106: 1, 107: 1,
    201: 2, 202: 2,
    301: 3, 302: 3, 303: 3,
    401: 4, 402: 4, 403: 4,
}

# Separate branches make each role and the depth-4 observation limit visible.
TRANSFERS = [
    (1, 101, 100_000), (1, 102, 80_000), (1, 103, 60_000),
    (2, 104, 50_000), (3, 104, 60_000), (4, 104, 70_000),
    (104, 201, 180_000), (201, 301, 170_000), (301, 401, 160_000),
    (6, 105, 80_000), (6, 106, 80_000), (6, 107, 80_000),
    (105, 202, 75_000), (106, 202, 75_000), (107, 202, 75_000),
    (202, 302, 110_000), (202, 303, 110_000),
    (302, 402, 100_000), (303, 403, 100_000),
]


def make_frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    nodes = pd.DataFrame(
        [(BASE + gid, depth, depth == 0) for gid, depth in DEPTHS.items()],
        columns=["gid", "depth", "is_seed"],
    )
    edge_rows = []
    transaction_rows = []
    for index, (src, dst, amount) in enumerate(TRANSFERS):
        amounts = [amount * 0.4, amount * 0.6] if index % 3 == 0 else [amount]
        edge_rows.append((BASE + src, BASE + dst, float(amount), len(amounts), DEPTHS[dst]))
        for part, part_amount in enumerate(amounts):
            day = 1 + (index * 2 + part) % 28
            transaction_rows.append((BASE + src, BASE + dst, date(2026, 7, day), part_amount))
    edges = pd.DataFrame(edge_rows, columns=["src", "dst", "sum_kzt", "n_tx", "depth"])
    transactions = pd.DataFrame(
        transaction_rows, columns=["src", "dst", "date", "sum_kzt"]
    )
    return nodes, edges, transactions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=Path(__file__).resolve().parent / "check",
        help="Directory for nodes.parquet, edges.parquet, transactions.parquet",
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for name, frame in zip(("nodes", "edges", "transactions"), make_frames()):
        duckdb.from_df(frame).write_parquet(str(args.out / f"{name}.parquet"))
    print(f"Generated {len(DEPTHS)} nodes, {len(TRANSFERS)} edges in {args.out}")


if __name__ == "__main__":
    main()
