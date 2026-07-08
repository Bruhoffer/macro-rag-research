// Keys live in sessionStorage only — never in source. Nothing is prompted
// upfront: in open-demo mode browse/chat need no key at all. A 401 triggers
// one prompt for the right key (admin endpoints use a separate key), then the
// request is retried once.
function _storageKey(path) {
  return path.startsWith('/api/admin') ? 'mr_admin_key' : 'mr_api_key';
}

// One shared prompt per storage key at a time. Parallel 401s (e.g. the admin
// dashboard's loadStats + loadChats) must not each pop their own dialog and
// clobber each other's key — they all await the same prompt.
const _keyPromptInFlight = {};

function promptForKey(path) {
  const storageKey = _storageKey(path);
  if (_keyPromptInFlight[storageKey]) return _keyPromptInFlight[storageKey];

  _keyPromptInFlight[storageKey] = (async () => {
    // A sibling request may have already stored a fresh key while we queued.
    const existing = sessionStorage.getItem(storageKey);
    if (existing) return existing;
    const label = path.startsWith('/api/admin') ? 'Enter ADMIN key' : 'Enter API key';
    const k = (window.prompt(label) || '').trim();
    if (k) sessionStorage.setItem(storageKey, k);
    return k;
  })();

  return _keyPromptInFlight[storageKey].finally(() => {
    delete _keyPromptInFlight[storageKey];
  });
}

function authHeaders(path = '/api/') {
  const k = sessionStorage.getItem(_storageKey(path));
  return k ? { Authorization: `Bearer ${k}` } : {};
}

async function _get(path, params = {}, _retried = false) {
  const url = new URL(path, window.location.origin);
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === '') continue;
    if (Array.isArray(v)) {
      for (const item of v) url.searchParams.append(k, item);
    } else {
      url.searchParams.set(k, String(v));
    }
  }
  const sentKey = sessionStorage.getItem(_storageKey(path)); // the key THIS request used
  const r = await fetch(url, { headers: authHeaders(path) });
  if (r.status === 401 && !_retried) {
    // Drop the rejected key only if it's still the one we sent. A sibling
    // request's 401 may have already prompted and stored a fresh, valid key
    // (parallel admin loads) — don't clobber it and re-prompt for each call.
    if (sentKey && sessionStorage.getItem(_storageKey(path)) === sentKey) {
      sessionStorage.removeItem(_storageKey(path));
    }
    if (await promptForKey(path)) return _get(path, params, true);
  }
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
  metaDateRange:  () => _get('/api/meta/date-range'),

  // Admin / observability
  adminChatTraces: (p) => _get('/api/admin/chat-traces', p),
  adminChatTrace:  (id) => _get(`/api/admin/chat-traces/${id}`),
  adminApiRequests:(p) => _get('/api/admin/api-requests', p),
  adminStats:      () => _get('/api/admin/stats'),
};
