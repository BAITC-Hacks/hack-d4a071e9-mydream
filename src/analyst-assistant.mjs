// Local question router: every answer is derived from the current graph.
const id = (value) => String(value ?? '');

export function answerQuestion(question, data, selectedId = null) {
  const nodes = new Map((data.nodes || []).map((node) => [id(node.gid), node]));
  const named = [...new Set((question.match(/\d{15,19}/g) || []).filter((gid) => nodes.has(gid)))];
  const sources = named.length ? named : selectedId && nodes.has(id(selectedId)) ? [id(selectedId)] : [];
  const prompt = question.toLocaleLowerCase('ru');

  if (/устойчив|изъят|удалени|распад/.test(prompt)) {
    const resilience = data.optional?.resilience;
    if (!resilience?.remove_top?.length) return { text: 'Оценка устойчивости ещё не рассчитана.', references: [] };
    const first = resilience.remove_top.find((item) => item.n === 5) || resilience.remove_top[0];
    return {
      text: `После удаления топ-${first.n} по приоритету: ${first.components} фрагментов, крупнейший содержит ${first.largest_component} узлов (${first.largest_share_pct}% оставшихся). Это структурный сценарий, а не прогноз движения денег.`,
      references: first.removed_gids.map((gid) => ({ gid, reason: 'Узел из сценария удаления' })),
    };
  }
  if (/цикл|возврат/.test(prompt) || /маршрут|цепочк/.test(prompt)) {
    const cycles = /цикл|возврат/.test(prompt);
    const matches = (cycles ? data.optional?.cycles : data.optional?.repeated_routes) || [];
    const visible = matches.filter((item) => !sources.length || sources.some((gid) => item.path.includes(gid))).slice(0, 3);
    if (!visible.length) return { text: `В наблюдаемом графе ${cycles ? 'циклов длиной 2–4' : 'повторяющихся маршрутов'} для указанного узла не найдено.`, references: [] };
    return {
      text: `${cycles ? 'Наблюдаемые возвратные контуры' : 'Маршруты с совпадением переводов минимум в два дня'}: ${visible.map((item) => item.path.join(' → ')).join('; ')}. Это гипотезы для проверки.`,
      references: [...new Set(visible.flatMap((item) => item.path))].map((gid) => ({ gid, reason: 'Узел указанного пути' })),
    };
  }

  if (!sources.length) return {
    text: 'Укажите один или несколько GID в вопросе либо выберите узел на графе. Например: «Кто собирает деньги с GID1 и GID2?»',
    references: [],
  };

  const outgoing = new Map();
  for (const edge of data.edges || []) {
    const source = id(edge.src);
    if (!outgoing.has(source)) outgoing.set(source, []);
    outgoing.get(source).push(id(edge.dst));
  }
  const candidates = new Map();
  for (const source of sources) {
    const reached = new Map();
    for (const first of outgoing.get(source) || []) {
      if (first !== source) reached.set(first, 1);
      for (const second of outgoing.get(first) || []) {
        if (second !== source && !reached.has(second)) reached.set(second, 2);
      }
    }
    for (const [target, hops] of reached) {
      if (sources.includes(target)) continue;
      const item = candidates.get(target) || { gid: target, sources: new Set(), minHops: hops };
      item.sources.add(source);
      item.minHops = Math.min(item.minHops, hops);
      candidates.set(target, item);
    }
  }
  const ranked = [...candidates.values()]
    .filter((item) => sources.length === 1 || item.sources.size >= 2)
    .sort((a, b) => b.sources.size - a.sources.size || a.minHops - b.minHops ||
      Number(nodes.get(b.gid)?.priority_score || 0) - Number(nodes.get(a.gid)?.priority_score || 0) || a.gid.localeCompare(b.gid))
    .slice(0, 5);
  if (!ranked.length) return { text: 'Общей точки получения в пределах двух направленных переходов не найдено. За пределами выгрузки связи неизвестны.', references: [] };
  return {
    text: `Кандидаты на общую точку получения от ${sources.length} исходных GID в пределах двух переходов. Для первого кандидата видны пути от ${ranked[0].sources.size} исходных узлов. Это гипотеза по наблюдаемым связям.`,
    references: ranked.map((item) => ({ gid: item.gid, reason: `${item.sources.size} исходных GID · ${item.minHops} ${item.minHops === 1 ? 'переход' : 'перехода'}` })),
  };
}
