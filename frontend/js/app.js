function renderMarkdown(text, sources, streaming) {
  if (!text) return '';

  // Strip complete or partial SOURCES block before parsing.
  // A partial block (no closing -->) would make the browser treat all
  // subsequent HTML as a comment, hiding the rest of the response.
  const cleanText = text
    .replace(/<!--\s*SOURCES[\s\S]*?-->/, '')
    .replace(/<!--\s*SOURCES[\s\S]*$/, '');

  const sanitized = DOMPurify.sanitize(marked.parse(cleanText));

  if (streaming) return sanitized;

  // Build footnote_num → source lookup from the SOURCES block in the original text.
  const resolvedMap = {};
  const blockMatch = text.match(/<!--\s*SOURCES\s*\n([\s\S]*?)-->/);
  if (blockMatch) {
    for (const line of blockMatch[1].trim().split('\n')) {
      const m = line.match(/^\[\^(\d+)\]:\s*(.+)$/);
      if (!m) continue;
      const src = (sources || []).find(s => s.key_point_id === m[2].trim());
      if (src) resolvedMap[m[1]] = src;
    }
  }

  if (!Object.keys(resolvedMap).length) return sanitized;

  const esc = s => (s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;');
  return sanitized.replace(/\[\^(\d+)\]/g, (_, n) => {
    const src = resolvedMap[n];
    if (!src) return `<sup class="text-gray-400 text-xs ml-0.5">[${n}]</sup>`;
    return (
      `<sup><button ` +
      `class="inline-flex items-center justify-center w-3.5 h-3.5 text-[10px] bg-blue-100 hover:bg-blue-200 text-blue-700 rounded-full font-bold ml-0.5 leading-none" ` +
      `data-email-hash="${esc(src.email_content_hash)}" ` +
      `data-email-citation="${esc(src.citation)}" ` +
      `title="${esc(src.org)} · ${esc(src.date)}"` +
      `>${n}</button></sup>`
    );
  });
}

function app() {
  return {
    ...chatMixin(),

    // Mode
    mode: 'browse',

    // Browse tab
    tab: 'key-points',
    tabs: [
      { id: 'key-points',    label: 'Key Points' },
      { id: 'trade-ideas',   label: 'Trade Ideas' },
      { id: 'disagreements', label: 'Disagreements' },
      { id: 'summaries',     label: 'Summaries' },
    ],

    // Summaries sub-tab
    summaryType: 'topic',

    // Browse data
    items: [],
    total: 0,
    page: 1,
    limit: 20,
    loading: false,
    errorMsg: null,

    // Filters
    q: '',
    dateFrom: '',
    dateTo: '',
    selectedBanks: [],
    selectedTopics: [],
    selectedGeos: [],
    selectedSentiments: [],
    timeRef: '',
    selectedAssetClasses: [],
    confirmedOnly: true,

    // Meta (populated on init)
    banks: [],
    topics: [],
    geos: [],
    sentimentOptions: ['very bearish', 'bearish', 'neutral', 'bullish', 'very bullish'],
    assetClassOptions: ['Rates', 'FX', 'Equities', 'Credit', 'Commodities'],
    timeRefOptions: ['past', 'present', 'future'],

    // Email viewer
    emailOpen: false,
    emailLoading: false,
    currentEmail: null,
    currentCitation: null,

    async init() {
      await this.loadMeta();
      await this.loadItems();
    },

    async loadMeta() {
      try {
        const [bs, ts, gs] = await Promise.all([
          api.metaBanks(), api.metaTopics(), api.metaGeos(),
        ]);
        this.banks = bs;
        this.topics = ts;
        this.geos = gs;
      } catch (e) {
        console.error('Meta load failed:', e);
      }
    },

    async loadItems() {
      this.loading = true;
      this.errorMsg = null;
      try {
        const p = this._params();
        let res;
        if (this.tab === 'key-points') {
          res = await api.keyPoints(p);
        } else if (this.tab === 'trade-ideas') {
          res = await api.tradeIdeas({ ...p, asset_class: this.selectedAssetClasses });
        } else if (this.tab === 'disagreements') {
          res = await api.disagreements({ ...p, topic: this.selectedTopics, geo: this.selectedGeos, confirmed_only: this.confirmedOnly });
        } else if (this.tab === 'summaries') {
          if (this.summaryType === 'topic') {
            res = await api.topicSummaries({ topic: this.selectedTopics[0], date: this.dateTo || undefined, page: this.page, limit: this.limit });
          } else {
            res = await api.tradeSummaries({ asset_class: this.selectedAssetClasses[0], date: this.dateTo || undefined, page: this.page, limit: this.limit });
          }
        }
        this.items = res?.data ?? [];
        this.total = res?.total ?? this.items.length;
      } catch (e) {
        this.errorMsg = e.message;
        this.items = [];
        this.total = 0;
      } finally {
        this.loading = false;
      }
    },

    _params() {
      return {
        q:             this.q || undefined,
        source_org:    this.selectedBanks.length ? this.selectedBanks : undefined,
        topic:         this.selectedTopics.length ? this.selectedTopics : undefined,
        geo:           this.selectedGeos.length ? this.selectedGeos : undefined,
        sentiment:     this.selectedSentiments.length ? this.selectedSentiments : undefined,
        time_reference: this.timeRef || undefined,
        date_from:     this.dateFrom || undefined,
        date_to:       this.dateTo || undefined,
        page:          this.page,
        limit:         this.limit,
      };
    },

    setTab(id) {
      this.tab = id;
      this.page = 1;
      this.loadItems();
    },

    setSummaryType(type) {
      this.summaryType = type;
      this.page = 1;
      this.loadItems();
    },

    applyFilters() {
      this.page = 1;
      this.loadItems();
    },

    clearFilters() {
      this.q = '';
      this.dateFrom = '';
      this.dateTo = '';
      this.selectedBanks = [];
      this.selectedTopics = [];
      this.selectedGeos = [];
      this.selectedSentiments = [];
      this.timeRef = '';
      this.selectedAssetClasses = [];
      this.confirmedOnly = true;
      this.page = 1;
      this.loadItems();
    },

    prevPage() { if (this.page > 1) { this.page--; this.loadItems(); } },
    nextPage() { if (this.page < this.totalPages) { this.page++; this.loadItems(); } },

    get totalPages() { return Math.max(1, Math.ceil(this.total / this.limit)); },

    async openEmail(hash, citation = null) {
      this.emailOpen = true;
      this.emailLoading = true;
      this.currentEmail = null;
      this.currentCitation = citation;
      try {
        this.currentEmail = await api.email(hash);
      } catch (e) {
        console.error('Email load failed:', e);
      } finally {
        this.emailLoading = false;
        this.$nextTick(() => {
          const mark = document.getElementById('citation-mark');
          if (mark) mark.scrollIntoView({ behavior: 'smooth', block: 'center' });
        });
      }
    },

    closeEmail() {
      this.emailOpen = false;
      this.currentEmail = null;
      this.currentCitation = null;
    },

    highlightedBody() {
      const body = this.currentEmail?.email_body ?? '';
      const cite = this.currentCitation;
      const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      if (!cite) return esc(body);
      const idx = body.indexOf(cite);
      if (idx === -1) return esc(body);
      return (
        esc(body.slice(0, idx)) +
        '<mark id="citation-mark" class="bg-yellow-200 rounded px-0.5">' +
        esc(cite) +
        '</mark>' +
        esc(body.slice(idx + cite.length))
      );
    },

    // Display helpers
    sentimentClass(s) {
      return {
        'very bearish': 'bg-red-100 text-red-800',
        'bearish':      'bg-red-50 text-red-700',
        'neutral':      'bg-gray-100 text-gray-600',
        'bullish':      'bg-green-50 text-green-700',
        'very bullish': 'bg-green-100 text-green-800',
      }[s] ?? 'bg-gray-100 text-gray-600';
    },

    scaleClass(s) {
      return { High: 'bg-red-100 text-red-800', Medium: 'bg-amber-100 text-amber-800', Low: 'bg-sky-100 text-sky-800' }[s] ?? 'bg-gray-100 text-gray-600';
    },

    fmtDate(dt) {
      if (!dt) return '—';
      return new Date(dt).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
    },

    fmtDateShort(dt) {
      if (!dt) return '—';
      return new Date(dt).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    },

    trunc(text, len = 220) {
      if (!text) return '';
      return text.length > len ? text.slice(0, len) + '…' : text;
    },
  };
}
