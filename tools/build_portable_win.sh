#!/usr/bin/env bash
# Сборка офлайн-архивов на Windows (Git Bash). Нужны интернет, curl, tar.
# Запуск из корня репозитория: bash tools/build_portable_win.sh
# Результат: dist/moneygraph-win-x64.zip, dist/moneygraph-linux-x64.tar.gz, dist/moneygraph-macos.tar.gz,
#            dist/SHA256SUMS, dist/BUILD_INFO.txt, части по 25 МБ и скрипты склейки.
# Аналог tools/build_portable.sh для Linux-хоста. Здесь Windows-часть ставится «родным» pip
# (маркеры Windows считаются правильно), а Linux-часть собирается из колёс manylinux и
# перепаковывается скриптом tools/pack_bundles.py — распаковывать Linux-интерпретатор на Windows
# нельзя, symlink'и не создаются.
set -euo pipefail
export PYTHONNOUSERSITE=1 PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1

PBS_TAG=20260901
PY_VER=3.11.16
BASE=https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_TAG
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
mkdir -p portable dist .cache

fetch() {  # fetch <triple> -> путь к архиву
  local f="cpython-$PY_VER+$PBS_TAG-$1-install_only_stripped.tar.gz"
  [ -f ".cache/$f" ] || curl -fL --retry 4 -o ".cache/$f" "$BASE/$f"
  echo ".cache/$f"
}
[ -f .cache/SHA256SUMS ] || curl -fL --retry 4 -o .cache/SHA256SUMS "$BASE/SHA256SUMS"
WIN=$(fetch x86_64-pc-windows-msvc)
LIN=$(fetch x86_64-unknown-linux-gnu)
(cd .cache && grep -F -e "$(basename "$WIN")" -e "$(basename "$LIN")" SHA256SUMS | sha256sum -c -)

# Windows: распаковать и поставить зависимости его же pip
rm -rf portable/win && mkdir -p portable/win
tar -xzf "$WIN" -C portable/win --strip-components=1
PYW=portable/win/python.exe
"$PYW" -m pip install -q --no-warn-script-location --disable-pip-version-check -r requirements.txt
"$PYW" -m pip freeze --disable-pip-version-check > .cache/lock.txt
"$PYW" tools/check_deps.py portable/win/Lib/site-packages win

# Linux: колёса manylinux тех же версий (из lock) в отдельную папку.
# pexpect и ptyprocess — зависимости ipython «кроме Windows», pip на Windows их не видит
rm -rf .cache/linux_site
"$PYW" -m pip install -q --disable-pip-version-check --only-binary=:all: \
  --python-version 3.11 --implementation cp --abi cp311 --abi abi3 --abi none \
  --platform manylinux_2_28_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64 \
  --platform manylinux_2_5_x86_64 --platform linux_x86_64 --platform any \
  --target .cache/linux_site -r .cache/lock.txt pexpect ptyprocess
"$PYW" tools/check_deps.py .cache/linux_site linux

# Проверка Windows-варианта: полный прогон и тесты (output/ попадает в архивы)
"$PYW" -m moneygraph run --data data --out output
"$PYW" -m pytest -q tests

# Упаковка трёх архивов, контрольные суммы, части, скрипты склейки
"$PYW" tools/pack_bundles.py --pbs-linux "$LIN" --linux-site .cache/linux_site
ls -lh dist/
