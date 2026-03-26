/* ── Chat Panel Logic ───────────────────────────────────── */
(function () {
  var history = [];
  var loading = false;

  var msgsEl   = document.getElementById('chat-messages');
  var inputEl  = document.getElementById('chat-input');
  var sendBtn  = document.getElementById('chat-send');

  // Show welcome on first load
  appendMsg('bot', '👋 嗨！我是 OpenClaw 安裝助教。\n有什麼關於安裝或設定的問題，歡迎問我！');

  // ── Send ───────────────────────────────────────────────
  function send() {
    var text = inputEl.value.trim();
    if (!text || loading) return;

    appendMsg('user', text);
    history.push({ role: 'user', content: text });
    inputEl.value = '';
    setLoading(true);

    fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, history: history }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var resp = data.response || data.error || '無回應';
        appendMsg('bot', resp);
        history.push({ role: 'assistant', content: resp });
      })
      .catch(function (e) {
        appendMsg('bot', '⚠️ 網路錯誤，請稍後再試。', 'error');
      })
      .finally(function () {
        setLoading(false);
        scrollBottom();
      });
  }

  sendBtn.addEventListener('click', send);
  inputEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });

  // ── Helpers ───────────────────────────────────────────
  function appendMsg(role, text, extraClass) {
    var div = document.createElement('div');
    div.className = 'msg ' + role + (extraClass ? ' ' + extraClass : '');
    div.textContent = text;
    msgsEl.appendChild(div);
  }

  function setLoading(val) {
    loading = val;
    sendBtn.disabled = val;
    inputEl.disabled = val;
  }

  function scrollBottom() {
    msgsEl.scrollTop = msgsEl.scrollHeight;
  }
})();
