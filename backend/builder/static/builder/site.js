// Site manager: pages, files, form submissions, settings/theme, export.
(function () {
  const D = JSON.parse(document.getElementById('site-data').textContent);
  const root = document.getElementById('tab');
  const site = D.site;
  const { api, toast, esc, modal, confirmBox, formData, showFieldError, bytes, ago, when } = BW;

  const tabs = { data: renderData, pages: renderPages, files: renderFiles, forms: renderForms, settings: renderSettings, export: renderExport };


  // ---------------------------------------------------------------- data (collections)
  const TYPES = { text: 'ข้อความ', longtext: 'ข้อความยาว', number: 'ตัวเลข', image: 'รูป', link: 'ลิงก์', date: 'วันที่', bool: 'ใช่/ไม่', html: 'HTML' };
  let DATA = { collections: [], connections: [] };

  async function renderData(selectId) {
    DATA = await api(`/api/sites/${site.id}/collections`);
    const sel = selectId || +(new URLSearchParams(location.search).get('c')) || (DATA.collections[0] || {}).id;
    root.innerHTML = `<div class="row between" style="margin-bottom:14px">
        <div class="muted">ชุดข้อมูลที่หน้าเว็บนำไปแสดงได้ — ใช้บล็อก “ข้อมูล” ในตัวออกแบบ หรือพิมพ์ <code>{{ฟิลด์}}</code></div>
        <div class="row"><button class="btn" id="d-mysql">${BW_ICON('database')} นำเข้าจาก MySQL / XAMPP</button>
        <button class="btn" id="d-file">${BW_ICON('upload')} นำเข้า .sql / CSV</button><button class="btn primary" id="d-new">${BW_ICON('plus')} สร้างเอง</button></div></div>
      <div class="data-layout"><div class="card data-list" id="d-list"></div><div id="d-main"></div></div>`;
    const list = document.getElementById('d-list');
    list.innerHTML = DATA.collections.length ? DATA.collections.map(c => `<a class="data-item ${c.id === sel ? 'active' : ''}" data-id="${c.id}">
        <div class="row between"><b>${esc(c.name)}</b>${c.mode === 'live' ? '<span class="badge brand">สด</span>' : ''}</div>
        <div class="small muted mono">${esc(c.slug)} · ${c.fields.length} ฟิลด์${c.count != null ? ' · ' + c.count + ' แถว' : ''}</div></a>`).join('')
      : `<div class="empty-state">${BW_ICON('table', 28)}<div style="margin-top:8px">ยังไม่มีชุดข้อมูล</div></div>`;
    list.querySelectorAll('[data-id]').forEach(a => a.onclick = () => openCollection(+a.dataset.id));
    document.getElementById('d-mysql').onclick = mysqlWizard;
    document.getElementById('d-file').onclick = fileImport;
    document.getElementById('d-new').onclick = newCollection;
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
    const src = c.connection ? `${esc(c.connection_name)} › ${esc(c.source_database)}.${esc(c.source_table)}` : '';
    main.innerHTML = `<div class="card">
      <div class="card-head"><div><h2>${esc(c.name)}</h2><div class="small muted">ใช้อ้างอิง <code>${esc(c.slug)}</code>${src ? ' · จาก ' + src : ''}${c.last_synced ? ' · ซิงก์ ' + ago(c.last_synced) : ''}</div></div>
        <div class="row">${c.connection ? `<button class="btn sm" id="c-sync">${BW_ICON('refresh')} ${c.mode === 'live' ? 'โหลดใหม่' : 'ซิงก์จาก MySQL'}</button>` : ''}
          <a class="btn sm" href="/api/collections/${c.id}/export.csv">CSV</a><button class="btn sm" id="c-settings">${BW_ICON('settings')} ฟิลด์ & ตั้งค่า</button>
          <button class="btn sm danger icon" id="c-del" title="ลบชุดข้อมูล">${BW_ICON('trash')}</button></div></div>
      ${r.error ? `<div class="alert err" style="margin:14px 16px 0">${esc(r.error)}</div>` : ''}
      ${c.mode === 'live' ? `<div class="alert info" style="margin:14px 16px 0">โหมดเชื่อมสด: อ่านจาก MySQL ทุกครั้งที่มีคนเปิดเว็บ (แคช 15 วินาที) · แก้ข้อมูลที่ phpMyAdmin</div>` : ''}
      <div class="data-table-wrap"><table class="table data-table"><thead><tr>${r.editable ? '<th style="width:32px"><input type="checkbox" id="c-all"></th>' : ''}
        ${c.fields.map(f => `<th title="${esc(f.label)}">${esc(f.name)} <span class="muted small">${TYPES[f.type] || f.type}</span></th>`).join('')}</tr></thead>
        <tbody>${rows.map(row => `<tr data-id="${row._id || ''}">${r.editable ? '<td><input type="checkbox" class="c-row"></td>' : ''}
          ${c.fields.map(f => cell(f, row[f.name], r.editable)).join('')}</tr>`).join('')}</tbody></table>
        ${rows.length ? '' : '<div class="empty-state">ยังไม่มีแถวข้อมูล</div>'}</div>
      ${r.editable ? `<div class="row" style="padding:12px 16px;border-top:1px solid var(--line)"><button class="btn sm" id="c-add">${BW_ICON('plus')} เพิ่มแถว</button>
        <button class="btn sm danger" id="c-remove" disabled>ลบแถวที่เลือก</button><span class="small muted" style="margin-left:auto">คลิกช่องเพื่อแก้ไข · บันทึกเมื่อออกจากช่อง</span></div>` : ''}
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
      const sync = () => document.getElementById('c-remove').disabled = !tbody.querySelector('.c-row:checked');
      tbody.querySelectorAll('.c-row').forEach(x => x.onchange = sync);
      document.getElementById('c-all').onchange = e => { tbody.querySelectorAll('.c-row').forEach(x => x.checked = e.target.checked); sync(); };
      document.getElementById('c-add').onclick = async () => {
        try { await api(`/api/collections/${c.id}/rows/save`, { data: {} }); openCollection(c.id); } catch (e) { toast(e.message, 'err'); }
      };
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
    document.getElementById('c-del').onclick = async () => {
      if (!await confirmBox('ลบชุดข้อมูล', `ลบ “${esc(c.name)}” และข้อมูลทั้งหมดในชุดนี้? (ตารางใน MySQL ไม่ถูกแตะ)`, { ok: 'ลบ', danger: true })) return;
      await api(`/api/collections/${c.id}/delete`, {}); history.replaceState(null, '', location.pathname); renderData();
    };
  }

  function cell(f, v, editable) {
    const val = v == null ? '' : String(v);
    if (!editable) return `<td>${f.type === 'image' && val ? `<span class="thumb-sm" style="background-image:url('${encodeURI(val)}')"></span>` : ''}${esc(val.slice(0, 200))}</td>`;
    return `<td contenteditable="plaintext-only" data-f="${esc(f.name)}" class="${f.type === 'number' ? 'num' : ''}">${esc(val)}</td>`;
  }

  function collectionSettings(c) {
    const row = f => `<div class="field-row"><input class="input mono" data-k="name" value="${esc(f.name)}" data-orig="${esc(f.name)}"><input class="input" data-k="label" value="${esc(f.label)}">
      <select class="input" data-k="type">${Object.entries(TYPES).map(([k, l]) => `<option value="${k}" ${k === f.type ? 'selected' : ''}>${l}</option>`).join('')}</select>
      <button class="btn sm ghost icon" data-rm title="ลบฟิลด์">${BW_ICON('x')}</button></div>`;
    const m = modal(`<header><h2>ตั้งค่าชุดข้อมูล</h2><button class="btn ghost icon sm" data-close>${BW_ICON('x')}</button></header><div class="body">
      <div class="grid g2" style="gap:0 12px"><label class="field"><span>ชื่อ</span><input class="input" name="name" value="${esc(c.name)}"></label>
      <label class="field"><span>ชื่อที่ใช้อ้างอิง <small>(ใน data-bw-repeat)</small></span><input class="input mono" name="slug" value="${esc(c.slug)}"></label></div>
      ${c.mode === 'live' ? `<div class="grid g3" style="gap:0 12px"><label class="field"><span>เรียงตามคอลัมน์</span><input class="input mono" name="live_order" value="${esc(c.live_order)}"></label>
        <label class="field"><span>ลำดับ</span><select class="input" name="live_desc"><option value="">น้อย → มาก</option><option value="1" ${c.live_desc ? 'selected' : ''}>มาก → น้อย</option></select></label>
        <label class="field"><span>ดึงสูงสุด (แถว)</span><input class="input mono" name="live_limit" type="number" value="${c.live_limit}"></label></div>` : ''}
      <div class="sect-title">ฟิลด์ <span class="small muted" style="text-transform:none;letter-spacing:0">— ชื่อ (ใช้ใน {{ }}) · ชื่อที่แสดง · ชนิด</span></div>
      <div id="f-rows">${c.fields.map(row).join('')}</div>
      ${c.mode === 'live' ? '' : `<button class="btn sm" id="f-add">${BW_ICON('plus')} เพิ่มฟิลด์</button>`}</div>
      <footer><button class="btn" data-close>ยกเลิก</button><button class="btn primary" data-save>บันทึก</button></footer>`, { wide: true });
    const bindRm = () => m.el.querySelectorAll('[data-rm]').forEach(b => b.onclick = () => b.closest('.field-row').remove());
    bindRm();
    const add = m.el.querySelector('#f-add');
    if (add) add.onclick = () => { m.el.querySelector('#f-rows').insertAdjacentHTML('beforeend', row({ name: 'field', label: 'ฟิลด์ใหม่', type: 'text' })); bindRm(); };
    m.el.querySelector('[data-save]').onclick = async () => {
      const d = formData(m.el);
      const rows = [...m.el.querySelectorAll('.field-row')];
      d.fields = rows.map(r => ({ name: r.querySelector('[data-k=name]').value, label: r.querySelector('[data-k=label]').value, type: r.querySelector('[data-k=type]').value }));
      d.renames = rows.map(r => ({ from: r.querySelector('[data-k=name]').dataset.orig, to: r.querySelector('[data-k=name]').value })).filter(x => x.from && x.from !== x.to);
      if ('live_desc' in d) d.live_desc = d.live_desc === '1';
      try { await api(`/api/collections/${c.id}/update`, d); m.close(); toast('บันทึกแล้ว', 'ok'); renderData(c.id); }
      catch (e) { showFieldError(m.el, e); }
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
        <span class="kind-icon">${BW_ICON(x.kind === 'header' ? 'panel-top' : 'panel-bottom')}</span>
        <div style="flex:1"><b>${esc(x.label)}</b><div class="muted small">แก้ไข ${ago(x.updated_at)}</div></div>
        <label class="switch" title="เปิด/ปิดทุกหน้า"><input type="checkbox" ${x.enabled ? 'checked' : ''}><span></span></label>
        <a class="btn sm" href="${x.edit_url}">ออกแบบ</a></div>`).join('') ||
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
        <td class="handle" title="ลากเพื่อเรียงลำดับ">${BW_ICON('drag', 15)}</td>
        <td><div class="page-title">${p.is_home ? '<span class="badge" style="height:18px;margin-right:6px">หน้าแรก</span>' : ''}${p.parent ? '<span class="muted">↳ </span>' : ''}${esc(p.title)}
          <small>${p.parent && byId[p.parent] ? 'อยู่ใต้ ' + esc(byId[p.parent].title) + ' · ' : ''}${p.seo_description ? esc(p.seo_description.slice(0, 70)) : 'ยังไม่มีคำอธิบาย SEO'}</small></div></td>
        <td class="mono small">${esc(p.filename)}</td>
        <td>${p.status === 'published' ? '<span class="badge ok">เผยแพร่</span>' : '<span class="badge warn">ฉบับร่าง</span>'}</td>
        <td>${p.show_in_nav ? esc(p.nav_label || p.title) : '<span class="muted">ซ่อน</span>'}</td>
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
      <footer>${isNew ? '' : `<a class="btn" href="${p.edit_url}" style="margin-right:auto">ไปออกแบบ</a>`}<button class="btn" data-close>ยกเลิก</button>
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
    root.innerHTML = `<div class="grid g2">
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
