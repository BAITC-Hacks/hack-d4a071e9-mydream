const ROLE = {
  consolidator: { label: 'Признаки консолидации', short: 'Сбор', color: '#72d5c7' },
  transit: { label: 'Признаки транзита', short: 'Транзит', color: '#75aaf1' },
  distributor: { label: 'Признаки распределения', short: 'Раздача', color: '#e7a36c' },
  terminal: { label: 'Возможный конечный получатель', short: 'Конечный', color: '#bb9ef3' },
  coordinator: { label: 'Признаки координации', short: 'Координация', color: '#f3d37b' },
  peripheral: { label: 'Периферия выборки', short: 'Периферия', color: '#78909e' },
};
const formatInteger = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });
const formatOne = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });
const $ = (id) => document.getElementById(id);
const state = { data: null, byId: new Map(), incoming: new Map(), outgoing: new Map(), selectedId: null, clusterId: null, view: 'overview', positions: [], busy: false };

function gid(value) { return String(value ?? '').trim(); }
function finite(value) { const number = Number(value); return Number.isFinite(number) ? number : 0; }
function fmt(value) { return formatInteger.format(finite(value)); }
function countWord(value, one, few, many) {
  const number = Math.abs(Math.trunc(finite(value)));
  const lastTwo = number % 100;
  if (lastTwo >= 11 && lastTwo <= 14) return many;
  const last = number % 10;
  return last === 1 ? one : last >= 2 && last <= 4 ? few : many;
}
function kzt(value) { return `${fmt(value)} ₸`; }
function percent(value) { return `${formatOne.format(finite(value) * 100)}%`; }
function roleOf(value) { return ROLE[value] || { label: 'Роль для проверки', short: String(value || '—'), color: '#91a2b1' }; }
function hash(value) { let h = 2166136261; for (const char of String(value)) h = Math.imul(h ^ char.charCodeAt(0), 16777619); return (h >>> 0) / 4294967295; }
function element(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = String(text); return node; }

function verificationPlan(node) {
  const items = [];
  if (node.is_seed) items.push({ key: 'seedIncoming', title: 'Источники денег исходного клиента', required: 'Полная входящая история до начала выборки и основания связи клиента с исходным эпизодом.', purpose: 'Установить источник поступлений, который исходящий обход не показывает.' });
  if (finite(node.depth) >= 4) items.push({ key: 'depthFourOutgoing', title: 'Продолжение цепочки за четвёртым коленом', required: 'Исходящие переводы после границы текущей выгрузки.', purpose: 'Проверить движение денег за пределами наблюдаемого графа.' });
  items.push(
    { key: 'fullFlow', title: 'Полный контур переводов', required: 'Операции по связанным счетам, переводы ниже порога 5 000 ₸ и доступные межбанковские сведения.', purpose: 'Найти пропущенные связи, точки сбора и дальнейших получателей.' },
    { key: 'timing', title: 'Время и назначение операций', required: 'Точное время переводов, остатки до и после операций, назначения платежей и снятие наличных.', purpose: 'Проверить последовательность и экономический смысл движения средств.' },
    { key: 'identity', title: 'Контроль над счетами', required: 'KYC, связанные счета, доверенные лица и сведения о бенефициарах.', purpose: 'Проверить, кто фактически распоряжается счетами и средствами.' },
    { key: 'caseContext', title: 'Материалы проверки', required: 'Оперативные основания для исходных клиентов и подтверждённые результаты прошлых проверок.', purpose: 'Сопоставить сетевые признаки с независимыми сведениями по делу.' },
  );
  return items;
}

function renderVerificationPlan(node) {
  const list = $('verificationItems'); list.replaceChildren();
  $('verificationGid').textContent = node ? `GID ${gid(node.gid)}` : 'Выберите gid';
  $('verificationObserved').textContent = node
    ? `Уже есть: колено ${node.depth ?? '—'}, ${fmt(node.in_deg)} входящих и ${fmt(node.out_deg)} исходящих связей, роль по расчёту — ${roleOf(node.role).short.toLowerCase()}.`
    : 'Выберите узел на карте или в очереди проверки.';
  if (!node) return;
  for (const item of verificationPlan(node)) {
    const card = element('article', 'verification-item');
    card.append(element('h3', '', item.title), element('p', '', item.required), element('small', '', `Зачем: ${item.purpose}`));
    list.append(card);
  }
}

const FACTOR_LABELS = [
  ['role', 'Признаки роли'], ['anomaly', 'Необычность'], ['volume', 'Оборот'],
  ['degree', 'Число связей'], ['bridge', 'Посредничество'], ['activity', 'Активность'],
];

function renderPriorityFactors(node) {
  const section = element('section', 'detail-section priority-breakdown');
  section.append(element('h3', '', 'РАСЧЁТ ПРИОРИТЕТА'));
  const factors = node.priority_factors;
  if (!factors) {
    section.append(element('p', '', 'Пересчитайте модель, чтобы увидеть вклад каждого фактора.'));
    return section;
  }
  section.append(element('p', 'factor-intro', 'Вклад каждого признака в итоговый индекс, в процентных пунктах.'));
  for (const [key, label] of FACTOR_LABELS) {
    const row = element('div', 'factor-row');
    row.append(element('span', '', label), element('strong', '', `+${formatOne.format(finite(factors[key]))} п.п.`));
    section.append(row);
  }
  const reasons = [];
  if (node.is_seed) reasons.push('неполный вход у исходного клиента');
  if (node.truncated_by_depth) reasons.push('граница 4-го колена');
  if (finite(node.in_tx) + finite(node.out_tx) <= 1) reasons.push('мало транзакций');
  if (finite(node.in_deg) + finite(node.out_deg) === 0) reasons.push('нет наблюдаемых связей');
  const penalty = element('div', 'factor-row factor-penalty');
  penalty.append(element('span', '', `Неполнота данных${reasons.length ? ' · ' + reasons.join(', ') : ''}`), element('strong', '', `−${formatOne.format(finite(factors.data_quality_penalty))} п.п.`));
  section.append(penalty);
  const total = element('div', 'factor-row factor-total');
  total.append(element('span', '', 'Итоговый приоритет'), element('strong', '', percent(node.priority_score)));
  section.append(total);
  return section;
}

function setNotice(message = '', tone = '') { $('notice').textContent = message; $('notice').className = `notice ${tone}`.trim(); }
function setLoading(message, isError = false) {
  const pane = $('initialState'); pane.hidden = false; pane.classList.toggle('error', isError);
  pane.querySelector('h2').textContent = isError ? 'Не удалось открыть сеть' : 'Загружаем сеть';
  pane.querySelector('p').textContent = message;
}
function setBusy(busy) { state.busy = busy; $('rebuildButton').disabled = busy; $('rebuildButton').firstChild.textContent = busy ? 'Пересчёт модели… ' : 'Пересчитать модель '; }

async function request(path, method = 'GET') {
  const response = await fetch(path, { method, cache: 'no-store' });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `Ошибка HTTP ${response.status}`);
  return payload;
}

function buildIndex(data) {
  const byId = new Map(), incoming = new Map(), outgoing = new Map();
  for (const node of data.nodes || []) { byId.set(gid(node.gid), node); incoming.set(gid(node.gid), []); outgoing.set(gid(node.gid), []); }
  for (const edge of data.edges || []) {
    const source = gid(edge.src), target = gid(edge.dst);
    if (outgoing.has(source)) outgoing.get(source).push(edge);
    if (incoming.has(target)) incoming.get(target).push(edge);
  }
  for (const links of incoming.values()) links.sort((a, b) => finite(b.sum_kzt) - finite(a.sum_kzt));
  for (const links of outgoing.values()) links.sort((a, b) => finite(b.sum_kzt) - finite(a.sum_kzt));
  return { byId, incoming, outgoing };
}

function mountData(payload, preserveSelection = false) {
  if (!Array.isArray(payload.nodes) || !Array.isArray(payload.edges) || !Array.isArray(payload.clusters) || !Array.isArray(payload.top)) {
    throw new Error('Ответ API не содержит полный набор узлов, связей, кластеров и приоритетов.');
  }
  const previous = preserveSelection ? state.selectedId : null;
  state.data = payload;
  Object.assign(state, buildIndex(payload));
  state.selectedId = previous && state.byId.has(previous) ? previous : null;
  state.clusterId = null;
  state.view = 'overview';
  $('dashboard').hidden = false;
  $('initialState').hidden = true;
  $('nodesMetric').textContent = fmt(payload.nodes.length);
  $('edgesMetric').textContent = fmt(payload.edges.length);
  $('seedsMetric').textContent = fmt(payload.nodes.filter((node) => node.is_seed).length);
  $('clustersMetric').textContent = fmt(payload.clusters.length);
  $('runMeta').textContent = `${fmt(payload.nodes.length)} узлов · ${fmt(payload.edges.length)} связей`;
  $('graphEmpty').hidden = payload.nodes.length > 0;
  $('graphStage').hidden = payload.nodes.length === 0;
  renderTop(); renderClusters(); renderDetail(); updateViewControls(); drawGraph();
  if (!state.selectedId && payload.top.length && state.byId.has(gid(payload.top[0].gid))) selectNode(payload.top[0].gid, false);
}

function selectNode(value, switchToEgo = true) {
  const id = gid(value);
  if (!state.byId.has(id)) { setNotice(`GID ${id || '—'} не найден в текущей выгрузке.`, 'error'); return false; }
  state.selectedId = id;
  if (switchToEgo) { state.view = 'ego'; state.clusterId = null; }
  $('gidSearch').value = id;
  $('searchSuggestions').hidden = true;
  setNotice('');
  renderDetail(); renderTop(); renderClusters(); updateViewControls(); drawGraph();
  return true;
}

function updateViewControls() {
  const ego = state.view === 'ego';
  $('egoButton').classList.toggle('active', ego); $('egoButton').setAttribute('aria-pressed', String(ego));
  $('overviewButton').classList.toggle('active', !ego); $('overviewButton').setAttribute('aria-pressed', String(!ego));
  $('egoButton').disabled = !state.selectedId;
  $('clearFocusButton').hidden = !state.selectedId && state.clusterId === null;
  const selected = state.byId.get(state.selectedId);
  $('graphCaption').textContent = ego && selected ? `Прямые входящие и исходящие связи gid ${state.selectedId}. Стрелки показывают движение денег.` : state.clusterId !== null ? `Кластер ${state.clusterId}: связи внутри группы.` : 'Все узлы и направленные связи в выборке.';
}

function renderTop() {
  const rows = state.data.top || [];
  $('topCount').textContent = `${fmt(rows.length)} ${countWord(rows.length, "узел", "узла", "узлов")}`;
  const body = $('topBody'); body.replaceChildren();
  if (!rows.length) { const row = element('tr'); const cell = element('td', 'empty-list', 'Приоритетный список пуст.'); cell.colSpan = 5; row.append(cell); body.append(row); return; }
  for (const item of rows) {
    const row = element('tr'); row.dataset.gid = gid(item.gid); row.tabIndex = 0;
    if (row.dataset.gid === state.selectedId) row.classList.add('selected');
    const role = roleOf(item.role);
    const cells = [String(item.rank ?? '—'), gid(item.gid), role.label, percent(item.priority_score), item.why || 'Основание не указано'];
    cells.forEach((value, index) => { const cell = element('td', index === 1 ? 'gid-cell' : index === 3 ? 'priority-cell' : index === 4 ? 'why-cell' : '', value); if (index === 2) cell.style.color = role.color; row.append(cell); });
    row.addEventListener('click', () => selectNode(item.gid));
    row.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectNode(item.gid); } });
    body.append(row);
  }
}

function topGids(value) {
  if (Array.isArray(value)) return value.map(gid).join(', ');
  return String(value ?? '').replace(/[\[\]"']/g, '');
}
function renderClusters() {
  const list = $('clusterList'); list.replaceChildren();
  const clusters = [...(state.data.clusters || [])].sort((a, b) => finite(b.n_nodes) - finite(a.n_nodes));
  $('clusterCount').textContent = `${fmt(clusters.length)} групп`;
  if (!clusters.length) { list.append(element('p', 'empty-list', 'Кластеры не найдены.')); return; }
  for (const cluster of clusters) {
    const card = element('button', 'cluster-card'); card.type = 'button';
    if (state.clusterId !== null && gid(cluster.cluster_id) === gid(state.clusterId)) card.classList.add('selected');
    const line = element('div', 'cluster-line'); line.append(element('strong', '', `Кластер ${cluster.cluster_id}`), element('span', '', `${fmt(cluster.n_nodes)} ${countWord(cluster.n_nodes, "узел", "узла", "узлов")}`));
    card.append(line, element('p', '', cluster.hypothesis || 'Гипотеза ещё не сформулирована.'), element('small', '', `${fmt(cluster.n_seed)} ${countWord(cluster.n_seed, "исходный", "исходных", "исходных")} · внутренний оборот ${kzt(cluster.sum_kzt_internal)}`));
    const top = topGids(cluster.top_gids); if (top) card.append(element('small', 'cluster-top', ` · Ключевые gid: ${top}`));
    card.addEventListener('click', () => { state.clusterId = cluster.cluster_id; state.view = 'overview'; updateViewControls(); renderClusters(); drawGraph(); $('graphStage').scrollIntoView({ behavior: 'smooth', block: 'nearest' }); });
    list.append(card);
  }
}

function scoreBox(label, value, accent = false) { const box = element('div', 'score-box'); box.append(element('span', '', label), element('strong', accent ? 'accent' : '', value)); return box; }
function flowBox(label, count, amount) { const box = element('div', 'flow-box'); box.append(element('span', '', label), element('strong', '', `${fmt(count)} ${countWord(count, "связь", "связи", "связей")}`), element('small', '', kzt(amount))); return box; }
function connectionList(title, edges, side) {
  const group = element('div', 'connection-group'); group.append(element('h4', '', `${title} · ${fmt(edges.length)}`));
  const list = element('div', 'connection-list');
  if (!edges.length) list.append(element('div', 'empty-connections', 'Связей в выборке нет.'));
  for (const edge of edges) {
    const otherId = side === 'incoming' ? gid(edge.src) : gid(edge.dst);
    const row = element('button', 'connection-row'); row.type = 'button';
    row.append(element('span', '', `${side === 'incoming' ? '←' : '→'} ${otherId}`), element('small', '', `${kzt(edge.sum_kzt)} · ${fmt(edge.n_tx)} транз.`));
    row.addEventListener('click', () => selectNode(otherId)); list.append(row);
  }
  group.append(list); return group;
}
function renderDetail() {
  const target = $('detailContent'); target.replaceChildren();
  const node = state.byId.get(state.selectedId);
  renderVerificationPlan(node);
  if (!node) { $('detailIndex').textContent = '—'; target.append(element('div', 'detail-placeholder', 'Выберите узел на карте, в топ-листе или найдите его по gid.')); return; }
  const incoming = state.incoming.get(state.selectedId) || [], outgoing = state.outgoing.get(state.selectedId) || [];
  const role = roleOf(node.role), body = element('div', 'detail-body'), idRow = element('div', 'detail-id');
  const heading = element('div'); heading.append(element('small', '', 'GID / ОБЕЗЛИЧЕННЫЙ КЛИЕНТ'), element('h2', 'detail-title', state.selectedId)); heading.lastChild.id = 'detailTitle';
  idRow.append(heading); if (node.is_seed) idRow.append(element('span', 'seed-tag', 'ИСХОДНЫЙ'));
  const roleChip = element('span', 'role-chip', role.label); roleChip.style.color = role.color;
  const scores = element('div', 'detail-score'); scores.append(scoreBox('Приоритет проверки', percent(node.priority_score), true), scoreBox('Сила признаков роли', percent(node.role_score)));
  const evidence = element('section', 'detail-section'); evidence.append(element('h3', '', 'ОСНОВАНИЕ ГИПОТЕЗЫ'), element('p', '', node.evidence || 'Обоснование отсутствует в результатах расчёта.'));
  const flow = element('section', 'detail-section'); flow.append(element('h3', '', 'ПОТОКИ В НАБЛЮДАЕМОЙ СЕТИ'));
  const flowGrid = element('div', 'flow-grid'); flowGrid.append(flowBox('Входящие', incoming.length, node.in_kzt ?? incoming.reduce((sum, edge) => sum + finite(edge.sum_kzt), 0)), flowBox('Исходящие', outgoing.length, node.out_kzt ?? outgoing.reduce((sum, edge) => sum + finite(edge.sum_kzt), 0))); flow.append(flowGrid);
  flow.append(connectionList('Отправители', incoming, 'incoming'), connectionList('Получатели', outgoing, 'outgoing'));
  if (finite(node.depth) >= 4 && !outgoing.length) flow.append(element('div', 'depth-warning', 'Узел на 4-м колене: отсутствие исходящих связей может быть следствием границы выгрузки, а не удержания средств.'));
  body.append(idRow, roleChip, scores, renderPriorityFactors(node), evidence, flow);
  const context = element('section', 'detail-section'); context.append(element('h3', '', 'ПОЛОЖЕНИЕ В ГРАФЕ'), element('p', '', `Кластер ${node.cluster_id ?? '—'} · колено ${node.depth ?? '—'} · ${node.is_seed ? 'исходный клиент' : 'узел расширения'}.`)); body.append(context);
  target.append(body); $('detailIndex').textContent = `КЛАСТЕР ${node.cluster_id ?? '—'}`;
}

function graphNodes() {
  if (!state.data) return [];
  if (state.view === 'ego' && state.selectedId) {
    const ids = new Set([state.selectedId]);
    for (const edge of state.incoming.get(state.selectedId) || []) ids.add(gid(edge.src));
    for (const edge of state.outgoing.get(state.selectedId) || []) ids.add(gid(edge.dst));
    return [...ids].map((id) => state.byId.get(id)).filter(Boolean);
  }
  if (state.clusterId !== null) return state.data.nodes.filter((node) => gid(node.cluster_id) === gid(state.clusterId));
  return state.data.nodes;
}
function graphEdges(nodes) {
  if (state.view === 'ego' && state.selectedId) return [...(state.incoming.get(state.selectedId) || []), ...(state.outgoing.get(state.selectedId) || [])].filter((edge, index, array) => array.indexOf(edge) === index);
  const ids = new Set(nodes.map((node) => gid(node.gid)));
  return state.data.edges.filter((edge) => ids.has(gid(edge.src)) && ids.has(gid(edge.dst)));
}
function overviewPositions(nodes, width, height) {
  const clusterIds = [...new Set(nodes.map((node) => gid(node.cluster_id)))].sort((a, b) => finite(a) - finite(b));
  const lane = (height - 80) / Math.max(1, clusterIds.length);
  return nodes.map((node) => {
    const depth = Math.max(0, Math.min(4, finite(node.depth)));
    const clusterIndex = Math.max(0, clusterIds.indexOf(gid(node.cluster_id)));
    const x = 55 + depth * (width - 110) / 4 + (hash(`${node.gid}-x`) - .5) * Math.min(80, (width - 100) / 9);
    const y = 40 + (clusterIndex + .5) * lane + (hash(`${node.gid}-y`) - .5) * lane * .8;
    return { id: gid(node.gid), node, x, y };
  });
}
function columnPositions(nodes, side, width, height) {
  const maxRows = 19, columns = Math.max(1, Math.ceil(nodes.length / maxRows));
  const sideWidth = width * .43 - 30;
  const positions = [];
  nodes.forEach((node, index) => {
    const column = Math.floor(index / maxRows), row = index % maxRows;
    const inColumn = Math.min(maxRows, nodes.length - column * maxRows);
    const fromCenter = 90 + (column + .5) * Math.max(25, sideWidth - 90) / columns;
    positions.push({ id: gid(node.gid), node, x: width / 2 + (side === 'left' ? -fromCenter : fromCenter), y: 35 + (row + .5) * (height - 70) / inColumn, side });
  });
  return positions;
}
function egoPositions(width, height) {
  const incoming = [...new Set((state.incoming.get(state.selectedId) || []).map((edge) => gid(edge.src)))].filter((id) => id !== state.selectedId).map((id) => state.byId.get(id)).filter(Boolean);
  const outgoing = [...new Set((state.outgoing.get(state.selectedId) || []).map((edge) => gid(edge.dst)))].filter((id) => id !== state.selectedId).map((id) => state.byId.get(id)).filter(Boolean);
  return [...columnPositions(incoming, 'left', width, height), { id: state.selectedId, node: state.byId.get(state.selectedId), x: width / 2, y: height / 2, side: 'center' }, ...columnPositions(outgoing, 'right', width, height)];
}

function drawArrow(ctx, source, target, color, lineWidth, alpha, radius = 3) {
  const dx = target.x - source.x, dy = target.y - source.y, distance = Math.hypot(dx, dy);
  if (distance < 1) return;
  const ux = dx / distance, uy = dy / distance;
  const ex = target.x - ux * radius, ey = target.y - uy * radius;
  ctx.globalAlpha = alpha; ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = lineWidth;
  ctx.beginPath(); ctx.moveTo(source.x + ux * radius, source.y + uy * radius); ctx.lineTo(ex, ey); ctx.stroke();
  const head = Math.max(3, Math.min(7, radius * 1.8));
  ctx.beginPath(); ctx.moveTo(ex, ey); ctx.lineTo(ex - ux * head - uy * head * .45, ey - uy * head + ux * head * .45); ctx.lineTo(ex - ux * head + uy * head * .45, ey - uy * head - ux * head * .45); ctx.closePath(); ctx.fill();
}
function drawGraph() {
  if (!state.data || $('graphStage').hidden) return;
  const canvas = $('graphCanvas'), rect = canvas.getBoundingClientRect(), width = rect.width, height = rect.height;
  if (!width || !height) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2); canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
  const ctx = canvas.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, width, height);
  const nodes = graphNodes(), edges = graphEdges(nodes);
  const positions = state.view === 'ego' && state.selectedId ? egoPositions(width, height) : overviewPositions(nodes, width, height);
  state.positions = positions;
  const selected = state.selectedId, ego = state.view === 'ego';
  const location = new Map(); for (const point of positions) { if (!location.has(point.id) || point.side === 'center') location.set(point.id, point); }
  for (const edge of edges) {
    const sourceId = gid(edge.src), targetId = gid(edge.dst);
    const source = ego && sourceId === selected ? location.get(selected) : ego ? positions.find((point) => point.id === sourceId && point.side === 'left') || location.get(sourceId) : location.get(sourceId);
    const target = ego && targetId === selected ? location.get(selected) : ego ? positions.find((point) => point.id === targetId && point.side === 'right') || location.get(targetId) : location.get(targetId);
    if (!source || !target) continue;
    const emphasized = sourceId === selected || targetId === selected;
    drawArrow(ctx, source, target, emphasized ? '#bdf3d0' : '#6b94a3', emphasized ? 1.35 : .65, ego ? .5 : emphasized ? .45 : .12, ego ? 5 : 2);
  }
  ctx.globalAlpha = 1;
  const topIds = new Set((state.data.top || []).slice(0, 20).map((item) => gid(item.gid)));
  for (const point of positions) {
    const active = point.id === selected, radius = active ? 7 : ego ? 4.4 : topIds.has(point.id) ? 3.7 : 2.3;
    ctx.beginPath(); ctx.arc(point.x, point.y, radius, 0, Math.PI * 2); ctx.fillStyle = roleOf(point.node.role).color; ctx.globalAlpha = ego || active || topIds.has(point.id) ? 1 : .68; ctx.fill();
    if (active) { ctx.globalAlpha = .45; ctx.strokeStyle = '#d6ffe0'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(point.x, point.y, radius + 6, 0, Math.PI * 2); ctx.stroke(); }
  }
  ctx.globalAlpha = 1;
  if (ego && selected) { const point = location.get(selected); if (point) { ctx.textAlign = 'center'; ctx.fillStyle = '#e9fff1'; ctx.font = '700 12px system-ui'; ctx.fillText(selected, point.x, point.y - 20); } }
  $('graphScale').textContent = ego ? `${fmt(nodes.length)} ${countWord(nodes.length, "узел", "узла", "узлов")} · ${fmt(edges.length)} ${countWord(edges.length, "направленная связь", "направленные связи", "направленных связей")} вокруг gid ${selected}` : state.clusterId !== null ? `${fmt(nodes.length)} ${countWord(nodes.length, "узел", "узла", "узлов")} · ${fmt(edges.length)} внутренних связей в кластере ${state.clusterId}` : `${fmt(nodes.length)} ${countWord(nodes.length, "узел", "узла", "узлов")} · ${fmt(edges.length)} ${countWord(edges.length, "направленная связь", "направленные связи", "направленных связей")} · слева направо: колено 0–4`;
}

function pointAt(event) {
  const rect = $('graphCanvas').getBoundingClientRect(), x = event.clientX - rect.left, y = event.clientY - rect.top;
  let nearest = null, distance = 12;
  for (const point of state.positions) { const d = Math.hypot(point.x - x, point.y - y); if (d < distance) { nearest = point; distance = d; } }
  return { point: nearest, x, y };
}
function showTooltip(event) {
  const { point, x, y } = pointAt(event), tooltip = $('graphTooltip');
  $('graphCanvas').style.cursor = point ? 'pointer' : 'crosshair';
  if (!point) { tooltip.hidden = true; return; }
  tooltip.textContent = `GID ${point.id} · ${roleOf(point.node.role).short} · приоритет ${percent(point.node.priority_score)}`;
  tooltip.style.left = `${Math.min(x + 13, $('graphStage').clientWidth - 228)}px`;
  tooltip.style.top = `${Math.max(8, y - 36)}px`; tooltip.hidden = false;
}

function showSuggestions() {
  const query = gid($('gidSearch').value), box = $('searchSuggestions'); box.replaceChildren();
  if (!query || !state.data) { box.hidden = true; return; }
  const matches = state.data.nodes.filter((node) => gid(node.gid).includes(query)).slice(0, 8);
  if (!matches.length) { box.hidden = true; return; }
  for (const node of matches) {
    const button = element('button', 'suggestion'); button.type = 'button';
    button.append(element('span', '', gid(node.gid)), element('small', '', roleOf(node.role).short));
    button.addEventListener('click', () => selectNode(node.gid)); box.append(button);
  }
  box.hidden = false;
}
function search() {
  const query = gid($('gidSearch').value);
  if (state.byId.has(query)) { selectNode(query); return; }
  const match = state.data?.nodes.find((node) => gid(node.gid).includes(query));
  if (query && match) selectNode(match.gid);
  else setNotice(query ? `GID ${query} не найден в текущей выгрузке.` : 'Введите gid для поиска.', 'error');
}
async function loadNetwork(rebuild = false) {
  if (state.busy) return;
  setBusy(true);
  if (!state.data) setLoading(rebuild ? 'Пересчитываем локальную модель…' : 'Читаем результаты локального пакетного анализа…');
  else setNotice(rebuild ? 'Пересчитываем модель из исходных данных…' : 'Обновляем результаты…');
  try {
    const payload = await request(rebuild ? '/api/rebuild' : '/api/network', rebuild ? 'POST' : 'GET');
    mountData(payload, rebuild);
    setNotice(rebuild ? 'Модель пересчитана. Результаты и CSV-выгрузки обновлены.' : 'Сеть загружена. Выберите узел или введите gid.', 'success');
  } catch (error) {
    if (!state.data) setLoading(`${error.message} Используйте «Пересчитать модель» для повторной попытки.`, true);
    setNotice(error.message, 'error');
  } finally { setBusy(false); }
}

function start() {
  $('rebuildButton').addEventListener('click', () => loadNetwork(true));
  $('searchButton').addEventListener('click', search);
  $('gidSearch').addEventListener('input', showSuggestions);
  $('gidSearch').addEventListener('keydown', (event) => { if (event.key === 'Enter') { event.preventDefault(); search(); } if (event.key === 'Escape') $('searchSuggestions').hidden = true; });
  $('overviewButton').addEventListener('click', () => { state.view = 'overview'; state.clusterId = null; updateViewControls(); renderClusters(); drawGraph(); });
  $('egoButton').addEventListener('click', () => { if (state.selectedId) { state.view = 'ego'; state.clusterId = null; updateViewControls(); renderClusters(); drawGraph(); } });
  $('clearFocusButton').addEventListener('click', () => { state.selectedId = null; state.clusterId = null; state.view = 'overview'; $('gidSearch').value = ''; renderDetail(); renderTop(); renderClusters(); updateViewControls(); drawGraph(); });
  $('graphCanvas').addEventListener('mousemove', showTooltip);
  $('graphCanvas').addEventListener('mouseleave', () => { $('graphTooltip').hidden = true; });
  $('graphCanvas').addEventListener('click', (event) => { const { point } = pointAt(event); if (point) selectNode(point.id); });
  let resizeFrame = 0; window.addEventListener('resize', () => { cancelAnimationFrame(resizeFrame); resizeFrame = requestAnimationFrame(drawGraph); });
  loadNetwork();
}

if (typeof document !== 'undefined') start();
export { buildIndex, gid, roleOf, verificationPlan };
