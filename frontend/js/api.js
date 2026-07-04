async function _get(path, params = {}) {
  const url = new URL(path, window.location.origin);
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === '') continue;
    if (Array.isArray(v)) {
      for (const item of v) url.searchParams.append(k, item);
    } else {
      url.searchParams.set(k, String(v));
    }
  }
  const r = await fetch(url);
  if (!r.ok) {
    const text = await r.text().catch(() => r.statusText);
    throw new Error(`${r.status}: ${text}`);
  }
  return r.json();
}

const api = {
  keyPoints:      (p) => _get('/api/key-points', p),
  keyPoint:       (id) => _get(`/api/key-points/${id}`),
  tradeIdeas:     (p) => _get('/api/trade-ideas', p),
  tradeIdea:      (id) => _get(`/api/trade-ideas/${id}`),
  disagreements:  (p) => _get('/api/disagreements', p),
  topicSummaries: (p) => _get('/api/topic-summaries', p),
  tradeSummaries: (p) => _get('/api/trade-summaries', p),
  email:          (hash) => _get(`/api/emails/${hash}`),
  metaBanks:      () => _get('/api/meta/source-orgs'),
  metaTopics:     () => _get('/api/meta/topics'),
  metaGeos:       () => _get('/api/meta/geographies'),

  // Admin / observability
  adminChatTraces: (p) => _get('/api/admin/chat-traces', p),
  adminChatTrace:  (id) => _get(`/api/admin/chat-traces/${id}`),
  adminApiRequests:(p) => _get('/api/admin/api-requests', p),
  adminStats:      () => _get('/api/admin/stats'),
};
