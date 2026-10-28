"""Site-wide widgets that ship in css/site.css and js/site.js:

- data lists: search box, category buttons and paging for repeats marked data-bw-search / data-bw-facet /
  data-bw-paginate (the server tags every row with data-bw-item, see data._mark_item)
- floating contact buttons (phone, LINE, Messenger, WhatsApp, ...) configured in Site.contact
"""
import html as htmllib
import re
from urllib.parse import quote

DATA_CSS = """
.bw-dctl{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 18px}
.bw-dsearch{flex:1 1 220px;max-width:420px;font:inherit;padding:10px 14px;border:1px solid #d9d9e3;border-radius:999px;background:#fff;color:inherit}
.bw-dsearch:focus{outline:2px solid var(--bw-primary,#7c3aed);border-color:transparent}
.bw-dchips{display:flex;flex-wrap:wrap;gap:6px}
.bw-dchip{font:inherit;font-size:.92em;padding:7px 14px;border-radius:999px;border:1px solid #d9d9e3;background:#fff;color:inherit;cursor:pointer}
.bw-dchip.on{background:var(--bw-primary,#7c3aed);border-color:var(--bw-primary,#7c3aed);color:#fff}
.bw-dempty{color:var(--bw-muted,#6b7280);text-align:center;padding:24px 0}
.bw-pager{display:flex;flex-wrap:wrap;justify-content:center;gap:6px;margin-top:22px}
.bw-pager:empty{display:none}
.bw-pager button{font:inherit;min-width:40px;height:40px;padding:0 12px;border-radius:10px;border:1px solid #d9d9e3;background:#fff;color:inherit;cursor:pointer}
.bw-pager button.on{background:var(--bw-primary,#7c3aed);border-color:var(--bw-primary,#7c3aed);color:#fff}
.bw-pager button:disabled{opacity:.4;cursor:default}
.bw-pager .bw-more{padding:0 26px;border-radius:999px}
"""

DATA_JS = r"""
  document.querySelectorAll('[data-bw-repeat]').forEach(function(box){
    var hasS = box.hasAttribute('data-bw-search'), facet = box.getAttribute('data-bw-facet');
    var per = parseInt(box.getAttribute('data-bw-paginate'), 10) || 0, mode = box.getAttribute('data-bw-pager') || 'pages';
    if (!hasS && !facet && !per) return;
    var items = [].slice.call(box.children).filter(function(c){ return c.hasAttribute('data-bw-item'); });
    items.forEach(function(it){ it.setAttribute('data-bw-disp', it.style.display || ''); });
    var anchor = box.tagName === 'TBODY' ? (box.closest('table') || box) : box;
    var q = '', cat = '', page = 1, more = per;
    var ctl = document.createElement('div'); ctl.className = 'bw-dctl';
    if (hasS) {
      var inp = document.createElement('input'); inp.type = 'search'; inp.className = 'bw-dsearch';
      inp.placeholder = box.getAttribute('data-bw-search') || 'ค้นหา…';
      inp.addEventListener('input', function(){ q = inp.value.trim().toLowerCase(); page = 1; more = per; draw(); });
      ctl.appendChild(inp);
    }
    if (facet) {
      var cats = [];
      items.forEach(function(it){ var c = it.getAttribute('data-bw-c'); if (c && cats.indexOf(c) < 0) cats.push(c); });
      var chips = document.createElement('div'); chips.className = 'bw-dchips';
      [''].concat(cats).forEach(function(c){
        var b = document.createElement('button'); b.type = 'button'; b.className = 'bw-dchip' + (c ? '' : ' on');
        b.textContent = c || box.getAttribute('data-bw-facet-all') || 'ทั้งหมด';
        b.addEventListener('click', function(){
          cat = c; page = 1; more = per;
          [].forEach.call(chips.children, function(x){ x.classList.toggle('on', x === b); });
          draw();
        });
        chips.appendChild(b);
      });
      ctl.appendChild(chips);
    }
    if (ctl.children.length) anchor.parentNode.insertBefore(ctl, anchor);
    var empty = document.createElement('p'); empty.className = 'bw-dempty';
    empty.textContent = box.getAttribute('data-bw-nomatch') || 'ไม่พบรายการที่ค้นหา'; empty.style.display = 'none';
    anchor.parentNode.insertBefore(empty, anchor.nextSibling);
    var pager = document.createElement('div'); pager.className = 'bw-pager';
    empty.parentNode.insertBefore(pager, empty.nextSibling);
    function btn(label, on, fn, cls){
      var b = document.createElement('button'); b.type = 'button'; b.textContent = label;
      if (cls) b.className = cls; if (on === null) b.disabled = true; else if (on) b.className += ' on';
      b.addEventListener('click', fn); pager.appendChild(b);
    }
    function go(p){ page = p; draw(); var top = (ctl.parentNode ? ctl : anchor).getBoundingClientRect().top + scrollY - 90; if (top < scrollY) scrollTo({top: top, behavior: 'smooth'}); }
    function draw(){
      var match = items.filter(function(it){
        return (!q || (it.getAttribute('data-bw-s') || '').indexOf(q) >= 0) && (!cat || it.getAttribute('data-bw-c') === cat);
      });
      var from = 0, to = match.length, pages = 1;
      if (per && mode === 'more') to = Math.min(more, match.length);
      else if (per) { pages = Math.ceil(match.length / per) || 1; if (page > pages) page = pages; from = (page - 1) * per; to = Math.min(from + per, match.length); }
      items.forEach(function(it){ it.style.display = 'none'; });
      match.slice(from, to).forEach(function(it){ it.style.display = it.getAttribute('data-bw-disp'); });
      empty.style.display = match.length ? 'none' : '';
      pager.innerHTML = '';
      if (per && mode === 'more') {
        if (to < match.length) btn(box.getAttribute('data-bw-more') || 'โหลดเพิ่ม', false, function(){ more += per; draw(); }, 'bw-more');
      } else if (pages > 1) {
        btn('‹', page > 1 ? false : null, function(){ go(page - 1); });
        for (var p = 1; p <= pages; p++) {
          if (pages > 7 && p > 1 && p < pages && Math.abs(p - page) > 1) { if (p === 2 || p === pages - 1) btn('…', null, function(){}); continue; }
          (function(p){ btn(String(p), p === page, function(){ go(p); }); })(p);
        }
        btn('›', page < pages ? false : null, function(){ go(page + 1); });
      }
    }
    draw();
  });
  document.addEventListener('click', function(e){
    var t = e.target.closest('[data-bw-fab-toggle]');
    if (t) { var f = t.closest('.bw-fab'); f.classList.toggle('open'); t.setAttribute('aria-expanded', f.classList.contains('open')); }
  });
"""

# --- floating contact buttons ---------------------------------------------------------------------

CHANNELS = [
    # key, label, colour, svg (24x24, fill=currentColor unless stroke)
    ("phone", "โทร", "", '<path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z"/>'),
    ("line", "LINE", "#06c755", '<path d="M12 3C6.5 3 2 6.6 2 11c0 3.9 3.5 7.2 8.3 7.9.3.1.8.2.9.5.1.3.1.7 0 1l-.1.9c0 .3-.2 1 .9.6 1.1-.5 5.9-3.5 8-6 1.4-1.6 2-3.2 2-4.9 0-4.4-4.5-8-10-8z"/><path fill="#06c755" d="M6.6 13.3h2V12.5H7.5V9.1h-.9zm2.7 0h.9V9.1h-.9zm1.8 0h.9v-2.5l1.7 2.5h.8V9.1h-.9v2.5l-1.7-2.5h-.8zm4.4 0h2.2v-.8h-1.3v-.9h1.3v-.8h-1.3v-.9h1.3v-.8h-2.2z"/>'),
    ("messenger", "Messenger", "linear-gradient(45deg,#0a7cff,#a033ff 60%,#ff5c87)", '<path d="M12 2C6.4 2 2 6.1 2 11.7c0 2.9 1.2 5.5 3.2 7.2v3.4l3-1.7c1.2.3 2.5.5 3.8.5 5.6 0 10-4.1 10-9.7S17.6 2 12 2zm1 13-2.5-2.7-5 2.7 5.5-5.8 2.6 2.7 4.9-2.7z"/>'),
    ("whatsapp", "WhatsApp", "#25d366", '<path d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2zm5.3 14.1c-.2.6-1.3 1.2-1.8 1.3-.5 0-.9.2-3.1-.7-2.6-1-4.3-3.7-4.4-3.9-.1-.2-1-1.4-1-2.7s.7-1.9 1-2.2c.2-.3.5-.3.7-.3h.5c.2 0 .4 0 .6.5l.8 2c.1.2.1.3 0 .5l-.3.5-.4.4c-.1.1-.3.3-.1.6.2.3.7 1.2 1.6 2 1.1 1 2 1.3 2.3 1.4.3.1.4.1.6-.1l.8-1c.2-.3.4-.2.6-.1l1.9.9c.3.1.4.2.5.3.1.2.1.7-.1 1.3z"/>'),
    ("facebook", "Facebook", "#1877f2", '<path d="M14 8h3V4h-3c-2.8 0-4.5 1.8-4.5 4.6V11H7v4h2.5v7h4v-7h3l.5-4h-3.5V8.9c0-.6.3-.9.9-.9z"/>'),
    ("email", "อีเมล", "#f97316", '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></g>'),
    ("map", "แผนที่", "#ea4335", '<path d="M12 2a7 7 0 0 0-7 7c0 5.2 7 13 7 13s7-7.8 7-13a7 7 0 0 0-7-7zm0 9.5A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5z"/>'),
]
CHANNEL_KEYS = [c[0] for c in CHANNELS]
CHAT_ICON = '<path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M21 11.5a8.4 8.4 0 0 1-9 8.4 8.6 8.6 0 0 1-3.8-.9L3 21l1.9-5.2A8.4 8.4 0 0 1 12 3a8.5 8.5 0 0 1 9 8.5z"/>'
CLOSE_ICON = '<path fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" d="M6 6l12 12M18 6 6 18"/>'

CONTACT_DEFAULTS = {
    "enabled": False,
    "position": "right",   # right | left
    "style": "stack",      # stack: all buttons · expand: one button that opens · bar: bottom bar on phones
    "labels": True,        # show the name next to each button on hover / in the bar
    "pulse": True,         # gentle pulse on the main button
    "color": "",           # main button colour (empty = theme primary)
    "label": "ติดต่อเรา",
    "bottom": 20,
    **{k: "" for k in CHANNEL_KEYS},
}

CONTACT_CSS = """
.bw-fab{position:fixed;bottom:var(--bw-fab-bottom,20px);right:20px;z-index:900;display:flex;flex-direction:column;align-items:flex-end;gap:10px;font-family:inherit}
.bw-fab.left{right:auto;left:20px;align-items:flex-start}
.bw-fab-list{display:flex;flex-direction:column;gap:10px;align-items:inherit}
.bw-fab-btn,.bw-fab-main{position:relative;width:52px;height:52px;border-radius:50%;display:grid;place-items:center;color:#fff;background:var(--c,var(--bw-primary,#7c3aed));
box-shadow:0 10px 24px -8px rgba(0,0,0,.35);text-decoration:none;border:0;cursor:pointer;transition:transform .18s}
.bw-fab-btn:hover,.bw-fab-main:hover{transform:scale(1.08)}
.bw-fab svg{width:26px;height:26px;fill:currentColor}
.bw-fab-tip{position:absolute;right:62px;top:50%;transform:translateY(-50%);background:#111827;color:#fff;font-size:13px;padding:5px 10px;border-radius:8px;white-space:nowrap;opacity:0;pointer-events:none;transition:opacity .15s}
.bw-fab.left .bw-fab-tip{right:auto;left:62px}
.bw-fab-btn:hover .bw-fab-tip,.bw-fab-btn:focus .bw-fab-tip{opacity:1}
.bw-fab.expand .bw-fab-list{display:none}
.bw-fab.expand.open .bw-fab-list{display:flex;animation:bw-fab-in .2s ease-out}
.bw-fab-main .bw-x{display:none}.bw-fab.open .bw-fab-main .bw-x{display:block}.bw-fab.open .bw-fab-main .bw-o{display:none}
.bw-fab.pulse .bw-fab-main::after,.bw-fab.pulse.stack .bw-fab-list>:last-child::after{content:"";position:absolute;inset:0;border-radius:50%;box-shadow:0 0 0 0 var(--c,var(--bw-primary,#7c3aed));animation:bw-fab-pulse 2.4s infinite}
.bw-fab.open .bw-fab-main::after{display:none}
@keyframes bw-fab-pulse{0%{box-shadow:0 0 0 0 rgba(0,0,0,.25)}70%{box-shadow:0 0 0 14px rgba(0,0,0,0)}100%{box-shadow:0 0 0 0 rgba(0,0,0,0)}}
@keyframes bw-fab-in{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
@media (max-width:768px){
.bw-fab{right:14px;bottom:calc(var(--bw-fab-bottom,20px) - 6px)}.bw-fab.left{left:14px}
.bw-fab-btn,.bw-fab-main{width:48px;height:48px}
.bw-fab.bar{left:0;right:0;bottom:0;flex-direction:row;gap:0;background:#fff;box-shadow:0 -6px 20px -10px rgba(0,0,0,.3);padding:6px 6px calc(6px + env(safe-area-inset-bottom))}
.bw-fab.bar .bw-fab-list{flex-direction:row;flex:1;gap:6px}
.bw-fab.bar .bw-fab-btn{flex:1;width:auto;height:46px;border-radius:12px;box-shadow:none;display:flex;gap:6px;justify-content:center;align-items:center;font-size:14px;font-weight:600}
.bw-fab.bar .bw-fab-btn svg{width:20px;height:20px}
.bw-fab.bar .bw-fab-tip{position:static;transform:none;opacity:1;background:none;padding:0;font-size:13px}
.bw-fab.bar .bw-fab-btn::after{display:none}
body.bw-has-bar{padding-bottom:64px}
}
"""


def clean_contact(d):
    d = d or {}
    out = dict(CONTACT_DEFAULTS)
    for k, default in CONTACT_DEFAULTS.items():
        if k not in d:
            continue
        v = d[k]
        if isinstance(default, bool):
            out[k] = v in (True, "1", "true", "on", 1)
        elif isinstance(default, int):
            try:
                out[k] = max(0, min(200, int(v)))
            except (TypeError, ValueError):
                pass
        else:
            out[k] = str(v or "").strip()[:300]
    if out["position"] not in ("right", "left"):
        out["position"] = "right"
    if out["style"] not in ("stack", "expand", "bar"):
        out["style"] = "stack"
    if out["color"] and not re.fullmatch(r"#[0-9a-fA-F]{3,8}", out["color"]):
        out["color"] = ""
    return out


def digits(s):
    return re.sub(r"[^\d+]", "", s or "")


def channel_url(key, value):
    v = (value or "").strip()
    if not v:
        return ""
    if key == "phone":
        return "tel:" + digits(v)
    if key == "email":
        return v if v.startswith("mailto:") else "mailto:" + v
    if re.match(r"^https?://", v, re.I):
        return v
    if key == "line":
        # @abc = LINE Official Account, anything else = personal LINE ID
        return f"https://line.me/R/ti/p/{quote(v)}" if v.startswith("@") else f"https://line.me/ti/p/~{quote(v)}"
    if key == "messenger":
        return "https://m.me/" + quote(v.lstrip("@"))
    if key == "whatsapp":
        n = re.sub(r"\D", "", v)
        if n.startswith("0") and len(n) == 10:  # Thai mobile 08x-xxx-xxxx -> 668xxxxxxxx
            n = "66" + n[1:]
        return "https://wa.me/" + n
    if key == "facebook":
        return "https://www.facebook.com/" + quote(v.lstrip("@"))
    if key == "map":
        return "https://www.google.com/maps/search/?api=1&query=" + quote(v)
    return ""


def contact_html(site):
    c = clean_contact(site.contact)
    if not c["enabled"]:
        return ""
    e = htmllib.escape
    links = []
    for key, label, colour, svg in CHANNELS:
        url = channel_url(key, c[key])
        if not url:
            continue
        ext = "" if url.startswith(("tel:", "mailto:")) else ' target="_blank" rel="noopener"'
        style = f' style="--c:{colour}"' if colour and not colour.startswith("linear") else (f' style="background:{colour}"' if colour else "")
        tip = f'<span class="bw-fab-tip">{e(label)}</span>' if c["labels"] or c["style"] == "bar" else ""
        links.append(f'<a class="bw-fab-btn bw-fab-{key}" href="{e(url)}"{ext}{style} aria-label="{e(label)}">'
                     f'<svg viewBox="0 0 24 24" aria-hidden="true">{svg}</svg>{tip}</a>')
    if not links:
        return ""
    cls = ["bw-fab", c["style"]] + (["left"] if c["position"] == "left" else []) + (["pulse"] if c["pulse"] else [])
    style = f"--bw-fab-bottom:{c['bottom']}px" + (f";--c:{c['color']}" if c["color"] else "")
    main = ""
    if c["style"] == "expand":
        main = (f'<button type="button" class="bw-fab-main" data-bw-fab-toggle aria-expanded="false" aria-label="{e(c["label"])}" title="{e(c["label"])}">'
                f'<svg class="bw-o" viewBox="0 0 24 24">{CHAT_ICON}</svg><svg class="bw-x" viewBox="0 0 24 24">{CLOSE_ICON}</svg></button>')
    bar = '<script>document.body.classList.add("bw-has-bar")</script>' if c["style"] == "bar" else ""
    return (f'<div class="{" ".join(cls)}" style="{style}"><div class="bw-fab-list">{"".join(links)}</div>{main}</div>{bar}')
