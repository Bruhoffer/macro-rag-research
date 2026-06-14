function chatMixin() {
  return {
    messages: [],
    chatInput: '',
    chatLoading: false,

    sendMessage() {
      const text = this.chatInput.trim();
      if (!text || this.chatLoading) return;

      this.messages.push({ role: 'user', content: text });
      this.chatInput = '';
      this.chatLoading = true;

      const assistantMsg = { role: 'assistant', content: '', toolCalls: [], sources: [], streaming: true };
      this.messages.push(assistantMsg);
      const idx = this.messages.length - 1;

      this._streamChat(idx);
      this.$nextTick(() => this._scrollChat());
    },

    async _streamChat(msgIdx) {
      const apiMessages = this.messages
        .slice(0, msgIdx)
        .map(m => ({ role: m.role, content: m.content }));

      try {
        const response = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
          body: JSON.stringify({ messages: apiMessages }),
        });

        if (!response.ok) {
          const err = await response.text().catch(() => response.statusText);
          this.messages[msgIdx].content = `Error: ${err}`;
          this.messages[msgIdx].streaming = false;
          this.chatLoading = false;
          return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop();

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            let event;
            try { event = JSON.parse(line.slice(6)); } catch { continue; }

            if (event.type === 'text') {
              this.messages[msgIdx].content += event.content;
              this.$nextTick(() => this._scrollChat());

            } else if (event.type === 'tool_call') {
              this.messages[msgIdx].toolCalls.push({
                name: event.name,
                input: event.input,
                result: null,
                expanded: false,
              });

            } else if (event.type === 'tool_result') {
              const tc = this.messages[msgIdx].toolCalls
                .find(t => t.name === event.name && t.result === null);
              if (tc) tc.result = event.result;

              // Collect citation sources for the Sources section
              const msg = this.messages[msgIdx];
              const seen = new Set(msg.sources.map(s => s.key_point_id || s.trade_idea_id));

              if (event.name === 'search_key_points' && Array.isArray(event.result)) {
                for (const r of event.result) {
                  if (r.email_content_hash && !seen.has(r.key_point_id)) {
                    seen.add(r.key_point_id);
                    msg.sources.push({ key_point_id: r.key_point_id, email_content_hash: r.email_content_hash,
                      citation: r.key_point_citation, org: r.effective_source_org, date: r.email_sent_dt });
                  }
                }
              } else if (event.name === 'search_trade_ideas' && Array.isArray(event.result)) {
                for (const r of event.result) {
                  if (r.email_content_hash && !seen.has(r.trade_idea_id)) {
                    seen.add(r.trade_idea_id);
                    msg.sources.push({ trade_idea_id: r.trade_idea_id, email_content_hash: r.email_content_hash,
                      citation: r.trade_idea_citation, org: r.effective_source_org, date: r.email_sent_dt });
                  }
                }
              } else if (event.name === 'get_topic_summary' && Array.isArray(event.result)) {
                for (const summary of event.result) {
                  for (const meta of Object.values(summary.label_map_enriched || {})) {
                    if (meta.email_content_hash && !seen.has(meta.key_point_id)) {
                      seen.add(meta.key_point_id);
                      msg.sources.push({ key_point_id: meta.key_point_id, email_content_hash: meta.email_content_hash,
                        citation: meta.key_point_citation, org: meta.effective_source_org, date: meta.email_sent_dt });
                    }
                  }
                }
              }

            } else if (event.type === 'done') {
              this.messages[msgIdx].streaming = false;
              this.chatLoading = false;

            } else if (event.type === 'error') {
              this.messages[msgIdx].content += (this.messages[msgIdx].content ? '\n\n' : '') + `⚠️ ${event.message}`;
              this.messages[msgIdx].streaming = false;
              this.chatLoading = false;
            }
          }
        }
      } catch (e) {
        this.messages[msgIdx].content = `Connection error: ${e.message}`;
        this.messages[msgIdx].streaming = false;
        this.chatLoading = false;
      }
    },

    _scrollChat() {
      const el = document.getElementById('chat-messages');
      if (el) el.scrollTop = el.scrollHeight;
    },

    clearChat() {
      this.messages = [];
      this.chatInput = '';
      this.chatLoading = false;
    },

    toolLabel(tc) {
      const map = {
        search_key_points:  '🔍 Searched key points',
        search_trade_ideas: '📈 Searched trade ideas',
        search_emails:      '📧 Searched emails',
        get_disagreements:  '⚖️ Fetched disagreements',
        get_topic_summary:  '📋 Got topic summary',
        get_stats:          '📊 Ran aggregation',
      };
      return map[tc.name] || `Called ${tc.name}`;
    },

    toolResultSummary(tc) {
      if (tc.result === null) return 'working…';
      const r = tc.result;
      if (Array.isArray(r)) return `${r.length} result${r.length !== 1 ? 's' : ''}`;
      if (r?.data && Array.isArray(r.data)) return `${r.data.length} result${r.data.length !== 1 ? 's' : ''}`;
      return 'done';
    },
  };
}
