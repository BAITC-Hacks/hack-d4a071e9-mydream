import { createHash } from 'node:crypto';
import { askAssistant, AssistantError } from './openai-assistant.mjs';

const validGid = (value) => typeof value === 'string' && /^\d{15,19}$/.test(value);
const priority = (node) => Number.isFinite(node.priority_score) ? node.priority_score : 0;

export function validateAnalysisInput(payload) {
  if (!payload || !['overview', 'node'].includes(payload.mode)) {
    throw new AssistantError(400, 'Выберите обзор графа или аналитику конкретного GID.');
  }
  if (payload.mode === 'node' && !validGid(payload.gid)) {
    throw new AssistantError(400, 'GID для аналитики должен быть строкой из 15–19 цифр.');
  }
  if (payload.mode === 'overview' && payload.gid != null) {
    throw new AssistantError(400, 'Обзор топ-10 рассчитывается по всей сети без выбранного GID.');
  }
  return { mode: payload.mode, gid: payload.mode === 'node' ? payload.gid : null };
}

function analysisQuestion(mode, focusGids) {
  if (mode === 'node') {
    return `Подготовь человеческое резюме для аналитика по выбранному GID ${focusGids[0]}. ` +
      'Текст объёмом примерно 120–180 слов, 3–5 коротких абзацев: гипотеза роли и почему узел получил такой приоритет; ' +
      'наблюдаемые входящие и исходящие потоки с числами; на что обратить внимание; ограничения именно этого узла; следующие ручные проверки. ' +
      'Объясняй термины обычными словами, не используй названия внутренних полей. Не пересчитывай роль или приоритет. ' +
      'Не утверждай, что деньги окончательно осели на границе четвёртого колена, и не считай наблюдаемые суммы полным балансом. ' +
      'В references обязательно добавь выбранный GID и две короткие фразы: фактическое основание приоритета и что проверить дальше.';
  }
  const orderedIds = focusGids.map((gid, index) => `${index + 1}. ${gid}`).join('\n');
  return `Подготовь обзор приоритетов по всей наблюдаемой сети. Ниже рассчитанный конвейером топ-${focusGids.length} в обязательном порядке убывания приоритета:\n${orderedIds}\n` +
    'Не меняй порядок и оценки. В поле text дай общую картину примерно на 150–220 слов, 3–5 коротких абзацев: ' +
    'какие признаки объединяют приоритетные узлы, на что обратить внимание, какие проверки выполнить и какие ограничения мешают выводам. ' +
    'Не дублируй весь список GID в тексте: интерфейс отдельно покажет карточки по references. ' +
    'В references ОБЯЗАТЕЛЬНО добавь каждый GID из списка, в этом же порядке, без пропусков. ' +
    'Для каждого reason напиши две короткие человеческие фразы: почему именно этот узел в приоритете, с его конкретными числами, и что проверить следующим шагом. ' +
    'Различай число контрагентов, число операций и суммы. Используй только переданные признаки; не придумывай атрибуты клиентов. ' +
    'Все выводы — гипотезы для проверки. Не выдавай ограниченный контекст связей за всю сеть, а оценки — за вероятность виновности.';
}

// Only successful model responses are cached. A content version prevents reuse
// after a recalculation; pending requests share work without a second API call.
export function createGraphAnalysisService({ ask = askAssistant, now = () => new Date(), maxEntries = 50 } = {}) {
  const capacity = Math.max(1, Math.min(50, maxEntries));
  const cache = new Map();
  const pending = new Map();
  let currentVersion = null;

  async function analyze(payload, network, datasetVersion) {
    const { mode, gid } = validateAnalysisInput(payload);
    const nodes = (network?.nodes || []).filter(node => validGid(node?.gid));
    if (mode === 'node' && !nodes.some(node => node.gid === gid)) {
      throw new AssistantError(404, 'GID не найден в наблюдаемом графе.');
    }
    const focusGids = mode === 'node' ? [gid] : [...nodes]
      .sort((a, b) => priority(b) - priority(a) || a.gid.localeCompare(b.gid))
      .slice(0, 10).map(node => node.gid);
    if (!focusGids.length) throw new AssistantError(409, 'Сначала пересчитайте модель графа.');
    const version = datasetVersion ?? createHash('sha256').update(JSON.stringify(network)).digest('hex');
    if (version !== currentVersion) { cache.clear(); currentVersion = version; }
    const key = JSON.stringify([version, mode, gid]);
    if (cache.has(key)) {
      const value = cache.get(key);
      cache.delete(key);
      cache.set(key, value);
      return { ...value, cached: true };
    }
    if (pending.has(key)) return { ...await pending.get(key), cached: true };

    const operation = (async () => {
      const reply = await ask({ question: analysisQuestion(mode, focusGids), selectedId: gid }, network);
      const references = new Set((reply?.references || []).map(item => item.gid));
      if (!focusGids.every(id => references.has(id))) {
        throw new AssistantError(502, 'Модель не объяснила каждый выбранный узел. Повторите запрос аналитики.');
      }
      const result = { ...reply, mode, gid, focus_gids: focusGids, generated_at: now().toISOString(), cached: false };
      if (version === currentVersion) {
        cache.set(key, result);
        while (cache.size > capacity) cache.delete(cache.keys().next().value);
      }
      return result;
    })();
    pending.set(key, operation);
    try { return await operation; }
    finally { if (pending.get(key) === operation) pending.delete(key); }
  }

  return { analyze };
}
