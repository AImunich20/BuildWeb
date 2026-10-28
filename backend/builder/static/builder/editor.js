// BuildWeb drag-and-drop editor (GrapesJS) — one GrapesJS project per page, saved to Django.
(function () {
  const D = JSON.parse(document.getElementById('editor-data').textContent);
  const { api, toast, esc, modal, confirmBox, formData, showFieldError, ago, when } = BW;
  const site = D.site, page = D.page || {}, target = D.target;
  const isShared = target.type === 'shared';
  const csrf = BW.cookie('buildweb_csrf');
  const $ = s => document.querySelector(s);
  const saveState = $('#save-state');

  function setState(text, cls = '') { saveState.textContent = text; saveState.className = 'save-state ' + cls; }

  function stripBody(html) {
    const m = /^\s*<body[^>]*>([\s\S]*)<\/body>\s*$/i.exec(html || '');
    return m ? m[1] : (html || '');
  }

  // ------------------------------------------------------------------ storage (Django)
  let loadedFromProject = false;
  let loaded = { html: '', css: '' };
  const djangoStorage = editor => {
    editor.Storage.add('django', {
      async load() {
        const r = await api(target.storage);
        loaded = r;
        loadedFromProject = !!(r.project && r.project.pages);
        return loadedFromProject ? r.project : {};
      },
      async store(data) {
        const html = editor.getHtml(), css = editor.getCss(), js = editor.getJs();
        await api(target.storage, { project: data, html, css, js });
      },
    });
  };

  // ------------------------------------------------------------------ i18n (Thai)
  const th = {
    assetManager: { addButton: 'เพิ่มรูป', inputPlh: 'วางลิงก์รูป https://...', modalTitle: 'เลือกรูปภาพ', uploadTitle: 'ลากไฟล์มาวางที่นี่ หรือคลิกเพื่ออัปโหลด' },
    domComponents: { names: { '': 'กล่อง', wrapper: 'หน้า', text: 'ข้อความ', comment: 'คอมเมนต์', image: 'รูปภาพ', video: 'วิดีโอ', label: 'ป้าย', link: 'ลิงก์', map: 'แผนที่', table: 'ตาราง', row: 'แถว', cell: 'ช่อง', form: 'ฟอร์ม', input: 'ช่องกรอก', textarea: 'ช่องข้อความ', select: 'ตัวเลือก', button: 'ปุ่ม', checkbox: 'กล่องเลือก', radio: 'ปุ่มเลือก' } },
    selectorManager: { label: 'คลาส', selected: 'ที่เลือก', emptyState: '- สถานะ -', states: { hover: 'เมื่อชี้เมาส์', active: 'เมื่อกด', 'nth-of-type(2n)': 'ตัวคู่' } },
    styleManager: {
      empty: 'เลือกองค์ประกอบก่อนปรับสไตล์', layer: 'เลเยอร์', fileButton: 'รูปภาพ',
      properties: {
        display: 'การแสดงผล', position: 'ตำแหน่ง', top: 'บน', right: 'ขวา', left: 'ซ้าย', bottom: 'ล่าง', width: 'กว้าง', height: 'สูง',
        'max-width': 'กว้างสุด', 'min-height': 'สูงต่ำสุด', margin: 'ระยะขอบนอก', padding: 'ระยะขอบใน', 'font-family': 'ฟอนต์', 'font-size': 'ขนาดตัวอักษร',
        'font-weight': 'ความหนา', 'letter-spacing': 'ระยะตัวอักษร', color: 'สีตัวอักษร', 'line-height': 'ระยะบรรทัด', 'text-align': 'จัดแนว',
        'text-decoration': 'ขีดเส้น', 'text-shadow': 'เงาตัวอักษร', 'background-color': 'สีพื้นหลัง', background: 'พื้นหลัง (รูป/ไล่สี)',
        'border-radius': 'มุมโค้ง', border: 'เส้นขอบ', 'box-shadow': 'เงา', opacity: 'ความทึบ', 'flex-direction': 'ทิศทาง', 'justify-content': 'จัดแนวนอน',
        'align-items': 'จัดแนวตั้ง', gap: 'ระยะห่าง', 'flex-wrap': 'ขึ้นบรรทัดใหม่', 'text-transform': 'ตัวพิมพ์', 'object-fit': 'การปรับรูป', overflow: 'ล้นกรอบ',
        transition: 'แอนิเมชัน', cursor: 'เคอร์เซอร์', 'z-index': 'ลำดับซ้อน', 'min-width': 'กว้างต่ำสุด', 'max-height': 'สูงสุด', 'grid-template-columns': 'คอลัมน์กริด',
      },
    },
    traitManager: {
      empty: 'เลือกองค์ประกอบก่อนตั้งค่า', label: 'ตั้งค่าองค์ประกอบ',
      traits: { labels: { id: 'ไอดี', title: 'คำอธิบาย (title)', href: 'ลิงก์ (URL)', target: 'เปิดใน', alt: 'คำอธิบายรูป (alt)', placeholder: 'ข้อความตัวอย่าง', name: 'ชื่อฟิลด์', required: 'ต้องกรอก', type: 'ชนิด', value: 'ค่า', method: 'วิธีส่ง', action: 'ส่งไปที่', checked: 'เลือกไว้', for: 'สำหรับฟิลด์', text: 'ข้อความ' },
        options: { target: { false: 'แท็บเดิม', _blank: 'แท็บใหม่' } } },
    },
    deviceManager: { device: 'อุปกรณ์', devices: { desktop: 'คอมพิวเตอร์', tablet: 'แท็บเล็ต', mobile: 'มือถือ' } },
  };

  const FONTS = ['Prompt', 'Kanit', 'Sarabun', 'Noto Sans Thai', 'Mitr', 'IBM Plex Sans Thai', 'Bai Jamjuree', 'Chakra Petch', 'Anuphan', 'K2D', 'Niramit',
    'Pridi', 'Taviraj', 'Trirong', 'Noto Serif Thai', 'Inter', 'Poppins', 'Roboto', 'Montserrat', 'Open Sans', 'Playfair Display', 'Lora'];
  const fontOptions = [{ id: '', label: '(ตามธีม)' }, { id: 'var(--bw-font-heading)', label: 'ฟอนต์หัวข้อของธีม' }, { id: 'var(--bw-font-body)', label: 'ฟอนต์เนื้อหาของธีม' },
    ...FONTS.map(f => ({ id: `'${f}', sans-serif`, label: f })), { id: 'system-ui, sans-serif', label: 'ฟอนต์ระบบ' }];

  function fontsUrl(theme) {
    const fams = [...new Set([theme.font_heading, theme.font_body])].filter(f => FONTS.includes(f));
    if (!fams.length) return '';
    return 'https://fonts.googleapis.com/css2?' + fams.map(f => `family=${encodeURIComponent(f).replace(/%20/g, '+')}:wght@300;400;500;600;700`).join('&') + '&display=swap';
  }

  // ------------------------------------------------------------------ init
  const P = n => window[n];
  const editor = grapesjs.init({
    container: '#gjs',
    height: '100%',
    width: 'auto',
    fromElement: false,
    showOffsets: true,
    noticeOnUnload: false,
    i18n: { locale: 'th', detectLocale: false, localeFallback: 'en', messagesAdd: { th } },
    storageManager: { type: 'django', autosave: true, autoload: true, stepsBeforeSave: 1 },
    undoManager: { trackSelection: false },
    canvas: {
      styles: [D.fonts_url, `${D.preview_base}css/site.css`, ...(D.canvas_styles || [])].filter(Boolean),
      scripts: D.canvas_scripts || [],
    },
    panels: { defaults: [] },
    blockManager: { appendTo: '#blocks' },
    layerManager: { appendTo: '#layers' },
    selectorManager: { appendTo: '#selectors', componentFirst: true },
    traitManager: { appendTo: '#traits' },
    deviceManager: {
      devices: [
        { id: 'desktop', name: 'desktop', width: '' },
        { id: 'tablet', name: 'tablet', width: '768px', widthMedia: '992px' },
        { id: 'mobile', name: 'mobile', width: '375px', widthMedia: '768px' },
      ],
    },
    assetManager: {
      upload: `/api/sites/${site.id}/assets/upload`, uploadName: 'files', multiUpload: true, autoAdd: true,
      headers: { 'X-CSRFToken': csrf }, credentials: 'same-origin', assets: [],
    },
    styleManager: {
      appendTo: '#styles',
      sectors: [
        { id: 'typography', name: 'ตัวอักษร', open: true, properties: ['font-family', 'font-size', 'font-weight', 'color', 'line-height', 'letter-spacing', 'text-align', 'text-transform', 'text-decoration', 'text-shadow'] },
        { id: 'size', name: 'ขนาด & ระยะห่าง', open: false, properties: ['width', 'max-width', 'min-width', 'height', 'min-height', 'max-height', 'margin', 'padding'] },
        { id: 'decor', name: 'พื้นหลัง & ขอบ', open: false, properties: ['background-color', 'background', 'border-radius', 'border', 'box-shadow', 'opacity'] },
        { id: 'layout', name: 'การจัดวาง', open: false, properties: ['display', 'flex-direction', 'flex-wrap', 'justify-content', 'align-items', 'gap', 'grid-template-columns', 'position', 'top', 'right', 'bottom', 'left', 'z-index', 'overflow'] },
        { id: 'extra', name: 'อื่นๆ', open: false, properties: ['object-fit', 'cursor', 'transition'] },
      ],
    },
    plugins: [djangoStorage, P('grapesjs-parser-postcss'), P('gjs-blocks-basic'), P('grapesjs-plugin-forms'), P('grapesjs-custom-code'), P('grapesjs-navbar'), P('grapesjs-tabs'),
      P('grapesjs-component-countdown'), P('grapesjs-tooltip')].filter(Boolean),
    pluginsOpts: {
      'gjs-blocks-basic': { flexGrid: true, category: 'พื้นฐาน', labelText: 'ข้อความ', labelLink: 'ลิงก์', labelImage: 'รูปภาพ', labelVideo: 'วิดีโอ', labelMap: 'แผนที่',
        blocks: ['column1', 'column2', 'column3', 'column3-7', 'text', 'link', 'image', 'video', 'map'] },
      'grapesjs-plugin-forms': { block: id => ({ category: 'ฟอร์ม', label: { form: 'ฟอร์มเปล่า', input: 'ช่องกรอก', textarea: 'ช่องข้อความยาว', select: 'ตัวเลือก', button: 'ปุ่มส่ง', label: 'ป้ายชื่อ', checkbox: 'กล่องติ๊ก', radio: 'ปุ่มเลือกข้อเดียว' }[id] }) },
      'grapesjs-custom-code': { blockCustomCode: { category: 'ขั้นสูง', label: 'โค้ด HTML เอง' }, modalTitle: 'แทรกโค้ด HTML/JS', buttonLabel: 'บันทึก' },
      'grapesjs-navbar': { block: { category: 'ส่วนประกอบ', label: 'เมนูนำทาง (ย่อได้)' } },
      'grapesjs-tabs': { tabsBlock: { category: 'ส่วนประกอบ', label: 'แท็บ' } },
      'grapesjs-component-countdown': { block: { category: 'ส่วนประกอบ', label: 'นับถอยหลัง' }, labelDays: 'วัน', labelHours: 'ชม.', labelMinutes: 'นาที', labelSeconds: 'วินาที', endText: 'หมดเวลาแล้ว' },
      'grapesjs-tooltip': { blockTooltip: { category: 'ส่วนประกอบ', label: 'ทูลทิป' } },
    },
  });
  window.editor = editor;

  // ------------------------------------------------------------------ blocks
  const bm = editor.BlockManager;
  const CAT_ORDER = ['ส่วนหัว/ท้าย', 'เนื้อหา', 'ขาย', 'ข้อมูล', 'สื่อ', 'ฟอร์ม', 'พื้นฐาน', 'ส่วนประกอบ', 'ขั้นสูง'];
  D.sections.forEach(s => bm.add('bw-' + s.id, {
    label: s.label, category: s.category, content: s.content, media: `<div class="bw-bicon">${BW_ICON(s.icon, 20)}</div>`,
    attributes: { title: 'ลากไปวางในหน้า' },
  }));
  // A few small Canva-style elements
  const el = (id, label, icon, content, category = 'พื้นฐาน') => bm.add('bw-el-' + id, { label, category, content, media: `<div class="bw-bicon">${BW_ICON(icon, 20)}</div>` });
  el('heading', 'หัวข้อ', 'heading', '<h2 style="padding:10px 0">หัวข้อใหม่</h2>');
  el('para', 'ย่อหน้า', 'text', '<p style="padding:6px 0">ดับเบิลคลิกเพื่อพิมพ์ข้อความของคุณ</p>');
  el('button', 'ปุ่ม', 'button', '<a href="#" class="bw-btn">ปุ่มของคุณ</a>');
  el('button2', 'ปุ่มขอบ', 'button-outline', '<a href="#" class="bw-btn bw-btn-outline">ปุ่มของคุณ</a>');
  el('divider', 'เส้นคั่น', 'divider', '<hr style="border:0;border-top:1px solid #e5e7eb;margin:24px 0">');
  el('spacer', 'ช่องว่าง', 'spacer', '<div style="height:60px"></div>');
  el('container', 'กล่องกึ่งกลาง', 'box', '<div class="bw-container" style="padding:40px 20px;min-height:80px"></div>');
  el('section', 'ส่วนว่าง', 'section', '<section style="padding:70px 0;min-height:120px"><div class="bw-container" style="min-height:60px"></div></section>');
  el('list', 'รายการ', 'list', '<ul style="padding-left:22px;line-height:1.9"><li>รายการที่หนึ่ง</li><li>รายการที่สอง</li><li>รายการที่สาม</li></ul>');
  el('icon', 'สัญลักษณ์', 'smile', '<span style="font-size:48px;display:inline-block">★</span>');
  el('repeat', 'กล่องวนซ้ำข้อมูล', 'repeat', '<div class="bw-container" data-bw-repeat="" style="display:grid;grid-template-columns:repeat(3,1fr);gap:20px;padding:30px 20px"><div style="padding:20px;border:1px solid #eee;border-radius:12px"><h3>{{ชื่อฟิลด์}}</h3><p>เลือกชุดข้อมูลที่แท็บ “ตั้งค่า”</p></div></div>', 'ข้อมูล');

  function renderBlocks(filter = '') {
    const q = filter.trim().toLowerCase();
    const all = bm.getAll().filter(b => !q || String(b.get('label')).toLowerCase().includes(q));
    const order = c => { const n = typeof c === 'string' ? c : (c && c.get ? c.get('id') : ''); const i = CAT_ORDER.indexOf(n); return i < 0 ? 99 : i; };
    all.sort((a, b) => order(a.get('category')) - order(b.get('category')));
    bm.render(all);
  }
  $('#block-search').addEventListener('input', e => renderBlocks(e.target.value));

  // ------------------------------------------------------------------ link → page trait
  const pageOptions = [{ id: '', name: '— เลือกหน้า —' }, ...D.pages.map(p => ({ id: p.filename, name: p.title + (p.status === 'draft' ? ' (ร่าง)' : '') })),
    { id: '#', name: '# (ไม่ลิงก์)' }];
  editor.DomComponents.addType('link', {
    model: {
      defaults: {
        traits: [
          { type: 'select', name: 'bw-page', label: 'ไปที่หน้าในเว็บ', changeProp: true, options: pageOptions },
          { name: 'href', label: 'หรือใส่ลิงก์ (URL)' },
          { type: 'select', name: 'target', label: 'เปิดใน', options: [{ id: '', name: 'แท็บเดิม' }, { id: '_blank', name: 'แท็บใหม่' }] },
          { name: 'title', label: 'คำอธิบาย' },
        ],
      },
      init() {
        this.on('change:bw-page', () => { const v = this.get('bw-page'); if (v) this.addAttributes({ href: v }); });
      },
    },
  });

  // ------------------------------------------------------------------ shared header/footer preview
  // Shown around the page in the canvas but never saved with it: toHTML() is empty and the components are
  // re-created on every load from the site's current shared sections.
  editor.DomComponents.addType('bw-shared', {
    isComponent: el => el && el.getAttribute && el.getAttribute('data-bw-shared') ? { type: 'bw-shared' } : false,
    model: {
      defaults: {
        tagName: 'div', draggable: false, droppable: false, copyable: false, removable: false, selectable: false,
        hoverable: false, highlightable: false, layerable: false, editable: false, badgable: false, stylable: false,
      },
      toHTML() { return ''; },
    },
    view: {
      events: { dblclick: 'openShared' },
      openShared() { const u = this.model.get('editUrl'); if (u) leaveTo(u); },
    },
  });
  function insertShared() {
    const wrapper = editor.getWrapper();
    wrapper.find('[data-bw-shared]').forEach(c => c.remove());
    wrapper.components().filter(c => c.get('type') === 'bw-shared').forEach(c => c.remove());
    const sp = D.shared_preview || {};
    const make = (kind, label) => ({
      type: 'bw-shared', editUrl: sp[kind].edit_url, attributes: { 'data-bw-shared': kind, title: `${label} — ดับเบิลคลิกเพื่อแก้ไข` },
      content: sp[kind].html, // raw HTML: parsing it would let plugins rewrite parts (e.g. <button> → "Send")
    });
    const lock = c => { c.onAll(x => x.set({ selectable: false, hoverable: false, editable: false, draggable: false, droppable: false, removable: false, copyable: false, layerable: false, badgable: false, highlightable: false })); };
    if (sp.header) lock(wrapper.append(make('header', 'ส่วนหัวร่วม'), { at: 0 })[0]);
    if (sp.footer) lock(wrapper.append(make('footer', 'ส่วนท้ายร่วม'))[0]);
    const doc = editor.Canvas.getDocument();
    if (doc && !doc.getElementById('bw-shared-css')) {
      const st = doc.createElement('style');
      st.id = 'bw-shared-css';
      st.textContent = Object.values(sp).map(x => x.css).join('\n') +
        '[data-bw-shared]{position:relative;cursor:pointer}' +
        '[data-bw-shared]:hover{outline:2px dashed #8b5cf6;outline-offset:-2px}' +
        '[data-bw-shared]:hover::after{content:attr(title);position:absolute;right:8px;top:8px;background:#111827;color:#fff;font:12px system-ui;padding:4px 8px;border-radius:6px;z-index:99;pointer-events:none}';
      doc.head.appendChild(st);
    }
  }

  // ------------------------------------------------------------------ load
  editor.on('load', async () => {
    renderBlocks();
    const sm = editor.StyleManager;
    try { const ff = sm.getProperty('typography', 'font-family'); ff && ff.setOptions(fontOptions); } catch (e) { /* older API */ }
    if (!loadedFromProject && (loaded.html || '').trim()) {
      // First open of a page made from a template: build the project from its HTML.
      editor.setComponents(stripBody(loaded.html) + (loaded.css ? `<style>${loaded.css}</style>` : ''));
      editor.UndoManager.clear();
      editor.store();
    }
    if (!isShared) { insertShared(); editor.UndoManager.clear(); }
    const cdoc = editor.Canvas.getDocument();
    if (cdoc && page.body_class) cdoc.body.classList.add(...page.body_class.split(/\s+/).filter(Boolean));
    setState('บันทึกแล้ว', 'ok');
    loadAssets();
    updateRight();
  });

  // ------------------------------------------------------------------ save state
  editor.on('update', () => { if (editor.getDirtyCount()) setState('ยังไม่บันทึก', 'dirty'); });
  editor.on('storage:start:store', () => setState('กำลังบันทึก…'));
  editor.on('storage:end:store', () => setState('บันทึกแล้ว ✓', 'ok'));
  editor.on('storage:error', err => { setState('บันทึกไม่สำเร็จ', 'err'); toast('บันทึกไม่สำเร็จ: ' + (err && err.message || err), 'err'); });
  async function save() {
    try { await editor.store(); toast('บันทึกแล้ว', 'ok'); } catch (e) { /* storage:error shows it */ }
  }
  editor.Keymaps.add('bw:save', '⌘+s, ctrl+s', () => save(), { prevent: true });
  document.addEventListener('keydown', e => { if ((e.metaKey || e.ctrlKey) && e.key === 's') { e.preventDefault(); save(); } });
  window.addEventListener('beforeunload', e => { if (editor.getDirtyCount()) { editor.store(); e.preventDefault(); e.returnValue = ''; } });

  async function leaveTo(url) {
    if (editor.getDirtyCount()) { setState('กำลังบันทึก…'); try { await editor.store(); } catch (e) { return; } }
    location.href = url;
  }
  document.querySelectorAll('a[href^="/sites/"]').forEach(a => a.addEventListener('click', e => { e.preventDefault(); leaveTo(a.href); }));

  // ------------------------------------------------------------------ top bar
  document.querySelectorAll('#devices .dev').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('#devices .dev').forEach(x => x.classList.toggle('active', x === b));
    editor.setDevice(b.dataset.dev);
  }));
  const outlineBtn = document.querySelector('[data-cmd=outline]');
  const cmds = {
    undo: () => editor.UndoManager.undo(),
    redo: () => editor.UndoManager.redo(),
    outline: () => {
      const id = 'core:component-outline';
      editor.Commands.isActive(id) ? editor.stopCommand(id) : editor.runCommand(id);
      outlineBtn.classList.toggle('on', editor.Commands.isActive(id));
    },
    code: () => editor.runCommand('core:open-code'),
    preview: () => editor.runCommand('core:preview'),
    open: async () => { await editor.store(); BW.openUrl(location.origin + D.preview_base + (isShared || page.is_home ? '' : page.filename)); },
    save,
    theme: () => {
      const dark = document.documentElement.getAttribute('data-theme') === 'dark';
      BW.setTheme(dark ? 'light' : 'dark');
      $('#theme-btn').innerHTML = BW_ICON(dark ? 'moon' : 'sun');
    },
    import: openImport,
    history: openHistory,
    clear: async () => {
      if (!await confirmBox('ล้างหน้า', 'ลบทุกอย่างในหน้านี้? (ย้อนกลับได้จาก “เวอร์ชันย้อนหลัง” หรือกด ⌘Z)', { ok: 'ล้างหน้า', danger: true })) return;
      editor.runCommand('core:canvas-clear');
    },
  };
  document.querySelectorAll('[data-cmd]').forEach(b => b.addEventListener('click', () => cmds[b.dataset.cmd]()));
  editor.runCommand('core:component-outline');
  outlineBtn.classList.add('on');

  const status = $('#status');
  if (isShared) {
    status.innerHTML = '<option value="on">● ใช้ทุกหน้า</option><option value="off">○ ปิดอยู่</option>';
    status.value = target.enabled ? 'on' : 'off';
    document.querySelector('[data-cmd=history]').classList.add('hidden');
    status.addEventListener('change', async () => {
      try { await api(`/api/shared/${target.id}/update`, { enabled: status.value === 'on' }); target.enabled = status.value === 'on'; toast(target.enabled ? 'เปิดใช้ทุกหน้าแล้ว' : 'ปิดส่วนนี้แล้ว', 'ok'); }
      catch (e) { toast(e.message, 'err'); }
    });
  }
  if (!isShared) status.value = page.status;
  if (!isShared) status.addEventListener('change', async () => {
    try { await api(`/api/pages/${page.id}/update`, { status: status.value }); page.status = status.value; toast(status.value === 'published' ? 'เผยแพร่หน้านี้แล้ว' : 'เปลี่ยนเป็นฉบับร่างแล้ว', 'ok'); }
    catch (e) { toast(e.message, 'err'); status.value = page.status; }
  });

  // ------------------------------------------------------------------ left rail
  document.querySelectorAll('#rail button').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('#rail button').forEach(x => x.classList.toggle('active', x === b));
    document.querySelectorAll('[data-pane]').forEach(p => p.classList.toggle('hidden', p.dataset.pane !== b.dataset.panel));
    if (b.dataset.panel === 'theme') drawTheme();
    if (b.dataset.panel === 'pages') drawPages();
    if (b.dataset.panel === 'data') drawData();
  }));

  // right tabs
  document.querySelectorAll('[data-rt]').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('[data-rt]').forEach(x => x.classList.toggle('active', x === b));
    document.querySelectorAll('[data-rpane]').forEach(p => p.classList.toggle('hidden', p.dataset.rpane !== b.dataset.rt));
  }));
  function updateRight() {
    const has = !!editor.getSelected();
    $('#r-empty').classList.toggle('hidden', has);
    $('#selectors').classList.toggle('hidden', !has);
    $('#styles').classList.toggle('hidden', !has);
  }
  editor.on('component:toggled', updateRight);

  // ------------------------------------------------------------------ pages panel
  function drawPages() {
    const sharedRows = (site.shared || []).map(x => `<div class="pg ${isShared && target.id === x.id ? 'cur' : ''}" data-url="${x.edit_url}">
      <span class="muted">${BW_ICON(x.kind === 'header' ? 'panel-top' : 'panel-bottom')}</span><div class="t"><b>${esc(x.label)}</b><span>ใช้ทุกหน้า</span></div>
      ${x.enabled ? '<span class="badge ok">เปิด</span>' : '<span class="badge">ปิด</span>'}</div>`).join('');
    $('#page-list').innerHTML = sharedRows + '<div class="pg-sep">หน้า</div>' + D.pages.map(p => `<div class="pg ${!isShared && p.id === page.id ? 'cur' : ''}" data-url="${p.edit_url}">
      <span class="muted">${BW_ICON(p.is_home ? 'home' : 'file')}</span><div class="t"><b>${esc(p.title)}</b><span class="mono">${esc(p.filename)}</span></div>
      ${p.status === 'draft' ? '<span class="badge warn">ร่าง</span>' : ''}</div>`).join('') +
      `<div style="padding:14px"><a class="btn sm" href="/sites/${site.id}/pages/" style="width:100%">จัดการหน้า & SEO</a></div>`;
    document.querySelectorAll('#page-list .pg').forEach(el => el.addEventListener('click', () => leaveTo(el.dataset.url)));
    document.querySelectorAll('#page-list a').forEach(a => a.addEventListener('click', e => { e.preventDefault(); leaveTo(a.href); }));
  }
  $('#page-switch').addEventListener('click', () => $('#rail [data-panel=pages]').click());
  $('#add-page').addEventListener('click', () => {
    const layouts = D.layouts.map((l, i) => `<option value="${l.id}" ${i === 1 ? 'selected' : ''}>${esc(l.name)}</option>`).join('');
    const m = modal(`<header><h2>เพิ่มหน้าใหม่</h2><button class="btn ghost icon" data-close>✕</button></header><div class="body">
      <label class="field"><span>ชื่อหน้า</span><input class="input" name="title" placeholder="เช่น บริการของเรา"></label>
      <label class="field"><span>ชื่อไฟล์ <small>(a-z 0-9 - · เว้นว่างได้)</small></span><input class="input mono" name="slug" placeholder="services"></label>
      <label class="field"><span>รูปแบบเริ่มต้น</span><select class="input" name="layout">${layouts}</select></label>
      <label class="check"><input type="checkbox" name="show_in_nav" checked>แสดงในเมนู</label>
      <div class="muted small">ตั้งค่า SEO และรายละเอียดอื่นๆ ได้ที่หน้า “จัดการหน้า”</div></div>
      <footer><button class="btn" data-close>ยกเลิก</button><button class="btn primary" data-ok>สร้างและเปิด</button></footer>`);
    const t = m.el.querySelector('[name=title]'), s = m.el.querySelector('[name=slug]');
    t.addEventListener('input', () => { if (!s.dataset.touched) s.value = t.value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, ''); });
    s.addEventListener('input', () => s.dataset.touched = 1);
    m.el.querySelector('[data-ok]').onclick = async () => {
      try { const r = await api(`/api/sites/${site.id}/pages/create`, formData(m.el)); leaveTo(r.page.edit_url); }
      catch (e) { showFieldError(m.el, e); }
    };
  });

  // ------------------------------------------------------------------ data (collections)
  const COLS = D.collections || [];
  const colBySlug = Object.fromEntries(COLS.map(c => [c.slug, c]));
  const fieldPh = f => `{{${f.name}}}`;

  function cardTemplate(c) {
    // A ready-made card using the collection's fields: image, first text as title, the rest as lines.
    const img = c.fields.find(f => f.type === 'image');
    const texts = c.fields.filter(f => f !== img && !['bool', 'html'].includes(f.type) && !/^id$/i.test(f.name));
    const [title, ...rest] = texts;
    const link = c.fields.find(f => f.type === 'link');
    return `<section class="bw-data-sec"><div class="bw-container">
      <div class="bw-data-grid" data-bw-repeat="${c.slug}" data-bw-limit="12" data-bw-empty="ยังไม่มีข้อมูล">
        <article class="bw-data-card">${img ? `<img src="${fieldPh(img)}" alt="${title ? fieldPh(title) : ''}">` : ''}
          <div class="bw-data-body">${title ? `<h3>${fieldPh(title)}</h3>` : ''}
          ${rest.filter(f => f !== link).slice(0, 3).map(f => `<p>${fieldPh(f)}</p>`).join('')}
          ${c.has_detail ? `<a class="bw-btn" href="{{_url}}">ดูรายละเอียด</a>` : link ? `<a class="bw-btn" href="${fieldPh(link)}">ดูเพิ่มเติม</a>` : ''}</div></article></div></div></section>
      <style>.bw-data-sec{padding:60px 0}.bw-data-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:20px}
      .bw-data-card{background:#fff;border:1px solid #eee;border-radius:var(--bw-radius);overflow:hidden}
      .bw-data-card img{width:100%;aspect-ratio:4/3;object-fit:cover;display:block}
      .bw-data-body{padding:16px 18px}.bw-data-body h3{margin:0 0 6px}.bw-data-body p{margin:0 0 6px;color:var(--bw-muted)}</style>`;
  }
  function tableTemplate(c) {
    const fs = c.fields.slice(0, 6);
    return `<section class="bw-data-sec"><div class="bw-container"><table class="bw-data-table"><thead><tr>${fs.map(f => `<th>${BW.esc(f.label)}</th>`).join('')}</tr></thead>
      <tbody data-bw-repeat="${c.slug}" data-bw-limit="50"><tr>${fs.map(f => `<td>${fieldPh(f)}</td>`).join('')}</tr></tbody></table></div></section>
      <style>.bw-data-table{width:100%;border-collapse:collapse}.bw-data-table th,.bw-data-table td{padding:10px 12px;border-bottom:1px solid #eee;text-align:left}
      .bw-data-table th{color:var(--bw-muted);font-weight:600}</style>`;
  }
  COLS.forEach(c => {
    bm.add('bw-data-cards-' + c.slug, { label: `${c.name} (การ์ด)`, category: 'ข้อมูล', content: cardTemplate(c), media: `<div class="bw-bicon">${BW_ICON('cards', 20)}</div>` });
    bm.add('bw-data-table-' + c.slug, { label: `${c.name} (ตาราง)`, category: 'ข้อมูล', content: tableTemplate(c), media: `<div class="bw-bicon">${BW_ICON('table', 20)}</div>` });
    if (c.forms) bm.add('bw-data-form-' + c.slug, { label: `ฟอร์ม ${c.name}`, category: 'ข้อมูล', content: c.form_html, media: `<div class="bw-bicon">${BW_ICON('form', 20)}</div>` });
  });
  const DETAIL = D.page && D.page.collection_slug ? colBySlug[D.page.collection_slug] : null;

  function drawData() {
    const box = $('#data-panel');
    if (!COLS.length) {
      box.innerHTML = `<div class="r-empty">ยังไม่มีชุดข้อมูล<br><a class="btn sm" style="margin-top:10px" href="/sites/${site.id}/data/">นำเข้าจาก XAMPP / .sql / CSV</a></div>`;
      return;
    }
    box.innerHTML = (DETAIL ? `<div style="margin:10px 12px 0;padding:10px 12px;border-radius:8px;background:var(--brand-soft,rgba(124,92,255,.1));font-size:12.5px;line-height:1.7">หน้านี้คือ<b>หน้ารายละเอียด</b>ของ “${BW.esc(DETAIL.name)}” — สร้างหนึ่งหน้าต่อหนึ่งแถว <code>{{ฟิลด์}}</code> คือค่าของแถวนั้น · ลิงก์ก่อนหน้า/ถัดไป: <code>{{_prev_url}}</code> <code>{{_next_url}}</code></div>` : '') +
      `<div class="small muted" style="padding:10px 12px">คลิกฟิลด์เพื่อแทรก <code>{{ฟิลด์}}</code> ในข้อความที่เลือก · ลากบล็อกจากหมวด “ข้อมูล” เพื่อแสดงทั้งชุด · ตัวแปลงค่า: <code>{{price|number}}</code> <code>{{date|date}}</code> <code>{{detail|truncate:100}}</code></div>` +
      COLS.map(c => `<div class="data-col"><div class="row between"><b>${BW.esc(c.name)}</b><code>${BW.esc(c.slug)}</code></div>
        <div class="chips">${c.fields.map(f => `<button class="chip" data-col="${c.slug}" data-f="${BW.esc(f.name)}" title="${BW.esc(f.label)} · ${f.type}">${BW.esc(f.name)}</button>`).join('')}
        ${c.has_detail ? `<button class="chip ghost" data-col="${c.slug}" data-f="_url" title="ลิงก์ไปหน้ารายละเอียดของแถว (ใช้ในกล่องวนซ้ำ)">_url</button>` : ''}
        <button class="chip ghost" data-col="${c.slug}" data-f="count" title="จำนวนแถว">count</button></div></div>`).join('');
    box.querySelectorAll('.chip').forEach(b => b.onclick = () => insertField(b.dataset.col, b.dataset.f));
  }
  function insertField(slug, field) {
    const sel = editor.getSelected();
    // Inside a repeat block use {{field}}; elsewhere {{collection.field}} (first row / count).
    let inRepeat = false;
    for (let c = sel; c; c = c.parent()) { if ((c.getAttributes()['data-bw-repeat'] || '') === slug) { inRepeat = true; break; } }
    if (DETAIL && DETAIL.slug === slug) inRepeat = true; // a detail page shows one row: plain {{field}}
    const ph = inRepeat && field !== 'count' ? `{{${field}}}` : `{{${slug}.${field}}}`;
    const rte = editor.RichTextEditor;
    if (sel && sel.is('text') && rte && sel.getView() && sel.getView().rte && sel.getView().rte.actionbar) {
      try { rte.insertHTML(ph); return; } catch (e) { /* fall back */ }
    }
    if (sel && sel.is('image')) { sel.set('src', ph); toast(`ตั้งรูปเป็น ${ph}`, 'ok'); return; }
    if (sel && sel.is('text')) { sel.components(sel.getInnerHTML() + ' ' + ph); toast(`แทรก ${ph}`, 'ok'); return; }
    navigator.clipboard.writeText(ph).then(() => toast(`คัดลอก ${ph} แล้ว — วางในข้อความได้เลย`, 'ok'));
  }

  // "Repeat from data" settings on every element (stored as data-bw-* attributes).
  const repeatTraits = () => {
    const opts = [{ id: '', name: '— ไม่วนซ้ำ —' }, ...COLS.map(c => ({ id: c.slug, name: c.name }))];
    return [
      { type: 'select', name: 'data-bw-repeat', label: 'วนซ้ำจากข้อมูล', options: opts },
      { type: 'number', name: 'data-bw-limit', label: 'แสดงสูงสุด (แถว)', min: 0 },
      { name: 'data-bw-sort', label: 'เรียงตามฟิลด์' },
      { type: 'select', name: 'data-bw-order', label: 'ลำดับ', options: [{ id: '', name: 'น้อย → มาก' }, { id: 'desc', name: 'มาก → น้อย' }] },
      { name: 'data-bw-filter', label: 'กรอง (เช่น category=coffee;price>50)' },
      { name: 'data-bw-empty', label: 'ข้อความเมื่อไม่มีข้อมูล' },
      { name: 'data-bw-search', label: 'ช่องค้นหา (ข้อความในช่อง เช่น ค้นหาสินค้า…)' },
      { name: 'data-bw-facet', label: 'ปุ่มหมวดหมู่จากฟิลด์ (เช่น category)' },
      { type: 'number', name: 'data-bw-paginate', label: 'แบ่งหน้า: กี่รายการต่อหน้า', min: 0 },
      { type: 'select', name: 'data-bw-pager', label: 'รูปแบบแบ่งหน้า', options: [{ id: '', name: 'เลขหน้า 1 2 3' }, { id: 'more', name: 'ปุ่ม “โหลดเพิ่ม”' }] },
    ];
  };
  // Forms can save into a collection (rows wait for approval unless the collection says otherwise).
  const formTraits = () => [
    { type: 'select', name: 'data-bw-collection', label: 'บันทึกลงชุดข้อมูล',
      options: [{ id: '', name: '— เก็บในข้อมูลจากฟอร์มเท่านั้น —' }, ...COLS.filter(c => c.forms).map(c => ({ id: c.slug, name: c.name }))] },
    { name: 'data-bw-success', label: 'ข้อความเมื่อส่งสำเร็จ' },
    { name: 'data-bw-pending', label: 'ข้อความเมื่อรออนุมัติ' },
  ];
  editor.on('component:selected', comp => {
    if (!comp || comp.get('type') === 'bw-shared' || comp.is('textnode') || comp.get('tagName') === 'body') return;
    if (comp.get('tagName') === 'form') {
      if (!comp.getTrait('data-bw-collection')) comp.addTrait(formTraits(), { at: comp.getTraits().length });
      return;
    }
    if (!['div', 'section', 'ul', 'ol', 'tbody', 'article', 'nav', 'main', 'aside', 'span'].includes(comp.get('tagName'))) return;
    if (comp.getTrait('data-bw-repeat')) return;
    comp.addTrait(repeatTraits(), { at: comp.getTraits().length });
  });

  // ------------------------------------------------------------------ animation panel
  const ANIMS = [['', 'ไม่มี'], ['fade', 'จางเข้า'], ['fade-up', 'เลื่อนขึ้น'], ['fade-down', 'เลื่อนลง'], ['fade-left', 'จากขวา'], ['fade-right', 'จากซ้าย'],
    ['zoom-in', 'ขยายเข้า'], ['zoom-out', 'ย่อเข้า'], ['flip-up', 'พลิกขึ้น'], ['blur', 'เบลอ → ชัด'], ['rise', 'ลอยขึ้นสูง'], ['pop', 'เด้ง']];
  const KEYFRAMES = {
    fade: [{ opacity: 0 }, { opacity: 1 }],
    'fade-up': [{ opacity: 0, transform: 'translateY(32px)' }, { opacity: 1, transform: 'none' }],
    'fade-down': [{ opacity: 0, transform: 'translateY(-32px)' }, { opacity: 1, transform: 'none' }],
    'fade-left': [{ opacity: 0, transform: 'translateX(40px)' }, { opacity: 1, transform: 'none' }],
    'fade-right': [{ opacity: 0, transform: 'translateX(-40px)' }, { opacity: 1, transform: 'none' }],
    'zoom-in': [{ opacity: 0, transform: 'scale(.88)' }, { opacity: 1, transform: 'none' }],
    'zoom-out': [{ opacity: 0, transform: 'scale(1.12)' }, { opacity: 1, transform: 'none' }],
    'flip-up': [{ opacity: 0, transform: 'perspective(800px) rotateX(18deg) translateY(20px)' }, { opacity: 1, transform: 'none' }],
    blur: [{ opacity: 0, filter: 'blur(12px)' }, { opacity: 1, filter: 'none' }],
    rise: [{ opacity: 0, transform: 'translateY(80px)' }, { opacity: 1, transform: 'none' }],
    pop: [{ opacity: 0, transform: 'scale(.6)' }, { opacity: 1, transform: 'scale(1.05)', offset: .7 }, { opacity: 1, transform: 'none' }],
  };
  const HOVERS = [['', 'ไม่มี'], ['lift', 'ยกลอย'], ['grow', 'ขยาย'], ['glow', 'เรืองแสง'], ['zoom-img', 'ซูมรูปข้างใน'], ['tilt', 'เอียง 3D'], ['shine', 'แสงวาบ']];

  function playAnim(comp) {
    const el = comp && comp.getEl(); if (!el) return;
    const a = comp.getAttributes();
    const dur = +(a['data-bw-anim-duration'] || 700), delay = +(a['data-bw-anim-delay'] || 0);
    const opts = { duration: dur, easing: 'cubic-bezier(.2,.7,.2,1)', fill: 'backwards' };
    if (a['data-bw-stagger'] != null) {
      const step = +(a['data-bw-stagger'] || 120);
      [...el.children].forEach((ch, i) => ch.animate(KEYFRAMES[a['data-bw-anim'] || 'fade-up'] || KEYFRAMES['fade-up'], { ...opts, delay: delay + i * step }));
    } else if (KEYFRAMES[a['data-bw-anim']]) el.animate(KEYFRAMES[a['data-bw-anim']], { ...opts, delay });
    if (a['data-bw-count'] != null) {
      const m = (el.textContent || '').match(/^(\D*)([\d,]+(?:\.\d+)?)(.*)$/);
      if (m) { const target = parseFloat(m[2].replace(/,/g, '')), t0 = performance.now(), orig = el.textContent;
        const f = t => { const p = Math.min(1, (t - t0) / 1600); el.textContent = m[1] + Math.round(target * (1 - Math.pow(1 - p, 3))).toLocaleString('en-US') + m[3];
          if (p < 1) requestAnimationFrame(f); else el.textContent = orig; };
        requestAnimationFrame(f); }
    }
  }

  function drawAnim() {
    const box = $('#anim-panel');
    const comp = editor.getSelected();
    if (!comp || comp.get('type') === 'bw-shared' || comp.get('tagName') === 'body' || comp.is('wrapper')) {
      box.innerHTML = '<div class="r-empty">เลือกองค์ประกอบในหน้าเพื่อใส่แอนิเมชัน</div>'; return;
    }
    const a = comp.getAttributes();
    const anim = a['data-bw-anim'] || '';
    const isStagger = a['data-bw-stagger'] != null;
    const kids = comp.components().filter(c => c.get('type') !== 'textnode').length;
    const text = (comp.getEl() && comp.getEl().textContent || '').trim();
    box.innerHTML = `<div class="anim-pane">
      <div class="row between"><b>ตอนเลื่อนมาถึง</b><button class="btn sm" id="an-play" ${anim || a['data-bw-count'] != null ? '' : 'disabled'}>${BW_ICON('play', 14)} ดูตัวอย่าง</button></div>
      <div class="anim-grid">${ANIMS.map(([v, l]) => `<button class="anim-opt ${v === anim ? 'on' : ''}" data-v="${v}">${l}</button>`).join('')}</div>
      <div class="anim-ctl ${anim ? '' : 'dim'}">
        <label class="anim-row"><span>ระยะเวลา</span><input type="range" min="200" max="2000" step="50" id="an-dur" value="${a['data-bw-anim-duration'] || 700}"><code id="an-dur-v">${a['data-bw-anim-duration'] || 700}ms</code></label>
        <label class="anim-row"><span>หน่วงเวลา</span><input type="range" min="0" max="2000" step="50" id="an-delay" value="${a['data-bw-anim-delay'] || 0}"><code id="an-delay-v">${a['data-bw-anim-delay'] || 0}ms</code></label>
        <label class="check"><input type="checkbox" id="an-repeat" ${a['data-bw-anim-once'] === 'false' ? 'checked' : ''}>เล่นซ้ำทุกครั้งที่เลื่อนมาถึง</label>
        ${kids > 1 ? `<label class="check"><input type="checkbox" id="an-stagger" ${isStagger ? 'checked' : ''}>ให้ ${kids} ชิ้นด้านในโผล่ทีละชิ้น</label>
          <label class="anim-row ${isStagger ? '' : 'hidden'}" id="an-step-row"><span>ห่างกัน</span><input type="range" min="40" max="600" step="20" id="an-step" value="${a['data-bw-stagger'] || 120}"><code id="an-step-v">${a['data-bw-stagger'] || 120}ms</code></label>` : ''}
      </div>
      <div class="sect-title">ตอนชี้เมาส์</div>
      <select class="input" id="an-hover">${HOVERS.map(([v, l]) => `<option value="${v}" ${v === (a['data-bw-hover'] || '') ? 'selected' : ''}>${l}</option>`).join('')}</select>
      <div class="sect-title">เอฟเฟกต์พิเศษ</div>
      <label class="check" ${/\d/.test(text) ? '' : 'title="ใช้กับข้อความที่มีตัวเลข เช่น 1,200+"'}><input type="checkbox" id="an-count" ${a['data-bw-count'] != null ? 'checked' : ''} ${/\d/.test(text) ? '' : 'disabled'}>ตัวเลขนับขึ้น <span class="muted small">(${/\d/.test(text) ? 'เช่น 0 → ' + BW.esc(text.slice(0, 12)) : 'ต้องมีตัวเลข'})</span></label>
      <label class="check"><input type="checkbox" id="an-typing" ${a['data-bw-typing'] != null ? 'checked' : ''}>ข้อความพิมพ์ทีละตัว</label>
      <input class="input ${a['data-bw-typing'] != null ? '' : 'hidden'}" id="an-words" placeholder="คำที่ 1|คำที่ 2|คำที่ 3" value="${BW.esc(a['data-bw-typing'] || '')}" style="margin-bottom:10px">
      <label class="check"><input type="checkbox" id="an-parallax" ${a['data-bw-parallax'] != null ? 'checked' : ''}>Parallax ภาพพื้นหลัง <span class="muted small">(ส่วนที่มีรูปพื้นหลัง)</span></label>
      <div class="small muted" style="margin-top:12px">แอนิเมชันเล่นบนเว็บจริงและไฟล์ที่ส่งออก · ในตัวออกแบบกด “ดูตัวอย่าง” · ผู้ที่ตั้งค่าลดการเคลื่อนไหวในเครื่องจะไม่เห็นแอนิเมชัน</div>
    </div>`;
    const set = (k, v) => { if (v === null || v === undefined || v === false) comp.removeAttributes(k); else comp.addAttributes({ [k]: v === true ? '' : String(v) }); };
    box.querySelectorAll('.anim-opt').forEach(b => b.onclick = () => {
      set('data-bw-anim', b.dataset.v || null);
      if (!b.dataset.v) ['data-bw-anim-duration', 'data-bw-anim-delay', 'data-bw-anim-once', 'data-bw-stagger'].forEach(k => set(k, null));
      drawAnim(); if (b.dataset.v) playAnim(comp);
    });
    const range = (id, attr, def) => { const r = box.querySelector(id); if (!r) return;
      r.oninput = () => { box.querySelector(id + '-v').textContent = r.value + 'ms'; };
      r.onchange = () => { set(attr, +r.value === def ? null : r.value); playAnim(comp); }; };
    range('#an-dur', 'data-bw-anim-duration', 700); range('#an-delay', 'data-bw-anim-delay', 0); range('#an-step', 'data-bw-stagger', -1);
    box.querySelector('#an-repeat').onchange = e => set('data-bw-anim-once', e.target.checked ? 'false' : null);
    const st = box.querySelector('#an-stagger');
    if (st) st.onchange = e => { set('data-bw-stagger', e.target.checked ? (box.querySelector('#an-step').value || 120) : null);
      if (e.target.checked && !comp.getAttributes()['data-bw-anim']) set('data-bw-anim', 'fade-up'); drawAnim(); playAnim(comp); };
    box.querySelector('#an-hover').onchange = e => set('data-bw-hover', e.target.value || null);
    box.querySelector('#an-count').onchange = e => { set('data-bw-count', e.target.checked ? true : null); drawAnim(); if (e.target.checked) playAnim(comp); };
    box.querySelector('#an-typing').onchange = e => { set('data-bw-typing', e.target.checked ? (text || 'ข้อความ') : null); drawAnim(); };
    const words = box.querySelector('#an-words'); words.onchange = () => set('data-bw-typing', words.value || text);
    box.querySelector('#an-parallax').onchange = e => set('data-bw-parallax', e.target.checked ? '0.3' : null);
    const play = box.querySelector('#an-play'); if (play) play.onclick = () => playAnim(comp);
  }
  editor.on('component:toggled', () => { if (!$('[data-rpane=anim]').classList.contains('hidden')) drawAnim(); });
  document.querySelector('[data-rt=anim]').addEventListener('click', drawAnim);

  // ------------------------------------------------------------------ media panel
  const am = editor.AssetManager;
  let mediaList = [];
  async function loadAssets() {
    const r = await api(`/api/sites/${site.id}/assets`);
    mediaList = r.assets.filter(a => a.kind === 'image' || a.kind === 'video');
    am.add(r.assets.filter(a => a.kind === 'image').map(a => ({ src: a.url, name: a.name })));
    drawMedia();
  }
  function drawMedia() {
    const box = $('#media-list');
    if (!mediaList.length) { box.innerHTML = '<div class="muted small" style="grid-column:1/-1;text-align:center;padding:30px 0">ยังไม่มีรูป กด “อัปโหลด”</div>'; return; }
    box.innerHTML = mediaList.map(a => `<div class="mi" data-url="${esc(a.url)}" data-kind="${a.kind}" title="${esc(a.name)}" style="${a.kind === 'image' ? `background-image:url('${encodeURI(a.url)}')` : ''}">${a.kind === 'video' ? BW_ICON('video', 22) : ''}<span>${esc(a.name)}</span></div>`).join('');
    box.querySelectorAll('.mi').forEach(it => it.addEventListener('click', () => useMedia(it.dataset.url, it.dataset.kind)));
  }
  function useMedia(url, kind) {
    const sel = editor.getSelected();
    if (kind === 'image' && sel && sel.is('image')) { sel.set('src', url); toast('เปลี่ยนรูปแล้ว', 'ok'); return; }
    const comp = kind === 'video' ? { type: 'video', src: url, style: { width: '100%' } } : { type: 'image', src: url, style: { 'max-width': '100%' } };
    if (sel && sel.parent()) {
      const parent = sel.parent();
      parent.append(comp, { at: parent.components().indexOf(sel) + 1 });
    } else editor.getWrapper().append(comp);
    toast('แทรกแล้ว — ลากย้ายตำแหน่งได้', 'ok');
  }
  $('#upload-btn').addEventListener('click', () => $('#upload-input').click());
  $('#upload-input').addEventListener('change', async e => {
    const fd = new FormData();
    [...e.target.files].forEach(f => fd.append('files', f));
    try { const r = await api(`/api/sites/${site.id}/assets/upload`, fd); toast(`อัปโหลดแล้ว ${r.assets.length} ไฟล์`, 'ok'); loadAssets(); }
    catch (err) { toast(err.message, 'err'); }
    e.target.value = '';
  });
  editor.on('asset:upload:response', () => setTimeout(loadAssets, 200));

  // ------------------------------------------------------------------ theme panel
  const COLORS = [['primary', 'สีหลัก'], ['secondary', 'สีรอง'], ['accent', 'สีเน้น'], ['text', 'ตัวอักษร'], ['muted', 'ข้อความรอง'], ['background', 'พื้นหลัง'], ['surface', 'พื้นส่วนเน้น']];
  let themeTimer = null;
  function drawTheme() {
    const t = site.theme;
    $('#theme-panel').innerHTML = COLORS.map(([k, l]) => `<label class="field"><span>${l}</span><div class="color-row"><input type="color" data-k="${k}" value="${t[k]}"><code>${t[k]}</code></div></label>`).join('') +
      `<label class="field"><span>ฟอนต์หัวข้อ</span><select class="input" data-k="font_heading">${FONTS.map(f => `<option ${f === t.font_heading ? 'selected' : ''}>${f}</option>`).join('')}</select></label>
       <label class="field"><span>ฟอนต์เนื้อหา</span><select class="input" data-k="font_body">${FONTS.map(f => `<option ${f === t.font_body ? 'selected' : ''}>${f}</option>`).join('')}</select></label>
       <label class="field"><span>มุมโค้ง</span><select class="input" data-k="radius">${['0px', '6px', '10px', '14px', '20px', '28px'].map(v => `<option ${v === t.radius ? 'selected' : ''}>${v}</option>`).join('')}</select></label>
       <a class="btn sm" href="/sites/${site.id}/settings/" style="width:100%">ตั้งค่าธีมเพิ่มเติม →</a>`;
    $('#theme-panel').querySelectorAll('[data-k]').forEach(inp => inp.addEventListener('input', () => {
      site.theme[inp.dataset.k] = inp.value;
      const code = inp.parentElement.querySelector('code'); if (code) code.textContent = inp.value;
      clearTimeout(themeTimer);
      themeTimer = setTimeout(saveTheme, 350);
    }));
    $('#theme-panel').querySelectorAll('a').forEach(a => a.addEventListener('click', e => { e.preventDefault(); leaveTo(a.href); }));
  }
  async function saveTheme() {
    try {
      const r = await api(`/api/sites/${site.id}/update`, { theme: site.theme });
      site.theme = r.site.theme;
      refreshCanvasCss();
    } catch (e) { toast(e.message, 'err'); }
  }
  function refreshCanvasCss() {
    const doc = editor.Canvas.getDocument();
    if (!doc) return;
    doc.querySelectorAll('link[rel=stylesheet]').forEach(l => {
      if (l.href.includes('/css/site.css')) l.href = `${D.preview_base}css/site.css?t=${Date.now()}`;
      if (l.href.includes('fonts.googleapis.com')) l.remove();
    });
    const fu = fontsUrl(site.theme);
    if (fu) { const l = doc.createElement('link'); l.rel = 'stylesheet'; l.href = fu; doc.head.appendChild(l); }
  }

  // ------------------------------------------------------------------ import / history
  function openImport() {
    const m = modal(`<header><h2>นำเข้า HTML</h2><button class="btn ghost icon" data-close>✕</button></header><div class="body">
      <div class="muted small" style="margin-bottom:10px">วางโค้ด HTML (ใส่ &lt;style&gt; มาด้วยได้) — จะแปลงเป็นองค์ประกอบที่ลากวางแก้ไขได้</div>
      <div class="row" style="margin-bottom:8px"><button class="btn sm" id="imp-file">เลือกไฟล์ .html…</button><input type="file" id="imp-file-input" accept=".html,.htm" hidden>
        <span class="small muted">นำเข้าทั้งเว็บ (หลายหน้า/รูป/CSS) หรือจาก GitHub ได้ที่ <a href="/#import">นำเข้าเว็บ</a></span></div>
      <textarea class="input code imp-area" placeholder="<section>...</section>"></textarea>
      <div class="row" style="margin-top:10px;gap:20px"><label class="check"><input type="radio" name="mode" value="append" checked>ต่อท้ายหน้า</label><label class="check"><input type="radio" name="mode" value="replace">แทนที่ทั้งหน้า</label></div></div>
      <footer><button class="btn" data-close>ยกเลิก</button><button class="btn primary" data-ok>นำเข้า</button></footer>`, { wide: true });
    m.el.querySelector('#imp-file').onclick = () => m.el.querySelector('#imp-file-input').click();
    m.el.querySelector('#imp-file-input').onchange = async e => {
      const f = e.target.files[0]; if (!f) return;
      let text = await f.text();
      const body = /<body[^>]*>([\s\S]*)<\/body>/i.exec(text);
      const styles = [...text.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/gi)].map(x => x[0]).join('');
      text = (body ? body[1] : text).replace(/<script[\s\S]*?<\/script>/gi, '');
      m.el.querySelector('textarea').value = styles + text;
      toast(`โหลด ${f.name} แล้ว — กด “นำเข้า”`);
    };
    m.el.querySelector('[data-ok]').onclick = () => {
      const code = m.el.querySelector('textarea').value;
      if (!code.trim()) return;
      if (m.el.querySelector('[name=mode]:checked').value === 'replace') editor.setComponents(code); else editor.addComponents(code);
      m.close(); toast('นำเข้าแล้ว', 'ok');
    };
  }

  async function openHistory() {
    await editor.store();
    const r = await api(`/api/pages/${page.id}/revisions`);
    const m = modal(`<header><h2>เวอร์ชันย้อนหลัง</h2><button class="btn ghost icon" data-close>✕</button></header><div class="body">
      <div class="row" style="margin-bottom:12px;flex-wrap:nowrap"><input class="input" id="rev-note" placeholder="ชื่อเวอร์ชัน เช่น ก่อนเปลี่ยนสี"><button class="btn primary" id="rev-snap">บันทึกเวอร์ชันนี้</button></div>
      <div class="muted small" style="margin-bottom:8px">ระบบเก็บเวอร์ชันอัตโนมัติทุก 5 นาทีที่มีการแก้ไข (สูงสุด 40 เวอร์ชัน)</div>
      ${r.revisions.length ? r.revisions.map(v => `<div class="rev"><div class="t"><b>${esc(v.note || 'เวอร์ชัน')}</b><div class="muted small">${when(v.created_at)} · ${ago(v.created_at)}</div></div><button class="btn sm" data-rev="${v.id}">ย้อนกลับไปเวอร์ชันนี้</button></div>`).join('')
        : '<div class="empty-state">ยังไม่มีเวอร์ชันย้อนหลัง</div>'}</div>`);
    m.el.querySelector('#rev-snap').onclick = async () => {
      await api(`/api/pages/${page.id}/snapshot`, { note: m.el.querySelector('#rev-note').value });
      m.close(); toast('บันทึกเวอร์ชันแล้ว', 'ok');
    };
    m.el.querySelectorAll('[data-rev]').forEach(b => b.onclick = async () => {
      if (!await confirmBox('ย้อนเวอร์ชัน', 'แทนที่หน้าปัจจุบันด้วยเวอร์ชันนี้? (หน้าปัจจุบันจะถูกเก็บเป็นเวอร์ชันไว้ก่อน)', { ok: 'ย้อนกลับ' })) return;
      await api(`/api/revisions/${b.dataset.rev}/restore`, {});
      editor.UndoManager.clear();
      location.reload();
    });
  }
})();
