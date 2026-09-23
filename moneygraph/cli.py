"""python -m moneygraph run|explain|check|ask"""
import argparse
import sys
from pathlib import Path


def _utf8_stdio():
    # Windows: cp1252/cp866 и перенаправление вывода не кодируют кириллицу и «—»
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")


def main():
    _utf8_stdio()
    ap = argparse.ArgumentParser(prog="moneygraph")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--data", default="data"); r.add_argument("--out", default="output")
    e = sub.add_parser("explain"); e.add_argument("gid", type=int); e.add_argument("--out", default="output")
    c = sub.add_parser("check"); c.add_argument("--out", default="output")
    q = sub.add_parser("ask"); q.add_argument("question"); q.add_argument("--out", default="output"); q.add_argument("--data", default="data")
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
    elif a.cmd == "ask":
        from .assistant import answer
        text, source, _ = answer(a.question, Path(a.out), Path(a.data))
        print(text); print(f"[источник: {source}]")


if __name__ == "__main__":
    main()
