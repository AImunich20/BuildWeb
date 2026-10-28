// Site manager: pages, files, form submissions, settings/theme, export.
(function () {
  const D = JSON.parse(document.getElementById('site-data').textContent);
  const root = document.getElementById('tab');
  const site = D.site;
  const { api, toast, esc, modal, confirmBox, formData, showFieldError, bytes, ago, when } = BW;

  const tabs = { pages: renderPages, files: renderFiles, forms: renderForms, settings: renderSettings, export: renderExport };

  // ---------------------------------------------------------------- pages
  function renderPages() {
    root.innerHTML = `
      <div class="row between" style="margin-bottom:14px">
        <div class="muted">ลากที่ <span class="handle">⋮⋮</span> เพื่อจัดลำดับเมนู · หน้าแรกจะถูกส่งออกเป็น <code>index.html</code></div>
        <div class="row"><button class="btn" id="sync-nav" title="อัปเดตลิงก์ในแถบเมนูและส่วนท้ายของทุกหน้าให้ตรงกับรายการหน้า">↻ อัปเดตเมนูทุกหน้า</button>
        <button class="btn primary" id="add-page">＋ เพิ่มหน้า</button></div>
      </div>
      <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h2>ส่วนหัว & ส่วนท้ายร่วม</h2>
        <div class="hint" style="margin:0">แก้ครั้งเดียว เปลี่ยนทุกหน้า · เมนูอัปเดตตามรายการหน้าอัตโนมัติ</div></div>
        <button class="btn sm" id="extract" title="ย้าย <header>/<footer> ของหน้าแรกมาเป็นส่วนร่วม และลบซ้ำออกจากทุกหน้า">⇪ แยกจากหน้าแรก</button></div>
        <div id="shared-rows"></div></div>
      <div class="card"><table class="table"><thead><tr><th></th><th>หน้า</th><th>ไฟล์</th><th>สถานะ</th><th>เมนู</th><th>แก้ไขล่าสุด</th><th></th></tr></thead>
      <tbody id="page-rows"></tbody></table></div>`;
    drawPageRows();
    drawShared();
    document.getElementById('extract').onclick = async () => {
      if (!await confirmBox('แยกส่วนหัว/ท้ายร่วม', 'นำ &lt;header&gt; และ &lt;footer&gt; ของหน้าแรกมาเป็นส่วนร่วม แล้วลบตัวซ้ำออกจากทุกหน้า (ทุกหน้าถูกเก็บเวอร์ชันไว้ก่อน ย้อนกลับได้)', { ok: 'แยกเลย' })) return;
      try { const r = await api(`/api/sites/${site.id}/shared/extract`, {}); toast(`แยกแล้ว ปรับ ${r.updated} หน้า`, 'ok'); setTimeout(() => location.reload(), 600); }
      catch (e) { toast(e.message, 'err'); }
    };
    document.getElementById('add-page').onclick = () => pageModal(null);
    document.getElementById('sync-nav').onclick = async () => {
      if (!await confirmBox('อัปเดตเมนูทุกหน้า', 'แทนที่ลิงก์ในแถบเมนู (navbar) และเมนูในส่วนท้ายของทุกหน้าด้วยรายการหน้าปัจจุบัน — ลิงก์อื่นที่แก้เองจะไม่ถูกแตะ', { ok: 'อัปเดต' })) return;
      try { const r = await api(`/api/sites/${site.id}/pages/sync-nav`, {}); toast(`อัปเดตแล้ว ${r.updated} หน้า`, 'ok'); }
      catch (e) { toast(e.message, 'err'); }
    };
  }

  function drawShared() {
    const box = document.getElementById('shared-rows');
    const rows = site.shared || [];
    box.innerHTML = rows.map(x => `<div class="list-row" data-id="${x.id}">
        <span class="kind-icon">${x.kind === 'header' ? '⬒' : '⬓'}</span>
        <div style="flex:1"><b>${esc(x.label)}</b><div class="muted small">แก้ไข ${ago(x.updated_at)}</div></div>
        <label class="switch" title="เปิด/ปิดทุกหน้า"><input type="checkbox" ${x.enabled ? 'checked' : ''}><span></span></label>
        <a class="btn sm" href="${x.edit_url}">✎ ออกแบบ</a></div>`).join('') ||
      `<div class="list-row muted">ยังไม่มีส่วนร่วม — <a href="/sites/${site.id}/edit-shared/header/">สร้างส่วนหัว</a> · <a href="/sites/${site.id}/edit-shared/footer/">สร้างส่วนท้าย</a></div>`;
    box.querySelectorAll('[data-id]').forEach(row => {
      row.querySelector('input').onchange = async e => {
        try { const r = await api(`/api/shared/${row.dataset.id}/update`, { enabled: e.target.checked }); toast(r.shared.enabled ? 'เปิดใช้ทุกหน้าแล้ว' : 'ปิดแล้ว', 'ok'); }
        catch (err) { toast(err.message, 'err'); e.target.checked = !e.target.checked; }
      };
    });
    const sync = document.getElementById('sync-nav');
    if (rows.some(x => x.kind === 'header' && x.enabled)) sync.classList.add('hidden');
  }

  function drawPageRows() {
    const tb = document.getElementById('page-rows');
    const byId = Object.fromEntries(D.pages.map(p => [p.id, p]));
    tb.innerHTML = D.pages.map(p => `
      <tr draggable="true" data-id="${p.id}">
        <td class="handle" title="ลากเพื่อเรียงลำดับ">⋮⋮</td>
        <td><div class="page-title">${p.is_home ? '🏠 ' : ''}${p.parent ? '<span class="muted">↳ </span>' : ''}${esc(p.title)}
          <small>${p.parent && byId[p.parent] ? 'อยู่ใต้ ' + esc(byId[p.parent].title) + ' · ' : ''}${p.seo_description ? esc(p.seo_description.slice(0, 70)) : 'ยังไม่มีคำอธิบาย SEO'}</small></div></td>
        <td class="mono small">${esc(p.filename)}</td>
        <td>${p.status === 'published' ? '<span class="badge ok">เผยแพร่</span>' : '<span class="badge warn">ฉบับร่าง</span>'}</td>
        <td>${p.show_in_nav ? esc(p.nav_label || p.title) : '<span class="muted">ซ่อน</span>'}</td>
        <td class="muted small">${ago(p.updated_at)}</td>
        <td><div class="row" style="justify-content:flex-end;flex-wrap:nowrap">
          <a class="btn sm primary" href="${p.edit_url}">✎ ออกแบบ</a>
          <button class="btn sm" data-act="settings">ตั้งค่า</button>
          <button class="btn sm ghost" data-act="more">⋯</button></div></td>
      </tr>`).join('');
    tb.querySelectorAll('tr').forEach(tr => {
      const p = byId[tr.dataset.id];
      tr.querySelector('[data-act=settings]').onclick = () => pageModal(p);
      tr.querySelector('[data-act=more]').onclick = e => pageMenu(p, e.currentTarget);
    });
    enableDrag(tb);
  }

  function enableDrag(tb) {
    let dragging = null;
    tb.querySelectorAll('tr').forEach(tr => {
      tr.addEventListener('dragstart', () => { dragging = tr; tr.style.opacity = '.4'; });
      tr.addEventListener('dragend', () => { tr.style.opacity = ''; tb.querySelectorAll('.drag-over').forEach(x => x.classList.remove('drag-over')); });
      tr.addEventListener('dragover', e => { e.preventDefault(); tr.classList.add('drag-over'); });
      tr.addEventListener('dragleave', () => tr.classList.remove('drag-over'));
      tr.addEventListener('drop', async e => {
        e.preventDefault();
        if (!dragging || dragging === tr) return;
        const rows = [...tb.children];
        if (rows.indexOf(dragging) < rows.indexOf(tr)) tr.after(dragging); else tr.before(dragging);
        const ids = [...tb.children].map(r => +r.dataset.id);
        D.pages.sort((a, b) => ids.indexOf(a.id) - ids.indexOf(b.id));
        try { await api(`/api/sites/${site.id}/pages/reorder`, { ids }); toast('จัดลำดับแล้ว', 'ok'); }
        catch (err) { toast(err.message, 'err'); }
      });
    });
  }

  function pageMenu(p, anchor) {
    const m = modal(`<header><h2>${esc(p.title)}</h2><button class="btn ghost icon" data-close>✕</button></header>
      <div class="body" style="display:grid;gap:8px">
        <a class="btn" href="/preview/${site.slug}/${p.is_home ? '' : p.slug + '.html'}" target="_blank">👁 ดูตัวอย่างหน้านี้</a>
        ${p.is_home ? '' : '<button class="btn" data-a="home">🏠 ตั้งเป็นหน้าแรก</button>'}
        <button class="btn" data-a="status">${p.status === 'published' ? '⏸ เปลี่ยนเป็นฉบับร่าง' : '✓ เผยแพร่หน้านี้'}</button>
        <button class="btn" data-a="dup">⧉ ทำสำเนาหน้า</button>
        <button class="btn danger" data-a="del">🗑 ลบหน้า</button>
      </div>`);
    const act = async (a) => {
      try {
        if (a === 'home') await api(`/api/pages/${p.id}/home`, {});
        if (a === 'status') await api(`/api/pages/${p.id}/update`, { status: p.status === 'published' ? 'draft' : 'published' });
        if (a === 'dup') await api(`/api/pages/${p.id}/duplicate`, {});
        if (a === 'del') {
          m.close();
          if (!await confirmBox('ลบหน้า', `ลบหน้า “${esc(p.title)}” ถาวร? เวอร์ชันย้อนหลังของหน้านี้จะถูกลบด้วย`, { ok: 'ลบหน้า', danger: true })) return;
          await api(`/api/pages/${p.id}/delete`, {});
        }
        location.reload();
      } catch (e) { toast(e.message, 'err'); }
    };
    m.el.querySelectorAll('[data-a]').forEach(b => b.onclick = () => act(b.dataset.a));
  }

  function slugify(s) { return s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60); }

  function pageModal(p) {
    const isNew = !p;
    p = p || { title: '', slug: '', status: 'published', show_in_nav: true, nav_label: '', parent: null, seo_title: '', seo_description: '',
      seo_keywords: '', og_image: '', noindex: false, head_code: '', custom_css: '', custom_js: '', is_home: false };
    const parents = D.pages.filter(x => x.id !== p.id).map(x => `<option value="${x.id}" ${x.id === p.parent ? 'selected' : ''}>${esc(x.title)}</option>`).join('');
    const layouts = D.layouts.map((l, i) => `<label class="opt ${i === 1 ? 'sel' : ''}" style="margin:0"><input type="radio" name="layout" value="${l.id}" ${i === 1 ? 'checked' : ''}>
      <div><b>${esc(l.name)}</b><span>${l.sections.length ? l.sections.length + ' ส่วน' : 'เริ่มจากว่าง'}</span></div></label>`).join('');
    const m = modal(`<header><h2>${isNew ? 'เพิ่มหน้าใหม่' : 'ตั้งค่าหน้า'}</h2><button class="btn ghost icon" data-close>✕</button></header>
      <div class="body">
        <div class="grid g2" style="gap:0 16px">
          <label class="field"><span>ชื่อหน้า *</span><input class="input" name="title" value="${esc(p.title)}" maxlength="200" placeholder="เช่น เกี่ยวกับเรา"></label>
          <label class="field"><span>ชื่อไฟล์ / ลิงก์ <small>(a-z 0-9 -)</small></span>
            <div class="input-group"><span class="prefix">/${esc(site.slug)}/</span><input class="input mono" name="slug" value="${esc(p.slug)}" placeholder="about" maxlength="80"></div></label>
          <label class="field"><span>สถานะ</span><select class="input" name="status">
            <option value="published" ${p.status === 'published' ? 'selected' : ''}>เผยแพร่</option><option value="draft" ${p.status === 'draft' ? 'selected' : ''}>ฉบับร่าง (ไม่แสดงบนเว็บจริง)</option></select></label>
          <label class="field"><span>อยู่ใต้หน้า</span><select class="input" name="parent"><option value="">— ไม่มี —</option>${parents}</select></label>
        </div>
        <div class="row" style="gap:22px;margin-bottom:6px">
          <label class="check"><input type="checkbox" name="show_in_nav" ${p.show_in_nav ? 'checked' : ''}>แสดงในเมนู</label>
          <label class="check"><input type="checkbox" name="use_header" ${p.use_header !== false ? 'checked' : ''}>ใช้ส่วนหัวร่วม</label>
          <label class="check"><input type="checkbox" name="use_footer" ${p.use_footer !== false ? 'checked' : ''}>ใช้ส่วนท้ายร่วม</label>
          <label class="check"><input type="checkbox" name="is_home" ${p.is_home ? 'checked disabled' : ''}>ตั้งเป็นหน้าแรก</label>
        </div>
        <label class="field"><span>ชื่อในเมนู <small>(เว้นว่าง = ใช้ชื่อหน้า)</small></span><input class="input" name="nav_label" value="${esc(p.nav_label)}" maxlength="100"></label>
        ${isNew ? `<div class="sect-title">รูปแบบเริ่มต้น</div><div class="grid g3" style="gap:10px" id="layouts">${layouts}</div>` : ''}
        <div class="sect-title">SEO & การแชร์</div>
        <label class="field"><span>ชื่อเรื่องบน Google <small>(เว้นว่าง = “ชื่อหน้า | ชื่อเว็บ”)</small></span><input class="input" name="seo_title" value="${esc(p.seo_title)}" maxlength="200"></label>
        <label class="field"><span>คำอธิบาย <small id="desc-count"></small></span><textarea class="input" name="seo_description" rows="2" maxlength="320">${esc(p.seo_description)}</textarea></label>
        <div class="grid g2" style="gap:0 16px">
          <label class="field"><span>คีย์เวิร์ด <small>(คั่นด้วย ,)</small></span><input class="input" name="seo_keywords" value="${esc(p.seo_keywords)}"></label>
          <label class="field"><span>รูปตอนแชร์ (og:image)</span><div class="row" style="flex-wrap:nowrap"><input class="input" name="og_image" value="${esc(p.og_image)}" placeholder="/media/..."><button class="btn sm" type="button" data-pick="og_image">เลือก</button></div></label>
        </div>
        <label class="check"><input type="checkbox" name="noindex" ${p.noindex ? 'checked' : ''}>ไม่ให้เครื่องมือค้นหาเก็บหน้านี้ (noindex)</label>
        <details style="margin-top:8px"><summary style="cursor:pointer;font-weight:500">โค้ดเพิ่มเติม (ขั้นสูง)</summary><div style="margin-top:12px">
          <label class="field"><span>โค้ดใน &lt;head&gt;</span><textarea class="input code" name="head_code" placeholder="<meta ...> หรือ Google Analytics">${esc(p.head_code)}</textarea></label>
          <label class="field"><span>CSS เฉพาะหน้านี้</span><textarea class="input code" name="custom_css">${esc(p.custom_css)}</textarea></label>
          <label class="field"><span>JavaScript เฉพาะหน้านี้</span><textarea class="input code" name="custom_js">${esc(p.custom_js)}</textarea></label>
        </div></details>
      </div>
      <footer>${isNew ? '' : `<a class="btn" href="${p.edit_url}" style="margin-right:auto">✎ ไปออกแบบ</a>`}<button class="btn" data-close>ยกเลิก</button>
        <button class="btn primary" data-save>${isNew ? 'สร้างหน้า' : 'บันทึก'}</button></footer>`, { wide: true });
    const title = m.el.querySelector('[name=title]'), slug = m.el.querySelector('[name=slug]');
    let slugTouched = !isNew;
    slug.addEventListener('input', () => slugTouched = true);
    title.addEventListener('input', () => { if (!slugTouched) slug.value = slugify(title.value); });
    const desc = m.el.querySelector('[name=seo_description]'), cnt = m.el.querySelector('#desc-count');
    const upd = () => cnt.textContent = `${desc.value.length}/160 ตัวอักษรแนะนำ`;
    desc.addEventListener('input', upd); upd();
    m.el.querySelectorAll('#layouts .opt').forEach(o => o.addEventListener('click', () => {
      m.el.querySelectorAll('#layouts .opt').forEach(x => x.classList.remove('sel')); o.classList.add('sel');
    }));
    m.el.querySelectorAll('[data-pick]').forEach(b => b.onclick = () => pickAsset(url => m.el.querySelector(`[name=${b.dataset.pick}]`).value = url));
    m.el.querySelector('[data-save]').onclick = async () => {
      const d = formData(m.el);
      if (!p.is_home && !d.is_home) delete d.is_home;
      try {
        const r = isNew ? await api(`/api/sites/${site.id}/pages/create`, d) : await api(`/api/pages/${p.id}/update`, d);
        if (isNew) {
          if (await confirmBox('สร้างหน้าแล้ว', `เปิดหน้า “${esc(r.page.title)}” ในตัวออกแบบเลยไหม? <br><small class="muted">อย่าลืมกด “อัปเดตเมนูทุกหน้า” ถ้าต้องการให้หน้านี้ขึ้นในแถบเมนูของหน้าอื่น</small>`, { ok: 'เปิดตัวออกแบบ' }))
            location.href = r.page.edit_url;
          else location.reload();
        } else location.reload();
      } catch (e) { showFieldError(m.el, e); }
    };
  }

  // ---------------------------------------------------------------- files
  let fmFolder = '';
  let fmState = { assets: [], folders: [] };

  async function loadAssets() {
    fmState = await api(`/api/sites/${site.id}/assets`);
  }

  async function renderFiles() {
    root.innerHTML = `<div class="fm">
      <div class="card fm-folders"><div class="row between" style="padding:2px 6px 8px"><b>โฟลเดอร์</b><button class="btn sm ghost" id="new-folder" title="สร้างโฟลเดอร์">＋</button></div><div id="folders"></div></div>
      <div><div class="drop" id="drop">ลากไฟล์มาวางที่นี่ หรือ <a href="#" id="pick">เลือกไฟล์</a> — รูป วิดีโอ PDF ฯลฯ (สูงสุด 200 MB ต่อไฟล์)
        <input type="file" id="file-input" multiple hidden><div class="progress hidden" id="prog"><i></i></div></div>
        <div class="row between" style="margin-bottom:12px"><div class="row"><input class="input" id="q" placeholder="ค้นหาไฟล์..." style="width:220px">
          <select class="input" id="kind" style="width:150px"><option value="">ทุกประเภท</option><option value="image">รูปภาพ</option><option value="video">วิดีโอ</option><option value="audio">เสียง</option><option value="document">เอกสาร</option><option value="other">อื่นๆ</option></select></div>
          <span class="muted small" id="fm-sum"></span></div>
        <div class="fm-grid" id="fm-grid"></div></div></div>`;
    await loadAssets();
    drawFolders(); drawAssets();
    const input = document.getElementById('file-input');
    document.getElementById('pick').onclick = e => { e.preventDefault(); input.click(); };
    input.onchange = () => upload(input.files);
    const drop = document.getElementById('drop');
    ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); }));
    ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); }));
    drop.addEventListener('drop', e => upload(e.dataTransfer.files));
    document.getElementById('q').oninput = drawAssets;
    document.getElementById('kind').onchange = drawAssets;
    document.getElementById('new-folder').onclick = newFolder;
  }

  function drawFolders() {
    const el = document.getElementById('folders');
    const count = f => fmState.assets.filter(a => a.folder === f).length;
    const item = (f, label, depth = 0) => `<a data-f="${esc(f)}" class="${f === fmFolder ? 'active' : ''}" style="padding-left:${10 + depth * 14}px">${f ? '📁' : '🗂'} ${esc(label)} <span class="muted small" style="margin-left:auto">${count(f)}</span></a>`;
    el.innerHTML = item('', 'ไฟล์ทั้งหมด (ราก)') + fmState.folders.map(f => item(f, f.split('/').pop(), f.split('/').length)).join('');
    el.querySelectorAll('a').forEach(a => a.onclick = () => { fmFolder = a.dataset.f; drawFolders(); drawAssets(); });
  }

  function drawAssets() {
    const q = (document.getElementById('q').value || '').toLowerCase();
    const kind = document.getElementById('kind').value;
    const list = fmState.assets.filter(a => a.folder === fmFolder && (!q || a.name.toLowerCase().includes(q)) && (!kind || a.kind === kind));
    const icons = { video: '🎬', audio: '🎵', document: '📄', other: '📦' };
    const grid = document.getElementById('fm-grid');
    const sub = fmState.folders.filter(f => f.startsWith(fmFolder ? fmFolder + '/' : '') && f.split('/').length === (fmFolder ? fmFolder.split('/').length + 1 : 1));
    grid.innerHTML = sub.map(f => `<div class="fm-item" data-folder="${esc(f)}"><div class="pv">📁</div><div class="nm">${esc(f.split('/').pop())}<small>โฟลเดอร์</small></div></div>`).join('') +
      list.map(a => `<div class="fm-item" data-id="${a.id}"><div class="pv" ${a.kind === 'image' ? `style="background-image:url('${encodeURI(a.url)}')"` : ''}>${a.kind === 'image' ? '' : icons[a.kind] || '📦'}</div>
        <div class="nm" title="${esc(a.name)}">${esc(a.name)}<small>${bytes(a.size)}</small></div></div>`).join('');
    if (!sub.length && !list.length) grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1"><div class="big">🖼</div>โฟลเดอร์นี้ยังไม่มีไฟล์</div>`;
    const total = fmState.assets.reduce((s, a) => s + a.size, 0);
    document.getElementById('fm-sum').textContent = `${fmState.assets.length} ไฟล์ · ${bytes(total)}`;
    grid.querySelectorAll('[data-folder]').forEach(el => {
      el.onclick = () => { fmFolder = el.dataset.folder; drawFolders(); drawAssets(); };
    });
    grid.querySelectorAll('[data-id]').forEach(el => el.onclick = () => assetModal(fmState.assets.find(a => a.id === +el.dataset.id)));
  }

  function upload(files) {
    if (!files || !files.length) return;
    const fd = new FormData();
    [...files].forEach(f => fd.append('files', f));
    fd.append('folder', fmFolder);
    const prog = document.getElementById('prog'), bar = prog.querySelector('i');
    prog.classList.remove('hidden'); bar.style.width = '0';
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `/api/sites/${site.id}/assets/upload`);
    xhr.setRequestHeader('X-CSRFToken', BW.cookie('buildweb_csrf'));
    xhr.upload.onprogress = e => { if (e.lengthComputable) bar.style.width = (e.loaded / e.total * 100) + '%'; };
    xhr.onload = async () => {
      prog.classList.add('hidden');
      let r = {};
      try { r = JSON.parse(xhr.responseText); } catch (e) { }
      if (!r.ok) return toast(r.error || 'อัปโหลดไม่สำเร็จ', 'err');
      toast(`อัปโหลดแล้ว ${r.assets.length} ไฟล์`, 'ok');
      await loadAssets(); drawFolders(); drawAssets();
    };
    xhr.onerror = () => { prog.classList.add('hidden'); toast('อัปโหลดไม่สำเร็จ', 'err'); };
    xhr.send(fd);
    document.getElementById('file-input').value = '';
  }

  async function newFolder() {
    const m = modal(`<header><h2>สร้างโฟลเดอร์</h2></header><div class="body">
      <label class="field"><span>ชื่อโฟลเดอร์</span><input class="input" name="name" placeholder="เช่น images"></label>
      <div class="muted small">จะสร้างไว้ใน: ${fmFolder ? esc(fmFolder) : 'ราก'}</div></div>
      <footer><button class="btn" data-close>ยกเลิก</button><button class="btn primary" data-ok>สร้าง</button></footer>`);
    const go = async () => {
      const name = m.el.querySelector('[name=name]').value.trim();
      try {
        const r = await api(`/api/sites/${site.id}/folders/create`, { path: (fmFolder ? fmFolder + '/' : '') + name });
        fmState.folders = r.folders; m.close(); drawFolders(); drawAssets();
      } catch (e) { toast(e.message, 'err'); }
    };
    m.el.querySelector('[data-ok]').onclick = go;
    m.el.querySelector('[name=name]').onkeydown = e => { if (e.key === 'Enter') go(); };
  }

  function assetModal(a) {
    const folders = ['', ...fmState.folders].map(f => `<option value="${esc(f)}" ${f === a.folder ? 'selected' : ''}>${f ? esc(f) : '— ราก —'}</option>`).join('');
    const pv = a.kind === 'image' ? `<img src="${encodeURI(a.url)}" style="max-width:100%;max-height:300px;border-radius:12px;display:block;margin:0 auto 16px;background:#f6f6fa">`
      : a.kind === 'video' ? `<video src="${encodeURI(a.url)}" controls style="width:100%;border-radius:12px;margin-bottom:16px"></video>` : '';
    const m = modal(`<header><h2>รายละเอียดไฟล์</h2><button class="btn ghost icon" data-close>✕</button></header><div class="body">${pv}
      <div class="grid g2" style="gap:0 16px"><label class="field"><span>ชื่อไฟล์</span><input class="input" name="name" value="${esc(a.name)}"></label>
      <label class="field"><span>โฟลเดอร์</span><select class="input" name="folder">${folders}</select></label></div>
      ${a.kind === 'image' ? `<label class="field"><span>คำอธิบายรูป (alt) <small>ช่วย SEO และผู้พิการทางสายตา</small></span><input class="input" name="alt" value="${esc(a.alt)}"></label>` : ''}
      <label class="field"><span>ลิงก์สำหรับใช้ในหน้าเว็บ</span><div class="row" style="flex-wrap:nowrap"><input class="input mono" readonly value="${esc(a.url)}" id="a-url"><button class="btn sm" id="copy">คัดลอก</button></div></label>
      <div class="muted small">${bytes(a.size)} · อัปโหลด ${when(a.created_at)}</div></div>
      <footer><button class="btn danger" data-del style="margin-right:auto">ลบไฟล์</button><button class="btn" data-close>ปิด</button><button class="btn primary" data-save>บันทึก</button></footer>`);
    m.el.querySelector('#copy').onclick = () => { navigator.clipboard.writeText(a.url); toast('คัดลอกลิงก์แล้ว', 'ok'); };
    m.el.querySelector('[data-save]').onclick = async () => {
      try { await api(`/api/assets/${a.id}/update`, formData(m.el)); m.close(); toast('บันทึกแล้ว', 'ok'); await loadAssets(); drawFolders(); drawAssets(); }
      catch (e) { showFieldError(m.el, e); }
    };
    m.el.querySelector('[data-del]').onclick = async () => {
      try { await api(`/api/assets/${a.id}/delete`, {}); }
      catch (e) {
        if (!e.in_use) return toast(e.message, 'err');
        if (!await confirmBox('ไฟล์นี้ถูกใช้อยู่', `ใช้อยู่ในหน้า: <b>${e.in_use.map(esc).join(', ')}</b><br>ลบแล้วรูป/ลิงก์ในหน้าเหล่านั้นจะเสีย ยืนยันลบ?`, { ok: 'ลบเลย', danger: true })) return;
        await api(`/api/assets/${a.id}/delete`, { force: true });
      }
      m.close(); toast('ลบไฟล์แล้ว', 'ok'); await loadAssets(); drawFolders(); drawAssets();
    };
  }

  async function pickAsset(cb) {
    const r = await api(`/api/sites/${site.id}/assets?kind=image`);
    const m = modal(`<header><h2>เลือกรูปภาพ</h2><button class="btn ghost icon" data-close>✕</button></header><div class="body">
      ${r.assets.length ? `<div class="fm-grid">${r.assets.map(a => `<div class="fm-item" data-url="${esc(a.url)}"><div class="pv" style="background-image:url('${encodeURI(a.url)}')"></div><div class="nm">${esc(a.name)}</div></div>`).join('')}</div>`
        : '<div class="empty-state">ยังไม่มีรูป — อัปโหลดได้ที่แท็บ “ไฟล์ & รูปภาพ”</div>'}</div>`, { wide: true });
    m.el.querySelectorAll('[data-url]').forEach(el => el.onclick = () => { cb(el.dataset.url); m.close(); });
  }

  // ---------------------------------------------------------------- forms
  async function renderForms() {
    root.innerHTML = `<div class="row between" style="margin-bottom:14px"><div class="muted">ข้อมูลที่ผู้เข้าชมกรอกในฟอร์มบนเว็บ (บันทึกลงฐานข้อมูลของโปรแกรม — <a href="/settings/database/">ตั้งค่าฐานข้อมูล</a>)</div>
      <div class="row"><button class="btn" id="read-all">✓ อ่านทั้งหมด</button><a class="btn" href="/sites/${site.id}/forms.csv">⬇ ดาวน์โหลด CSV (Excel)</a></div></div>
      <div class="card" id="subs"><div class="empty-state">กำลังโหลด...</div></div>`;
    const r = await api(`/api/sites/${site.id}/submissions`);
    const box = document.getElementById('subs');
    if (!r.submissions.length) {
      box.innerHTML = `<div class="empty-state"><div class="big">📭</div>ยังไม่มีข้อมูลจากฟอร์ม<br><small>เพิ่มบล็อก “ฟอร์มติดต่อ” ในตัวออกแบบ แล้วเปิดโฮสติ้งเพื่อให้ผู้คนส่งข้อความได้</small></div>`;
    } else {
      box.innerHTML = r.submissions.map(s => `<div class="sub-item ${s.is_read ? '' : 'unread'}" data-id="${s.id}">
        <div><div class="row"><b>${esc(s.form || 'ฟอร์ม')}</b>${s.page ? `<span class="badge">${esc(s.page)}</span>` : ''}${s.is_read ? '' : '<span class="badge brand">ใหม่</span>'}<span class="muted small">${when(s.created_at)}</span></div>
        <dl>${Object.entries(s.data).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(Array.isArray(v) ? v.join(', ') : v)}</dd>`).join('')}</dl></div>
        <div class="row" style="align-items:flex-start"><button class="btn sm" data-a="read">${s.is_read ? 'ทำเป็นยังไม่อ่าน' : 'อ่านแล้ว'}</button><button class="btn sm danger" data-a="delete">ลบ</button></div></div>`).join('');
      box.querySelectorAll('.sub-item').forEach(el => {
        const s = r.submissions.find(x => x.id === +el.dataset.id);
        el.querySelector('[data-a=read]').onclick = async () => { await api(`/api/submissions/${s.id}/read`, { value: !s.is_read }); renderForms(); };
        el.querySelector('[data-a=delete]').onclick = async () => {
          if (!await confirmBox('ลบข้อมูล', 'ลบข้อมูลฟอร์มนี้ถาวร?', { ok: 'ลบ', danger: true })) return;
          await api(`/api/submissions/${s.id}/delete`, {}); renderForms();
        };
      });
    }
    document.getElementById('read-all').onclick = async () => { await api(`/api/sites/${site.id}/submissions/read-all`, {}); renderForms(); };
  }

  // ---------------------------------------------------------------- settings
  const FONTS = ['Prompt', 'Kanit', 'Sarabun', 'Noto Sans Thai', 'Mitr', 'IBM Plex Sans Thai', 'Bai Jamjuree', 'Chakra Petch', 'Anuphan', 'K2D', 'Niramit',
    'Pridi', 'Taviraj', 'Trirong', 'Noto Serif Thai', 'Inter', 'Poppins', 'Roboto', 'Montserrat', 'Open Sans', 'Playfair Display', 'Lora'];
  const COLORS = [['primary', 'สีหลัก'], ['secondary', 'สีรอง'], ['accent', 'สีเน้น'], ['text', 'สีตัวอักษร'], ['muted', 'สีข้อความรอง'], ['background', 'สีพื้นหลัง'], ['surface', 'สีพื้นส่วนเน้น']];
  const PALETTES = [
    ['ม่วง-ฟ้า', { primary: '#7c3aed', secondary: '#06b6d4', accent: '#f59e0b', surface: '#f5f3ff' }],
    ['คาเฟ่', { primary: '#b45309', secondary: '#f59e0b', accent: '#16a34a', surface: '#fffbeb' }],
    ['ธรรมชาติ', { primary: '#059669', secondary: '#0ea5e9', accent: '#f97316', surface: '#ecfdf5' }],
    ['ชมพู', { primary: '#ec4899', secondary: '#8b5cf6', accent: '#14b8a6', surface: '#fdf2f8' }],
    ['องค์กร', { primary: '#1d4ed8', secondary: '#0f172a', accent: '#eab308', surface: '#eff6ff' }],
    ['มินิมอล', { primary: '#111827', secondary: '#6b7280', accent: '#ef4444', surface: '#f3f4f6' }],
  ];

  function renderSettings() {
    const t = site.theme;
    root.innerHTML = `<div class="grid g2">
      <div class="card pad"><h2>ข้อมูลเว็บไซต์</h2><div class="hint">ชื่อ คำอธิบาย และการเผยแพร่</div>
        <label class="field"><span>ชื่อเว็บไซต์</span><input class="input" name="name" value="${esc(site.name)}"></label>
        <label class="field"><span>ชื่อในลิงก์</span><div class="input-group"><span class="prefix">http://…/</span><input class="input mono" name="slug" value="${esc(site.slug)}"></div>
          <small>ใช้ในลิงก์ของโฮสติ้งและชื่อโฟลเดอร์ตอนส่งออก</small></label>
        <label class="field"><span>คำอธิบายเว็บ</span><textarea class="input" name="description" rows="2">${esc(site.description)}</textarea></label>
        <label class="field"><span>ภาษา</span><select class="input" name="language"><option value="th" ${site.language === 'th' ? 'selected' : ''}>ไทย</option><option value="en" ${site.language === 'en' ? 'selected' : ''}>English</option></select></label>
        <label class="field"><span>ไอคอนเว็บ (favicon)</span><div class="row" style="flex-wrap:nowrap"><input class="input" name="favicon" value="${esc(site.favicon)}" placeholder="/media/..."><button class="btn sm" type="button" id="pick-fav">เลือก</button></div></label>
        <label class="check"><input type="checkbox" name="published" ${site.published ? 'checked' : ''}>เผยแพร่เว็บนี้บนโฮสติ้ง</label>
        <label class="field"><span>ที่ส่งฟอร์มเมื่อส่งออกเป็นไฟล์ <small>(ไม่บังคับ)</small></span><input class="input mono" name="form_endpoint" value="${esc(site.form_endpoint)}" placeholder="เช่น http://192.168.1.10:8090/${esc(site.slug)}/__form">
          <small>เว้นว่างไว้ = ฟอร์มส่งเข้า BuildWeb ตอนโฮสต์ และใช้ bw-form.php ตอนส่งออกไป XAMPP</small></label>
      </div>
      <div class="card pad"><h2>ธีม</h2><div class="hint">สีและฟอนต์ที่ใช้ทั่วทั้งเว็บ — บล็อกสำเร็จรูปทุกอันจะเปลี่ยนตาม</div>
        <div class="row" style="margin-bottom:14px">${PALETTES.map(([n, p], i) => `<button class="btn sm" data-pal="${i}"><span style="display:inline-flex;gap:2px">${['primary', 'secondary', 'accent'].map(k => `<i style="width:12px;height:12px;border-radius:4px;background:${p[k]}"></i>`).join('')}</span>${n}</button>`).join('')}</div>
        <div class="grid g2" style="gap:0 16px">${COLORS.map(([k, l]) => `<label class="field"><span>${l}</span><div class="color-row"><input type="color" data-theme="${k}" value="${t[k]}"><input class="input mono" data-theme-text="${k}" value="${t[k]}"></div></label>`).join('')}</div>
        <div class="grid g2" style="gap:0 16px">
          <label class="field"><span>ฟอนต์หัวข้อ</span><select class="input" data-theme="font_heading">${FONTS.map(f => `<option ${f === t.font_heading ? 'selected' : ''}>${f}</option>`).join('')}</select></label>
          <label class="field"><span>ฟอนต์เนื้อหา</span><select class="input" data-theme="font_body">${FONTS.map(f => `<option ${f === t.font_body ? 'selected' : ''}>${f}</option>`).join('')}</select></label>
          <label class="field"><span>ความโค้งมุม</span><select class="input" data-theme="radius">${['0px', '6px', '10px', '14px', '20px', '28px'].map(v => `<option ${v === t.radius ? 'selected' : ''}>${v}</option>`).join('')}</select></label>
          <label class="field"><span>ความกว้างเนื้อหาสูงสุด</span><select class="input" data-theme="max_width">${['960px', '1040px', '1140px', '1280px', '1440px'].map(v => `<option ${v === t.max_width ? 'selected' : ''}>${v}</option>`).join('')}</select></label>
        </div>
      </div>
      <div class="card pad" style="grid-column:1/-1"><h2>โค้ดเพิ่มเติมทุกหน้า</h2><div class="hint">เช่น Google Analytics, Facebook Pixel, CSS/JS ของคุณเอง</div>
        <div class="grid g3"><label class="field"><span>โค้ดใน &lt;head&gt;</span><textarea class="input code" name="head_code">${esc(site.head_code)}</textarea></label>
        <label class="field"><span>CSS</span><textarea class="input code" name="custom_css">${esc(site.custom_css)}</textarea></label>
        <label class="field"><span>JavaScript</span><textarea class="input code" name="custom_js">${esc(site.custom_js)}</textarea></label></div></div>
    </div>
    <div class="row between" style="margin-top:20px"><div class="row"><button class="btn" id="dup-site">⧉ ทำสำเนาเว็บ</button><button class="btn danger" id="del-site">🗑 ลบเว็บนี้</button></div>
      <button class="btn primary" id="save-site">บันทึกการตั้งค่า</button></div>`;
    const theme = { ...t };
    root.querySelectorAll('[data-theme]').forEach(el => el.addEventListener('input', () => {
      theme[el.dataset.theme] = el.value;
      const txt = root.querySelector(`[data-theme-text="${el.dataset.theme}"]`); if (txt) txt.value = el.value;
    }));
    root.querySelectorAll('[data-theme-text]').forEach(el => el.addEventListener('input', () => {
      if (/^#[0-9a-f]{6}$/i.test(el.value)) { theme[el.dataset.themeText] = el.value; root.querySelector(`[data-theme="${el.dataset.themeText}"]`).value = el.value; }
    }));
    root.querySelectorAll('[data-pal]').forEach(b => b.onclick = () => {
      Object.entries(PALETTES[b.dataset.pal][1]).forEach(([k, v]) => {
        theme[k] = v; root.querySelector(`[data-theme="${k}"]`).value = v; root.querySelector(`[data-theme-text="${k}"]`).value = v;
      });
    });
    document.getElementById('pick-fav').onclick = () => pickAsset(u => root.querySelector('[name=favicon]').value = u);
    document.getElementById('save-site').onclick = async () => {
      const d = formData(root);
      d.theme = theme;
      try { const r = await api(`/api/sites/${site.id}/update`, d); Object.assign(site, r.site); toast('บันทึกแล้ว', 'ok'); }
      catch (e) { showFieldError(root, e); }
    };
    document.getElementById('dup-site').onclick = async () => {
      try { const r = await api(`/api/sites/${site.id}/duplicate`, {}); location.href = `/sites/${r.site.id}/`; } catch (e) { toast(e.message, 'err'); }
    };
    document.getElementById('del-site').onclick = async () => {
      if (!await confirmBox('ลบเว็บไซต์', `ลบ “${esc(site.name)}” พร้อมทุกหน้า ไฟล์ และข้อมูลฟอร์มถาวร — ย้อนกลับไม่ได้`, { ok: 'ลบถาวร', danger: true })) return;
      try { await api(`/api/sites/${site.id}/delete`, {}); location.href = '/'; } catch (e) { toast(e.message, 'err'); }
    };
  }

  // ---------------------------------------------------------------- export
  function renderExport() {
    const ex = D.export || {};
    const h = D.hosting;
    const target = ex.last_target || 'downloads';
    const opt = (val, title, desc, disabled) => `<label class="opt ${val === target ? 'sel' : ''}" ${disabled ? 'style="opacity:.5"' : ''}><input type="radio" name="target" value="${val}" ${val === target ? 'checked' : ''} ${disabled ? 'disabled' : ''}><div><b>${title}</b><span>${desc}</span></div></label>`;
    root.innerHTML = `<div class="grid g2">
      <div class="card pad"><h2>ส่งออกเป็นไฟล์ HTML / CSS / JS</h2><div class="hint">ได้โฟลเดอร์เว็บที่ใช้งานได้ทันที เปิดจากเครื่อง อัปขึ้นโฮสต์ใดก็ได้</div>
        ${opt('downloads', '📁 โฟลเดอร์ดาวน์โหลด', '~/Downloads/BuildWeb/' + esc(site.slug))}
        ${opt('xampp', '🟧 XAMPP htdocs', D.xampp.htdocs ? `${esc(D.xampp.htdocs)}/${esc(site.slug)} → เปิดที่ http://localhost/${esc(site.slug)}/` : 'ไม่พบ XAMPP ในเครื่อง', !D.xampp.htdocs)}
        ${opt('custom', '📂 เลือกโฟลเดอร์เอง', 'ระบุตำแหน่งด้านล่าง')}
        <input class="input mono ${target === 'custom' ? '' : 'hidden'}" name="custom_path" value="${esc(ex.custom_path || '')}" placeholder="/Users/you/Sites" style="margin-bottom:12px">
        <div class="row" style="gap:20px;margin:6px 0 12px"><label class="check"><input type="radio" name="format" value="folder" checked>โฟลเดอร์</label><label class="check"><input type="radio" name="format" value="zip">ไฟล์ .zip</label></div>
        <label class="check"><input type="checkbox" name="php_forms" ${target === 'xampp' ? 'checked' : ''}>ใส่ตัวรับฟอร์ม PHP (<code>bw-form.php</code>) บันทึกลง MySQL ของ XAMPP</label>
        <label class="check"><input type="checkbox" name="include_drafts">รวมหน้าฉบับร่างด้วย</label>
        <button class="btn primary" id="do-export" style="margin-top:8px">⬇ ส่งออก</button>
        <div id="ex-result" style="margin-top:14px"></div>
        <div class="muted small" style="margin-top:12px">โครงสร้าง: <code>index.html</code>, <code>&lt;หน้า&gt;.html</code>, <code>css/</code>, <code>js/site.js</code>, <code>assets/</code></div>
      </div>
      <div class="card pad"><h2>โฮสต์เว็บจากเครื่องนี้</h2><div class="hint">ให้คนในเครือข่ายเดียวกัน (Wi-Fi เดียวกัน) เปิดเว็บได้ทันที</div>
        ${h.running ? `<div class="alert ok">● โฮสติ้งเปิดอยู่</div>
          ${h.urls.map(u => `<div class="row" style="margin-bottom:8px"><code style="flex:1">${esc(u + site.slug)}/</code><a class="btn sm" href="${esc(u + site.slug)}/" target="_blank">เปิด</a></div>`).join('')}
          ${site.published ? '' : '<div class="alert warn">เว็บนี้ปิดการเผยแพร่อยู่ — เปิดได้ที่แท็บ “ตั้งค่าเว็บ”</div>'}`
        : `<div class="alert warn">โฮสติ้งยังปิดอยู่</div>`}
        <a class="btn" href="/settings/">⚙ ตั้งค่าโฮสติ้ง</a>
        <div class="sect-title">ตัวอย่างในเครื่อง</div>
        <div class="row"><code style="flex:1">${location.origin}/preview/${esc(site.slug)}/</code><a class="btn sm" href="/preview/${esc(site.slug)}/" target="_blank">เปิด</a></div>
        <div class="muted small" style="margin-top:6px">หน้าตัวอย่างแสดงหน้าฉบับร่างด้วย และเปิดได้เฉพาะเครื่องนี้</div>
      </div></div>`;
    const custom = root.querySelector('[name=custom_path]');
    root.querySelectorAll('[name=target]').forEach(r => r.addEventListener('change', () => {
      root.querySelectorAll('.opt').forEach(o => o.classList.toggle('sel', o.querySelector('input').checked));
      custom.classList.toggle('hidden', r.value !== 'custom' || !r.checked);
      if (r.checked) root.querySelector('[name=php_forms]').checked = r.value === 'xampp';
    }));
    document.getElementById('do-export').onclick = async (e) => {
      const btn = e.currentTarget; btn.disabled = true;
      const out = document.getElementById('ex-result');
      out.innerHTML = '<div class="muted">กำลังส่งออก...</div>';
      try {
        const r = await api(`/api/sites/${site.id}/export`, formData(root));
        out.innerHTML = `<div class="alert ok"><div>✓ ส่งออกแล้ว ${r.count} ไฟล์<br><code>${esc(r.path)}</code></div></div>
          <div class="row"><button class="btn sm" id="reveal">เปิดใน Finder</button>${r.url ? `<a class="btn sm" href="${esc(r.url)}" target="_blank">เปิด ${esc(r.url)}</a>` : ''}</div>`;
        document.getElementById('reveal').onclick = () => BW.reveal(r.path);
      } catch (err) { out.innerHTML = `<div class="alert err">${esc(err.message)}</div>`; }
      btn.disabled = false;
    };
  }
  // Run last: the tab renderers use constants declared above.
  (tabs[root.dataset.tab] || renderPages)();
})();
