// Shared helpers for the BuildWeb admin pages.
(function () {
  function cookie(name) {
    const m = document.cookie.match('(^|;)\\s*' + name + '=([^;]*)');
    return m ? decodeURIComponent(m[2]) : '';
  }

  async function api(url, data, opts = {}) {
    const init = { method: data === undefined && !opts.method ? 'GET' : (opts.method || 'POST'), headers: { 'X-CSRFToken': cookie('buildweb_csrf') } };
    if (data instanceof FormData) init.body = data;
    else if (data !== undefined) { init.body = JSON.stringify(data); init.headers['Content-Type'] = 'application/json'; }
    let res, json;
    try {
      res = await fetch(url, init);
      json = await res.json();
    } catch (e) {
      throw Object.assign(new Error(res ? `เซิร์ฟเวอร์ตอบกลับผิดพลาด (${res.status})` : 'เชื่อมต่อโปรแกรมไม่ได้'), { status: res && res.status });
    }
    if (!json.ok) throw Object.assign(new Error(json.error || 'เกิดข้อผิดพลาด'), json, { status: res.status });
    return json;
  }

  function toast(msg, kind = '') {
    let box = document.getElementById('toasts');
    if (!box) { box = document.createElement('div'); box.id = 'toasts'; document.body.appendChild(box); }
    const t = document.createElement('div');
    t.className = 'toast ' + kind;
    t.textContent = msg;
    box.appendChild(t);
    setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity .3s'; }, kind === 'err' ? 5200 : 2800);
    setTimeout(() => t.remove(), kind === 'err' ? 5600 : 3200);
  }

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  // modal(html, {wide}) -> {el, close}; elements with [data-close] close it.
  function modal(html, opts = {}) {
    const back = document.createElement('div');
    back.className = 'modal-back';
    back.innerHTML = `<div class="modal ${opts.wide ? 'wide' : ''}" role="dialog">${html}</div>`;
    document.body.appendChild(back);
    const close = () => { back.remove(); document.removeEventListener('keydown', onKey); opts.onClose && opts.onClose(); };
    const onKey = e => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', onKey);
    back.addEventListener('mousedown', e => { if (e.target === back) close(); });
    back.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', close));
    const first = back.querySelector('input:not([type=hidden]),textarea,select');
    if (first) setTimeout(() => first.focus(), 50);
    return { el: back.querySelector('.modal'), close };
  }

  function confirmBox(title, text, { ok = 'ยืนยัน', danger = false } = {}) {
    return new Promise(resolve => {
      const m = modal(`<header><h2>${esc(title)}</h2></header><div class="body"><p style="margin:0;color:var(--ink-2)">${text}</p></div>
        <footer><button class="btn" data-close>ยกเลิก</button><button class="btn ${danger ? 'danger' : 'primary'}" data-ok>${esc(ok)}</button></footer>`,
        { onClose: () => resolve(false) });
      m.el.querySelector('[data-ok]').addEventListener('click', () => { resolve(true); m.close(); });
      setTimeout(() => m.el.querySelector('[data-ok]').focus(), 50);
    });
  }

  function formData(root) {
    const out = {};
    root.querySelectorAll('[name]').forEach(el => {
      if (el.type === 'checkbox') out[el.name] = el.checked;
      else if (el.type === 'radio') { if (el.checked) out[el.name] = el.value; }
      else out[el.name] = el.value;
    });
    return out;
  }

  function showFieldError(root, err) {
    root.querySelectorAll('.input.err').forEach(i => i.classList.remove('err'));
    if (err.field) {
      const el = root.querySelector(`[name="${err.field}"]`);
      if (el) { el.classList.add('err'); el.focus(); }
    }
    toast(err.message, 'err');
  }

  function bytes(n) {
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
    return (n / 1024 / 1024 / 1024).toFixed(2) + ' GB';
  }

  function ago(iso) {
    const s = (Date.now() - new Date(iso)) / 1000;
    if (s < 60) return 'เมื่อสักครู่';
    if (s < 3600) return Math.floor(s / 60) + ' นาทีที่แล้ว';
    if (s < 86400) return Math.floor(s / 3600) + ' ชั่วโมงที่แล้ว';
    if (s < 86400 * 30) return Math.floor(s / 86400) + ' วันที่แล้ว';
    return new Date(iso).toLocaleDateString('th-TH', { day: 'numeric', month: 'short', year: 'numeric' });
  }

  function when(iso) {
    return new Date(iso).toLocaleString('th-TH', { day: 'numeric', month: 'short', year: '2-digit', hour: '2-digit', minute: '2-digit' });
  }

  function openUrl(url) {
    // Inside the desktop app links to the outside world go to the default browser.
    return api('/api/system/open-url', { url }).catch(() => window.open(url, '_blank'));
  }

  function reveal(path) {
    return api('/api/system/reveal', { path }).catch(e => toast(e.message, 'err'));
  }

  function checkUpdates() {
    const t = window.__TAURI__;
    if (t && t.core) return t.core.invoke('check_for_updates');
    toast('ตรวจสอบอัพเดทได้เมื่อเปิดผ่านแอป BuildWeb', 'err');
  }

  // The desktop webview can't open new windows: send target=_blank links to the default browser.
  document.addEventListener('click', e => {
    const a = e.target.closest('a[target=_blank]');
    if (a && window.__TAURI__) { e.preventDefault(); openUrl(a.href); }
  });

  window.BW = { api, toast, esc, modal, confirmBox, formData, showFieldError, bytes, ago, when, openUrl, reveal, checkUpdates, cookie };
})();
