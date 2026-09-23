"""Проверка site-packages, собранного для чужой платформы: все Requires-Dist,
активные на целевой ОС, установлены. pip --platform вычисляет маркеры по машине
сборки и молча пропускает зависимости вида `colorama; sys_platform == "win32"`.

    python tools/check_deps.py <site-packages> win|linux|mac
"""
import glob
import re
import sys

from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.utils import canonicalize_name as cn

ENVS = {
    "win":   dict(os_name="nt", sys_platform="win32", platform_system="Windows", platform_machine="AMD64"),
    "linux": dict(os_name="posix", sys_platform="linux", platform_system="Linux", platform_machine="x86_64"),
    "mac":   dict(os_name="posix", sys_platform="darwin", platform_system="Darwin", platform_machine="arm64"),
}

sp, target = sys.argv[1], sys.argv[2]
env = dict(ENVS[target], python_version="3.11", python_full_version="3.11.16",
           implementation_name="cpython", platform_python_implementation="CPython", extra="")
dists = {}
for d in glob.glob(sp + "/*.dist-info"):
    meta = open(d + "/METADATA", encoding="utf-8").read()
    dists[cn(re.search(r"^Name: (.+)$", meta, re.M).group(1).strip())] = \
        [l[15:] for l in meta.splitlines() if l.startswith("Requires-Dist: ")]
missing = sorted({f"{cn(q.name)} (нужен {n})" for n, reqs in dists.items() for q in map(Requirement, reqs)
                  if (q.marker is None or q.marker.evaluate(env)) and cn(q.name) not in dists})
if missing:
    sys.exit(f"[{target}] не хватает: " + ", ".join(missing))
print(f"[{target}] {len(dists)} пакетов, зависимости под целевую ОС полные")
