// Site manager: pages, files, form submissions, settings/theme, export.
(function () {
  const D = JSON.parse(document.getElementById('site-data').textContent);
  const root = document.getElementById('tab');
  const site = D.site;
  const { api, toast, esc, modal, confirmBox, formData, showFieldError, bytes, ago, when } = BW;

  const tabs = { data: renderData, api: renderApi, pages: renderPages, files: renderFiles, forms: renderForms, stats: renderStats, settings: renderSettings, export: renderExport };



  // ---------------------------------------------------------------- navbar settings
  const NAV_LAYOUTS = [
    ['split', 'โลโก้ซ้าย · เมนูขวา', '▣ ─── ≡ ≡ ≡ [ ]'],
    ['center-menu', 'เมนูกลาง', '▣ ── ≡ ≡ ≡ ── [ ]'],
    ['center-logo', 'โลโก้กลาง', '    ▣\n ≡ ≡ ≡ ≡ [ ]'],
    ['minimal', 'มินิมอล (ปุ่มเมนู)', '▣ ─────── ☰'],
  ];
  const NAV_MOBILE = [['drawer', 'เลื่อนจากด้านข้าง'], ['dropdown', 'ดรอปดาวน์'], ['fullscreen', 'เต็มจอ']];

  async function navbarModal() {
    let r;
    try { r = await api(`/api/sites/${site.id}/navbar`); } catch (e) { return toast(e.message, 'err'); }
    let st = r.settings;
    const pageOpts = r.pages.map(p => `<option value="${esc(p.href)}">${esc(p.title)}</option>`).join('');
    const m = modal(`<header><h2>ตั้งค่าแถบเมนู</h2><button class="btn ghost icon sm" data-close>${BW_ICON('x')}</button></header>
      <div class="body nav-modal">
        <div class="nav-form">
          <div class="alert ${r.managed ? 'info' : 'warn'}" style="margin-bottom:12px"><div>${r.managed
            ? 'แถบเมนูสร้างจากการตั้งค่านี้ — เมนูอัปเดตตามรายการหน้าอัตโนมัติ'
            : 'ตอนนี้ส่วนหัวถูก “ออกแบบเอง” ในตัวออกแบบ — เปิดใช้ตัวตั้งค่าเพื่อแทนที่ด้วยแถบเมนูสำเร็จรูป'}</div></div>
          <div class="row" style="margin-bottom:6px">${r.managed
            ? `<button class="btn sm" id="nv-free">${BW_ICON('layers')} ออกแบบเองในตัวออกแบบ</button>`
            : `<button class="btn sm primary" id="nv-managed">${BW_ICON('check')} ใช้ตัวตั้งค่าแถบเมนู</button>`}</div>

          <div class="sect-title">รูปแบบ</div>
          <div class="nav-layouts">${NAV_LAYOUTS.map(([id, label, art]) => `<label class="nav-layout ${st.layout === id ? 'sel' : ''}">
            <input type="radio" name="layout" value="${id}" ${st.layout === id ? 'checked' : ''}><pre>${art}</pre><span>${label}</span></label>`).join('')}</div>

          <div class="sect-title">โลโก้</div>
          <div class="grid g2" style="gap:0 12px">
            <label class="field"><span>ข้อความโลโก้ <small>(เว้นว่าง = ชื่อเว็บ)</small></span><input class="input" name="logo_text" value="${esc(st.logo_text)}" placeholder="${esc(site.name)}"></label>
            <label class="field"><span>ความสูงโลโก้ (px)</span><input class="input mono" type="number" name="logo_height" value="${st.logo_height}"></label>
          </div>
          <label class="field"><span>รูปโลโก้ <small>(ใช้แทนข้อความ)</small></span><div class="row" style="flex-wrap:nowrap"><input class="input" name="logo_image" value="${esc(st.logo_image)}" placeholder="/media/...">
            <button class="btn sm" type="button" id="nv-logo">เลือก</button><button class="btn sm ghost" type="button" id="nv-logo-clear">ล้าง</button></div></label>

          <div class="sect-title">การทำงาน</div>
          <label class="check"><input type="checkbox" name="sticky" ${st.sticky ? 'checked' : ''}>ติดด้านบนตอนเลื่อน</label>
          <label class="check"><input type="checkbox" name="transparent" ${st.transparent ? 'checked' : ''}>ใสทับหัวเว็บ แล้วเป็นสีทึบเมื่อเลื่อนลง</label>
          <label class="check"><input type="checkbox" name="autohide" ${st.autohide ? 'checked' : ''}>ซ่อนเมื่อเลื่อนลง แสดงเมื่อเลื่อนขึ้น</label>
          <label class="check"><input type="checkbox" name="shadow" ${st.shadow ? 'checked' : ''}>มีเงาใต้แถบ</label>
          <div class="grid g2" style="gap:0 12px;margin-top:6px">
            <label class="field"><span>เมนูบนมือถือ</span><select class="input" name="mobile">${NAV_MOBILE.map(([v, l]) => `<option value="${v}" ${st.mobile === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
            <label class="field"><span>ความสูงแถบ (px)</span><input class="input mono" type="number" name="height" value="${st.height}"></label>
            <label class="field"><span>สีพื้น <small>(ว่าง = ตามธีม)</small></span><div class="color-row"><input type="color" data-color="bg" value="${st.bg || '#ffffff'}"><input class="input mono" name="bg" value="${esc(st.bg)}" placeholder="ตามธีม"></div></label>
            <label class="field"><span>สีตัวอักษร <small>(ว่าง = ตามธีม)</small></span><div class="color-row"><input type="color" data-color="color" value="${st.color || '#1f2937'}"><input class="input mono" name="color" value="${esc(st.color)}" placeholder="ตามธีม"></div></label>
          </div>

          <div class="sect-title">เมนู</div>
          <div class="seg" id="nv-mode"><button data-v="auto" class="${st.menu_mode !== 'custom' ? 'on' : ''}">อัตโนมัติจากรายการหน้า</button><button data-v="custom" class="${st.menu_mode === 'custom' ? 'on' : ''}">จัดเอง</button></div>
          <div class="small muted" id="nv-auto-hint" style="margin-top:8px">ใช้หน้าที่ติ๊ก “แสดงในเมนู” · หน้าที่มีหน้าแม่จะเป็นเมนูย่อย · จัดลำดับได้ที่แท็บ “หน้าเว็บ”</div>
          <div id="nv-items" style="margin-top:10px"></div>

          <div class="sect-title">ปุ่มเด่น (CTA)</div>
          <label class="check"><input type="checkbox" id="cta-show" ${st.cta.show ? 'checked' : ''}>แสดงปุ่ม</label>
          <div class="grid g2" style="gap:0 12px"><label class="field"><span>ข้อความ</span><input class="input" id="cta-text" value="${esc(st.cta.text)}"></label>
            <label class="field"><span>ลิงก์</span><input class="input mono" id="cta-href" value="${esc(st.cta.href)}" list="nv-pages"></label></div>

          <div class="sect-title">แถบด้านบน</div>
          <label class="check"><input type="checkbox" id="tb-show" ${st.topbar.show ? 'checked' : ''}>แสดงแถบเล็กเหนือเมนู (เช่น เบอร์โทร เวลาเปิด)</label>
          <label class="field"><span>ข้อความ</span><input class="input" id="tb-text" value="${esc(st.topbar.text)}" placeholder="โทร 02-123-4567 · เปิดทุกวัน 8:00–20:00"></label>
          <label class="field"><span>ลิงก์ <small>(ชื่อ|ลิงก์ บรรทัดละอัน)</small></span><textarea class="input" id="tb-links" rows="2" placeholder="LINE|https://line.me/...">${esc((st.topbar.links || []).map(l => l.label + '|' + l.href).join('\n'))}</textarea></label>
          <datalist id="nv-pages">${pageOpts}<option value="#contact"></datalist>
        </div>
        <div class="nav-preview">
          <div class="row between" style="margin-bottom:8px"><b class="small">ตัวอย่าง</b>
            <div class="seg" id="nv-dev"><button data-w="100%" class="on">${BW_ICON('monitor', 14)}</button><button data-w="390px">${BW_ICON('phone', 14)}</button></div></div>
          <div class="nav-frame-wrap"><iframe id="nv-frame" src="/preview/${site.slug}/" title="ตัวอย่าง"></iframe></div>
          <div class="small muted" id="nv-state" style="margin-top:8px">บันทึกอัตโนมัติ</div>
        </div>
      </div>
      <footer><button class="btn" data-close>ปิด</button></footer>`, { wide: true });
    m.el.classList.add('xwide');
    const $q = q => m.el.querySelector(q);

    // custom menu editor
    let items = (st.items || []).map(it => ({ ...it, children: it.children || [] }));
    const itemRow = (it, i, ci) => `<div class="nav-item ${ci != null ? 'child' : ''}" data-i="${i}" ${ci != null ? `data-c="${ci}"` : ''}>
      <input class="input" data-k="label" value="${esc(it.label)}" placeholder="ชื่อเมนู">
      <input class="input mono" data-k="href" value="${esc(it.href)}" placeholder="about.html หรือ https://" list="nv-pages">
      <label class="check" style="margin:0" title="เปิดแท็บใหม่"><input type="checkbox" data-k="target" ${it.target === '_blank' ? 'checked' : ''}>${BW_ICON('external', 14)}</label>
      ${ci == null ? `<button class="btn sm ghost icon" data-a="up" title="ขึ้น">↑</button><button class="btn sm ghost icon" data-a="sub" title="เพิ่มเมนูย่อย">${BW_ICON('plus', 14)}</button>` : ''}
      <button class="btn sm ghost icon" data-a="rm" title="ลบ">${BW_ICON('x', 14)}</button></div>`;
    function drawItems() {
      const custom = $q('#nv-mode .on').dataset.v === 'custom';
      $q('#nv-auto-hint').classList.toggle('hidden', custom);
      const box = $q('#nv-items');
      if (!custom) { box.innerHTML = ''; return; }
      box.innerHTML = items.map((it, i) => itemRow(it, i) + it.children.map((c, ci) => itemRow(c, i, ci)).join('')).join('') +
        `<div class="row" style="margin-top:8px"><button class="btn sm" id="nv-add">${BW_ICON('plus')} เพิ่มเมนู</button>
         <button class="btn sm ghost" id="nv-from-pages">เริ่มจากรายการหน้า</button></div>`;
      box.querySelectorAll('.nav-item').forEach(row => {
        const i = +row.dataset.i, ci = row.dataset.c != null ? +row.dataset.c : null;
        const target = () => ci == null ? items[i] : items[i].children[ci];
        row.querySelectorAll('[data-k]').forEach(inp => inp.addEventListener(inp.type === 'checkbox' ? 'change' : 'input', () => {
          const t = target(); t[inp.dataset.k] = inp.type === 'checkbox' ? (inp.checked ? '_blank' : '') : inp.value; queueSave();
        }));
        row.querySelectorAll('[data-a]').forEach(b => b.onclick = () => {
          if (b.dataset.a === 'rm') { if (ci == null) items.splice(i, 1); else items[i].children.splice(ci, 1); }
          if (b.dataset.a === 'sub') items[i].children.push({ label: 'เมนูย่อย', href: '#' });
          if (b.dataset.a === 'up' && i > 0) [items[i - 1], items[i]] = [items[i], items[i - 1]];
          drawItems(); queueSave();
        });
      });
      $q('#nv-add').onclick = () => { items.push({ label: 'เมนูใหม่', href: '#', children: [] }); drawItems(); queueSave(); };
      $q('#nv-from-pages').onclick = () => { items = r.pages.map(p => ({ label: p.title, href: p.href, children: [] })); drawItems(); queueSave(); };
    }
    m.el.querySelectorAll('#nv-mode button').forEach(b => b.onclick = () => {
      m.el.querySelectorAll('#nv-mode button').forEach(x => x.classList.toggle('on', x === b));
      if (b.dataset.v === 'custom' && !items.length) items = r.pages.map(p => ({ label: p.title, href: p.href, children: [] }));
      drawItems(); queueSave();
    });
    drawItems();

    // collect + save
    function collect() {
      const f = n => m.el.querySelector(`.nav-form [name=${n}]`);
      return {
        layout: (m.el.querySelector('[name=layout]:checked') || {}).value || 'split',
        logo_text: f('logo_text').value, logo_image: f('logo_image').value, logo_height: f('logo_height').value,
        sticky: f('sticky').checked, transparent: f('transparent').checked, autohide: f('autohide').checked, shadow: f('shadow').checked,
        mobile: f('mobile').value, height: f('height').value, bg: f('bg').value.trim(), color: f('color').value.trim(),
        menu_mode: $q('#nv-mode .on').dataset.v, items,
        cta: { show: $q('#cta-show').checked, text: $q('#cta-text').value, href: $q('#cta-href').value },
        topbar: { show: $q('#tb-show').checked, text: $q('#tb-text').value,
          links: $q('#tb-links').value.split('\n').map(l => l.split('|')).filter(x => x[0] && x[0].trim()).map(([label, href]) => ({ label: label.trim(), href: (href || '#').trim() })) },
      };
    }
    let timer = null;
    const frame = $q('#nv-frame'), state = $q('#nv-state');
    function queueSave() {
      clearTimeout(timer);
      state.textContent = 'กำลังบันทึก…';
      timer = setTimeout(async () => {
        try {
          const res = await api(`/api/sites/${site.id}/navbar`, { settings: collect() });
          st = res.settings; state.textContent = 'บันทึกแล้ว ✓';
          const y = frame.contentWindow ? frame.contentWindow.scrollY : 0;
          frame.onload = () => { try { frame.contentWindow.scrollTo(0, y); } catch (e) { } };
          frame.src = `/preview/${site.slug}/?t=${Date.now()}`;
        } catch (e) { state.textContent = e.message; }
      }, 450);
    }
    m.el.querySelectorAll('.nav-form input, .nav-form select, .nav-form textarea').forEach(el => {
      if (el.closest('#nv-items')) return;
      el.addEventListener(el.type === 'checkbox' || el.type === 'radio' || el.tagName === 'SELECT' ? 'change' : 'input', queueSave);
    });
    m.el.querySelectorAll('[name=layout]').forEach(r2 => r2.addEventListener('change', () =>
      m.el.querySelectorAll('.nav-layout').forEach(l => l.classList.toggle('sel', l.querySelector('input').checked))));
    m.el.querySelectorAll('[data-color]').forEach(c => c.addEventListener('input', () => {
      const t = m.el.querySelector(`.nav-form [name=${c.dataset.color}]`); t.value = c.value; queueSave();
    }));
    $q('#nv-logo').onclick = () => pickAsset(u => { m.el.querySelector('.nav-form [name=logo_image]').value = u; queueSave(); });
    $q('#nv-logo-clear').onclick = () => { m.el.querySelector('.nav-form [name=logo_image]').value = ''; queueSave(); };
    // Desktop preview renders at 1280px and is scaled to fit; mobile at real phone width.
    const wrap = $q('.nav-frame-wrap');
    function fit() {
      const mobile = $q('#nv-dev .on').dataset.w !== '100%';
      if (mobile) { frame.style.width = '390px'; frame.style.height = '100%'; frame.style.transform = ''; return; }
      const k = wrap.clientWidth / 1280;
      frame.style.width = '1280px'; frame.style.height = (wrap.clientHeight / k) + 'px';
      frame.style.transform = `scale(${k})`; frame.style.transformOrigin = '0 0';
    }
    m.el.querySelectorAll('#nv-dev button').forEach(b => b.onclick = () => {
      m.el.querySelectorAll('#nv-dev button').forEach(x => x.classList.toggle('on', x === b));
      wrap.classList.toggle('mobile', b.dataset.w !== '100%');
      fit();
    });
    setTimeout(fit, 30);
    const sw = async (managed) => {
      if (!managed && !await confirmBox('ออกแบบเอง', 'ส่วนหัวจะถูกแปลงเป็นบล็อกให้ลากวางแก้ไขเองในตัวออกแบบ (เมนูยังอัปเดตอัตโนมัติ) — กลับมาใช้ตัวตั้งค่าได้ภายหลัง', { ok: 'ออกแบบเอง' })) return;
      try {
        await api(`/api/sites/${site.id}/navbar`, { managed });
        m.close();
        if (managed) { toast('ใช้ตัวตั้งค่าแถบเมนูแล้ว', 'ok'); navbarModal(); }
        else location.href = `/sites/${site.id}/edit-shared/header/`;
      } catch (e) { toast(e.message, 'err'); }
    };
    const fr = $q('#nv-free'); if (fr) fr.onclick = () => sw(false);
    const mg = $q('#nv-managed'); if (mg) mg.onclick = () => sw(true);
  }

  // ---------------------------------------------------------------- data (collections)
  const TYPES = { text: 'ข้อความ', longtext: 'ข้อความยาว', html: 'HTML', number: 'ตัวเลข', bool: 'ใช่/ไม่', date: 'วันที่', datetime: 'วันเวลา',
    email: 'อีเมล', link: 'ลิงก์', image: 'รูป', select: 'ตัวเลือก', relation: 'เชื่อมชุดข้อมูล', json: 'JSON' };
  let DATA = { collections: [], connections: [] };

  async function renderData(selectId) {
    DATA = await api(`/api/sites/${site.id}/collections`);
    const sel = selectId || +(new URLSearchParams(location.search).get('c')) || (DATA.collections[0] || {}).id;
    root.innerHTML = `<div class="row between" style="margin-bottom:14px">
        <div class="muted">ชุดข้อมูลที่หน้าเว็บนำไปแสดงได้ — ใช้บล็อก “ข้อมูล” ในตัวออกแบบ หรือพิมพ์ <code>{{ฟิลด์}}</code></div>
        <div class="row"><button class="btn" id="d-blog">${BW_ICON('article')} สร้างระบบบทความ</button><button class="btn" id="d-mysql">${BW_ICON('database')} นำเข้าจาก MySQL / XAMPP</button>
        <button class="btn" id="d-file">${BW_ICON('upload')} นำเข้า .sql / CSV</button><button class="btn primary" id="d-new">${BW_ICON('plus')} สร้างเอง</button></div></div>
      <div class="data-layout"><div class="card data-list" id="d-list"></div><div id="d-main"></div></div>`;
    const list = document.getElementById('d-list');
    list.innerHTML = DATA.collections.length ? DATA.collections.map(c => `<a class="data-item ${c.id === sel ? 'active' : ''}" data-id="${c.id}">
        <div class="row between"><b>${esc(c.name)}</b>${c.mode === 'live' ? '<span class="badge brand">สด</span>' : ''}</div>
        <div class="small muted mono">${esc(c.slug)} · ${c.fields.length} ฟิลด์${c.count != null ? ' · ' + c.count + ' แถว' : ''}</div>
        ${c.pending ? `<div style="margin-top:4px"><span class="badge warn">รออนุมัติ ${c.pending}</span></div>` : ''}</a>`).join('')
      : `<div class="empty-state">${BW_ICON('table', 28)}<div style="margin-top:8px">ยังไม่มีชุดข้อมูล</div></div>`;
    list.querySelectorAll('[data-id]').forEach(a => a.onclick = () => openCollection(+a.dataset.id));
    document.getElementById('d-mysql').onclick = mysqlWizard;
    document.getElementById('d-file').onclick = fileImport;
    document.getElementById('d-new').onclick = newCollection;
    document.getElementById('d-blog').onclick = async () => {
      if (!await confirmBox('สร้างระบบบทความ', 'จะสร้างชุดข้อมูล “บทความ” พร้อมบทความตัวอย่าง 3 เรื่อง, หน้ารวมบทความ (ค้นหา · หมวดหมู่ · แบ่งหน้า), หน้าอ่านบทความ และ RSS ให้อัตโนมัติ', { ok: 'สร้างเลย' })) return;
      try { const r = await api(`/api/sites/${site.id}/blog`, {}); toast('สร้างระบบบทความแล้ว', 'ok'); renderData(r.collection.id); }
      catch (e) { toast(e.message, 'err'); }
    };
    if (sel) openCollection(sel); else document.getElementById('d-main').innerHTML = `<div class="card pad"><h2>เริ่มใช้ข้อมูลในเว็บ</h2>
      <div class="hint">ตัวอย่าง: นำตาราง <code>products</code> จาก XAMPP มาแสดงเป็นการ์ดสินค้าในหน้าเว็บ — แก้ใน phpMyAdmin แล้วหน้าเว็บเปลี่ยนตาม (โหมดเชื่อมสด)</div>
      <ol class="small" style="line-height:2;margin:0;padding-left:18px"><li>กด “นำเข้าจาก MySQL / XAMPP” หรือ “นำเข้า .sql / CSV”</li>
      <li>เปิดตัวออกแบบ › แท็บ “ข้อมูล” หรือหมวดบล็อก “ข้อมูล” แล้วลากการ์ด/ตารางลงหน้า</li>
      <li>หรือเลือกกล่องใดก็ได้ › “ตั้งค่า” › “วนซ้ำจากข้อมูล” แล้วใส่ <code>{{ฟิลด์}}</code> ในข้อความ</li></ol></div>`;
  }

  async function openCollection(id) {
    document.querySelectorAll('.data-item').forEach(a => a.classList.toggle('active', +a.dataset.id === id));
    history.replaceState(null, '', `?c=${id}`);
    const main = document.getElementById('d-main');
    main.innerHTML = '<div class="card pad muted">กำลังโหลด…</div>';
    const r = await api(`/api/collections/${id}`);
    const c = r.collection, rows = r.rows;
    const opts = c.options || {};
    const pending = rows.filter(x => x._approved === false).length;
    const showStatus = r.editable && (opts.forms || pending);
    const src = c.connection ? `${esc(c.connection_name)} › ${esc(c.source_database)}.${esc(c.source_table)}` : '';
    main.innerHTML = `<div class="card">
      <div class="card-head"><div><h2>${esc(c.name)}</h2><div class="small muted">ใช้อ้างอิง <code>${esc(c.slug)}</code>${src ? ' · จาก ' + src : ''}${c.last_synced ? ' · ซิงก์ ' + ago(c.last_synced) : ''}</div></div>
        <div class="row">${c.connection ? `<button class="btn sm" id="c-sync">${BW_ICON('refresh')} ${c.mode === 'live' ? 'โหลดใหม่' : 'ซิงก์จาก MySQL'}</button>` : ''}
          <a class="btn sm" href="/api/collections/${c.id}/export.csv">CSV</a><button class="btn sm" id="c-settings">${BW_ICON('settings')} ฟิลด์ & ตั้งค่า</button>
          <button class="btn sm danger icon" id="c-del" title="ลบชุดข้อมูล">${BW_ICON('trash')}</button></div></div>
      ${r.error ? `<div class="alert err" style="margin:14px 16px 0">${esc(r.error)}</div>` : ''}
      ${c.mode === 'live' ? `<div class="alert info" style="margin:14px 16px 0">โหมดเชื่อมสด: อ่านจาก MySQL ทุกครั้งที่มีคนเปิดเว็บ (แคช 15 วินาที) · แก้ข้อมูลที่ phpMyAdmin</div>` : ''}
      ${pending ? `<div class="alert warn" style="margin:14px 16px 0">มี ${pending} แถวที่ส่งมาจากฟอร์มรออนุมัติ — เลือกแล้วกด “อนุมัติ” เพื่อให้แสดงบนเว็บ</div>` : ''}
      <div class="data-table-wrap"><table class="table data-table"><thead><tr>${r.editable ? '<th style="width:32px"><input type="checkbox" id="c-all"></th><th style="width:34px"></th>' : ''}
        ${showStatus ? '<th>สถานะ</th>' : ''}
        ${c.fields.map(f => `<th title="${esc(f.label)}">${esc(f.name)} <span class="muted small">${TYPES[f.type] || f.type}</span></th>`).join('')}</tr></thead>
        <tbody>${rows.map(row => `<tr data-id="${row._id || ''}" class="${row._approved === false ? 'row-pending' : ''}">${r.editable ? `<td><input type="checkbox" class="c-row"></td><td><button class="btn sm ghost icon" data-edit title="แก้ไขแถวนี้แบบเต็ม">${BW_ICON('edit', 14)}</button></td>` : ''}
          ${showStatus ? `<td>${row._approved === false ? '<span class="badge warn">รออนุมัติ</span>' : '<span class="badge ok">แสดงอยู่</span>'}</td>` : ''}
          ${c.fields.map(f => cell(f, row[f.name], r.editable)).join('')}</tr>`).join('')}</tbody></table>
        ${rows.length ? '' : '<div class="empty-state">ยังไม่มีแถวข้อมูล</div>'}</div>
      ${r.editable ? `<div class="row" style="padding:12px 16px;border-top:1px solid var(--line)"><button class="btn sm" id="c-add">${BW_ICON('plus')} เพิ่มแถว</button>
        ${showStatus ? `<button class="btn sm" id="c-approve" disabled>${BW_ICON('check')} อนุมัติ</button><button class="btn sm" id="c-hide" disabled>ซ่อนจากเว็บ</button>` : ''}
        <button class="btn sm danger" id="c-remove" disabled>ลบแถวที่เลือก</button><span class="small muted" style="margin-left:auto">คลิกช่องเพื่อแก้ไข · ปุ่ม ${BW_ICON('edit', 12)} แก้แบบเต็ม (ตัวแก้ไขข้อความ, เลือกรูป)</span></div>` : ''}
    </div>
    <div class="grid g2" style="margin-top:16px">
      <div class="card pad"><h2>หน้าเว็บจากข้อมูลชุดนี้</h2>
        ${c.detail_pages.length ? `<div class="hint">แต่ละแถวมีหน้าของตัวเองที่ <code>${esc(c.detail_pages[0].slug)}/ชื่อแถว.html</code> — ในบล็อกรายการใช้ลิงก์ <code>{{_url}}</code></div>
          ${c.detail_pages.map(p => `<div class="row" style="margin-bottom:6px"><b style="flex:1">${esc(p.title)}</b><a class="btn sm" href="/preview/${esc(site.slug)}/${esc(p.slug)}.html" target="_blank">ดูตัวอย่าง</a><a class="btn sm primary" href="${p.edit_url}">ออกแบบ</a></div>`).join('')}`
        : `<div class="hint">สร้างหน้ารายการ (การ์ด + ค้นหา + หมวดหมู่ + แบ่งหน้า) และหน้ารายละเอียดของทุกแถวอัตโนมัติ เช่น <code>products.html</code> → <code>product/latte.html</code></div>
          <div class="row"><button class="btn primary sm" id="c-pages">${BW_ICON('pages')} สร้างหน้ารายการ + รายละเอียด</button><button class="btn sm" id="c-detail">เฉพาะหน้ารายละเอียด</button></div>`}
      </div>
      <div class="card pad"><h2>รับข้อมูลจากฟอร์ม</h2>
        ${opts.forms ? `<div class="hint">เปิดอยู่ · ${opts.auto_approve ? 'แสดงบนเว็บทันที' : 'รออนุมัติก่อนแสดง'}${c.mode === 'live' ? ' · บันทึกลงตาราง MySQL โดยตรง' + (c.fields.some(f => f.name === 'approved') ? ' (ใช้คอลัมน์ approved)' : '') : ''}</div>
          <div class="small">ในตัวออกแบบ: ลากบล็อก “ฟอร์ม ${esc(c.name)}” จากหมวดข้อมูล หรือเลือกฟอร์มใดก็ได้ › ตั้งค่า › “บันทึกลงชุดข้อมูล”</div>`
        : `<div class="hint">ให้ผู้เข้าชมส่งรีวิว สมัครสมาชิก หรือลงชื่อ แล้วข้อมูลเข้าชุดนี้ (พร้อมระบบอนุมัติ)</div><button class="btn sm" id="c-forms">เปิดรับข้อมูลจากฟอร์ม</button>`}
      </div>
    </div>
    <div class="card pad" style="margin-top:16px"><h2>วิธีใช้ในหน้าเว็บ</h2><div class="hint">วางในโค้ด HTML หรือใช้บล็อก/การตั้งค่า “วนซ้ำจากข้อมูล” ในตัวออกแบบ</div>
      <div class="log">&lt;div data-bw-repeat="${esc(c.slug)}" data-bw-limit="6"&gt;
  &lt;h3&gt;{{${esc((c.fields[0] || { name: 'field' }).name)}}}&lt;/h3&gt;
&lt;/div&gt;
จำนวนแถว: {{${esc(c.slug)}.count}}</div></div>`;
    const tbody = main.querySelector('tbody');
    if (r.editable) {
      tbody.querySelectorAll('[contenteditable]').forEach(td => {
        td.addEventListener('focus', () => td.dataset.before = td.innerText);
        td.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); td.blur(); } });
        td.addEventListener('blur', async () => {
          if (td.innerText === td.dataset.before) return;
          const tr = td.closest('tr'), payload = {};
          tr.querySelectorAll('[data-f]').forEach(x => payload[x.dataset.f] = x.innerText);
          try { const res = await api(`/api/collections/${c.id}/rows/save`, { _id: +tr.dataset.id || null, data: payload }); tr.dataset.id = res.row._id; td.classList.add('saved'); setTimeout(() => td.classList.remove('saved'), 800); }
          catch (e) { toast(e.message, 'err'); }
        });
      });
      tbody.querySelectorAll('[data-edit]').forEach(b => b.onclick = () => {
        const id = +b.closest('tr').dataset.id;
        rowModal(c, rows.find(x => x._id === id));
      });
      const approve = async (value) => {
        const ids = [...tbody.querySelectorAll('.c-row:checked')].map(x => +x.closest('tr').dataset.id);
        try { await api(`/api/collections/${c.id}/rows/approve`, { ids, value }); toast(value ? `อนุมัติ ${ids.length} แถว` : `ซ่อน ${ids.length} แถว`, 'ok'); renderData(c.id); }
        catch (e) { toast(e.message, 'err'); }
      };
      const ap = document.getElementById('c-approve');
      if (ap) { ap.onclick = () => approve(true); document.getElementById('c-hide').onclick = () => approve(false); }
      const sync = () => ['c-remove', 'c-approve', 'c-hide'].forEach(id => { const b = document.getElementById(id); if (b) b.disabled = !tbody.querySelector('.c-row:checked'); });
      tbody.querySelectorAll('.c-row').forEach(x => x.onchange = sync);
      document.getElementById('c-all').onchange = e => { tbody.querySelectorAll('.c-row').forEach(x => x.checked = e.target.checked); sync(); };
      document.getElementById('c-add').onclick = () => rowModal(c, null);
      document.getElementById('c-remove').onclick = async () => {
        const ids = [...tbody.querySelectorAll('.c-row:checked')].map(x => +x.closest('tr').dataset.id);
        if (!await confirmBox('ลบแถว', `ลบ ${ids.length} แถวที่เลือก?`, { ok: 'ลบ', danger: true })) return;
        await api(`/api/collections/${c.id}/rows/delete`, { ids }); openCollection(c.id);
      };
    }
    const syncBtn = document.getElementById('c-sync');
    if (syncBtn) syncBtn.onclick = async () => {
      syncBtn.disabled = true;
      try { const s = await api(`/api/collections/${c.id}/resync`, {}); toast(`ได้ ${s.rows} แถว`, 'ok'); renderData(c.id); } catch (e) { toast(e.message, 'err'); syncBtn.disabled = false; }
    };
    document.getElementById('c-settings').onclick = () => collectionSettings(c);
    const mkPages = async (withList) => {
      try {
        const res = await api(`/api/collections/${c.id}/pages`, { with_list: withList });
        if (await confirmBox('สร้างหน้าแล้ว', `${res.list ? `หน้ารายการ <code>${esc(res.list.filename)}</code> และ ` : ''}หน้ารายละเอียด <code>${esc(res.detail.slug)}/…html</code> พร้อมแล้ว — เปิดหน้ารายละเอียดในตัวออกแบบเลยไหม?`, { ok: 'เปิดตัวออกแบบ' }))
          location.href = res.detail.edit_url;
        else renderData(c.id);
      } catch (e) { toast(e.message, 'err'); }
    };
    const pb = document.getElementById('c-pages');
    if (pb) { pb.onclick = () => mkPages(true); document.getElementById('c-detail').onclick = () => mkPages(false); }
    const fb = document.getElementById('c-forms');
    if (fb) fb.onclick = () => collectionSettings(c, true);
    document.getElementById('c-del').onclick = async () => {
      if (!await confirmBox('ลบชุดข้อมูล', `ลบ “${esc(c.name)}” และข้อมูลทั้งหมดในชุดนี้? (ตารางใน MySQL ไม่ถูกแตะ)`, { ok: 'ลบ', danger: true })) return;
      await api(`/api/collections/${c.id}/delete`, {}); history.replaceState(null, '', location.pathname); renderData();
    };
  }

  function cell(f, v, editable) {
    const val = v == null ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v);
    if (!editable) return `<td>${f.type === 'image' && val ? `<span class="thumb-sm" style="background-image:url('${encodeURI(val)}')"></span>` : ''}${esc(val.slice(0, 200))}</td>`;
    return `<td contenteditable="plaintext-only" data-f="${esc(f.name)}" class="${f.type === 'number' ? 'num' : ''}">${esc(val)}</td>`;
  }

  function collectionSettings(c, focusForms) {
    const o = c.options || {};
    const others = (D.collections || []).filter(x => x.id !== c.id);
    const flags = f => [f.required && 'จำเป็น', f.unique && 'ไม่ซ้ำ', f.hidden && 'ซ่อนจาก API'].filter(Boolean).join(' · ');
    const row = f => `<div class="field-wrap"><div class="field-row"><input class="input mono" data-k="name" value="${esc(f.name)}" data-orig="${esc(f.name)}"><input class="input" data-k="label" value="${esc(f.label)}">
      <select class="input" data-k="type">${Object.entries(TYPES).map(([k, l]) => `<option value="${k}" ${k === f.type ? 'selected' : ''}>${l}</option>`).join('')}</select>
      <button class="btn sm ghost icon" data-adv title="กฎของฟิลด์ (จำเป็น, ไม่ซ้ำ, ช่วงค่า...)">${BW_ICON('settings')}</button>
      <button class="btn sm ghost icon" data-rm title="ลบฟิลด์">${BW_ICON('x')}</button></div>
      <div class="small muted adv-sum" style="margin:-4px 0 6px 2px">${flags(f)}</div>
      <div class="field-adv hidden">
        <div class="row" style="gap:16px"><label class="check"><input type="checkbox" data-o="required" ${f.required ? 'checked' : ''}>จำเป็นต้องกรอก</label>
          <label class="check"><input type="checkbox" data-o="unique" ${f.unique ? 'checked' : ''}>ห้ามซ้ำ</label>
          <label class="check"><input type="checkbox" data-o="hidden" ${f.hidden ? 'checked' : ''}>ซ่อนจาก API สาธารณะ</label></div>
        <div class="grid g4" style="gap:0 10px"><label class="field"><span>ค่าเริ่มต้น</span><input class="input" data-o="default" value="${esc(f.default ?? '')}"></label>
          <label class="field"><span>ต่ำสุด <small>(ค่า/ความยาว)</small></span><input class="input mono" data-o="min" value="${esc(f.min ?? '')}"></label>
          <label class="field"><span>สูงสุด</span><input class="input mono" data-o="max" value="${esc(f.max ?? '')}"></label>
          <label class="field"><span>รูปแบบ (regex)</span><input class="input mono" data-o="pattern" value="${esc(f.pattern || '')}" placeholder="^0[0-9]{9}$"></label></div>
        <label class="field opt-select"><span>ตัวเลือก <small>(คั่นด้วย , สำหรับชนิด “ตัวเลือก”)</small></span><input class="input" data-o="options" value="${esc((f.options || []).join(', '))}"></label>
        <div class="grid g2 opt-relation" style="gap:0 10px"><label class="field"><span>เชื่อมไปที่ชุดข้อมูล</span><select class="input" data-o="relation"><option value="">— เลือก —</option>
          ${others.map(x => `<option value="${esc(x.slug)}" ${x.slug === f.relation ? 'selected' : ''}>${esc(x.name)} (${esc(x.slug)})</option>`).join('')}</select></label>
          <label class="check" style="margin-top:26px"><input type="checkbox" data-o="multiple" ${f.multiple ? 'checked' : ''}>เลือกได้หลายแถว</label></div>
      </div></div>`;
    const m = modal(`<header><h2>ตั้งค่าชุดข้อมูล</h2><button class="btn ghost icon sm" data-close>${BW_ICON('x')}</button></header><div class="body">
      <div class="grid g2" style="gap:0 12px"><label class="field"><span>ชื่อ</span><input class="input" name="name" value="${esc(c.name)}"></label>
      <label class="field"><span>ชื่อที่ใช้อ้างอิง <small>(ใน data-bw-repeat)</small></span><input class="input mono" name="slug" value="${esc(c.slug)}"></label></div>
      ${c.mode === 'live' ? `<div class="grid g3" style="gap:0 12px"><label class="field"><span>เรียงตามคอลัมน์</span><input class="input mono" name="live_order" value="${esc(c.live_order)}"></label>
        <label class="field"><span>ลำดับ</span><select class="input" name="live_desc"><option value="">น้อย → มาก</option><option value="1" ${c.live_desc ? 'selected' : ''}>มาก → น้อย</option></select></label>
        <label class="field"><span>ดึงสูงสุด (แถว)</span><input class="input mono" name="live_limit" type="number" value="${c.live_limit}"></label></div>` : ''}
      <div class="sect-title">ตัวเลือก</div>
      <label class="check"><input type="checkbox" data-opt="forms" ${o.forms || focusForms ? 'checked' : ''}>รับข้อมูลจากฟอร์มบนเว็บ <span class="muted small">(ฟอร์มที่ตั้ง “บันทึกลงชุดข้อมูล” เป็นชุดนี้)</span></label>
      <label class="check"><input type="checkbox" data-opt="auto_approve" ${o.auto_approve ? 'checked' : ''}>แสดงบนเว็บทันทีโดยไม่ต้องอนุมัติ</label>
      <label class="check"><input type="checkbox" data-opt="rss" ${o.rss ? 'checked' : ''}>รวมในฟีด RSS (<code>rss.xml</code>) <span class="muted small">(ต้องมีหน้ารายละเอียด)</span></label>
      ${c.mode === 'live' ? '<div class="small muted">ชุดข้อมูลเชื่อมสด: ข้อมูลจากฟอร์มบันทึกลงตาราง MySQL โดยตรง — ถ้าตารางมีคอลัมน์ <code>approved</code> จะใช้เป็นสถานะอนุมัติ</div>' : ''}
      <div class="sect-title">ฟิลด์ <span class="small muted" style="text-transform:none;letter-spacing:0">— ชื่อ (ใช้ใน {{ }}) · ชื่อที่แสดง · ชนิด</span></div>
      <div id="f-rows">${c.fields.map(row).join('')}</div>
      ${c.mode === 'live' ? '' : `<button class="btn sm" id="f-add">${BW_ICON('plus')} เพิ่มฟิลด์</button>`}</div>
      <footer><button class="btn" data-close>ยกเลิก</button><button class="btn primary" data-save>บันทึก</button></footer>`, { wide: true });
    const bindRm = () => {
      m.el.querySelectorAll('[data-rm]').forEach(b => b.onclick = () => b.closest('.field-wrap').remove());
      m.el.querySelectorAll('.field-wrap').forEach(w => {
        const sync = () => { const t = w.querySelector('[data-k=type]').value; w.querySelector('.opt-select').classList.toggle('hidden', t !== 'select'); w.querySelector('.opt-relation').classList.toggle('hidden', t !== 'relation'); };
        w.querySelector('[data-k=type]').onchange = () => { sync(); if (['select', 'relation'].includes(w.querySelector('[data-k=type]').value)) w.querySelector('.field-adv').classList.remove('hidden'); };
        w.querySelector('[data-adv]').onclick = () => w.querySelector('.field-adv').classList.toggle('hidden');
        sync();
      });
    };
    bindRm();
    const add = m.el.querySelector('#f-add');
    if (add) add.onclick = () => { m.el.querySelector('#f-rows').insertAdjacentHTML('beforeend', row({ name: 'field', label: 'ฟิลด์ใหม่', type: 'text' })); bindRm(); };
    m.el.querySelector('[data-save]').onclick = async () => {
      const d = formData(m.el);
      const rows = [...m.el.querySelectorAll('.field-wrap')];
      d.fields = rows.map(r => {
        const f = { name: r.querySelector('[data-k=name]').value, label: r.querySelector('[data-k=label]').value, type: r.querySelector('[data-k=type]').value };
        r.querySelectorAll('[data-o]').forEach(x => { const v = x.type === 'checkbox' ? x.checked : x.value.trim(); if (v !== '' && v !== false) f[x.dataset.o] = v; });
        const old = c.fields.find(x => x.name === r.querySelector('[data-k=name]').dataset.orig);
        if (old && old.source) f.source = old.source;
        return f;
      });
      d.renames = rows.map(r => ({ from: r.querySelector('[data-k=name]').dataset.orig, to: r.querySelector('[data-k=name]').value })).filter(x => x.from && x.from !== x.to);
      if ('live_desc' in d) d.live_desc = d.live_desc === '1';
      d.options = {}; m.el.querySelectorAll('[data-opt]').forEach(x => d.options[x.dataset.opt] = x.checked);
      try { await api(`/api/collections/${c.id}/update`, d); m.close(); toast('บันทึกแล้ว', 'ok'); renderData(c.id); }
      catch (e) { showFieldError(m.el, e); }
    };
  }

  // Full editor for one row: inputs by field type, image picker, rich text for "html" fields.
  const RTE_CMDS = [['bold', '<b>B</b>'], ['italic', '<i>I</i>'], ['h2', 'H2'], ['h3', 'H3'], ['ul', '• รายการ'], ['ol', '1. รายการ'],
    ['quote', '“ ”'], ['link', 'ลิงก์'], ['img', 'รูป'], ['clear', 'ล้างรูปแบบ']];

  function rowModal(c, row) {
    const isNew = !row;
    row = row || {};
    const input = f => {
      const raw = row[f.name] ?? f.default ?? '';
      const v = typeof raw === 'object' ? (f.type === 'json' ? JSON.stringify(raw, null, 2) : raw.join(', ')) : String(raw);
      const n = `name="${esc(f.name)}" ${f.required ? 'required' : ''}`;
      if (f.type === 'select') return `<select class="input" ${n}><option value=""></option>${(f.options || []).map(o => `<option ${o === v ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
      if (f.type === 'json') return `<textarea class="input code" rows="4" ${n}>${esc(v)}</textarea>`;
      if (f.type === 'relation') return `<input class="input mono" ${n} value="${esc(v)}" placeholder="_id ของ ${esc(f.relation || '')}${f.multiple ? ' (หลายค่าคั่นด้วย ,)' : ''}">`;
      if (f.type === 'datetime') return `<input class="input" type="datetime-local" step="1" ${n} value="${esc(v.slice(0, 19))}">`;
      if (f.type === 'email') return `<input class="input" type="email" ${n} value="${esc(v)}">`;
      if (f.type === 'html') return `<div class="rte" data-rte="${esc(f.name)}"><div class="rte-bar">
          ${RTE_CMDS.map(([k, l]) => `<button type="button" class="btn sm ghost" data-cmd="${k}">${l}</button>`).join('')}</div>
          <div class="rte-body" contenteditable="true">${v}</div></div>`;
      if (f.type === 'longtext') return `<textarea class="input" rows="3" ${n}>${esc(v)}</textarea>`;
      if (f.type === 'image') return `<div class="row" style="flex-wrap:nowrap">${v ? `<span class="thumb-sm" style="background-image:url('${encodeURI(v)}')"></span>` : ''}<input class="input" ${n} value="${esc(v)}" placeholder="/media/... หรือ https://..."><button type="button" class="btn sm" data-pick="${esc(f.name)}">เลือกรูป</button></div>`;
      if (f.type === 'bool') return `<label class="check"><input type="checkbox" ${n} ${v && v !== '0' && v !== 'false' ? 'checked' : ''}>ใช่</label>`;
      const t = { number: 'number', date: 'date', link: 'url' }[f.type] || 'text';
      return `<input class="input ${f.type === 'number' ? 'mono' : ''}" type="${t}" ${n} value="${esc(v)}" ${t === 'number' ? 'step="any"' : ''}>`;
    };
    const m = modal(`<header><h2>${isNew ? 'เพิ่มแถว' : 'แก้ไขแถว'} · ${esc(c.name)}${row._id ? ` <code>_id ${row._id}</code>` : ''}</h2><button class="btn ghost icon sm" data-close>${BW_ICON('x')}</button></header>
      <div class="body">${c.fields.map(f => `<div class="field" data-field="${esc(f.name)}"><span>${esc(f.label)}${f.required ? ' <b style="color:var(--err)">*</b>' : ''} <small class="mono">${esc(f.name)}</small></span>${input(f)}<small class="field-err"></small></div>`).join('')}
      ${!isNew && row._approved === false ? '<label class="check"><input type="checkbox" id="rm-approve" checked>อนุมัติให้แสดงบนเว็บ</label>' : ''}</div>
      <footer><button class="btn" data-close>ยกเลิก</button><button class="btn primary" data-save>บันทึก</button></footer>`, { wide: true });
    m.el.querySelectorAll('[data-pick]').forEach(b => b.onclick = () => pickAsset(u => m.el.querySelector(`[name="${b.dataset.pick}"]`).value = u));
    m.el.querySelectorAll('.rte').forEach(box => {
      const ed = box.querySelector('.rte-body');
      box.querySelectorAll('[data-cmd]').forEach(b => b.onmousedown = e => {
        e.preventDefault(); // keep the selection inside the editor
        const k = b.dataset.cmd;
        if (k === 'bold' || k === 'italic') document.execCommand(k);
        else if (k === 'h2' || k === 'h3') document.execCommand('formatBlock', false, k);
        else if (k === 'quote') document.execCommand('formatBlock', false, 'blockquote');
        else if (k === 'ul') document.execCommand('insertUnorderedList');
        else if (k === 'ol') document.execCommand('insertOrderedList');
        else if (k === 'clear') { document.execCommand('removeFormat'); document.execCommand('formatBlock', false, 'p'); }
        else if (k === 'link') { const u = prompt('ลิงก์ (https://...)'); if (u) document.execCommand('createLink', false, u); }
        else if (k === 'img') {
          const sel = window.getSelection(), range = sel.rangeCount && ed.contains(sel.anchorNode) ? sel.getRangeAt(0) : null;
          pickAsset(u => {
            ed.focus();
            if (range) { sel.removeAllRanges(); sel.addRange(range); }
            document.execCommand('insertImage', false, u);
          });
        }
      });
      ed.addEventListener('paste', e => { // pasted text stays clean (no fonts/colours from Word or web pages)
        e.preventDefault();
        document.execCommand('insertText', false, (e.clipboardData || window.clipboardData).getData('text/plain'));
      });
    });
    m.el.querySelector('[data-save]').onclick = async () => {
      const payload = {};
      c.fields.forEach(f => {
        if (f.type === 'html') { payload[f.name] = m.el.querySelector(`[data-rte="${f.name}"] .rte-body`).innerHTML.trim(); return; }
        const el = m.el.querySelector(`[name="${f.name}"]`);
        payload[f.name] = el.type === 'checkbox' ? (el.checked ? 1 : 0) : el.value;
      });
      try {
        const res = await api(`/api/collections/${c.id}/rows/save`, { _id: row._id || null, data: payload });
        const ap = m.el.querySelector('#rm-approve');
        if (ap && ap.checked) await api(`/api/collections/${c.id}/rows/approve`, { ids: [res.row._id], value: true });
        m.close(); toast('บันทึกแล้ว', 'ok'); renderData(c.id);
      } catch (e) {
        toast(e.message, 'err');
        // "ราคา: ต้องเป็นตัวเลข · ชื่อ: จำเป็นต้องกรอก" → show next to each field
        m.el.querySelectorAll('.field-err').forEach(x => x.textContent = '');
        e.message.split(' · ').forEach(part => {
          const [label, ...msg] = part.split(': ');
          const f = c.fields.find(x => (x.label || x.name) === label);
          const box = f && m.el.querySelector(`[data-field="${f.name}"] .field-err`);
          if (box) box.textContent = msg.join(': ');
        });
      }
    };
  }

  function newCollection() {
    const m = modal(`<header><h2>สร้างชุดข้อมูล</h2><button class="btn ghost icon sm" data-close>${BW_ICON('x')}</button></header><div class="body">
      <label class="field"><span>ชื่อ</span><input class="input" name="name" placeholder="เช่น สินค้า, ผลงาน, ข่าว"></label>
      <label class="field"><span>ชื่อที่ใช้อ้างอิง <small>(a-z 0-9 -)</small></span><input class="input mono" name="slug" placeholder="products"></label>
      <div class="small muted">เริ่มด้วยฟิลด์ ชื่อ · รายละเอียด · รูป แล้วปรับได้ภายหลัง</div></div>
      <footer><button class="btn" data-close>ยกเลิก</button><button class="btn primary" data-ok>สร้าง</button></footer>`);
    m.el.querySelector('[data-ok]').onclick = async () => {
      try { const r = await api(`/api/sites/${site.id}/collections/create`, formData(m.el)); m.close(); renderData(r.collection.id); }
      catch (e) { showFieldError(m.el, e); }
    };
  }

  function fileImport() {
    const m = modal(`<header><h2>นำเข้า .sql / CSV</h2><button class="btn ghost icon sm" data-close>${BW_ICON('x')}</button></header><div class="body">
      <div class="drop" id="fi-drop">${BW_ICON('upload', 20)}<div style="margin-top:6px">ลากไฟล์ <b>.sql</b> (export จาก phpMyAdmin) หรือ <b>.csv</b> มาวาง หรือ <a href="#" id="fi-pick">เลือกไฟล์</a></div>
        <input type="file" id="fi-input" accept=".sql,.csv,.txt" hidden></div>
      <div id="fi-preview"></div></div>
      <footer><button class="btn" data-close>ยกเลิก</button><button class="btn primary" data-ok disabled>นำเข้า</button></footer>`, { wide: true });
    let file = null;
    const ok = m.el.querySelector('[data-ok]'), prev = m.el.querySelector('#fi-preview');
    const pick = async f => {
      file = f; ok.disabled = false;
      if (/\.sql$/i.test(f.name)) {
        const fd = new FormData(); fd.append('file', f); fd.append('preview', '1');
        prev.innerHTML = '<div class="muted small">กำลังอ่านไฟล์…</div>';
        try {
          const r = await api(`/api/sites/${site.id}/collections/import-file`, fd);
          prev.innerHTML = `<div class="sect-title">เลือกตาราง</div>` + r.tables.map(t => `<label class="opt sel"><input type="checkbox" name="tables" value="${esc(t.name)}" checked>
            <div><b class="mono">${esc(t.name)}</b><span>${t.rows} แถว · ${t.columns.map(esc).join(', ')}</span></div></label>`).join('');
        } catch (e) { prev.innerHTML = `<div class="alert err">${esc(e.message)}</div>`; ok.disabled = true; }
      } else prev.innerHTML = `<label class="field" style="margin-top:12px"><span>ชื่อชุดข้อมูล</span><input class="input" name="name" value="${esc(f.name.replace(/\.[^.]+$/, ''))}"></label>`;
    };
    m.el.querySelector('#fi-pick').onclick = e => { e.preventDefault(); m.el.querySelector('#fi-input').click(); };
    m.el.querySelector('#fi-input').onchange = e => e.target.files[0] && pick(e.target.files[0]);
    const drop = m.el.querySelector('#fi-drop');
    ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); }));
    ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); }));
    drop.addEventListener('drop', e => e.dataTransfer.files[0] && pick(e.dataTransfer.files[0]));
    ok.onclick = async () => {
      const fd = new FormData(); fd.append('file', file);
      m.el.querySelectorAll('[name=tables]:checked').forEach(x => fd.append('tables', x.value));
      const nm = m.el.querySelector('[name=name]'); if (nm) fd.append('name', nm.value);
      ok.disabled = true;
      try { const r = await api(`/api/sites/${site.id}/collections/import-file`, fd); m.close(); toast(`นำเข้าแล้ว ${r.collections.length} ชุด`, 'ok'); renderData(r.collections[0] && r.collections[0].id); }
      catch (e) { toast(e.message, 'err'); ok.disabled = false; }
    };
  }

  function mysqlWizard() {
    const conns = DATA.connections;
    const m = modal(`<header><h2>นำเข้าจาก MySQL / XAMPP</h2><button class="btn ghost icon sm" data-close>${BW_ICON('x')}</button></header><div class="body">
      <div class="sect-title" style="margin-top:0">1 · การเชื่อมต่อ</div>
      <div class="row" style="margin-bottom:10px"><select class="input" id="w-conn" style="flex:1">${conns.map(c => `<option value="${c.id}">${esc(c.name)} — ${esc(c.user)}@${esc(c.host)}:${c.port}</option>`).join('')}
        <option value="new">＋ การเชื่อมต่อใหม่…</option></select></div>
      <div id="w-new" class="${conns.length ? 'hidden' : ''}"><div class="grid g3" style="gap:0 12px">
        <label class="field"><span>ชื่อ</span><input class="input" name="name" value="XAMPP"></label>
        <label class="field"><span>โฮสต์</span><input class="input mono" name="host" value="127.0.0.1"></label>
        <label class="field"><span>พอร์ต</span><input class="input mono" name="port" value="3306"></label>
        <label class="field"><span>ผู้ใช้</span><input class="input mono" name="user" value="root"></label>
        <label class="field"><span>รหัสผ่าน</span><input class="input mono" name="password" type="password" placeholder="XAMPP: ไม่มีรหัส"></label>
        <label class="field"><span>Socket <small>(ไม่บังคับ)</small></span><input class="input mono" name="socket"></label></div>
        <button class="btn sm" id="w-save">${BW_ICON('check')} ทดสอบและบันทึก</button></div>
      <div id="w-db" class="hidden"><div class="sect-title">2 · ฐานข้อมูล</div><select class="input" id="w-dbsel"></select></div>
      <div id="w-tables" class="hidden"><div class="sect-title">3 · ตาราง</div><div id="w-tlist"></div>
        <div class="sect-title">วิธีใช้ข้อมูล</div>
        <label class="opt sel"><input type="radio" name="mode" value="copy" checked><div><b>คัดลอกมาเก็บใน BuildWeb</b><span>แก้ในแอปได้ ไม่ต้องเปิด XAMPP ตลอด · กด “ซิงก์” เพื่อดึงใหม่</span></div></label>
        <label class="opt"><input type="radio" name="mode" value="live"><div><b>เชื่อมสด</b><span>อ่านจาก MySQL ทุกครั้งที่เปิดเว็บ · แก้ใน phpMyAdmin แล้วเว็บเปลี่ยนตาม (ต้องเปิด XAMPP ไว้)</span></div></label></div>
      <div id="w-msg"></div></div>
      <footer><button class="btn" data-close>ยกเลิก</button><button class="btn primary" data-ok disabled>นำเข้า</button></footer>`, { wide: true });
    const $m = q => m.el.querySelector(q);
    const msg = (t, k = 'err') => $m('#w-msg').innerHTML = t ? `<div class="alert ${k}" style="margin-top:12px">${esc(t)}</div>` : '';
    let connId = conns.length ? conns[0].id : null;
    m.el.querySelectorAll('[name=mode]').forEach(r => r.onchange = () => m.el.querySelectorAll('.opt').forEach(o => o.classList.toggle('sel', o.querySelector('input') && o.querySelector('input').checked && o.querySelector('[name=mode]'))));
    const loadDbs = async () => {
      msg('');
      $m('#w-db').classList.add('hidden'); $m('#w-tables').classList.add('hidden'); $m('[data-ok]').disabled = true;
      try {
        const r = await api('/api/data/mysql/browse', { connection_id: connId });
        $m('#w-dbsel').innerHTML = '<option value="">— เลือกฐานข้อมูล —</option>' + r.databases.map(d => `<option>${esc(d)}</option>`).join('');
        $m('#w-db').classList.remove('hidden');
      } catch (e) { msg(e.message); }
    };
    $m('#w-conn').onchange = e => {
      if (e.target.value === 'new') { $m('#w-new').classList.remove('hidden'); connId = null; }
      else { $m('#w-new').classList.add('hidden'); connId = +e.target.value; loadDbs(); }
    };
    if (!conns.length) $m('#w-conn').value = 'new';
    $m('#w-save').onclick = async () => {
      const d = formData($m('#w-new'));
      $m('#w-save').disabled = true;
      try {
        const r = await api('/api/data/connections', d);
        connId = r.connection.id;
        DATA.connections.push(r.connection);
        $m('#w-conn').insertAdjacentHTML('afterbegin', `<option value="${connId}">${esc(r.connection.name)} — ${esc(r.connection.user)}@${esc(r.connection.host)}:${r.connection.port}</option>`);
        $m('#w-conn').value = connId; $m('#w-new').classList.add('hidden'); loadDbs();
      } catch (e) { msg(e.message); }
      $m('#w-save').disabled = false;
    };
    $m('#w-dbsel').onchange = async e => {
      const db = e.target.value; if (!db) return;
      try {
        const r = await api('/api/data/mysql/browse', { connection_id: connId, database: db });
        $m('#w-tlist').innerHTML = r.tables.length ? r.tables.map(t => `<label class="opt"><input type="checkbox" name="t" value="${esc(t.name)}">
          <div><b class="mono">${esc(t.name)}</b><span>~${t.rows} แถว · ${t.columns.map(c => esc(c.name)).join(', ')}</span></div></label>`).join('') : '<div class="muted">ไม่มีตาราง</div>';
        m.el.querySelectorAll('[name=t]').forEach(x => x.onchange = () => { x.closest('.opt').classList.toggle('sel', x.checked); $m('[data-ok]').disabled = !m.el.querySelector('[name=t]:checked'); });
        $m('#w-tables').classList.remove('hidden');
      } catch (er) { msg(er.message); }
    };
    $m('[data-ok]').onclick = async () => {
      const tables = [...m.el.querySelectorAll('[name=t]:checked')].map(x => x.value);
      $m('[data-ok]').disabled = true;
      try {
        const r = await api(`/api/sites/${site.id}/collections/import-mysql`, { connection_id: connId, database: $m('#w-dbsel').value, tables, mode: m.el.querySelector('[name=mode]:checked').value });
        m.close(); toast(`นำเข้าแล้ว ${r.collections.length} ตาราง`, 'ok'); renderData(r.collections[0].id);
      } catch (e) { msg(e.message); $m('[data-ok]').disabled = false; }
    };
    if (connId) loadDbs();
  }

  // ---------------------------------------------------------------- pages
  function renderPages() {
    root.innerHTML = `
      <div class="row between" style="margin-bottom:14px">
        <div class="muted">ลากที่ <span class="handle" style="display:inline-flex;vertical-align:middle">${BW_ICON('drag', 14)}</span> เพื่อจัดลำดับเมนู · หน้าแรกจะถูกส่งออกเป็น <code>index.html</code></div>
        <div class="row"><button class="btn" id="sync-nav" title="อัปเดตลิงก์ในแถบเมนูและส่วนท้ายของทุกหน้าให้ตรงกับรายการหน้า">อัปเดตเมนูทุกหน้า</button>
        <button class="btn primary" id="add-page">＋ เพิ่มหน้า</button></div>
      </div>
      <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h2>ส่วนหัว & ส่วนท้ายร่วม</h2>
        <div class="hint" style="margin:0">แก้ครั้งเดียว เปลี่ยนทุกหน้า · เมนูอัปเดตตามรายการหน้าอัตโนมัติ</div></div>
        <button class="btn sm" id="extract" title="ย้าย <header>/<footer> ของหน้าแรกมาเป็นส่วนร่วม และลบซ้ำออกจากทุกหน้า">แยกจากหน้าแรก</button></div>
        <div id="shared-rows"></div></div>
      <div class="card"><table class="table"><thead><tr><th></th><th>หน้า</th><th>ไฟล์</th><th>สถานะ</th><th>เมนู</th><th title="คะแนน SEO — คลิกเพื่อดูสิ่งที่ควรแก้">SEO</th><th>แก้ไขล่าสุด</th><th></th></tr></thead>
      <tbody id="page-rows"></tbody></table></div>
      <div class="card" style="margin-top:16px" id="seo-card"><div class="card-head"><div><h2>SEO ทั้งเว็บ</h2><div class="hint" style="margin:0">sitemap.xml · robots.txt · RSS สร้างให้อัตโนมัติ</div></div><span id="seo-total" class="seo-score">…</span></div><div id="seo-site" style="padding:6px 16px 14px"></div></div>`;
    drawPageRows();
    drawShared();
    loadSeo();
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
        <span class="kind-icon">${BW_ICON(x.kind === 'header' ? 'panel-top' : 'panel-bottom')}</span>
        <div style="flex:1"><b>${esc(x.label)}</b><div class="muted small">${x.kind === 'header' && x.managed ? 'สร้างจากตัวตั้งค่าแถบเมนู' : 'ออกแบบเอง'} · แก้ไข ${ago(x.updated_at)}</div></div>
        <label class="switch" title="เปิด/ปิดทุกหน้า"><input type="checkbox" ${x.enabled ? 'checked' : ''}><span></span></label>
        ${x.kind === 'header' ? `<button class="btn sm ${x.managed ? 'primary' : ''}" data-navbar>${BW_ICON('settings')} ตั้งค่าแถบเมนู</button>` : ''}
        ${x.kind === 'header' && x.managed ? '' : `<a class="btn sm" href="${x.edit_url}">ออกแบบ</a>`}</div>`).join('') ||
      `<div class="list-row muted">ยังไม่มีส่วนร่วม — <a href="/sites/${site.id}/edit-shared/header/">สร้างส่วนหัว</a> · <a href="/sites/${site.id}/edit-shared/footer/">สร้างส่วนท้าย</a></div>`;
    box.querySelectorAll('[data-id]').forEach(row => {
      row.querySelector('input').onchange = async e => {
        try { const r = await api(`/api/shared/${row.dataset.id}/update`, { enabled: e.target.checked }); toast(r.shared.enabled ? 'เปิดใช้ทุกหน้าแล้ว' : 'ปิดแล้ว', 'ok'); }
        catch (err) { toast(err.message, 'err'); e.target.checked = !e.target.checked; }
      };
    });
    box.querySelectorAll('[data-navbar]').forEach(b => b.onclick = navbarModal);
    if (new URLSearchParams(location.search).get('navbar')) { history.replaceState(null, '', location.pathname); navbarModal(); }
    const sync = document.getElementById('sync-nav');
    if (rows.some(x => x.kind === 'header' && x.enabled)) sync.classList.add('hidden');
  }

  function drawPageRows() {
    const tb = document.getElementById('page-rows');
    const byId = Object.fromEntries(D.pages.map(p => [p.id, p]));
    tb.innerHTML = D.pages.map(p => `
      <tr draggable="true" data-id="${p.id}">
        <td class="handle" title="ลากเพื่อเรียงลำดับ">${BW_ICON('drag', 15)}</td>
        <td><div class="page-title">${p.is_home ? '<span class="badge" style="height:18px;margin-right:6px">หน้าแรก</span>' : ''}${p.parent ? '<span class="muted">↳ </span>' : ''}${esc(p.title)}
          <small>${p.parent && byId[p.parent] ? 'อยู่ใต้ ' + esc(byId[p.parent].title) + ' · ' : ''}${p.seo_description ? esc(p.seo_description.slice(0, 70)) : 'ยังไม่มีคำอธิบาย SEO'}</small></div></td>
        <td class="mono small">${p.collection ? `${esc(p.slug)}/…html<div><span class="badge brand" title="สร้างหนึ่งหน้าต่อหนึ่งแถวของชุดข้อมูล">รายละเอียด: ${esc(p.collection_name)}</span></div>` : esc(p.filename)}</td>
        <td>${p.status === 'published' ? '<span class="badge ok">เผยแพร่</span>' : '<span class="badge warn">ฉบับร่าง</span>'}</td>
        <td>${p.show_in_nav && !p.collection ? esc(p.nav_label || p.title) : '<span class="muted">ซ่อน</span>'}</td>
        <td><button class="seo-score sm" data-seo="${p.id}" title="ดูรายละเอียด SEO">…</button></td>
        <td class="muted small">${ago(p.updated_at)}</td>
        <td><div class="row" style="justify-content:flex-end;flex-wrap:nowrap">
          <a class="btn sm primary" href="${p.edit_url}">ออกแบบ</a>
          <button class="btn sm" data-act="settings">ตั้งค่า</button>
          <button class="btn sm ghost icon" data-act="more">${BW_ICON('more')}</button></div></td>
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

  let SEO = null;
  const seoClass = n => n >= 80 ? 'ok' : n >= 50 ? 'warn' : 'err';
  const checkRow = c => `<div class="seo-check ${c.level}"><span class="seo-dot"></span><div><b>${esc(c.title)}</b>${c.tip ? `<div class="small muted">${esc(c.tip)}</div>` : ''}</div></div>`;
  async function loadSeo() {
    try { SEO = await api(`/api/sites/${site.id}/seo`); } catch (e) { return; }
    const total = document.getElementById('seo-total');
    if (!total) return;
    total.textContent = SEO.score; total.className = 'seo-score ' + seoClass(SEO.score);
    document.getElementById('seo-site').innerHTML = SEO.site.map(checkRow).join('') +
      `<div class="row" style="margin-top:10px"><a class="btn sm" href="/preview/${esc(site.slug)}/sitemap.xml" target="_blank">sitemap.xml</a><a class="btn sm" href="/preview/${esc(site.slug)}/robots.txt" target="_blank">robots.txt</a></div>`;
    SEO.pages.forEach(r => {
      const b = document.querySelector(`[data-seo="${r.page}"]`);
      if (!b) return;
      b.textContent = r.score; b.className = 'seo-score sm ' + seoClass(r.score);
      b.onclick = () => seoModal(r);
    });
  }
  function seoModal(r) {
    const p = D.pages.find(x => x.id === r.page);
    const m = modal(`<header><h2>SEO · ${esc(r.title)}</h2><span class="seo-score ${seoClass(r.score)}">${r.score}</span></header>
      <div class="body">${sharePreview(r.preview)}<div style="margin-top:14px">${r.checks.map(checkRow).join('')}</div></div>
      <footer><button class="btn" data-close>ปิด</button><button class="btn primary" data-fix>แก้ไขชื่อเรื่อง & คำอธิบาย</button></footer>`, { wide: true });
    m.el.querySelector('[data-fix]').onclick = () => { m.close(); pageModal(p); };
  }
  // How a link looks when shared on Facebook / LINE.
  function sharePreview(pv) {
    const host = (site.base_url || '').replace(/^https?:\/\//, '').replace(/\/.*$/, '') || (site.slug + '.example');
    const img = pv.image && !pv.image.includes('{{') ? pv.image : '';
    return `<div class="share-card">${img ? `<div class="share-img" style="background-image:url('${encodeURI(img)}')"></div>` : '<div class="share-img empty">ไม่มีรูปตอนแชร์</div>'}
      <div class="share-meta"><div class="share-host">${esc(host.toUpperCase())}</div><div class="share-title">${esc(pv.title || '')}</div><div class="share-desc">${esc(pv.description || '')}</div></div></div>`;
  }

  function pageMenu(p, anchor) {
    const m = modal(`<header><h2>${esc(p.title)}</h2><button class="btn ghost icon sm" data-close>${BW_ICON('x')}</button></header>
      <div class="body" style="display:grid;gap:8px">
        <a class="btn" href="/preview/${site.slug}/${p.is_home ? '' : p.slug + '.html'}" target="_blank">ดูตัวอย่างหน้านี้</a>
        ${p.is_home ? '' : '<button class="btn" data-a="home">ตั้งเป็นหน้าแรก</button>'}
        <button class="btn" data-a="status">${p.status === 'published' ? 'เปลี่ยนเป็นฉบับร่าง' : 'เผยแพร่หน้านี้'}</button>
        <button class="btn" data-a="dup">ทำสำเนาหน้า</button>
        <button class="btn danger" data-a="del">ลบหน้า</button>
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
    const m = modal(`<header><h2>${isNew ? 'เพิ่มหน้าใหม่' : 'ตั้งค่าหน้า'}</h2><button class="btn ghost icon sm" data-close>${BW_ICON('x')}</button></header>
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
        ${(D.collections || []).length ? `<div class="grid g2" style="gap:0 16px">
          <label class="field"><span>หน้ารายละเอียดของชุดข้อมูล <small>(หนึ่งหน้าต่อหนึ่งแถว)</small></span><select class="input" name="collection" ${p.is_home ? 'disabled' : ''}>
            <option value="">— หน้าปกติ —</option>${D.collections.map(c => `<option value="${c.id}" ${c.id === p.collection ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}</select>
            <small>ลิงก์จะเป็น <code>${esc(p.slug || 'ชื่อหน้า')}/ชื่อแถว.html</code> · ใช้ <code>{{ฟิลด์}}</code> ในหน้าและในชื่อเรื่อง/คำอธิบายได้</small></label>
          <label class="field" id="df-wrap"><span>ใช้ฟิลด์ไหนตั้งชื่อลิงก์</span><select class="input" name="detail_field"></select></label></div>` : ''}
        ${isNew ? `<div class="sect-title">รูปแบบเริ่มต้น</div><div class="grid g3" style="gap:10px" id="layouts">${layouts}</div>` : ''}
        <div class="sect-title">SEO & การแชร์</div>
        <label class="field"><span>ชื่อเรื่องบน Google <small>(เว้นว่าง = “ชื่อหน้า | ชื่อเว็บ”)</small></span><input class="input" name="seo_title" value="${esc(p.seo_title)}" maxlength="200"></label>
        <label class="field"><span>คำอธิบาย <small id="desc-count"></small></span><textarea class="input" name="seo_description" rows="2" maxlength="320">${esc(p.seo_description)}</textarea></label>
        <div class="grid g2" style="gap:0 16px">
          <label class="field"><span>คีย์เวิร์ด <small>(คั่นด้วย ,)</small></span><input class="input" name="seo_keywords" value="${esc(p.seo_keywords)}"></label>
          <label class="field"><span>รูปตอนแชร์ (og:image)</span><div class="row" style="flex-wrap:nowrap"><input class="input" name="og_image" value="${esc(p.og_image)}" placeholder="/media/..."><button class="btn sm" type="button" data-pick="og_image">เลือก</button></div></label>
        </div>
        <label class="check"><input type="checkbox" name="noindex" ${p.noindex ? 'checked' : ''}>ไม่ให้เครื่องมือค้นหาเก็บหน้านี้ (noindex)</label>
        <div class="sect-title">ตัวอย่างตอนแชร์ลง Facebook / LINE</div><div id="share-live"></div>
        <details style="margin-top:8px"><summary style="cursor:pointer;font-weight:500">โค้ดเพิ่มเติม (ขั้นสูง)</summary><div style="margin-top:12px">
          <label class="field"><span>โค้ดใน &lt;head&gt;</span><textarea class="input code" name="head_code" placeholder="<meta ...> หรือ Google Analytics">${esc(p.head_code)}</textarea></label>
          <label class="field"><span>CSS เฉพาะหน้านี้</span><textarea class="input code" name="custom_css">${esc(p.custom_css)}</textarea></label>
          <label class="field"><span>JavaScript เฉพาะหน้านี้</span><textarea class="input code" name="custom_js">${esc(p.custom_js)}</textarea></label>
        </div></details>
      </div>
      <footer>${isNew ? '' : `<a class="btn" href="${p.edit_url}" style="margin-right:auto">ไปออกแบบ</a>`}<button class="btn" data-close>ยกเลิก</button>
        <button class="btn primary" data-save>${isNew ? 'สร้างหน้า' : 'บันทึก'}</button></footer>`, { wide: true });
    const title = m.el.querySelector('[name=title]'), slug = m.el.querySelector('[name=slug]');
    let slugTouched = !isNew;
    slug.addEventListener('input', () => slugTouched = true);
    title.addEventListener('input', () => { if (!slugTouched) slug.value = slugify(title.value); });
    const desc = m.el.querySelector('[name=seo_description]'), cnt = m.el.querySelector('#desc-count');
    const upd = () => cnt.textContent = `${desc.value.length}/160 ตัวอักษรแนะนำ`;
    desc.addEventListener('input', upd); upd();
    const live = () => {
      const t = m.el.querySelector('[name=seo_title]').value || `${title.value || 'ชื่อหน้า'} | ${site.name}`;
      m.el.querySelector('#share-live').innerHTML = sharePreview({ title: t, description: desc.value || site.description, image: m.el.querySelector('[name=og_image]').value });
    };
    ['seo_title', 'seo_description', 'og_image', 'title'].forEach(n => m.el.querySelector(`[name=${n}]`).addEventListener('input', live)); live();
    const colSel = m.el.querySelector('[name=collection]'), dfSel = m.el.querySelector('[name=detail_field]');
    const drawDf = () => {
      const c = (D.collections || []).find(x => x.id === +colSel.value);
      m.el.querySelector('#df-wrap').classList.toggle('hidden', !c);
      if (c) dfSel.innerHTML = `<option value="">อัตโนมัติ (slug / ชื่อ)</option>` + c.fields.map(f => `<option value="${esc(f.name)}" ${f.name === p.detail_field ? 'selected' : ''}>${esc(f.label)} (${esc(f.name)})</option>`).join('');
    };
    if (colSel) { colSel.onchange = drawDf; drawDf(); }
    m.el.querySelectorAll('#layouts .opt').forEach(o => o.addEventListener('click', () => {
      m.el.querySelectorAll('#layouts .opt').forEach(x => x.classList.remove('sel')); o.classList.add('sel');
    }));
    m.el.querySelectorAll('[data-pick]').forEach(b => b.onclick = () => pickAsset(url => m.el.querySelector(`[name=${b.dataset.pick}]`).value = url));
    m.el.querySelector('[data-save]').onclick = async () => {
      const d = formData(m.el);
      if (!p.is_home && !d.is_home) delete d.is_home;
      if (colSel && colSel.disabled) { delete d.collection; delete d.detail_field; }
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
      <div class="card fm-folders"><div class="row between" style="padding:2px 6px 8px"><b>โฟลเดอร์</b><button class="btn sm ghost icon" id="new-folder" title="สร้างโฟลเดอร์">${BW_ICON('plus')}</button></div><div id="folders"></div></div>
      <div><div class="drop" id="drop">${BW_ICON('upload', 20)}<div style="margin-top:6px">ลากไฟล์มาวางที่นี่ หรือ <a href="#" id="pick">เลือกไฟล์</a> — รูป วิดีโอ PDF ฯลฯ (สูงสุด 200 MB ต่อไฟล์)
        </div><input type="file" id="file-input" multiple hidden><div class="progress hidden" id="prog"><i></i></div></div>
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
    const item = (f, label, depth = 0) => `<a data-f="${esc(f)}" class="${f === fmFolder ? 'active' : ''}" style="padding-left:${10 + depth * 14}px">${BW_ICON(f ? 'folder' : 'images', 15)} ${esc(label)} <span class="muted small" style="margin-left:auto">${count(f)}</span></a>`;
    el.innerHTML = item('', 'ไฟล์ทั้งหมด (ราก)') + fmState.folders.map(f => item(f, f.split('/').pop(), f.split('/').length)).join('');
    el.querySelectorAll('a').forEach(a => a.onclick = () => { fmFolder = a.dataset.f; drawFolders(); drawAssets(); });
  }

  function drawAssets() {
    const q = (document.getElementById('q').value || '').toLowerCase();
    const kind = document.getElementById('kind').value;
    const list = fmState.assets.filter(a => a.folder === fmFolder && (!q || a.name.toLowerCase().includes(q)) && (!kind || a.kind === kind));
    const icons = { video: BW_ICON('video', 30), audio: BW_ICON('music', 30), document: BW_ICON('file', 30), other: BW_ICON('box', 30) };
    const grid = document.getElementById('fm-grid');
    const sub = fmState.folders.filter(f => f.startsWith(fmFolder ? fmFolder + '/' : '') && f.split('/').length === (fmFolder ? fmFolder.split('/').length + 1 : 1));
    grid.innerHTML = sub.map(f => `<div class="fm-item" data-folder="${esc(f)}"><div class="pv">${BW_ICON('folder', 30)}</div><div class="nm">${esc(f.split('/').pop())}<small>โฟลเดอร์</small></div></div>`).join('') +
      list.map(a => `<div class="fm-item" data-id="${a.id}"><div class="pv" ${a.kind === 'image' ? `style="background-image:url('${encodeURI(a.url)}')"` : ''}>${a.kind === 'image' ? '' : icons[a.kind] || icons.other}</div>
        <div class="nm" title="${esc(a.name)}">${esc(a.name)}<small>${bytes(a.size)}</small></div></div>`).join('');
    if (!sub.length && !list.length) grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1"><div class="big">${BW_ICON('image', 30)}</div>โฟลเดอร์นี้ยังไม่มีไฟล์</div>`;
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
    const m = modal(`<header><h2>รายละเอียดไฟล์</h2><button class="btn ghost icon sm" data-close>${BW_ICON('x')}</button></header><div class="body">${pv}
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
    const m = modal(`<header><h2>เลือกรูปภาพ</h2><button class="btn ghost icon sm" data-close>${BW_ICON('x')}</button></header><div class="body">
      ${r.assets.length ? `<div class="fm-grid">${r.assets.map(a => `<div class="fm-item" data-url="${esc(a.url)}"><div class="pv" style="background-image:url('${encodeURI(a.url)}')"></div><div class="nm">${esc(a.name)}</div></div>`).join('')}</div>`
        : '<div class="empty-state">ยังไม่มีรูป — อัปโหลดได้ที่แท็บ “ไฟล์ & รูปภาพ”</div>'}</div>`, { wide: true });
    m.el.querySelectorAll('[data-url]').forEach(el => el.onclick = () => { cb(el.dataset.url); m.close(); });
  }

  // ---------------------------------------------------------------- forms
  async function renderForms() {
    root.innerHTML = `<div class="row between" style="margin-bottom:14px"><div class="muted">ข้อมูลที่ผู้เข้าชมกรอกในฟอร์มบนเว็บ (บันทึกลงฐานข้อมูลของโปรแกรม — <a href="/settings/database/">ตั้งค่าฐานข้อมูล</a>)</div>
      <div class="row"><button class="btn" id="read-all">อ่านทั้งหมด</button><a class="btn" href="/sites/${site.id}/forms.csv">ดาวน์โหลด CSV</a></div></div>
      <div class="card" id="subs"><div class="empty-state">กำลังโหลด...</div></div>`;
    const r = await api(`/api/sites/${site.id}/submissions`);
    const box = document.getElementById('subs');
    if (!r.submissions.length) {
      box.innerHTML = `<div class="empty-state"><div class="big">${BW_ICON('form', 30)}</div>ยังไม่มีข้อมูลจากฟอร์ม<br><small>เพิ่มบล็อก “ฟอร์มติดต่อ” ในตัวออกแบบ แล้วเปิดโฮสติ้งเพื่อให้ผู้คนส่งข้อความได้</small></div>`;
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
        <label class="field"><span>พอร์ตเฉพาะของเว็บนี้ <small>(ไม่บังคับ)</small></span><input class="input mono" name="host_port" type="number" min="1024" max="65535" value="${site.host_port || ''}" placeholder="เช่น 8101">
          <small>ใส่แล้วเว็บนี้จะเปิดที่ <code>http://…:พอร์ต/</code> ได้ตรงๆ — ทำให้โฮสต์หลายเว็บที่ “/” พร้อมกันได้</small></label>
        <label class="check"><input type="checkbox" name="use_base_styles" ${site.use_base_styles ? 'checked' : ''}>ใช้สไตล์พื้นฐาน & ฟอนต์ของธีม <span class="muted small">(ปิดไว้สำหรับเว็บที่นำเข้า)</span></label>
        <label class="field"><span>ที่ส่งฟอร์มเมื่อส่งออกเป็นไฟล์ <small>(ไม่บังคับ)</small></span><input class="input mono" name="form_endpoint" value="${esc(site.form_endpoint)}" placeholder="เช่น http://192.168.1.10:8090/${esc(site.slug)}/__form">
          <small>เว้นว่างไว้ = ฟอร์มส่งเข้า BuildWeb ตอนโฮสต์ และใช้ bw-form.php ตอนส่งออกไป XAMPP</small></label>
        <label class="field"><span>ที่อยู่เว็บจริง <small>(ไม่บังคับ)</small></span><input class="input mono" name="base_url" value="${esc(site.base_url || '')}" placeholder="https://myshop.com/">
          <small>ใช้สร้าง sitemap.xml, RSS และลิงก์ตอนแชร์ — ตั้งให้เองเมื่อเผยแพร่ด้วยปุ่มเดียวครั้งแรก</small></label>
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
      <div class="card pad" style="grid-column:1/-1" id="contact-card"></div>
      <div class="card pad" style="grid-column:1/-1"><h2>โค้ดเพิ่มเติมทุกหน้า</h2><div class="hint">เช่น Google Analytics, Facebook Pixel, CSS/JS ของคุณเอง</div>
        <div class="grid g3"><label class="field"><span>โค้ดใน &lt;head&gt;</span><textarea class="input code" name="head_code">${esc(site.head_code)}</textarea></label>
        <label class="field"><span>CSS</span><textarea class="input code" name="custom_css">${esc(site.custom_css)}</textarea></label>
        <label class="field"><span>JavaScript</span><textarea class="input code" name="custom_js">${esc(site.custom_js)}</textarea></label></div></div>
    </div>
    <div class="row between" style="margin-top:20px"><div class="row"><button class="btn" id="dup-site">ทำสำเนาเว็บ</button><button class="btn danger" id="del-site">ลบเว็บนี้</button></div>
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
    const contact = contactEditor(document.getElementById('contact-card'), theme);
    document.getElementById('save-site').onclick = async () => {
      const d = formData(root);
      d.theme = theme;
      d.contact = contact();
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

  // ---------------------------------------------------------------- REST API
  const RULE_OPTS = [['public', 'ทุกคน'], ['key', 'ต้องมี key'], ['off', 'ปิด']];
  const ACTIONS = [['list', 'ดูรายการ'], ['view', 'ดูทีละแถว'], ['create', 'เพิ่ม'], ['update', 'แก้ไข'], ['delete', 'ลบ']];
  let API = null;
  async function renderApi() {
    root.innerHTML = '<div class="card pad muted">กำลังโหลด…</div>';
    API = await api(`/api/sites/${site.id}/restapi`);
    const st = API.settings;
    const hostBase = (D.hosting.running ? siteUrls(D.hosting) : [])[0];
    const base = (site.base_url || hostBase || `${location.origin}/preview/${site.slug}/`).replace(/\/?$/, '/') + 'api/v1';
    root.innerHTML = `<div class="card pad" style="margin-bottom:16px"><div class="row between">
        <div><h2>REST API ของเว็บนี้</h2><div class="hint" style="margin:0">ให้แอปมือถือ, หน้าเว็บอื่น, n8n/Zapier หรือโค้ดของคุณอ่าน-เขียนชุดข้อมูลได้ · ตรวจข้อมูลตามกฎของฟิลด์ทุกครั้ง</div></div>
        <label class="switch" title="เปิด/ปิด API สำหรับคนภายนอก"><input type="checkbox" id="api-on" ${st.enabled ? 'checked' : ''}><span></span></label></div>
        <div class="row" style="margin-top:12px;flex-wrap:nowrap"><code style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(base)}</code>
          <button class="btn sm" id="api-copy">${BW_ICON('copy')} คัดลอก</button>
          <a class="btn sm" href="/preview/${esc(site.slug)}/api/v1/openapi.json" target="_blank" download="${esc(site.slug)}-openapi.json">openapi.json</a></div>
        ${st.enabled ? '' : '<div class="alert warn" style="margin-top:10px">API ปิดอยู่ — คนภายนอกเรียกไม่ได้ (คุณยังทดลองในแอปได้)</div>'}
        ${D.hosting.running || site.base_url ? '' : '<div class="small muted" style="margin-top:8px">API ทำงานบนเซิร์ฟเวอร์โฮสติ้งของเครื่องนี้ — <a href="/settings/">เปิดโฮสติ้ง</a> เพื่อให้เครื่องอื่นเรียกได้ · เว็บที่เผยแพร่ไป GitHub/Netlify/FTP เป็นไฟล์อย่างเดียว ไม่มี API</div>'}
      </div>
      <div class="grid" style="grid-template-columns:minmax(0,1.5fr) minmax(0,1fr);align-items:start" id="api-grid">
        <div class="card"><div class="card-head"><div><h2>สิทธิ์ต่อชุดข้อมูล</h2><div class="hint" style="margin:0">ใครทำอะไรได้บ้าง · ฟิลด์ที่ตั้ง “ซ่อนจาก API” จะไม่ถูกส่งออก</div></div></div>
          ${API.collections.length ? `<div class="data-table-wrap"><table class="table"><thead><tr><th>ชุดข้อมูล</th>${ACTIONS.map(([, l]) => `<th>${l}</th>`).join('')}</tr></thead><tbody>
            ${API.collections.map(c => `<tr data-slug="${esc(c.slug)}"><td><b>${esc(c.name)}</b><div class="small muted mono">/${esc(c.slug)}${c.hidden.length ? ` · ซ่อน ${c.hidden.length} ฟิลด์` : ''}</div></td>
              ${ACTIONS.map(([a]) => `<td><select class="input sm rule-${c.rules[a]}" data-a="${a}">${RULE_OPTS.map(([v, l]) => `<option value="${v}" ${c.rules[a] === v ? 'selected' : ''}>${l}</option>`).join('')}</select></td>`).join('')}</tr>`).join('')}
            </tbody></table></div>` : `<div class="empty-state">ยังไม่มีชุดข้อมูล — <a href="/sites/${site.id}/data/">สร้างที่แท็บข้อมูล</a></div>`}
        </div>
        <div class="card"><div class="card-head"><div><h2>API keys</h2><div class="hint" style="margin:0">สำหรับโปรแกรมที่ต้องเขียนข้อมูลหรืออ่านชุดที่ล็อกไว้</div></div><button class="btn sm primary" id="key-new">${BW_ICON('plus')} สร้าง key</button></div>
          <div id="key-list">${API.keys.length ? API.keys.map(k => `<div class="list-row" data-id="${k.id}" style="${k.revoked ? 'opacity:.5' : ''}">
              <div style="flex:1"><b>${esc(k.name)}</b> ${k.revoked ? '<span class="badge err">ยกเลิกแล้ว</span>' : k.write ? '<span class="badge warn">อ่าน+เขียน</span>' : '<span class="badge">อ่านอย่างเดียว</span>'}
                <div class="small muted"><code>${esc(k.prefix)}…</code> · ${k.collections.length ? esc(k.collections.join(', ')) : 'ทุกชุดข้อมูล'} · ${k.last_used ? 'ใช้ล่าสุด ' + ago(k.last_used) : 'ยังไม่เคยใช้'}</div></div>
              ${k.revoked ? `<button class="btn sm ghost icon" data-del title="ลบ">${BW_ICON('trash')}</button>` : '<button class="btn sm danger" data-revoke>ยกเลิก</button>'}</div>`).join('')
            : '<div class="empty-state">ยังไม่มี key</div>'}</div>
          <div style="padding:14px 16px;border-top:1px solid var(--line)"><div class="sect-title" style="margin-top:0">ความปลอดภัย</div>
            <div class="grid g2" style="gap:0 12px"><label class="field"><span>โดเมนที่เรียกจากเบราว์เซอร์ได้ (CORS)</span><input class="input mono" id="api-cors" value="${esc(st.cors)}" placeholder="* หรือ https://app.com, https://admin.app.com"></label>
            <label class="field"><span>จำกัดครั้ง/นาที ต่อ IP <small>(key ได้ 5 เท่า · 0 = ไม่จำกัด)</small></span><input class="input mono" id="api-rate" type="number" min="0" value="${st.rate}"></label></div>
            <div class="row between"><label class="check"><input type="checkbox" id="api-log" ${st.log ? 'checked' : ''}>บันทึกการเรียก (30 วัน)</label><button class="btn sm" id="api-save">บันทึก</button></div></div>
        </div>
      </div>
      <div class="card" style="margin-top:16px"><div class="card-head"><div><h2>ทดลองเรียก API</h2><div class="hint" style="margin:0">ส่งคำขอจริงจากในแอป แล้วดูผลลัพธ์ · มีโค้ดตัวอย่างให้คัดลอก</div></div>
          <div class="seg" id="pg-as"><button data-v="public" class="on">แบบผู้เข้าชม</button><button data-v="owner">แบบเจ้าของเว็บ</button></div></div>
        <div class="pad" style="padding:16px">
          <div class="row" style="flex-wrap:nowrap;gap:8px"><select class="input mono" id="pg-method" style="width:110px">${['GET', 'POST', 'PATCH', 'PUT', 'DELETE'].map(m => `<option>${m}</option>`).join('')}</select>
            <div class="input-group" style="flex:1"><span class="prefix mono">/api/v1/</span><input class="input mono" id="pg-path" value="${esc((API.collections[0] || { slug: '' }).slug)}?per_page=5"></div>
            <button class="btn primary" id="pg-send">ส่ง</button></div>
          <div class="grid g2" style="gap:12px;margin-top:12px">
            <div><label class="field"><span>API key <small>(ไม่บังคับ)</small></span><input class="input mono" id="pg-key" placeholder="bw_…"></label>
              <label class="field"><span>Body (JSON) <small>สำหรับ POST / PATCH / PUT</small></span><textarea class="input code" id="pg-body" rows="7">{\n  \n}</textarea></label>
              <div class="seg" id="pg-lang">${['curl', 'fetch', 'PHP', 'Python'].map((l, i) => `<button data-v="${l}" class="${i ? '' : 'on'}">${l}</button>`).join('')}</div>
              <div class="log" id="pg-code" style="margin-top:8px;white-space:pre-wrap;word-break:break-all"></div></div>
            <div><div class="row between"><b>ผลลัพธ์</b><span class="small muted" id="pg-meta"></span></div><div class="log" id="pg-out" style="min-height:260px;max-height:460px;overflow:auto;margin-top:6px">กด “ส่ง” เพื่อทดลอง</div></div>
          </div></div></div>
      <div class="grid g2" style="margin-top:16px;align-items:start">
        <div class="card pad"><h2>เอกสาร endpoint</h2><div class="hint">ทุกชุดข้อมูลมี endpoint ครบ — พารามิเตอร์: <code>page</code> <code>per_page</code> <code>sort=-price,name</code> <code>q</code> <code>filter=price>50;category=coffee</code> <code>ฟิลด์=ค่า</code> <code>expand</code> <code>fields</code></div>
          ${API.collections.map(c => `<details style="margin-bottom:8px"><summary style="cursor:pointer"><b>${esc(c.name)}</b> <code>/${esc(c.slug)}</code></summary>
            <div class="small" style="margin:8px 0 4px">${[['GET', '', 'list'], ['POST', '', 'create'], ['GET', '/{_id}', 'view'], ['PATCH', '/{_id}', 'update'], ['DELETE', '/{_id}', 'delete']].map(([m, p, a]) =>
              `<div class="row" style="gap:8px;margin:3px 0"><code style="width:62px;text-align:center">${m}</code><code>/${esc(c.slug)}${p}</code><span class="muted">${RULE_OPTS.find(r => r[0] === c.rules[a])[1]}</span></div>`).join('')}</div>
            <table class="table small"><thead><tr><th>ฟิลด์</th><th>ชนิด</th><th>กฎ</th></tr></thead><tbody>${c.fields.map(f => `<tr><td class="mono">${esc(f.name)}${f.hidden ? ' <span class="badge">ซ่อน</span>' : ''}</td><td>${TYPES[f.type] || f.type}${f.relation ? ' → ' + esc(f.relation) : ''}</td>
              <td class="muted">${[f.required && 'จำเป็น', f.unique && 'ไม่ซ้ำ', f.min != null && 'min ' + f.min, f.max != null && 'max ' + f.max, f.pattern && 'regex', f.options && f.options.length && f.options.join('/')].filter(Boolean).join(' · ')}</td></tr>`).join('')}</tbody></table></details>`).join('') || '<div class="muted">ยังไม่มีชุดข้อมูล</div>'}
          <div class="small muted" style="margin-top:8px">ในหน้าเว็บใช้ JavaScript ได้เลย: <code>bw.list('${esc((API.collections[0] || { slug: 'products' }).slug)}', {sort: '-_id'})</code> · <code>bw.create(…)</code> · <code>bw.update(…)</code> · <code>bw.remove(…)</code></div></div>
        <div class="card"><div class="card-head"><h2>บันทึกการเรียกล่าสุด</h2><button class="btn sm" id="log-refresh">${BW_ICON('refresh')} รีเฟรช</button></div><div id="api-logs" class="data-table-wrap" style="max-height:520px"></div></div>
      </div>`;
    document.getElementById('api-copy').onclick = () => navigator.clipboard.writeText(base).then(() => toast('คัดลอกแล้ว', 'ok'));
    document.getElementById('api-on').onchange = async e => {
      try { await api(`/api/sites/${site.id}/restapi`, { settings: { enabled: e.target.checked } }); toast(e.target.checked ? 'เปิด API แล้ว' : 'ปิด API แล้ว', 'ok'); renderApi(); }
      catch (err) { toast(err.message, 'err'); }
    };
    root.querySelectorAll('tr[data-slug] select').forEach(sel => sel.onchange = async () => {
      sel.className = `input sm rule-${sel.value}`;
      try { await api(`/api/sites/${site.id}/restapi`, { rules: { [sel.closest('tr').dataset.slug]: { [sel.dataset.a]: sel.value } } }); toast('บันทึกสิทธิ์แล้ว', 'ok'); }
      catch (err) { toast(err.message, 'err'); }
    });
    document.getElementById('api-save').onclick = async () => {
      try {
        await api(`/api/sites/${site.id}/restapi`, { settings: { cors: document.getElementById('api-cors').value, rate: document.getElementById('api-rate').value, log: document.getElementById('api-log').checked } });
        toast('บันทึกแล้ว', 'ok');
      } catch (err) { toast(err.message, 'err'); }
    };
    document.getElementById('key-new').onclick = newKeyModal;
    root.querySelectorAll('#key-list [data-id]').forEach(row => {
      const id = row.dataset.id;
      const rv = row.querySelector('[data-revoke]'), del = row.querySelector('[data-del]');
      if (rv) rv.onclick = async () => {
        if (!await confirmBox('ยกเลิก key', 'โปรแกรมที่ใช้ key นี้จะเรียก API ไม่ได้ทันที — ย้อนกลับไม่ได้', { ok: 'ยกเลิก key', danger: true })) return;
        await api(`/api/apikeys/${id}/revoke`, {}); renderApi();
      };
      if (del) del.onclick = async () => { await api(`/api/apikeys/${id}/delete`, {}); renderApi(); };
    });
    playground(base);
    loadLogs();
    document.getElementById('log-refresh').onclick = loadLogs;
  }

  function newKeyModal() {
    const m = modal(`<header><h2>สร้าง API key</h2><button class="btn ghost icon sm" data-close>${BW_ICON('x')}</button></header><div class="body">
      <label class="field"><span>ชื่อ</span><input class="input" name="name" placeholder="เช่น แอปมือถือ, ระบบหลังร้าน, n8n"></label>
      <label class="check"><input type="checkbox" name="write">เขียนข้อมูลได้ (เพิ่ม/แก้ไข/ลบ ตามสิทธิ์ที่ตั้งเป็น “ต้องมี key”)</label>
      <div class="sect-title">ใช้กับชุดข้อมูล <span class="small muted" style="text-transform:none;letter-spacing:0">— ไม่เลือก = ทุกชุด</span></div>
      ${API.collections.map(c => `<label class="check"><input type="checkbox" data-col="${esc(c.slug)}">${esc(c.name)} <code>${esc(c.slug)}</code></label>`).join('')}
      <div class="alert info" style="margin-top:10px">key ที่เขียนได้ห้ามใส่ในโค้ดหน้าเว็บ (ใครก็เปิดดูได้) — ใช้ในเซิร์ฟเวอร์ แอป หรือเครื่องมืออัตโนมัติเท่านั้น</div></div>
      <footer><button class="btn" data-close>ยกเลิก</button><button class="btn primary" data-ok>สร้าง</button></footer>`);
    m.el.querySelector('[data-ok]').onclick = async () => {
      const d = formData(m.el);
      d.collections = [...m.el.querySelectorAll('[data-col]:checked')].map(x => x.dataset.col);
      try {
        const r = await api(`/api/sites/${site.id}/restapi/keys`, d);
        m.close();
        const k = modal(`<header><h2>key ใหม่: ${esc(r.key.name)}</h2></header><div class="body">
          <div class="alert warn">คัดลอกเก็บไว้ตอนนี้ — key จะแสดงครั้งเดียว BuildWeb เก็บไว้แค่ค่าแฮช</div>
          <div class="row" style="flex-wrap:nowrap"><code style="flex:1;word-break:break-all;padding:8px">${esc(r.plain)}</code><button class="btn" data-copy>${BW_ICON('copy')} คัดลอก</button></div>
          <div class="small muted" style="margin-top:10px">ส่งใน header: <code>X-API-Key: ${esc(r.plain.slice(0, 10))}…</code> หรือ <code>Authorization: Bearer …</code></div></div>
          <footer><button class="btn primary" data-close>เสร็จแล้ว</button></footer>`, { onClose: renderApi });
        k.el.querySelector('[data-copy]').onclick = () => navigator.clipboard.writeText(r.plain).then(() => toast('คัดลอกแล้ว', 'ok'));
      } catch (e) { showFieldError(m.el, e); }
    };
  }

  function playground(base) {
    let as = 'public', lang = 'curl';
    const $ = id => document.getElementById(id);
    const segs = (id, cb) => $(id).querySelectorAll('button').forEach(b => b.onclick = () => {
      $(id).querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); cb(b.dataset.v); code();
    });
    segs('pg-as', v => as = v); segs('pg-lang', v => lang = v);
    const parts = () => {
      const method = $('pg-method').value, path = $('pg-path').value.replace(/^\/+/, ''), key = $('pg-key').value.trim();
      let bodyText = method === 'GET' || method === 'DELETE' ? '' : $('pg-body').value.trim();
      return { method, path, key, bodyText, url: `${base}/${path}` };
    };
    function code() {
      const p = parts(), b = p.bodyText;
      const hk = p.key ? p.key : '';
      const out = {
        curl: `curl -X ${p.method} '${p.url}'${hk ? ` \\\n  -H 'X-API-Key: ${hk}'` : ''}${b ? ` \\\n  -H 'Content-Type: application/json' \\\n  -d '${b.replace(/\n\s*/g, ' ')}'` : ''}`,
        fetch: `const res = await fetch('${p.url}', {\n  method: '${p.method}',\n  headers: {${hk ? ` 'X-API-Key': '${hk}',` : ''}${b ? " 'Content-Type': 'application/json'" : ''} },${b ? `\n  body: JSON.stringify(${b.replace(/\n\s*/g, ' ')}),` : ''}\n});\nconst data = await res.json();`,
        PHP: `$ch = curl_init('${p.url}');\ncurl_setopt_array($ch, [\n  CURLOPT_CUSTOMREQUEST => '${p.method}',\n  CURLOPT_RETURNTRANSFER => true,\n  CURLOPT_HTTPHEADER => [${hk ? `'X-API-Key: ${hk}', ` : ''}'Content-Type: application/json'],${b ? `\n  CURLOPT_POSTFIELDS => '${b.replace(/\n\s*/g, ' ')}',` : ''}\n]);\n$data = json_decode(curl_exec($ch), true);`,
        Python: `import requests\nr = requests.request('${p.method}', '${p.url}'${hk ? `,\n    headers={'X-API-Key': '${hk}'}` : ''}${b ? `,\n    json=${b.replace(/\n\s*/g, ' ').replace(/\btrue\b/g, 'True').replace(/\bfalse\b/g, 'False').replace(/\bnull\b/g, 'None')}` : ''})\ndata = r.json()`,
      }[lang];
      $('pg-code').textContent = out;
    }
    ['pg-method', 'pg-path', 'pg-key', 'pg-body'].forEach(id => $(id).addEventListener('input', code));
    code();
    $('pg-send').onclick = async () => {
      const p = parts(), h = {};
      if (as === 'public') h['X-BW-As'] = 'public';
      if (p.key) h['X-API-Key'] = p.key;
      if (p.bodyText) h['Content-Type'] = 'application/json';
      const t0 = performance.now();
      $('pg-out').textContent = 'กำลังส่ง…';
      try {
        const r = await fetch(`/preview/${site.slug}/api/v1/${p.path}`, { method: p.method, headers: h, body: p.bodyText || undefined });
        const ms = Math.round(performance.now() - t0), text = await r.text();
        $('pg-meta').innerHTML = `<span class="badge ${r.ok ? 'ok' : r.status >= 500 ? 'err' : 'warn'}">${r.status}</span> ${ms} ms`;
        try { $('pg-out').textContent = text ? JSON.stringify(JSON.parse(text), null, 2) : '(ไม่มีเนื้อหา)'; } catch (e) { $('pg-out').textContent = text; }
        loadLogs();
      } catch (e) { $('pg-out').textContent = e.message; }
    };
  }

  async function loadLogs() {
    const box = document.getElementById('api-logs');
    if (!box) return;
    const r = await api(`/api/sites/${site.id}/restapi/logs`);
    box.innerHTML = r.logs.length ? `<table class="table small"><thead><tr><th>เวลา</th><th>คำขอ</th><th>ผล</th><th class="num">ms</th></tr></thead><tbody>
      ${r.logs.map(x => `<tr title="${esc(x.error || '')}"><td class="muted" style="white-space:nowrap">${when(x.at)}</td><td class="mono" style="word-break:break-all"><b>${esc(x.method)}</b> ${esc(x.path.replace(/^\/(preview\/)?[^/]+\/api\/v1/, ''))}
        <div class="muted">${esc(x.key || x.ip)}</div></td><td><span class="badge ${x.status < 300 ? 'ok' : x.status >= 500 ? 'err' : 'warn'}">${x.status}</span></td><td class="num">${x.ms}</td></tr>`).join('')}</tbody></table>`
      : '<div class="empty-state">ยังไม่มีการเรียก API</div>';
  }

  // ---------------------------------------------------------------- statistics
  let statDays = 30;
  async function renderStats() {
    root.innerHTML = '<div class="card pad muted">กำลังโหลด…</div>';
    let r;
    try { r = await api(`/api/sites/${site.id}/stats?days=${statDays}`); } catch (e) { root.innerHTML = `<div class="alert err">${esc(e.message)}</div>`; return; }
    const s = r.stats, t = s.total, num = n => Number(n).toLocaleString('th-TH');
    const trend = t.trend == null ? '' : `<small class="${t.trend >= 0 ? 'up' : 'down'}">${t.trend >= 0 ? '▲' : '▼'} ${Math.abs(t.trend)}%</small>`;
    root.innerHTML = `<div class="row between" style="margin-bottom:14px">
        <div class="muted">นับจากเว็บที่โฮสต์ด้วยเครื่องนี้ (LAN · พอร์ตของเว็บ · Tailscale) — ไม่ใช้คุกกี้ ไม่ส่งข้อมูลออกไปไหน ไม่นับบอทและหน้าตัวอย่าง</div>
        <div class="seg">${[7, 30, 90].map(d => `<button data-d="${d}" class="${d === statDays ? 'on' : ''}">${d} วัน</button>`).join('')}</div></div>
      ${r.hosting ? '' : `<div class="alert warn" style="margin-bottom:14px">โฮสติ้งปิดอยู่ จึงยังไม่มีผู้เข้าชมใหม่ — <a href="/settings/">เปิดโฮสติ้ง</a> · เว็บที่เผยแพร่ไป GitHub/Netlify/FTP นับที่นี่ไม่ได้</div>`}
      <div class="grid g4" style="margin-bottom:16px">
        <div class="card stat"><span>การเข้าชม ${statDays} วัน</span><b>${num(t.views)} ${trend}</b></div>
        <div class="card stat"><span>ผู้เข้าชม (ไม่ซ้ำต่อวัน)</span><b>${num(t.visitors)}</b></div>
        <div class="card stat"><span>วันนี้</span><b>${num(t.today)}</b></div>
        <div class="card stat"><span>เฉลี่ยต่อวัน</span><b>${num(Math.round(t.views / statDays))}</b></div></div>
      <div class="card pad" style="margin-bottom:16px"><div class="row between"><h2>การเข้าชมรายวัน</h2>
        <div class="chart-legend"><span><i class="lg-bar"></i>การเข้าชม</span><span><i class="lg-line"></i>ผู้เข้าชม</span></div></div>
        <div class="chart" id="st-chart"></div>
        <details class="small" style="margin-top:8px"><summary class="muted" style="cursor:pointer">ดูเป็นตาราง</summary>
          <table class="table" style="margin-top:8px"><thead><tr><th>วันที่</th><th class="num">การเข้าชม</th><th class="num">ผู้เข้าชม</th></tr></thead>
          <tbody>${s.days.slice().reverse().map(d => `<tr><td>${dayLabel(d.day, true)}</td><td class="num">${num(d.views)}</td><td class="num">${num(d.visitors)}</td></tr>`).join('')}</tbody></table></details></div>
      <div class="grid g3">
        ${topList('หน้าที่คนดูมากที่สุด', s.pages, k => k === '/' ? '/ (หน้าแรก)' : k)}
        ${topList('มาจากที่ไหน', s.refs, k => k || 'เข้าตรง / ไม่ทราบ')}
        ${topList('อุปกรณ์', s.devices, k => ({ mobile: 'มือถือ / แท็บเล็ต', desktop: 'คอมพิวเตอร์' }[k] || k))}</div>`;
    root.querySelectorAll('[data-d]').forEach(b => b.onclick = () => { statDays = +b.dataset.d; renderStats(); });
    drawChart(document.getElementById('st-chart'), s.days);
  }
  function dayLabel(iso, long) {
    return new Date(iso + 'T00:00:00').toLocaleDateString('th-TH', long ? { day: 'numeric', month: 'short', year: '2-digit' } : { day: 'numeric', month: 'short' });
  }
  function topList(title, items, label) {
    const max = Math.max(1, ...items.map(x => x.count));
    return `<div class="card pad"><h2 style="margin-bottom:10px">${title}</h2>${items.length ? items.map(x => `<div class="top-row">
        <div class="row between"><span class="top-k" title="${esc(label(x.key))}">${esc(label(x.key))}</span><b class="mono">${Number(x.count).toLocaleString('th-TH')}</b></div>
        <div class="top-bar"><i style="width:${Math.max(2, x.count / max * 100)}%"></i></div></div>`).join('') : '<div class="muted small">ยังไม่มีข้อมูล</div>'}</div>`;
  }
  // Bars = views, line = visitors (same unit, one axis). Hover shows the day's numbers.
  function drawChart(box, days) {
    const W = Math.max(320, box.clientWidth), H = 220, pad = { l: 36, r: 8, t: 10, b: 24 };
    const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
    const max = Math.max(4, ...days.map(d => d.views));
    const step = Math.pow(10, Math.floor(Math.log10(max))), nice = Math.ceil(max / step) * step;
    const y = v => pad.t + ih - v / nice * ih, bw = iw / days.length, gap = Math.min(2, bw * .25);
    const ticks = [0, .25, .5, .75, 1].map(f => Math.round(nice * f));
    const every = Math.ceil(days.length / 8);
    const line = days.map((d, i) => `${i ? 'L' : 'M'}${(pad.l + i * bw + bw / 2).toFixed(1)},${y(d.visitors).toFixed(1)}`).join('');
    box.innerHTML = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="กราฟการเข้าชมรายวัน">
      ${[...new Set(ticks)].map(v => `<line class="grid" x1="${pad.l}" x2="${W - pad.r}" y1="${y(v)}" y2="${y(v)}"/><text class="ax" x="${pad.l - 6}" y="${y(v) + 4}" text-anchor="end">${v.toLocaleString('th-TH')}</text>`).join('')}
      ${days.map((d, i) => { const h = ih - (y(d.views) - pad.t); const x = pad.l + i * bw + gap / 2, w = Math.max(1, bw - gap);
        return d.views ? `<path class="bar" d="M${x},${pad.t + ih}V${y(d.views) + Math.min(4, h)}q0,-${Math.min(4, h)} ${Math.min(4, w / 2)},-${Math.min(4, h)}H${x + w - Math.min(4, w / 2)}q${Math.min(4, w / 2)},0 ${Math.min(4, w / 2)},${Math.min(4, h)}V${pad.t + ih}z"/>` : ''; }).join('')}
      <path class="vline" d="${line}"/>
      ${days.map((d, i) => i % every === 0 || (i === days.length - 1 && i % every >= every / 2) ? `<text class="ax" x="${pad.l + i * bw + bw / 2}" y="${H - 6}" text-anchor="middle">${dayLabel(d.day)}</text>` : '').join('')}
      <line class="cross" x1="0" x2="0" y1="${pad.t}" y2="${pad.t + ih}" style="display:none"/>
      ${days.map((d, i) => `<rect class="hit" data-i="${i}" x="${pad.l + i * bw}" y="${pad.t}" width="${bw}" height="${ih}"/>`).join('')}
    </svg><div class="chart-tip" hidden></div>`;
    const tip = box.querySelector('.chart-tip'), cross = box.querySelector('.cross');
    box.querySelectorAll('.hit').forEach(r => {
      r.addEventListener('mouseenter', () => {
        const d = days[+r.dataset.i], cx = +r.getAttribute('x') + bw / 2;
        cross.setAttribute('x1', cx); cross.setAttribute('x2', cx); cross.style.display = '';
        tip.innerHTML = `<b>${dayLabel(d.day, true)}</b><div><i class="lg-bar"></i>การเข้าชม <b>${d.views.toLocaleString('th-TH')}</b></div><div><i class="lg-line"></i>ผู้เข้าชม <b>${d.visitors.toLocaleString('th-TH')}</b></div>`;
        tip.hidden = false;
        tip.style.left = Math.min(W - 170, Math.max(0, cx + 12)) + 'px';
      });
    });
    box.querySelector('svg').addEventListener('mouseleave', () => { tip.hidden = true; cross.style.display = 'none'; });
  }

  // ---------------------------------------------------------------- floating contact buttons
  const CHANNELS = [
    ['phone', 'โทร', 'เบอร์โทร เช่น 081-234-5678', ''],
    ['line', 'LINE', '@ร้านของคุณ (OA) หรือ LINE ID หรือลิงก์', '#06c755'],
    ['messenger', 'Messenger', 'ชื่อเพจ เช่น mycafe หรือ m.me/...', 'linear-gradient(45deg,#0a7cff,#a033ff 60%,#ff5c87)'],
    ['whatsapp', 'WhatsApp', 'เบอร์ เช่น 0812345678', '#25d366'],
    ['facebook', 'Facebook', 'ชื่อเพจ หรือลิงก์', '#1877f2'],
    ['email', 'อีเมล', 'hello@example.com', '#f97316'],
    ['map', 'แผนที่', 'ชื่อร้าน/ที่อยู่ หรือลิงก์ Google Maps', '#ea4335'],
  ];
  function contactEditor(box, theme) {
    const c = { ...site.contact };
    box.innerHTML = `<div class="row between"><div><h2>ปุ่มติดต่อลอย</h2><div class="hint" style="margin:0">ปุ่มโทร / LINE / Messenger / WhatsApp มุมจอทุกหน้า แบบที่ร้านค้านิยม</div></div>
        <label class="switch" title="เปิด/ปิด"><input type="checkbox" data-ct="enabled" ${c.enabled ? 'checked' : ''}><span></span></label></div>
      <div class="contact-layout" style="margin-top:14px"><div>
        <div class="grid g2" style="gap:0 14px">${CHANNELS.map(([k, l, ph]) => `<label class="field"><span>${l}</span><input class="input" data-ct="${k}" value="${esc(c[k] || '')}" placeholder="${esc(ph)}"></label>`).join('')}</div>
        <div class="grid g3" style="gap:0 14px">
          <label class="field"><span>รูปแบบ</span><select class="input" data-ct="style"><option value="stack">ปุ่มเรียงกัน</option><option value="expand">ปุ่มเดียว กดแล้วกาง</option><option value="bar">แถบล่างบนมือถือ</option></select></label>
          <label class="field"><span>ตำแหน่ง</span><select class="input" data-ct="position"><option value="right">มุมขวาล่าง</option><option value="left">มุมซ้ายล่าง</option></select></label>
          <label class="field"><span>ข้อความปุ่มหลัก</span><input class="input" data-ct="label" value="${esc(c.label || 'ติดต่อเรา')}"></label></div>
        <div class="row" style="gap:20px"><label class="check"><input type="checkbox" data-ct="labels" ${c.labels ? 'checked' : ''}>แสดงชื่อเมื่อชี้</label>
          <label class="check"><input type="checkbox" data-ct="pulse" ${c.pulse ? 'checked' : ''}>เอฟเฟกต์กระพริบเบาๆ</label></div>
      </div><div><div class="small muted" style="margin-bottom:6px">ตัวอย่าง</div><div class="fab-preview" id="fab-preview"></div></div></div>`;
    box.querySelector('[data-ct=style]').value = c.style || 'stack';
    box.querySelector('[data-ct=position]').value = c.position || 'right';
    const read = () => {
      const out = { ...c };
      box.querySelectorAll('[data-ct]').forEach(el => out[el.dataset.ct] = el.type === 'checkbox' ? el.checked : el.value);
      return out;
    };
    const draw = () => {
      const v = read(), on = CHANNELS.filter(([k]) => (v[k] || '').trim());
      const pv = document.getElementById('fab-preview');
      const mark = { phone: BW_ICON('phone', 15), email: BW_ICON('mail', 15), map: BW_ICON('pin', 15), line: 'LINE', messenger: 'M', whatsapp: 'W', facebook: 'f' };
      const btn = ([k, l, , col]) => `<span class="pv-btn" style="background:${col || theme.primary};font-size:${k === 'line' ? 8 : 12}px" title="${l}">${mark[k]}</span>`;
      let inner = '';
      if (!v.enabled) inner = '<div class="pv-off">ปิดอยู่</div>';
      else if (!on.length) inner = '<div class="pv-off">ใส่ช่องทางติดต่ออย่างน้อยหนึ่งช่อง</div>';
      else if (v.style === 'bar') inner = `<div class="pv-bar">${on.map(ch => `<span style="background:${ch[3] || theme.primary}">${ch[1]}</span>`).join('')}</div>`;
      else if (v.style === 'expand') inner = `<div class="pv-stack ${v.position}">${on.map(btn).join('')}<span class="pv-btn main" style="background:${theme.primary}">${BW_ICON('chat', 16)}</span></div>`;
      else inner = `<div class="pv-stack ${v.position}">${on.map(btn).join('')}</div>`;
      pv.innerHTML = `<div class="pv-page"><i></i><i></i><i></i></div>${inner}`;
    };
    box.querySelectorAll('[data-ct]').forEach(el => el.addEventListener('input', draw));
    box.querySelectorAll('select[data-ct],input[type=checkbox][data-ct]').forEach(el => el.addEventListener('change', draw));
    draw();
    return read;
  }

  // ---------------------------------------------------------------- one-click publish
  const PUB_TARGETS = [
    ['github', 'GitHub Pages', 'ฟรี · ได้ลิงก์ ชื่อ.github.io · ใช้กับ Cloudflare Pages ได้', 'github'],
    ['netlify', 'Netlify', 'ฟรี · ได้ลิงก์ ชื่อ.netlify.app · ผูกโดเมนเองได้', 'cloud'],
    ['ftp', 'FTP / โฮสติ้งที่เช่า', 'cPanel, Plesk, DirectAdmin หรือโฮสต์ใดก็ได้', 'server'],
  ];
  let pubSel = null;
  async function drawPublish() {
    const box = document.getElementById('pub-card');
    let P;
    try { P = await api(`/api/sites/${site.id}/publish`); } catch (e) { box.innerHTML = `<div class="alert err">${esc(e.message)}</div>`; return; }
    try { pubSel = pubSel || localStorage.getItem('bw-pub-' + site.id); } catch (e) { }
    pubSel = pubSel || (PUB_TARGETS.find(([k]) => (P.publish[k] || {}).last) || PUB_TARGETS[0])[0];
    box.innerHTML = `<div class="row between"><div><h2>เผยแพร่ขึ้นอินเทอร์เน็ตด้วยปุ่มเดียว</h2>
        <div class="hint" style="margin:0">อัปโหลดเว็บไปโฮสต์ฟรีหรือโฮสต์ที่เช่าไว้ — เว็บออนไลน์ตลอดโดยไม่ต้องเปิดเครื่องนี้ทิ้งไว้</div></div>
        ${P.base_url ? `<a class="btn sm" href="${esc(P.base_url)}" target="_blank">${BW_ICON('external')} ${esc(P.base_url)}</a>` : ''}</div>
      <div class="pub-tiles">${PUB_TARGETS.map(([k, l, d, ic]) => { const last = (P.publish[k] || {}).last;
        return `<button class="pub-tile ${k === pubSel ? 'sel' : ''}" data-t="${k}">${BW_ICON(ic, 20)}<div><b>${l}</b><span>${d}</span>
          ${last ? `<span class="badge ok" style="margin-top:6px">เผยแพร่ ${ago(last.at)}</span>` : ''}</div></button>`; }).join('')}</div>
      <div id="pub-form"></div><div id="pub-log"></div>`;
    box.querySelectorAll('.pub-tile').forEach(b => b.onclick = () => {
      pubSel = b.dataset.t; try { localStorage.setItem('bw-pub-' + site.id, pubSel); } catch (e) { }
      box.querySelectorAll('.pub-tile').forEach(x => x.classList.toggle('sel', x === b)); drawPubForm(P);
    });
    drawPubForm(P);
  }
  function drawPubForm(P) {
    const t = pubSel, cfg = P.publish[t] || {}, f = document.getElementById('pub-form');
    const tokenField = (name, link, hint) => `<label class="field"><span>${name} token ${P.tokens[t] ? '<span class="badge ok">บันทึกแล้ว</span>' : ''}</span>
      <input class="input mono" type="password" name="${t}_token" placeholder="${P.tokens[t] ? 'เว้นว่าง = ใช้ token เดิม' : 'วาง token ที่นี่'}" autocomplete="off">
      <small>${hint} — <a href="${link}" target="_blank">สร้าง token</a> · เก็บไว้ในเครื่องนี้เท่านั้น</small></label>`;
    let html = '';
    if (t === 'github') html = `${tokenField('GitHub', 'https://github.com/settings/tokens/new?scopes=repo&description=BuildWeb', 'ใช้ classic token สิทธิ์ <code>repo</code>')}
      <div class="grid g3" style="gap:0 14px"><label class="field"><span>Repo</span><input class="input mono" name="repo" value="${esc(cfg.repo || site.slug)}" placeholder="ชื่อ หรือ เจ้าของ/ชื่อ"><small>ยังไม่มี = สร้างให้ (repo สาธารณะ)</small></label>
        <label class="field"><span>Branch</span><input class="input mono" name="branch" value="${esc(cfg.branch || 'gh-pages')}"><small>ไฟล์ใน branch นี้ถูกแทนที่ทั้งหมด</small></label>
        <label class="field"><span>โดเมนของคุณ <small>(ไม่บังคับ)</small></span><input class="input mono" name="url" value="${esc(cfg.url || '')}" placeholder="https://www.myshop.com/"></label></div>
      <label class="check"><input type="checkbox" name="pages" ${cfg.pages === false ? '' : 'checked'}>เปิด GitHub Pages ให้อัตโนมัติ</label>
      <div class="small muted">ใช้ Cloudflare Pages / Vercel: เชื่อม repo นี้ในหน้าเว็บของบริการนั้นครั้งเดียว แล้วทุกครั้งที่กดเผยแพร่ เว็บจะอัปเดตเอง</div>`;
    if (t === 'netlify') html = `${tokenField('Netlify', 'https://app.netlify.com/user/applications#personal-access-tokens', 'Personal access token')}
      <div class="grid g2" style="gap:0 14px"><label class="field"><span>ชื่อเว็บบน Netlify</span><input class="input mono" name="name" value="${esc(cfg.name || site.slug)}" ${cfg.site_id ? 'disabled' : ''}><small>${cfg.site_id ? 'ผูกกับเว็บ Netlify แล้ว' : 'ได้ลิงก์ <code>ชื่อ.netlify.app</code> (ถ้าชื่อซ้ำจะสุ่มให้)'}</small></label>
        <label class="field"><span>โดเมนของคุณ <small>(ไม่บังคับ)</small></span><input class="input mono" name="url" value="${esc(cfg.url || '')}" placeholder="https://www.myshop.com/"></label></div>`;
    if (t === 'ftp') html = `<div class="grid g3" style="gap:0 14px"><label class="field"><span>Host</span><input class="input mono" name="host" value="${esc(cfg.host || '')}" placeholder="ftp.myshop.com"></label>
        <label class="field"><span>Port</span><input class="input mono" name="port" type="number" value="${esc(cfg.port || 21)}"></label>
        <label class="field"><span>โฟลเดอร์ปลายทาง</span><input class="input mono" name="path" value="${esc(cfg.path ?? 'public_html')}"></label>
        <label class="field"><span>ชื่อผู้ใช้</span><input class="input mono" name="user" value="${esc(cfg.user || '')}"></label>
        <label class="field"><span>รหัสผ่าน ${cfg.password_set ? '<span class="badge ok">บันทึกแล้ว</span>' : ''}</span><input class="input mono" type="password" name="password" placeholder="${cfg.password_set ? 'เว้นว่าง = ใช้รหัสเดิม' : ''}" autocomplete="off"></label>
        <label class="field"><span>ที่อยู่เว็บ</span><input class="input mono" name="url" value="${esc(cfg.url || '')}" placeholder="https://www.myshop.com/"></label></div>
      <label class="check"><input type="checkbox" name="tls" ${cfg.tls ? 'checked' : ''}>ใช้ FTPS (เข้ารหัส) — แนะนำถ้าโฮสต์รองรับ</label>`;
    const last = cfg.last;
    f.innerHTML = `<div class="pub-form">${html}
      ${site.form_endpoint ? '' : '<div class="alert info" style="margin-top:10px">ฟอร์มบนเว็บที่เผยแพร่จะส่งข้อมูลได้เมื่อตั้ง “ที่ส่งฟอร์ม” ในแท็บตั้งค่าเว็บ (เช่นลิงก์ Tailscale Funnel ของเครื่องนี้)</div>'}
      <div class="row" style="margin-top:12px"><button class="btn primary" id="pub-go">${BW_ICON('cloud')} เผยแพร่เลย</button><button class="btn" id="pub-save">บันทึกการตั้งค่า</button>
        ${t === 'ftp' ? '<button class="btn" id="pub-test">ทดสอบการเชื่อมต่อ</button>' : ''}
        ${last ? `<span class="small muted" style="margin-left:auto">ล่าสุด ${when(last.at)} · ${last.files} ไฟล์ ${last.url ? `· <a href="${esc(last.url)}" target="_blank">${esc(last.url)}</a>` : ''}</span>` : ''}</div></div>`;
    const collect = () => { const d = formData(f); d.target = t; return d; };
    const save = async () => { const r = await api(`/api/sites/${site.id}/publish`, collect()); Object.assign(P, r); return r; };
    document.getElementById('pub-save').onclick = async () => { try { await save(); toast('บันทึกแล้ว', 'ok'); drawPublish(); } catch (e) { showFieldError(f, e); } };
    const test = document.getElementById('pub-test');
    if (test) test.onclick = async () => { try { await save(); const r = await api(`/api/sites/${site.id}/publish/test-ftp`, {}); toast(r.message, 'ok'); } catch (e) { toast(e.message, 'err'); } };
    document.getElementById('pub-go').onclick = async (e) => {
      const btn = e.currentTarget; btn.disabled = true;
      try { await save(); const r = await api(`/api/sites/${site.id}/publish/${t}`, {}); watchJob(r.job); }
      catch (err) { showFieldError(f, err); btn.disabled = false; }
    };
  }
  function watchJob(job) {
    const out = document.getElementById('pub-log');
    const draw = j => {
      out.innerHTML = `<div class="log" style="margin-top:14px;max-height:220px;overflow:auto">${j.log.map(esc).join('\n')}</div>
        ${j.state === 'done' ? `<div class="alert ok" style="margin-top:10px"><div>${BW_ICON('check')} เผยแพร่แล้ว${j.url ? ` — <a href="${esc(j.url)}" target="_blank">${esc(j.url)}</a><div class="small muted">ครั้งแรกอาจใช้เวลา 1–2 นาทีก่อนเปิดได้</div>` : ''}</div></div>` : ''}
        ${j.state === 'error' ? `<div class="alert err" style="margin-top:10px">${esc(j.error)}</div>` : ''}`;
      const lg = out.querySelector('.log'); lg.scrollTop = lg.scrollHeight;
    };
    draw(job);
    const timer = setInterval(async () => {
      try {
        const r = await api(`/api/publish/jobs/${job.id}`);
        draw(r.job);
        if (r.job.state !== 'running') {
          clearInterval(timer);
          const go = document.getElementById('pub-go'); if (go) go.disabled = false;
          if (r.job.state === 'done') { toast('เผยแพร่เรียบร้อย', 'ok'); const keep = out.innerHTML; await drawPublish(); document.getElementById('pub-log').innerHTML = keep; }
        }
      } catch (e) { clearInterval(timer); toast(e.message, 'err'); }
    }, 1000);
  }

  // ---------------------------------------------------------------- export
  function siteUrls(h) {
    const urls = h.urls.map(u => u + site.slug + '/');
    if (h.tailscale && h.tailscale.url) urls.push(h.tailscale.url + site.slug + '/');
    const own = (h.site_ports || []).find(x => x.slug === site.slug);
    if (own) urls.unshift(...own.urls);
    return urls;
  }

  function renderExport() {
    const ex = D.export || {};
    const h = D.hosting;
    const target = ex.last_target || 'downloads';
    const opt = (val, title, desc, disabled) => `<label class="opt ${val === target ? 'sel' : ''}" ${disabled ? 'style="opacity:.5"' : ''}><input type="radio" name="target" value="${val}" ${val === target ? 'checked' : ''} ${disabled ? 'disabled' : ''}><div><b>${title}</b><span>${desc}</span></div></label>`;
    root.innerHTML = `<div class="card pad" id="pub-card" style="margin-bottom:16px"><div class="muted">กำลังโหลด…</div></div><div class="grid g2">
      <div class="card pad"><h2>ส่งออกเป็นไฟล์ HTML / CSS / JS</h2><div class="hint">ได้โฟลเดอร์เว็บที่ใช้งานได้ทันที เปิดจากเครื่อง อัปขึ้นโฮสต์ใดก็ได้</div>
        ${opt('downloads', 'โฟลเดอร์ดาวน์โหลด', '~/Downloads/BuildWeb/' + esc(site.slug))}
        ${opt('xampp', 'XAMPP htdocs', D.xampp.htdocs ? `${esc(D.xampp.htdocs)}/${esc(site.slug)} → เปิดที่ http://localhost/${esc(site.slug)}/` : 'ไม่พบ XAMPP ในเครื่อง', !D.xampp.htdocs)}
        ${opt('custom', 'เลือกโฟลเดอร์เอง', 'ระบุตำแหน่งด้านล่าง')}
        <input class="input mono ${target === 'custom' ? '' : 'hidden'}" name="custom_path" value="${esc(ex.custom_path || '')}" placeholder="/Users/you/Sites" style="margin-bottom:12px">
        <div class="row" style="gap:20px;margin:6px 0 12px"><label class="check"><input type="radio" name="format" value="folder" checked>โฟลเดอร์</label><label class="check"><input type="radio" name="format" value="zip">ไฟล์ .zip</label></div>
        <label class="check"><input type="checkbox" name="php_forms" ${target === 'xampp' ? 'checked' : ''}>ใส่ตัวรับฟอร์ม PHP (<code>bw-form.php</code>) บันทึกลง MySQL ของ XAMPP</label>
        <label class="check"><input type="checkbox" name="include_drafts">รวมหน้าฉบับร่างด้วย</label>
        <button class="btn primary" id="do-export" style="margin-top:8px">ส่งออก</button>
        <div id="ex-result" style="margin-top:14px"></div>
        <div class="muted small" style="margin-top:12px">โครงสร้าง: <code>index.html</code>, <code>&lt;หน้า&gt;.html</code>, <code>css/</code>, <code>js/site.js</code>, <code>assets/</code></div>
      </div>
      <div class="card pad"><h2>โฮสต์เว็บจากเครื่องนี้</h2><div class="hint">ให้คนในเครือข่ายเดียวกัน (Wi-Fi เดียวกัน) เปิดเว็บได้ทันที</div>
        ${h.running ? `<div class="alert ok"><span class="badge ok"><span class="dot"></span>ออนไลน์</span></div>
          ${siteUrls(h).map(u => `<div class="row" style="margin-bottom:8px;flex-wrap:nowrap"><code style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(u)}</code><a class="btn sm" href="${esc(u)}" target="_blank">เปิด</a></div>`).join('')}
          ${site.published ? '' : '<div class="alert warn">เว็บนี้ปิดการเผยแพร่อยู่ — เปิดได้ที่แท็บ “ตั้งค่าเว็บ”</div>'}`
        : `<div class="alert warn">โฮสติ้งยังปิดอยู่</div>`}
        <a class="btn" href="/settings/">ตั้งค่าโฮสติ้ง</a>
        <div class="sect-title">ตัวอย่างในเครื่อง</div>
        <div class="row"><code style="flex:1">${location.origin}/preview/${esc(site.slug)}/</code><a class="btn sm" href="/preview/${esc(site.slug)}/" target="_blank">เปิด</a></div>
        <div class="muted small" style="margin-top:6px">หน้าตัวอย่างแสดงหน้าฉบับร่างด้วย และเปิดได้เฉพาะเครื่องนี้</div>
      </div></div>`;
    drawPublish();
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
