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

      const assistantMsg = { role: 'assistant', content: '', toolCalls: [], streaming: true };
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
