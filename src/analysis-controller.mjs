/** Coordinate automatic analysis without overlapping external requests. */
export function createAnalysisController({
  request,
  onChange,
  onBusyChange = () => {},
  delayMs = 600,
  setTimer = setTimeout,
  clearTimer = clearTimeout,
  maxEntries = 50,
}) {
  const cache = new Map();
  const cacheLimit = Number.isFinite(maxEntries) ? Math.max(0, Math.floor(maxEntries)) : 50;
  let desired = null;
  let inFlight = null;
  let timer = null;
  let generation = 0;
  let paused = false;

  function cancelTimer() {
    if (timer !== null) clearTimer(timer);
    timer = null;
  }

  function remember(key, data) {
    cache.delete(key);
    cache.set(key, data);
    while (cache.size > cacheLimit) cache.delete(cache.keys().next().value);
  }

  function settle(operation, result) {
    const valid = operation.generation === generation;
    if (valid && result.status === 'ready') remember(operation.key, result.data);
    const current = valid && desired?.key === operation.key ? desired : null;
    if (current) current.status = result.status;

    // Release busy before callbacks: an explicit retry may start in onChange.
    inFlight = null;
    onBusyChange(false);
    if (current && desired === current && current.status === result.status) {
      onChange({ ...result, key: current.key });
    }
    startIfReady();
  }

  function startIfReady() {
    if (paused || inFlight || !desired?.due || desired.status !== 'waiting') return;
    const current = desired;
    const operation = { key: current.key, generation };
    inFlight = operation;
    current.status = 'loading';
    onBusyChange(true);
    if (desired === current) onChange({ status: 'loading', key: current.key });

    let response;
    try {
      response = request(current.payload);
    } catch (error) {
      response = Promise.reject(error);
    }
    Promise.resolve(response).then(
      (data) => settle(operation, { status: 'ready', data }),
      (error) => settle(operation, {
        status: 'error',
        error: error instanceof Error ? error : new Error(String(error)),
      }),
    );
  }

  function select({ key, payload }) {
    if (desired?.key === key) return;
    cancelTimer();
    const current = { key, payload, due: false, status: 'waiting' };
    desired = current;

    if (cache.has(key)) {
      const data = cache.get(key);
      remember(key, data);
      current.status = 'ready';
      onChange({ status: 'ready', key, data: { ...data, cached: true } });
      return;
    }
    if (inFlight?.key === key && inFlight.generation === generation) {
      current.status = 'loading';
      onChange({ status: 'loading', key });
      return;
    }

    timer = setTimer(() => {
      if (desired !== current) return;
      timer = null;
      current.due = true;
      startIfReady();
    }, delayMs);
    onChange({ status: 'waiting', key });
  }

  function retry() {
    if (desired?.status !== 'error') return;
    desired.status = 'waiting';
    desired.due = true;
    onChange({ status: 'waiting', key: desired.key });
    startIfReady();
  }

  function setPaused(value) {
    paused = Boolean(value);
    if (!paused) startIfReady();
  }

  function clear() {
    cancelTimer();
    desired = null;
    generation += 1;
    cache.clear();
    // Keep the old request in flight until it settles, even after invalidation.
  }

  return { select, retry, setPaused, clear };
}
