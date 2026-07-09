function adminApp() {
  return {
    tab: 'chats',            // 'chats' | 'requests'
    stats: null,
    refreshing: false,

    // auth gate — one passcode, entered once (see api.js setKeyPrompt)
    authed: false,
    keyInput: '',
    authError: '',
    unlocking: false,

    // chat traces
    chats: [],
    chatTotal: 0,
    chatPage: 1,
    chatLimit: 20,
    chatStatus: '',
    chatDateFrom: '',
    chatDateTo: '',
    chatsLoading: false,

    // selected trace detail (drawer)
    detail: null,
    detailLoading: false,

    // api request log
    requests: [],
    reqTotal: 0,
    reqPage: 1,
    reqLimit: 50,
    reqPath: '',
    reqDateFrom: '',
    reqDateTo: '',
    reqLoading: false,

    async init() {
      // Show our own key gate on a 401 instead of a native window.prompt.
      api.setKeyPrompt(() => { this.authed = false; return ''; });
      if (sessionStorage.getItem('mr_admin_key')) await this.load();
    },

    // Validate the current key by loading stats (throws on 401), then the panels.
    async load() {
      try {
        this.stats = await api.adminStats();   // 401 here throws → gate stays
        this.authed = true;
        await this.loadChats();
      } catch { this.authed = false; }
    },

    async unlock() {
      const k = this.keyInput.trim();
      if (!k) return;
      this.unlocking = true;
      this.authError = '';
      sessionStorage.setItem('mr_admin_key', k);
      await this.load();
      if (this.authed) {
        this.keyInput = '';
      } else {
        sessionStorage.removeItem('mr_admin_key');
        this.authError = 'Invalid key';
      }
      this.unlocking = false;
    },

    signOut() {
      sessionStorage.removeItem('mr_admin_key');
      this.authed = false;
      this.stats = null;
      this.chats = [];
      this.requests = [];
      this.detail = null;
    },

    // The dashboard fetches on load only (no polling) — re-fetch the active views.
    async refresh() {
      this.refreshing = true;
      const jobs = [this.loadStats(), this.loadChats()];
      if (this.tab === 'requests') jobs.push(this.loadRequests());
      await Promise.all(jobs);
      this.refreshing = false;
    },

    async loadStats() {
      try { this.stats = await api.adminStats(); } catch (e) { console.error(e); }
    },

    async loadChats() {
      this.chatsLoading = true;
      try {
        const r = await api.adminChatTraces({
          status: this.chatStatus || null,
          date_from: this.chatDateFrom || null,
          date_to: this.chatDateTo || null,
          page: this.chatPage,
          limit: this.chatLimit,
        });
        this.chats = r.data;
        this.chatTotal = r.total;
      } catch (e) { console.error(e); }
      this.chatsLoading = false;
    },

    async loadRequests() {
      this.reqLoading = true;
      try {
        const r = await api.adminApiRequests({
          path: this.reqPath || null,
          date_from: this.reqDateFrom || null,
          date_to: this.reqDateTo || null,
          page: this.reqPage,
          limit: this.reqLimit,
        });
        this.requests = r.data;
        this.reqTotal = r.total;
      } catch (e) { console.error(e); }
      this.reqLoading = false;
    },

    async openTrace(id) {
      this.detailLoading = true;
      this.detail = null;
      try { this.detail = await api.adminChatTrace(id); } catch (e) { console.error(e); }
      this.detailLoading = false;
    },
    closeTrace() { this.detail = null; },

    switchTab(t) {
      this.tab = t;
      if (t === 'requests' && this.requests.length === 0) this.loadRequests();
    },

    // pagination
    get chatPages() { return Math.max(1, Math.ceil(this.chatTotal / this.chatLimit)); },
    chatPrev() { if (this.chatPage > 1) { this.chatPage--; this.loadChats(); } },
    chatNext() { if (this.chatPage < this.chatPages) { this.chatPage++; this.loadChats(); } },
    get reqPages() { return Math.max(1, Math.ceil(this.reqTotal / this.reqLimit)); },
    reqPrev() { if (this.reqPage > 1) { this.reqPage--; this.loadRequests(); } },
    reqNext() { if (this.reqPage < this.reqPages) { this.reqPage++; this.loadRequests(); } },

    // formatting helpers
    fmtDate(s) {
      if (!s) return '';
      const d = new Date(s);
      return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
    },
    fmtMs(ms) {
      if (ms == null) return '—';
      return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(2)} s`;
    },
    fmtNum(n) { return (n ?? 0).toLocaleString(); },
    fmtCost(n) { return n == null ? '—' : '$' + n.toFixed(4); },
    truncate(s, n = 90) { if (!s) return ''; return s.length > n ? s.slice(0, n) + '…' : s; },
    prettyJson(obj) { try { return JSON.stringify(obj, null, 2); } catch { return String(obj); } },

    toolLabel(name) {
      const map = {
        search_key_points:  '🔍 search_key_points',
        search_trade_ideas: '📈 search_trade_ideas',
        search_emails:      '📧 search_emails',
        get_disagreements:  '⚖️ get_disagreements',
        get_topic_summary:  '📋 get_topic_summary',
        get_stats:          '📊 get_stats',
      };
      return map[name] || name;
    },
    statusClass(s) {
      return {
        ok:         'bg-green-100 text-green-700',
        error:      'bg-red-100 text-red-700',
        max_rounds: 'bg-amber-100 text-amber-700',
      }[s] || 'bg-gray-100 text-gray-600';
    },
    methodClass(m) {
      return { GET: 'bg-sky-100 text-sky-700', POST: 'bg-purple-100 text-purple-700' }[m] || 'bg-gray-100 text-gray-600';
    },
    codeClass(c) {
      if (c >= 500) return 'text-red-600';
      if (c >= 400) return 'text-amber-600';
      return 'text-green-600';
    },
  };
}
