"""Проверка Windows-сборки: все Requires-Dist с маркерами Windows установлены.
pip --platform вычисляет маркеры по машине сборки (Linux) и молча пропускает
зависимости вида `colorama; sys_platform == "win32"`."""
import glob
import re
import sys

from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.utils import canonicalize_name as cn

sp = sys.argv[1]
env = dict(os_name="nt", sys_platform="win32", platform_system="Windows", platform_machine="AMD64",
           python_version="3.11", python_full_version="3.11.11", implementation_name="cpython",
           platform_python_implementation="CPython", extra="")
dists = {}
for d in glob.glob(sp + "/*.dist-info"):
    meta = open(d + "/METADATA", encoding="utf-8").read()
    dists[cn(re.search(r"^Name: (.+)$", meta, re.M).group(1).strip())] = \
        [l[15:] for l in meta.splitlines() if l.startswith("Requires-Dist: ")]
missing = sorted({f"{cn(q.name)} (нужен {n})" for n, reqs in dists.items() for q in map(Requirement, reqs)
                  if (q.marker is None or q.marker.evaluate(env)) and cn(q.name) not in dists})
if missing:
    sys.exit("Windows-сборке не хватает: " + ", ".join(missing))
print(f"[win] {len(dists)} пакетов, зависимости под Windows полные")
