#!/usr/bin/env bash
# Запуск без установки Python: ./run_offline.sh run | explain <gid> | check | test | app
cd "$(dirname "$0")"
PY=portable/linux/bin/python3
export PYTHONNOUSERSITE=1 PYTHONUTF8=1
[ -x "$PY" ] || { echo "Нет $PY — соберите: bash tools/build_portable.sh"; exit 1; }
cmd=${1:-run}; shift || true
case "$cmd" in
  run)     "$PY" -m moneygraph run --data data --out output ;;
  explain) "$PY" -m moneygraph explain "$@" ;;
  check)   "$PY" -m moneygraph check --out output ;;
  test)    "$PY" -m pytest -q tests ;;
  app)     "$PY" -m streamlit run app/streamlit_app.py --server.headless true --browser.gatherUsageStats false ;;
  *)       echo "run | explain <gid> | check | test | app" ;;
esac
