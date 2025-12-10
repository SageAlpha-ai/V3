// static/js/chat.js (cleaned & fixed)
(async function () {
  const messagesEl = document.getElementById('messages');
  const messageBox = document.getElementById('messageBox');
  const sendBtn = document.getElementById('sendBtn');
  const newChatBtn = document.getElementById('newChatBtn');
  const chatHistoryEl = document.getElementById('chatHistory');
  const fileInput = document.getElementById('fileInput');
  const usernameEl = document.getElementById('username');
  const userEmailEl = document.getElementById('userEmail');
  const userAvatarEl = document.getElementById('userAvatar');

  let currentSessionId = null;
  let currentSessionMeta = null;

  const emptyStateEl = document.getElementById('emptyState');
  const messagesWrapperEl = document.querySelector('.messages-wrapper');

  function showEmptyState(show = true) {
    const composerEl = document.querySelector('.composer') || document.getElementById('composer');
    const wrapper = document.querySelector('.messages-wrapper') || document.querySelector('.messages') || document.querySelector('.hero-cta-composer-wrapper');
    const empty = document.getElementById('emptyState');

    // guard
    if (show) {
      // show welcome hero + CTA, center composer visually but don't move it in DOM
      if (empty) {
        empty.removeAttribute('hidden');
        empty.style.display = 'block';
      }
      wrapper && wrapper.classList.add('centered');
      if (composerEl) composerEl.classList.add('centered');
      if (messagesEl) messagesEl.innerHTML = '';
      messageBox && messageBox.focus();
      const ctaWrap = document.querySelector('.report-cta-wrap');
      if (ctaWrap) ctaWrap.classList.remove('hidden');
    } else {
      // hide welcome hero permanently for this session view
      if (empty) {
        empty.setAttribute('hidden', 'true');
        empty.style.display = 'none';
      }
      wrapper && wrapper.classList.remove('centered');
      if (composerEl) composerEl.classList.remove('centered');

      // ensure space is reserved and scroll to bottom (defensive)
      setTimeout(() => {
        try { wrapper.scrollTop = wrapper.scrollHeight; } catch (e) { try { messagesEl.scrollTop = messagesEl.scrollHeight; } catch (e) { } }
      }, 40);
      messageBox && messageBox.focus();

      // hide CTA when conversation exists (CTA should be clickable only on welcome screen by design)
      const ctaWrap = document.querySelector('.report-cta-wrap');
      if (ctaWrap) {
        ctaWrap.classList.add('hidden');
        // keep CTA element in DOM (don't remove) so its listeners remain active for later re-show if needed
        ctaWrap.style.display = 'none';
      }
    }
  }
  function renderMessage(role, text, meta) {
    if (!messagesEl) return;
    const d = document.createElement('div');
    d.className = 'msg ' + (role === 'user' ? 'user' : 'assistant');

    if (meta && meta.filename) {
      const a = document.createElement('a');
      a.href = meta.url;
      a.textContent = meta.filename;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      d.appendChild(a);
      if (text) d.appendChild(document.createTextNode(' ' + text));
    } else {
      const escapeHtml = (s) => String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');

      let safe = escapeHtml(text || '');
      const urlRegex = /(https?:\/\/[^\s]+)/g;
      safe = safe.replace(urlRegex, (url) => `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`);
      safe = safe.replace(/\n/g, '<br>');
      d.innerHTML = safe;

      // PDF Download Button Logic
      if (meta && meta.can_download_pdf) {
        const btn = document.createElement('button');
        btn.className = 'pdf-download-btn'; // You might need to add CSS for this
        btn.textContent = 'Download PDF';
        btn.style.marginTop = '10px';
        btn.style.padding = '5px 10px';
        btn.style.fontSize = '12px';
        btn.style.cursor = 'pointer';

        btn.onclick = async () => {
          btn.disabled = true;
          btn.textContent = 'Generating...';
          try {
            const resp = await fetch('/generate-pdf', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ content: text, title: 'SageAlpha Report' })
            });

            if (!resp.ok) throw new Error('Generation failed');

            const blob = await resp.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `SageAlpha_Report_${new Date().toISOString().slice(0, 10)}.pdf`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(url);
            btn.textContent = 'Download PDF';
          } catch (e) {
            console.error(e);
            btn.textContent = 'Error';
            alert('Failed to generate PDF');
          } finally {
            btn.disabled = false;
          }
        };
        d.appendChild(btn);
      }

      // Download HTML Report Button Logic
      if (meta && meta.html) {
        // Center the entire message container
        d.style.textAlign = 'center';
        d.style.display = 'flex';
        d.style.flexDirection = 'column';
        d.style.alignItems = 'center';
        d.style.gap = '15px';

        const viewBtn = document.createElement('button');
        viewBtn.textContent = 'View HTML Report';
        viewBtn.className = 'btn';
        viewBtn.style.padding = '12px 24px';
        viewBtn.style.backgroundColor = '#2e8b57'; // Green for View
        viewBtn.style.color = '#ffffff';
        viewBtn.style.border = 'none';
        viewBtn.style.borderRadius = '6px';
        viewBtn.style.fontSize = '14px';
        viewBtn.style.fontWeight = '600';
        viewBtn.style.cursor = 'pointer';
        viewBtn.style.boxShadow = '0 2px 4px rgba(0,0,0,0.1)';

        viewBtn.onclick = () => {
          const blob = new Blob([meta.html], { type: 'text/html' });
          const url = window.URL.createObjectURL(blob);
          window.open(url, '_blank');
        };
        d.appendChild(viewBtn);

        const dlBtn = document.createElement('button');
        dlBtn.textContent = 'Download HTML Report';
        dlBtn.className = 'btn';
        // Professional Blue Styling
        dlBtn.style.marginTop = '10px';
        dlBtn.style.padding = '12px 24px';
        dlBtn.style.backgroundColor = '#0056b3'; // Professional Blue
        dlBtn.style.color = '#ffffff';
        dlBtn.style.border = 'none';
        dlBtn.style.borderRadius = '6px';
        dlBtn.style.fontSize = '14px';
        dlBtn.style.fontWeight = '600';
        dlBtn.style.cursor = 'pointer';
        dlBtn.style.boxShadow = '0 2px 4px rgba(0,0,0,0.1)';
        dlBtn.style.transition = 'background-color 0.2s';

        dlBtn.onmouseover = () => { dlBtn.style.backgroundColor = '#004494'; };
        dlBtn.onmouseout = () => { dlBtn.style.backgroundColor = '#0056b3'; };

        dlBtn.onclick = () => {
          const blob = new Blob([meta.html], { type: 'text/html' });
          const url = window.URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = (meta.title || 'Research_Report') + '.html';
          document.body.appendChild(a);
          a.click();
          a.remove();
          window.URL.revokeObjectURL(url);
        };
        d.appendChild(dlBtn);
      }
    }

    messagesEl.appendChild(d);
    const wrapper = document.querySelector('.messages-wrapper') || messagesEl.parentElement;
    setTimeout(() => {
      try { wrapper.scrollTop = wrapper.scrollHeight; } catch (e) { try { messagesEl.scrollTop = messagesEl.scrollHeight; } catch (err) { } }
    }, 40);
  }

  function hideReportCTA() {
    const cta = document.querySelector('.report-cta-wrap');
    if (!cta) return;
    if (cta.classList.contains('hidden')) return;
    cta.classList.add('hidden');
    setTimeout(() => {
      if (cta && cta.parentElement) cta.parentElement.removeChild(cta);
    }, 140);
  }

  async function loadUser() {
    try {
      const r = await fetch('/user');
      if (r.ok) {
        const d = await r.json();
        if (usernameEl) usernameEl.textContent = d.username || 'Guest';
        if (userEmailEl) userEmailEl.textContent = d.email || '';
        if (d.avatar_url && userAvatarEl) {
          userAvatarEl.src = d.avatar_url;
        }
      }
    } catch (e) { }
  }

  async function loadSessions() {
    try {
      const r = await fetch('/sessions');
      if (!r.ok) return;
      const j = await r.json();
      if (!chatHistoryEl) return;
      chatHistoryEl.innerHTML = '';
      const sessions = j.sessions || [];
      if (sessions.length === 0) {
        const no = document.createElement('div');
        no.className = 'history-item';
        no.textContent = 'No chats yet. Click New chat to start.';
        chatHistoryEl.appendChild(no);
        return;
      }
      sessions.forEach(s => {
        const el = document.createElement('div');
        el.className = 'history-item' + (s.id === currentSessionId ? ' active' : '');
        el.innerHTML = `<div>${escapeHtml(s.title)}</div><div class="sub">${new Date(s.created).toLocaleString()}</div>`;
        el.onclick = async () => { await openSession(s.id); };
        chatHistoryEl.appendChild(el);
      });
    } catch (e) {
      console.error(e);
    }
  }

  async function openSession(sessionId) {
    try {
      const r = await fetch(`/sessions/${sessionId}`);
      if (!r.ok) return;
      const j = await r.json();
      if (messagesEl) messagesEl.innerHTML = '';

      const sessionMessages = j.session.messages || [];
      if (!sessionMessages.length) {
        showEmptyState(true);
        const ctaWrap = document.querySelector('.report-cta-wrap');
        if (ctaWrap) ctaWrap.classList.remove('hidden');
      } else {
        showEmptyState(false);
        sessionMessages.forEach(m => { renderMessage(m.role, m.content, m.meta || null); });
        hideReportCTA();
      }

      currentSessionId = j.session.id;
      currentSessionMeta = { id: j.session.id, title: j.session.title, created: j.session.created, message_count: (j.session.messages || []).length };
      loadSessions();
    } catch (e) { console.error(e); }
  }

  if (newChatBtn) {
    newChatBtn.addEventListener('click', async () => {
      try {
        const r = await fetch('/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: 'New chat' }) });
        if (!r.ok) return;
        const j = await r.json();
        currentSessionId = j.session.id;
        currentSessionMeta = { id: j.session.id, title: j.session.title, created: j.session.created, message_count: 0 };
        if (messagesEl) messagesEl.innerHTML = '';
        showEmptyState(true);
        loadSessions();
        if (messageBox) messageBox.focus();
      } catch (e) { console.error(e); }
    });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[m]));
  }

  async function maybeRenameSessionOnFirstMessage(firstMessageText) {
    try {
      if (!currentSessionId) return;
      const title = (currentSessionMeta && currentSessionMeta.title) || '';
      const lower = (title || '').toLowerCase();
      if (!lower || lower.startsWith('new chat') || lower.startsWith('new conversation') || lower === 'default') {
        let t = firstMessageText.replace(/\s+/g, ' ').trim().slice(0, 60);
        if (t.length === 60) t = t.replace(/\s+\S*$/, '');
        if (!t) t = 'Chat';
        const rr = await fetch(`/sessions/${currentSessionId}/rename`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: t })
        });
        if (rr.ok) {
          const jj = await rr.json();
          currentSessionMeta.title = jj.session.title;
          loadSessions();
        }
      }
    } catch (e) { console.warn('rename failed', e); }
  }

  async function sendMessage() {
    if (!messageBox) return;
    const text = messageBox.value.trim();
    if (!text) return;

    // Easter Egg: Google Antigravity
    if (text.trim().toLowerCase() === 'google antigravity') {
      messageBox.value = '';
      activateAntigravity();
      return;
    }

    renderMessage('user', text);
    hideReportCTA();
    messageBox.value = '';
    try {
      if (!currentSessionId) {
        const resp = await fetch('/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: 'New chat' }) });
        const js = await resp.json();
        currentSessionId = js.session.id;
        currentSessionMeta = { id: js.session.id, title: js.session.title, created: js.session.created, message_count: 0 };
      }
      showEmptyState(false);
      await maybeRenameSessionOnFirstMessage(text);

      const r = await fetch('/chat_session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: currentSessionId, message: text })
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ error: 'Unknown' }));
        renderMessage('assistant', '⚠ Error: ' + (err.error || r.statusText));
        return;
      }
      const j = await r.json();
      renderMessage('assistant', j.response || '(no reply)', j.data);
      hideReportCTA();
      showEmptyState(false);
      loadSessions();
    } catch (e) {
      renderMessage('assistant', '⚠ Network error: ' + (e && e.message ? e.message : e));
    }
  }

  if (fileInput) {
    fileInput.addEventListener('change', async (ev) => {
      const f = ev.target.files[0];
      if (!f) return;
      const fd = new FormData();
      fd.append('file', f);
      if (currentSessionId) fd.append('session_id', currentSessionId);
      try {
        const r = await fetch('/upload', { method: 'POST', body: fd });
        if (!r.ok) { const err = await r.json().catch(() => ({ error: 'Upload failed' })); renderMessage('assistant', '⚠ Upload error: ' + (err.error || r.statusText)); return; }
        const j = await r.json();
        renderMessage('user', '', { filename: j.filename, url: j.url });
        const rr = await fetch('/chat_session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: currentSessionId, message: `[attachment] ${j.url}` }) });
        if (rr.ok) { const jj = await rr.json(); renderMessage('assistant', jj.response || '(no reply)'); }
        loadSessions();
      } catch (e) {
        renderMessage('assistant', '⚠ Upload error: ' + (e && e.message ? e.message : e));
      } finally {
        fileInput.value = '';
      }
    });
  }

  if (messageBox) {
    messageBox.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        if (e.shiftKey) {
          return;
        } else {
          e.preventDefault();
          sendMessage();
        }
      }
    });
  }

  if (sendBtn) sendBtn.addEventListener('click', sendMessage);

  // init load
  await loadUser();
  await loadSessions();
  try {
    const res = await fetch('/sessions');
    const js = await res.json();
    if (js.sessions && js.sessions.length > 0) {
      await openSession(js.sessions[0].id);
    } else {
      const rp = await fetch('/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: 'New chat' }) });
      const newj = await rp.json();
      currentSessionId = newj.session.id;
      currentSessionMeta = { id: newj.session.id, title: newj.session.title, created: newj.session.created, message_count: 0 };
      showEmptyState(true);
    }
  } catch (e) { }

  function activateAntigravity() {
    const elements = document.body.querySelectorAll('div, p, span, img, h1, h2, h3, button, input, textarea, model-viewer');
    document.body.style.overflow = 'hidden'; // Prevent scrolling

    elements.forEach(el => {
      el.style.transition = 'all 2s ease-out';
      // Random values
      const x = (Math.random() - 0.5) * window.innerWidth;
      const y = (Math.random() - 0.5) * window.innerHeight;
      const z = (Math.random() - 0.5) * 500;
      const rot = Math.random() * 360;

      el.style.transform = `translate3d(${x}px, ${y}px, ${z}px) rotate(${rot}deg)`;
      el.style.opacity = Math.random() * 0.5 + 0.5;
    });
  }

})();

// ============= USER DROPDOWN & LOGOUT (ADDED) =============
(function initUserMenu() {
  const userInfo = document.getElementById('userInfo');
  const userMenu = document.getElementById('userMenu');
  const logoutBtn = document.getElementById('logoutBtn');
  const profileBtn = document.getElementById('profileBtn');

  if (!userInfo || !userMenu) return;

  function openMenu() {
    userMenu.hidden = false;
    userInfo.setAttribute('aria-expanded', 'true');
    setTimeout(() => { (userMenu.querySelector('button') || userMenu).focus(); }, 40);
  }
  function closeMenu() {
    userMenu.hidden = true;
    userInfo.setAttribute('aria-expanded', 'false');
  }

  userInfo.addEventListener('click', (e) => {
    e.stopPropagation();
    if (userMenu.hidden) openMenu(); else closeMenu();
  });

  document.addEventListener('click', (e) => {
    if (!userInfo.contains(e.target)) closeMenu();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeMenu();
  });

  if (logoutBtn) {
    logoutBtn.addEventListener('click', (e) => {
      e.preventDefault();
      window.location.href = '/logout';
    });
  }

  if (profileBtn) {
    profileBtn.addEventListener('click', (e) => {
      e.preventDefault();
      window.location.href = '/profile';
    });
  }
})();

// ==================== THEME TOGGLE (light/dark) ====================
(function initThemeToggle() {
  const toggle = document.getElementById('themeToggle');
  const icon = document.getElementById('themeIcon');
  if (!toggle || !icon) return;

  const DARK = 'dark';
  const LIGHT = 'light';

  function applyTheme(theme) {
    if (theme === DARK) {
      document.body.classList.add('dark-mode');
      icon.textContent = '☀️';
    } else {
      document.body.classList.remove('dark-mode');
      icon.textContent = '🌙';
    }
    localStorage.setItem('sagealpha-theme', theme);
  }

  const saved = localStorage.getItem('sagealpha-theme');
  if (saved === DARK || saved === LIGHT) {
    applyTheme(saved);
  } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    applyTheme(DARK);
  } else {
    applyTheme(LIGHT);
  }

  toggle.addEventListener('click', () => {
    const isDark = document.body.classList.contains('dark-mode');
    applyTheme(isDark ? LIGHT : DARK);
  });
})();

/* REPORT CTA: fetch() report HTML and convert to PDF client-side using html2pdf.bundle.min.js */
/* REPORT CTA: robust client-side PDF generation (replace the previous initReportDownload block) */
/* REPORT CTA: robust client-side PDF generation using a hidden iframe.
   Replace previous initReportDownload() block with this - safe, debug-friendly. */
/* REPORT CTA: server-first non-blocking download handler
   Replaces previous client-side html2pdf-heavy handler.
   Behavior:
   1) Try GET /download-report (timeout 30s). If success -> download PDF blob.
   2) If server errors / times out -> open /report-html in a new tab for inspection (safe fallback).
   3) Minimal UI changes, prevents double-clicks, logs errors to console.
*/
(function initReportDownload() {
  const btn = document.getElementById('downloadReportBtn');
  if (!btn) return;

  // status element (create if missing)
  let status = document.getElementById('download-status');
  if (!status) {
    status = document.createElement('div');
    status.id = 'download-status';
    status.style.display = 'none';
    status.style.marginTop = '8px';
    status.style.fontSize = '0.95rem';
    btn.parentNode && btn.parentNode.insertBefore(status, btn.nextSibling);
  }

  let inProgress = false;

  // small helper that downloads a blob response
  async function downloadBlobResponse(resp, defaultFilename) {
    const contentDisposition = resp.headers.get('Content-Disposition') || '';
    let filename = defaultFilename || 'sagalpha_report.pdf';
    const match = contentDisposition.match(/filename\*?=(?:UTF-8'')?["']?([^;"']+)/);
    if (match) filename = decodeURIComponent(match[1]);
    const blob = await resp.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  }

  // Attempt server PDF first
  async function serverDownloadWithTimeout(timeoutMs = 30000) {
    const ac = new AbortController();
    const timer = setTimeout(() => {
      ac.abort();
    }, timeoutMs);

    try {
      // GET /download-report - change to POST if your backend expects POST
      const resp = await fetch('/download-report', { method: 'GET', signal: ac.signal, credentials: 'same-origin' });
      clearTimeout(timer);

      if (!resp.ok) {
        // server responded with error status
        const text = await resp.text().catch(() => `Server returned ${resp.status}`);
        console.error('[download-report] server error:', resp.status, text);
        throw new Error('Server error');
      }

      // If content-type is PDF, download
      const ct = (resp.headers.get('Content-Type') || '').toLowerCase();
      if (ct.includes('application/pdf') || resp.headers.get('Content-Disposition')) {
        await downloadBlobResponse(resp, 'sagalpha_report.pdf');
        return true;
      }

      // Unexpected content-type, but still try to download if we got bytes
      try {
        await downloadBlobResponse(resp, 'sagalpha_report.bin');
        return true;
      } catch (e) {
        console.warn('[download-report] fallback download failed', e);
        throw e;
      }
    } catch (err) {
      clearTimeout(timer);
      if (err.name === 'AbortError') {
        console.warn('[download-report] request aborted due to timeout');
        throw new Error('timeout');
      }
      throw err;
    }
  }

  async function handleClick(e) {
    e.preventDefault();
    if (inProgress) {
      console.warn('report download already in progress');
      return;
    }
    inProgress = true;
    btn.disabled = true;
    const prevText = btn.innerText;
    status.style.display = 'inline-block';
    status.textContent = 'Preparing report...';

    try {
      // Try server-first approach
      try {
        await serverDownloadWithTimeout(30000); // 30 sec timeout
        status.textContent = 'Download started.';
      } catch (serr) {
        console.warn('[download-report] server-first attempt failed:', serr);
        // Fallback behaviour: open the HTML page so user can inspect / print to PDF manually.
        // This avoids running html2pdf on the main thread which is the root cause of hangs.
        status.textContent = 'Server failed to prepare PDF — opening report preview...';
        window.open('/report-html', '_blank');
      }
    } catch (err) {
      console.error('[download-report] unexpected error:', err);
      alert('Could not download report — check console and server logs.');
    } finally {
      inProgress = false;
      btn.disabled = false;
      btn.innerText = prevText;
      setTimeout(() => {
        status.style.display = 'none';
      }, 1500);
    }
  }

  // attach both click and keyboard activation
  btn.addEventListener('click', handleClick);
  btn.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' || ev.key === ' ') {
      ev.preventDefault();
      handleClick(ev);
    }
  });
})();



/* Layout / composer stabilization - single authoritative module
   Replaces previous placeReportCTA / ensureComposerFlow / layoutFix / etc.
   This enforces a fixed bottom composer, reserves message padding, and
   prevents other scripts from moving the composer visually.
*/
(function initStableComposer() {
  // selectors / defaults
  const COMPOSER_SELECTOR = '#composer, .composer';
  const MESSAGES_WRAPPER_SELECTOR = '.messages-wrapper, .messages';
  const SIDEBAR_SELECTOR = '.sidebar';
  const CTA_SELECTOR = '.report-cta-wrap';
  const EMPTY_STATE_ID = 'emptyState';

  // desired bottom spacing (px)
  const BOTTOM_GAP = 16;
  const RIGHT_GAP = 24;
  const DESIRED_COMPOSER_MAX_WIDTH = 980; // px

  // enforce styles on composer
  function enforceComposerStyles() {
    const composer = document.querySelector(COMPOSER_SELECTOR);
    if (!composer) return;

    // apply authoritative fixed positioning
    composer.style.position = 'fixed';
    composer.style.bottom = BOTTOM_GAP + 'px';
    composer.style.zIndex = '1100';
    composer.style.transform = 'none';
    composer.style.margin = '0';
    composer.style.pointerEvents = 'auto';

    // compute left offset based on sidebar width (if present)
    const sidebar = document.querySelector(SIDEBAR_SELECTOR);
    const leftOffset = sidebar ? Math.ceil(sidebar.getBoundingClientRect().width + 16) : 260;
    composer.style.left = leftOffset + 'px';
    composer.style.right = RIGHT_GAP + 'px';
    // width constraints — prefer fluid, but cap it so composer pill looks right
    composer.style.maxWidth = `calc(100% - ${leftOffset + RIGHT_GAP}px)`;
    composer.style.boxSizing = 'border-box';

    // make inner composer pill centered within max width if .composer-inner exists
    const inner = composer.querySelector ? composer.querySelector('.composer-inner') : null;
    if (inner) {
      inner.style.maxWidth = DESIRED_COMPOSER_MAX_WIDTH + 'px';
      inner.style.marginLeft = 'auto';
      inner.style.marginRight = 'auto';
    }

    // ensure any inline marginTop set by prior scripts is cleared
    composer.style.marginTop = '';
  }

  // reserve bottom padding in messages wrapper so messages do not hide under composer
  function reserveMessagesPadding() {
    const wrapper = document.querySelector(MESSAGES_WRAPPER_SELECTOR);
    const composer = document.querySelector(COMPOSER_SELECTOR);
    if (!wrapper || !composer) return;
    const composerHeight = Math.ceil((composer.getBoundingClientRect && composer.getBoundingClientRect().height) || 0);
    // add an extra gap to ensure breathing room
    const pad = composerHeight + 24;
    // only increase padding if current is smaller (avoid shrinking unexpectedly)
    const currentPad = parseFloat(window.getComputedStyle(wrapper).paddingBottom || 0);
    if (isNaN(currentPad) || currentPad < pad) {
      wrapper.style.paddingBottom = pad + 'px';
    }
  }

  // When we show the empty hero we want the composer to appear visually centered,
  // but we MUST NOT move it in DOM. We only toggle visibility of hero/CTA via existing functions.
  function ensureHeroNotReinjected() {
    // keep the hero DOM in place; do not move it into new wrappers
    const hero = document.getElementById(EMPTY_STATE_ID);
    if (hero) {
      // ensure it uses 'display' control rather than DOM moves by other scripts
      // nothing else needed here; showEmptyState will toggle hidden/display.
    }
  }

  // Micro-utility: run all enforcement steps
  function applyAll() {
    enforceComposerStyles();
    reserveMessagesPadding();
    ensureHeroNotReinjected();
  }

  // Run initially after DOM loads
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      setTimeout(applyAll, 40); // small delay to allow other init scripts to run first
    });
  } else {
    setTimeout(applyAll, 40);
  }

  // Recompute on resize (layout changes)
  window.addEventListener('resize', () => {
    setTimeout(applyAll, 60);
  });

  // Also run after fonts/images load (safer to do once again)
  window.addEventListener('load', () => {
    setTimeout(applyAll, 120);
  });

  // MutationObserver: if anything attempts to move or re-style the composer,
  // we immediately re-apply our fixed authoritative styles. This prevents other
  // layout helpers from making the composer jump.
  try {
    const observerRoot = document.body;
    if (observerRoot && window.MutationObserver) {
      const mo = new MutationObserver((mutations) => {
        let changed = false;
        for (const m of mutations) {
          // if any childList or attributes change under body, re-enforce
          if (m.type === 'childList' || m.type === 'attributes') {
            changed = true;
            break;
          }
        }
        if (changed) {
          // quick debounce, as many mutations come in bursts
          requestAnimationFrame(() => {
            applyAll();
          });
        }
      });
      mo.observe(observerRoot, { childList: true, subtree: true, attributes: true });
    }
  } catch (e) {
    // if MutationObserver isn't available, we still did the basic applyAll runs above.
    console.warn('stable composer observer not installed', e);
  }

  // Small helper: when new messages are added, ensure scrolling & padding
  // We hook into the messages element via another MutationObserver that only watches children,
  // so we can adjust padding bottom and auto-scroll.
  (function watchMessagesChildren() {
    try {
      const messagesEl = document.getElementById('messages') || document.querySelector('.messages');
      if (!messagesEl || !window.MutationObserver) return;
      const mo = new MutationObserver(() => {
        // ensure bottom padding reserved in case composer height changed
        reserveMessagesPadding();
        // auto-scroll to bottom (small delay)
        setTimeout(() => {
          try {
            messagesEl.scrollTop = messagesEl.scrollHeight;
          } catch (e) { }
        }, 40);
      });
      mo.observe(messagesEl, { childList: true, subtree: false });
    } catch (e) { }
  })();

  // final safety apply shortly after script load
  setTimeout(applyAll, 280);
})();
