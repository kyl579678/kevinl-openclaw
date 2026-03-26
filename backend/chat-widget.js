/* ── Chat Widget Logic ──────────────────────────────────────────── */
(function () {
  var history = [];
  var loading = false;

  var launcher = document.getElementById('chat-launcher');
  var win = document.getElementById('chat-window');
  var msgs = document.getElementById('chat-messages');
  var input = document.getElementById('chat-input');
  var sendBtn = document.getElementById('chat-send');
  var closeBtn = document.getElementById('chat-close');

  // ── Toggle window ─────────────────────────────────────────────
  launcher.addEventListener('click', function () {
    win.style.display = win.style.display === 'flex' ? 'none' : 'flex';
    if (win.style.display === 'flex') {
      input.focus();
      scrollBottom();
      // Welcome message if empty
      if (msgs.children.length === 0) {
        appendMsg('bot', '👋 嗨！我是 OpenClaw 安裝助教。\n有什麼關於安裝或設定的問題，歡迎問我！');
      }
    }
  });

  closeBtn.addEventListener('click', function () {
    win.style.display = 'none';
  });

  // ── Send ─────────────────────────────────────────────────────
  function send() {
    var text = input.value.trim();
    if (!text || loading) return;

    appendMsg('user', text);
    history.push({ role: 'user', content: text });
    input.value = '';
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
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });

  // ── Helpers ───────────────────────────────────────────────────
  function appendMsg(role, text, extraClass) {
    var div = document.createElement('div');
    div.className = 'msg ' + role + (extraClass ? ' ' + extraClass : '');
    div.textContent = text;
    msgs.appendChild(div);
  }

  function setLoading(val) {
    loading = val;
    sendBtn.disabled = val;
    input.disabled = val;
  }

  function scrollBottom() {
    msgs.scrollTop = msgs.scrollHeight;
  }
})();
