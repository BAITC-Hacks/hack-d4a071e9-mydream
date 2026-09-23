#!/usr/bin/env bash
# macOS (Apple Silicon и Intel). Установка Python и Homebrew не нужны.
# При первом запуске нужен интернет: скрипт скачивает портативный Python 3.11
# (python-build-standalone) в portable/mac и ставит библиотеки из PyPI.
# Дальше всё работает офлайн.
#   ./run_mac.sh                 пайплайн: CSV в output/
#   ./run_mac.sh check|test|app
#   ./run_mac.sh explain <gid>
#   ./run_mac.sh ask "кто собирает деньги с <gid> <gid> ..."
set -e
cd "$(dirname "$0")"

PBS_TAG=20260901
PY_VER=3.11.16
case "$(uname -m)" in
  arm64)  ARCH=aarch64-apple-darwin; SHA=768f05cf200273bbdda9a5955a5a6892a4b22f2a0b1e4b0a9160f5c7fce86816 ;;
  x86_64) ARCH=x86_64-apple-darwin;  SHA=908b381433f78b832c8d64960ced0f85871893cc8779f413f963e0c9e293c258 ;;
  *) echo "Неподдерживаемая архитектура: $(uname -m)"; exit 1 ;;
esac

PY=./portable/mac/bin/python3
export PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1

if [ ! -x "$PY" ]; then
  F="cpython-$PY_VER+$PBS_TAG-$ARCH-install_only_stripped.tar.gz"
  URL="https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_TAG/$F"
  echo ">> Первый запуск: скачиваю портативный Python 3.11 ($ARCH, ~20 МБ)..."
  mkdir -p portable .cache
  [ -f ".cache/$F" ] || curl -fL --retry 4 -o ".cache/$F" "$URL"
  echo "$SHA  .cache/$F" | shasum -a 256 -c -
  rm -rf portable/mac portable/python
  tar -xzf ".cache/$F" -C portable && mv portable/python portable/mac
fi

if ! "$PY" -s -c "import pandas, networkx, pyarrow, scipy, streamlit, pyvis, pytest, openai" 2>/dev/null; then
  echo ">> Первый запуск: ставлю библиотеки из PyPI (~200 МБ)..."
  "$PY" -s -m pip install -q --no-warn-script-location --disable-pip-version-check -r requirements.txt
fi

case "${1:-run}" in
  run)     "$PY" -s -m moneygraph run --data data --out output ;;
  check)   "$PY" -s -m moneygraph check --out output ;;
  test)    "$PY" -s -m pytest -q tests ;;
  explain) "$PY" -s -m moneygraph explain "$2" --out output ;;
  ask)     "$PY" -s -m moneygraph ask "$2" --out output --data data ;;
  app)     "$PY" -s -m streamlit run app/streamlit_app.py ;;
  *)       echo "run | check | test | explain <gid> | ask \"вопрос\" | app" ;;
esac
