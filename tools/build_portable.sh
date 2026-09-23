#!/usr/bin/env bash
# Сборка портативного Python с зависимостями (Linux x64 + Windows x64).
# Нужны интернет, curl, tar, zip. Запуск из корня репозитория: bash tools/build_portable.sh
# Результат: portable/linux, portable/win и архивы dist/moneygraph-{linux,win}-x64.*
set -euo pipefail
# Не видеть чужие пакеты из ~/.local, иначе pip «найдёт» их там и не положит в сборку
export PYTHONNOUSERSITE=1

PBS_TAG=20250317
PY_VER=3.11.11
BASE=https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_TAG
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
mkdir -p portable dist .cache
rm -rf portable/linux portable/win

fetch() {  # fetch <triple> -> путь к архиву
  local f="cpython-$PY_VER+$PBS_TAG-$1-install_only_stripped.tar.gz"
  [ -f ".cache/$f" ] || curl -fL --retry 4 -o ".cache/$f" "$BASE/$f"
  echo ".cache/$f"
}

# Linux: распаковать и поставить зависимости его же pip
tar -xzf "$(fetch x86_64-unknown-linux-gnu)" -C portable && mv portable/python portable/linux
portable/linux/bin/python3 -m pip install -q --no-warn-script-location -r requirements.txt

# Windows: распаковать и поставить колёса win_amd64 в его site-packages.
# colorama и tzdata — зависимости «только для Windows», pip --platform их не видит
tar -xzf "$(fetch x86_64-pc-windows-msvc)" -C portable && mv portable/python portable/win
portable/linux/bin/python3 -m pip install -q --no-warn-script-location \
  --platform win_amd64 --python-version 3.11 --implementation cp --abi cp311 \
  --only-binary=:all: --target portable/win/Lib/site-packages -r requirements.txt colorama tzdata
portable/linux/bin/python3 tools/check_win_deps.py portable/win/Lib/site-packages

# Проверка Linux-варианта: полный прогон и тесты
portable/linux/bin/python3 -m moneygraph run --data data --out output
portable/linux/bin/python3 -m pytest -q tests

# Архивы: проект + свой интерпретатор, без git и кэшей
FILES=(moneygraph app data output tests requirements.txt README.md DESIGN.md run.sh run.ps1 run_offline.sh run_offline.bat)
EXCL=(--exclude='__pycache__' --exclude='*.pyc')
rm -f dist/moneygraph-linux-x64.tar.gz dist/moneygraph-win-x64.zip
stage=$(mktemp -d)
mkdir "$stage/moneygraph"
tar -cf - "${EXCL[@]}" "${FILES[@]}" portable/linux | tar -xf - -C "$stage/moneygraph"
tar -czf dist/moneygraph-linux-x64.tar.gz -C "$stage" moneygraph
rm -rf "$stage/moneygraph/portable/linux"
tar -cf - "${EXCL[@]}" portable/win | tar -xf - -C "$stage/moneygraph"
(cd "$stage" && zip -qr9 "$ROOT/dist/moneygraph-win-x64.zip" moneygraph)
rm -rf "$stage"
ls -lh dist/
