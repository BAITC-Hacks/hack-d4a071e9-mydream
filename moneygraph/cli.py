"""python -m moneygraph run|explain|check"""
import argparse
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(prog="moneygraph")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--data", default="data"); r.add_argument("--out", default="output")
    e = sub.add_parser("explain"); e.add_argument("gid", type=int); e.add_argument("--out", default="output")
    c = sub.add_parser("check"); c.add_argument("--out", default="output")
    a = ap.parse_args()
    if a.cmd == "run":
        from . import pipeline
        pipeline.run(Path(a.data), Path(a.out))
    elif a.cmd == "explain":
        from .explain import explain
        print(explain(a.gid, Path(a.out)))
    elif a.cmd == "check":
        from .export import validate_outputs
        validate_outputs(Path(a.out)); print("OK")


if __name__ == "__main__":
    main()
