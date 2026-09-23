"""Ассистент аналитика (DESIGN.md §3.8): вопрос → gid из текста → факты из output/ и edges → ответ.
Факты и кандидаты считаются здесь детерминированно; LLM (OpenAI) только формулирует ответ из них
и роли не присваивает. Без ключа или без сети — шаблонный ответ по тем же фактам."""
import os
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

from . import config as C
from .explain import ROLE_RU
from .extras import _plural

GID_RE = re.compile(r"\b\d{15,20}\b")
KEY_FILE = "openai_key.txt"          # ключ OpenAI для демо жюри; приоритет у переменной OPENAI_API_KEY

SYSTEM_PROMPT = (
    "Ты помощник аналитика AML. Отвечай по-русски, кратко, 5–10 строк. Используй ТОЛЬКО факты из "
    "сообщения пользователя, ничего не додумывай. Каждое утверждение подкрепляй gid и числами из фактов. "
    "Роли узлов уже присвоены правилами — не меняй и не оспаривай их. Формулируй как гипотезы для проверки "
    "(«признаки консолидации», «стоит проверить»), не как утверждения о виновности. "
    "Если фактов недостаточно, так и скажи."
)


def _load(out_dir: Path, data_dir: Path):
    f = pd.read_parquet(out_dir / "features.parquet").set_index("gid", drop=False)
    e = pd.read_parquet(data_dir / "edges.parquet")
    return f, e


def parse_gids(question: str, known) -> list:
    seen, out = set(), []
    for g in GID_RE.findall(question):
        g = int(g)
        if g in known and g not in seen:
            seen.add(g)
            out.append(g)
    return out


def _walk(adj: dict, starts: list, hops: int) -> dict:
    """node -> {start: колено}, до hops шагов по adj (без самих стартов)."""
    hit = defaultdict(dict)
    for s in starts:
        frontier, seen = {s}, {s}
        for h in range(1, hops + 1):
            nxt = set()
            for n in frontier:
                nxt |= set(adj.get(n, ())) - seen
            for n in nxt:
                hit[n].setdefault(s, h)
            seen |= nxt
            frontier = nxt
    return hit


def facts(question: str, out_dir: Path = Path("output"), data_dir: Path = Path("data")) -> dict:
    f, e = _load(out_dir, data_dir)
    gids = parse_gids(question, f.index)
    res = {"question": question, "gids": gids, "nodes": [], "collectors": [], "payers": []}
    if not gids:
        return res
    for g in gids:
        r = f.loc[g]
        res["nodes"].append({"gid": g, "role": r.role, "priority": float(r.priority_score),
                             "cluster": int(r.cluster_id), "seed": bool(r.is_seed), "evidence": r.evidence})
    succ, pred = defaultdict(list), defaultdict(list)
    for s, d in zip(e.src, e.dst):
        succ[s].append(d)
        pred[d].append(s)
    direct_in = e[e.src.isin(gids)].groupby("dst").sum_kzt.sum()
    direct_out = e[e.dst.isin(gids)].groupby("src").sum_kzt.sum()

    def rank(hit: dict, direct: pd.Series, key: str):
        rows = []
        for n, by in hit.items():
            if n in gids or len(by) < 2:            # общий — значит, связан хотя бы с двумя из заданных
                continue
            r = f.loc[n]
            rows.append({"gid": int(n), "n_linked": len(by), "linked": sorted(int(x) for x in by),
                         "max_hops": max(by.values()), key: float(direct.get(n, 0.0)), "role": r.role, "seed": bool(r.is_seed),
                         "priority": float(r.priority_score), "evidence": r.evidence})
        rows.sort(key=lambda x: (-x["n_linked"], x["max_hops"], -x[key], -x["priority"], x["gid"]))
        return rows[: C.ASSISTANT_TOP]

    res["collectors"] = rank(_walk(succ, gids, C.ASSISTANT_MAX_HOPS), direct_in, "direct_kzt_from_them")
    res["payers"] = rank(_walk(pred, gids, C.ASSISTANT_MAX_HOPS), direct_out, "direct_kzt_to_them")
    return res


def facts_text(fx: dict) -> str:
    if not fx["gids"]:
        return "В вопросе нет известных gid (нужны 15–20-значные номера из выборки)."
    lines = [f"Заданные узлы ({len(fx['gids'])}):"]
    for n in fx["nodes"]:
        lines.append(f"- {n['gid']}: {ROLE_RU[n['role']]}{', seed' if n['seed'] else ''}, "
                     f"приоритет {n['priority']:.2f}, кластер {n['cluster']}; {n['evidence']}")
    for key, title, amt in (("collectors", "Общие получатели (куда уходят деньги от ≥2 заданных)", "direct_kzt_from_them"),
                            ("payers", "Общие плательщики (кто платит ≥2 заданным)", "direct_kzt_to_them")):
        lines.append(f"{title}, до {C.ASSISTANT_MAX_HOPS} колен:")
        if not fx[key]:
            lines.append("- не найдено")
        for c in fx[key]:
            lines.append(f"- {c['gid']}: {ROLE_RU[c['role']]}{', сам seed' if c['seed'] else ''}, связан с "
                         f"{c['n_linked']} из {len(fx['gids'])} ({', '.join(str(x)[-6:] for x in c['linked'])}), "
                         f"{'напрямую' if c['max_hops'] == 1 else 'через ' + _plural(c['max_hops'], 'колено', 'колена', 'колен')}, "
                         f"прямые переводы {c[amt]:,.0f} KZT, приоритет {c['priority']:.2f}; {c['evidence']}")
    return "\n".join(lines)


def fallback_answer(fx: dict) -> str:
    if not fx["gids"]:
        return facts_text(fx)
    head = []
    if fx["collectors"]:
        c = fx["collectors"][0]
        head.append(f"Главный кандидат на сбор денег: {c['gid']} ({ROLE_RU[c['role']]}{', сам seed' if c['seed'] else ''}) — получает от "
                    f"{c['n_linked']} из {len(fx['gids'])} заданных узлов, напрямую "
                    f"{c['direct_kzt_from_them']:,.0f} KZT.")
    else:
        head.append("Общего получателя у заданных узлов в пределах "
                    f"{C.ASSISTANT_MAX_HOPS} колен не найдено.")
    return "\n".join(head + ["", facts_text(fx), "", "Это гипотеза для проверки аналитиком, не утверждение."])


def api_key():
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    for base in (Path.cwd(), Path(__file__).resolve().parents[1]):
        p = base / KEY_FILE
        if p.exists():
            return p.read_text(encoding="utf-8").strip() or None
    return None


def answer(question: str, out_dir: Path = Path("output"), data_dir: Path = Path("data")):
    """(текст ответа, источник: 'openai:<model>' | 'rules' | 'rules (ошибка LLM: ...)', факты)."""
    fx = facts(question, out_dir, data_dir)
    key = api_key()
    if not fx["gids"] or not key:
        return fallback_answer(fx), "rules", fx
    model = os.environ.get("OPENAI_MODEL", C.ASSISTANT_MODEL)
    try:
        from openai import OpenAI, OpenAIError
    except ImportError:
        return fallback_answer(fx), "rules (пакет openai не установлен)", fx
    try:
        client = OpenAI(api_key=key, timeout=C.ASSISTANT_TIMEOUT_S, max_retries=0)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": f"Вопрос аналитика: {question}\n\nФакты:\n{facts_text(fx)}"}],
        )
        text = (resp.choices[0].message.content or "").strip()
        if not text:
            return fallback_answer(fx), "rules (пустой ответ LLM)", fx
        return text, f"openai:{model}", fx
    except OpenAIError as err:
        return fallback_answer(fx), f"rules (ошибка LLM: {type(err).__name__})", fx
