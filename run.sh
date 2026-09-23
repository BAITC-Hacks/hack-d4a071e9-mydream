#!/usr/bin/env bash
# Запуск на Linux/macOS: ./run.sh install | run | check | test | app
set -e
case "${1:-run}" in
  install) pip install -r requirements.txt ;;
  run)     python -m moneygraph run --data data --out output ;;
  check)   python -m moneygraph check --out output ;;
  test)    pytest -q tests ;;
  app)     streamlit run app/streamlit_app.py ;;
  *)       echo "install | run | check | test | app" ;;
esac
