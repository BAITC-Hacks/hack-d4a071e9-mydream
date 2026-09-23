"""Упаковка офлайн-архивов. Вызывается из tools/build_portable_win.sh (корень репозитория):

    python tools/pack_bundles.py --pbs-linux .cache/<cpython-linux>.tar.gz --linux-site .cache/linux_site

Результат в dist/:
  moneygraph-win-x64.zip        проект + portable/win (Python и библиотеки уже установлены)
  moneygraph-linux-x64.tar.gz   проект + portable/linux (интерпретатор перепакован из архива
                                python-build-standalone, symlink'и сохранены; библиотеки — колёса manylinux)
  moneygraph-macos.tar.gz       проект + run_mac.sh (Python и библиотеки скачиваются при первом запуске)
  SHA256SUMS, BUILD_INFO.txt, части по 25 МБ (*.part00…) и join_win.bat / join_linux.sh

openai_key.txt в архивы не кладётся (см. README).
"""
import argparse
import hashlib
import os
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path

FILES = [".streamlit", "moneygraph", "app", "data", "output", "tests", "docs",
         "conftest.py", "requirements.txt", "README.md", "README_dataset.md", "DESIGN.md",
         "run.sh", "run.ps1", "run_offline.sh", "run_offline.bat", "run_mac.sh"]
EXCL_DIRS = {"__pycache__", ".pytest_cache"}
PART = 25 * 1024 * 1024
SPLIT_OVER = 95 * 1024 * 1024          # лимит файла GitHub — 100 МБ
LINUX_PREFIX = "moneygraph/portable/linux"
LINUX_SITE = LINUX_PREFIX + "/lib/python3.11/site-packages"


def iter_tree(base: Path, top: str):
    """(абсолютный путь, относительный posix-путь) для файла или дерева без кэшей."""
    p = base / top
    if p.is_file():
        yield p, top
        return
    for dp, dns, fns in os.walk(p):
        dns[:] = sorted(d for d in dns if d not in EXCL_DIRS)
        for fn in sorted(fns):
            if fn.endswith(".pyc"):
                continue
            fp = Path(dp) / fn
            yield fp, fp.relative_to(base).as_posix()


def tarinfo(tf: tarfile.TarFile, fp: Path, arcname: str, mode: int) -> tarfile.TarInfo:
    ti = tf.gettarinfo(str(fp), arcname=arcname)
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = ""
    ti.mode = mode
    return ti


def add_project(tf: tarfile.TarFile, root: Path):
    for top in FILES:
        for fp, rel in iter_tree(root, top):
            mode = 0o755 if rel.endswith(".sh") else 0o644
            with open(fp, "rb") as f:
                tf.addfile(tarinfo(tf, fp, "moneygraph/" + rel, mode), f)


def build_linux(root: Path, pbs: Path, site: Path, out: Path):
    n_py = n_site = 0
    with tarfile.open(out, "w:gz", compresslevel=6) as tf, tarfile.open(pbs, "r:gz") as src:
        for m in src:
            # python/... -> moneygraph/portable/linux/... ; symlink'и и hardlink'и переносятся как есть
            if not (m.name == "python" or m.name.startswith("python/")):
                raise SystemExit(f"неожиданный путь в архиве python-build-standalone: {m.name}")
            m.name = LINUX_PREFIX + m.name[len("python"):]
            if m.islnk():
                m.linkname = LINUX_PREFIX + m.linkname[len("python"):]
            m.uid = m.gid = 0
            m.uname = m.gname = ""
            tf.addfile(m, src.extractfile(m) if m.isfile() else None)
            n_py += 1
        for dp, dns, fns in os.walk(site):
            dns[:] = sorted(d for d in dns if d not in EXCL_DIRS)
            rel_dir = Path(dp).relative_to(site).as_posix()
            if rel_dir == "bin" or rel_dir.startswith("bin/"):
                continue                      # консольные скрипты pip --target не нужны: запуск через -m
            for fn in sorted(fns):
                if fn.endswith(".pyc"):
                    continue
                fp = Path(dp) / fn
                rel = fp.relative_to(site).as_posix()
                with open(fp, "rb") as f:
                    tf.addfile(tarinfo(tf, fp, f"{LINUX_SITE}/{rel}", 0o644), f)
                n_site += 1
        add_project(tf, root)
    print(f"[linux] {out.name}: интерпретатор {n_py} записей, site-packages {n_site} файлов")


def build_mac(root: Path, out: Path):
    with tarfile.open(out, "w:gz", compresslevel=6) as tf:
        add_project(tf, root)
    print(f"[mac] {out.name}: проект без интерпретатора (run_mac.sh скачает Python при первом запуске)")


def build_win(root: Path, out: Path):
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as zf:
        for top in FILES + ["portable/win"]:
            for fp, rel in iter_tree(root, top):
                zf.write(fp, "moneygraph/" + rel)
                n += 1
    print(f"[win] {out.name}: {n} файлов")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def split(p: Path):
    parts = []
    with open(p, "rb") as f:
        i = 0
        while chunk := f.read(PART):
            part = p.with_name(f"{p.name}.part{i:02d}")
            part.write_bytes(chunk)
            parts.append(part.name)
            i += 1
    return parts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbs-linux", required=True, type=Path)
    ap.add_argument("--linux-site", required=True, type=Path)
    ap.add_argument("--dist", default="dist", type=Path)
    a = ap.parse_args()
    root = Path.cwd()
    dist = a.dist
    dist.mkdir(exist_ok=True)
    for old in dist.iterdir():
        if old.is_file():
            old.unlink()

    win = dist / "moneygraph-win-x64.zip"
    lin = dist / "moneygraph-linux-x64.tar.gz"
    mac = dist / "moneygraph-macos.tar.gz"
    build_win(root, win)
    build_linux(root, a.pbs_linux, a.linux_site, lin)
    build_mac(root, mac)

    sums = {p.name: sha256(p) for p in (win, lin, mac)}
    (dist / "SHA256SUMS").write_text("".join(f"{h}  {n}\n" for n, h in sums.items()), encoding="utf-8", newline="\n")

    joins_win, joins_lin = [], []
    for p in (win, lin, mac):
        if p.stat().st_size > SPLIT_OVER:
            parts = split(p)
            (joins_win if p.suffix == ".zip" else joins_lin).append((p.name, parts))
    bat = ["@echo off", "rem Склеивает части в целые архивы и печатает SHA256 (сверьте с SHA256SUMS)", 'cd /d "%~dp0"']
    for name, parts in joins_win + joins_lin:
        bat.append(f"if exist {parts[0]} copy /b {'+'.join(parts)} {name} >nul")
        bat.append(f"if exist {name} certutil -hashfile {name} SHA256")
    bat += ["type SHA256SUMS", "pause", ""]
    (dist / "join_win.bat").write_text("\r\n".join(bat), encoding="utf-8", newline="")
    sh = ["#!/usr/bin/env bash", 'cd "$(dirname "$0")"',
          "for f in moneygraph-linux-x64.tar.gz moneygraph-win-x64.zip; do",
          '  ls "$f".part* >/dev/null 2>&1 && cat "$f".part* > "$f"', "done",
          "sha256sum -c --ignore-missing SHA256SUMS 2>/dev/null || shasum -a 256 -c --ignore-missing SHA256SUMS", ""]
    (dist / "join_linux.sh").write_text("\n".join(sh), encoding="utf-8", newline="\n")

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    freeze = subprocess.run([sys.executable, "-m", "pip", "freeze", "--disable-pip-version-check"],
                            capture_output=True, text=True).stdout
    info = [f"commit: {commit}", f"built: {time.strftime('%Y-%m-%d %H:%M')}", f"builder: {sys.platform} {sys.version.split()[0]}",
            f"python-build-standalone: {a.pbs_linux.name}", "", "packages (Windows-сборка; Linux — те же версии):", freeze]
    (dist / "BUILD_INFO.txt").write_text("\n".join(info), encoding="utf-8", newline="\n")
    for n, h in sums.items():
        print(f"{h}  {n}  ({(dist / n).stat().st_size / 2**20:.1f} MB)")


if __name__ == "__main__":
    main()
