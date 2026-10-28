"""The configurable navigation bar ("managed" shared header).

Settings live in Site.nav; when the site's header SharedSection is ``managed`` the header HTML is generated
from them on every render (so the menu, logo, CTA and active page are always current). Switching to
"design freely" copies the generated HTML into the shared header for the drag-and-drop editor.
"""
import html as htmllib

LAYOUTS = ["split", "center-menu", "center-logo", "minimal"]
MOBILE = ["dropdown", "drawer", "fullscreen"]

DEFAULTS = {
    "layout": "split",          # split: logo left, menu right · center-menu · center-logo: logo above menu · minimal: menu button only
    "sticky": True,             # stays at the top while scrolling
    "transparent": False,       # over the first section, turns solid after scrolling
    "autohide": False,          # hides when scrolling down, shows when scrolling up
    "shadow": True,
    "mobile": "drawer",         # dropdown | drawer | fullscreen
    "logo_text": "",            # empty = site name
    "logo_image": "",           # /media/... ; shown instead of the text
    "logo_height": 36,
    "menu_mode": "auto",        # auto: pages marked "show in menu" · custom: items below
    "items": [],                # [{"label", "href", "target", "children": [...]}]
    "cta": {"show": True, "text": "ติดต่อเรา", "href": "contact.html"},
    "topbar": {"show": False, "text": "", "links": []},  # small bar above: text left, links right
    "bg": "",                   # empty = theme background
    "color": "",                # empty = theme text
    "height": 68,
}


def settings(site):
    raw = site.nav or {}
    out = {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}
    out["cta"] = {**DEFAULTS["cta"], **(raw.get("cta") or {})}
    out["topbar"] = {**DEFAULTS["topbar"], **(raw.get("topbar") or {})}
    if out["layout"] not in LAYOUTS:
        out["layout"] = "split"
    if out["mobile"] not in MOBILE:
        out["mobile"] = "drawer"
    return out


def clean(data):
    """Validate settings coming from the UI."""
    d = settings_from_dict(data)
    d["logo_height"] = max(16, min(120, int(d.get("logo_height") or 36)))
    d["height"] = max(44, min(140, int(d.get("height") or 68)))

    def items(lst, depth=0):
        out = []
        for it in (lst or [])[:30]:
            label = str(it.get("label") or "").strip()[:80]
            href = str(it.get("href") or "").strip()[:500]
            if not label:
                continue
            item = {"label": label, "href": href or "#", "target": "_blank" if it.get("target") == "_blank" else ""}
            if depth == 0:
                item["children"] = items(it.get("children"), 1)
            out.append(item)
        return out

    d["items"] = items(d.get("items"))
    d["topbar"]["links"] = [{"label": str(l.get("label") or "")[:60], "href": str(l.get("href") or "#")[:500]}
                            for l in (d["topbar"].get("links") or [])[:8] if l.get("label")]
    return d


def settings_from_dict(data):
    class _S:
        nav = data

    return settings(_S)


def _active(href, current):
    return current is not None and href.split("#")[0] in (current.filename, current.slug)


def _link(label, href, current, cls="", target=""):
    e = htmllib.escape
    classes = " ".join(c for c in (cls, "active" if _active(href, current) else "") if c)
    cls_attr = f' class="{classes}"' if classes else ""
    t = ' target="_blank" rel="noopener"' if target == "_blank" else ""
    return f'<a href="{e(href)}"{cls_attr}{t}>{e(label)}</a>'


def menu_html(s, pages, current):
    from .render import nav_html

    if s["menu_mode"] != "custom":
        return nav_html(pages, current)
    out = []
    for it in s["items"]:
        if it.get("children"):
            kids = "".join(_link(c["label"], c["href"], current, target=c.get("target")) for c in it["children"])
            out.append(f'<span class="bw-dd">{_link(it["label"], it["href"], current, target=it.get("target"))}'
                       f'<span class="bw-dd-menu">{kids}</span></span>')
        else:
            out.append(_link(it["label"], it["href"], current, target=it.get("target")))
    return "".join(out)


BURGER = ('<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
          'stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg>')
CLOSE = ('<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
         'stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>')


def render_header(site, pages, current=None):
    s = settings(site)
    e = htmllib.escape
    logo_text = s["logo_text"] or site.name
    if s["logo_image"]:
        logo = f'<img src="{e(s["logo_image"])}" alt="{e(logo_text)}" style="height:{int(s["logo_height"])}px;width:auto">'
    else:
        logo = e(logo_text)
    cta = ""
    if s["cta"].get("show") and s["cta"].get("text"):
        cta = f'<a href="{e(s["cta"].get("href") or "#")}" class="bw-btn bw-nav-cta">{e(s["cta"]["text"])}</a>'
    classes = ["bw-nav", "bw-nav--managed", f"bw-nav--{s['layout']}", f"bw-nav--m-{s['mobile']}"]
    for flag in ("sticky", "transparent", "autohide", "shadow"):
        if s[flag]:
            classes.append(f"bw-nav--{flag}")
    style = [f"--bw-nav-h:{int(s['height'])}px"]
    if s["bg"]:
        style.append(f"--bw-nav-bg:{e(s['bg'])}")
    if s["color"]:
        style.append(f"--bw-nav-fg:{e(s['color'])}")
    topbar = ""
    tb = s["topbar"]
    if tb.get("show") and (tb.get("text") or tb.get("links")):
        links = "".join(f'<a href="{e(l["href"])}">{e(l["label"])}</a>' for l in tb.get("links") or [])
        topbar = (f'<div class="bw-topbar"><div class="bw-container bw-topbar-in"><span>{e(tb.get("text") or "")}</span>'
                  f'<span class="bw-topbar-links">{links}</span></div></div>')
    menu = menu_html(s, pages, current)
    return (
        f'<header class="{" ".join(classes)}" style="{";".join(style)}" data-bw-nav>{topbar}'
        f'<div class="bw-container bw-nav-in"><a href="index.html" class="bw-logo">{logo}</a>'
        f'<button class="bw-nav-toggle" type="button" aria-label="เปิดเมนู" aria-expanded="false" data-bw-nav-toggle>{BURGER}</button>'
        f'<nav class="bw-nav-links" aria-label="เมนูหลัก"><button class="bw-nav-close" type="button" aria-label="ปิดเมนู" data-bw-nav-toggle>{CLOSE}</button>'
        f'<span class="bw-nav-menu">{menu}</span>{cta}</nav></div>'
        f'<div class="bw-nav-backdrop" data-bw-nav-toggle></div></header>'
    )


NAV_CSS = """
.bw-nav--managed{--bw-nav-bg:var(--bw-background);--bw-nav-fg:var(--bw-text);position:relative;z-index:50;background:var(--bw-nav-bg);color:var(--bw-nav-fg);transition:background .25s,box-shadow .25s,transform .3s}
.bw-nav--managed .bw-nav-in{display:flex;align-items:center;justify-content:space-between;gap:20px;min-height:var(--bw-nav-h)}
.bw-nav--managed .bw-logo{display:inline-flex;align-items:center;font-family:var(--bw-font-heading);font-weight:700;font-size:22px;color:inherit;text-decoration:none;flex:none}
.bw-nav--managed .bw-nav-links{display:flex;align-items:center;gap:22px}
.bw-nav--managed .bw-nav-menu{display:flex;align-items:center;gap:22px}
.bw-nav--managed .bw-nav-menu a{color:inherit;text-decoration:none;font-weight:500;opacity:.85;transition:opacity .15s,color .15s}
.bw-nav--managed .bw-nav-menu a:hover,.bw-nav--managed .bw-nav-menu a.active{opacity:1;color:var(--bw-primary)}
.bw-nav--managed .bw-nav-cta{padding:9px 20px;color:#fff}
.bw-nav--managed .bw-nav-toggle,.bw-nav--managed .bw-nav-close{display:none;background:none;border:0;color:inherit;cursor:pointer;padding:6px;line-height:0}
.bw-nav--managed .bw-nav-backdrop{display:none}
.bw-nav--shadow{box-shadow:0 1px 0 rgba(0,0,0,.06),0 8px 24px -18px rgba(0,0,0,.35)}
.bw-nav--sticky{position:sticky;top:0}
.bw-nav--transparent{position:fixed;top:0;left:0;right:0;background:transparent;box-shadow:none;--bw-nav-fg:#fff}
.bw-nav--transparent.bw-scrolled{background:var(--bw-background);--bw-nav-fg:var(--bw-text);box-shadow:0 8px 24px -18px rgba(0,0,0,.35)}
.bw-nav--autohide.bw-hidden{transform:translateY(-100%)}
.bw-nav--center-menu .bw-nav-links{flex:1;justify-content:space-between}
.bw-nav--center-menu .bw-nav-menu{margin:0 auto}
.bw-nav--center-logo .bw-nav-in{flex-direction:column;justify-content:center;gap:8px;padding:14px 0}
.bw-nav--center-logo .bw-nav-links{justify-content:center}
.bw-nav--minimal .bw-nav-toggle{display:block}
.bw-nav--minimal .bw-nav-links{display:none}
.bw-topbar{font-size:13px;background:var(--bw-text);color:#fff}
.bw-topbar-in{display:flex;justify-content:space-between;gap:16px;padding:6px 20px}
.bw-topbar a{color:#fff;text-decoration:none;opacity:.85;margin-left:16px}
@media (max-width:768px){
 .bw-nav--managed .bw-nav-in{flex-direction:row;justify-content:space-between;padding:0 20px}
 .bw-nav--managed .bw-nav-toggle{display:block}
 .bw-nav--managed .bw-nav-links{display:none}
 .bw-topbar-in{font-size:12px}
}
@media (max-width:768px){
 .bw-nav--m-dropdown.bw-open .bw-nav-links{display:flex;flex-direction:column;align-items:flex-start;position:absolute;left:0;right:0;top:100%;background:var(--bw-background);color:var(--bw-text);padding:16px 20px 22px;gap:14px;box-shadow:0 18px 30px -20px rgba(0,0,0,.4)}
 .bw-nav--m-dropdown.bw-open .bw-nav-menu{flex-direction:column;align-items:flex-start;gap:14px}
}
@media (max-width:768px){
 .bw-nav--m-drawer .bw-nav-links{display:flex;flex-direction:column;align-items:flex-start;position:fixed;top:0;right:0;bottom:0;width:min(320px,84vw);background:var(--bw-background);color:var(--bw-text);padding:70px 26px 26px;gap:16px;transform:translateX(100%);transition:transform .3s ease;box-shadow:-20px 0 50px -20px rgba(0,0,0,.4);z-index:2}
 .bw-nav--m-drawer .bw-nav-menu{flex-direction:column;align-items:flex-start;gap:16px;font-size:18px}
 .bw-nav--m-drawer.bw-open .bw-nav-links{transform:none}
 .bw-nav--m-drawer.bw-open .bw-nav-backdrop{display:block;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:1}
 .bw-nav--m-drawer .bw-nav-close,.bw-nav--m-fullscreen .bw-nav-close{display:block;position:absolute;top:16px;right:18px}
 .bw-nav--m-fullscreen .bw-nav-links{display:flex;flex-direction:column;justify-content:center;align-items:center;position:fixed;inset:0;background:var(--bw-background);color:var(--bw-text);gap:22px;opacity:0;pointer-events:none;transition:opacity .25s;z-index:2}
 .bw-nav--m-fullscreen .bw-nav-menu{flex-direction:column;gap:22px;font-size:24px;font-family:var(--bw-font-heading)}
 .bw-nav--m-fullscreen.bw-open .bw-nav-links{opacity:1;pointer-events:auto}
}
.bw-nav--minimal.bw-open .bw-nav-links{display:flex}
.bw-nav--minimal .bw-nav-links{flex-direction:column;align-items:flex-start;position:fixed;top:0;right:0;bottom:0;width:min(340px,86vw);background:var(--bw-background);color:var(--bw-text);padding:70px 26px 26px;gap:16px;z-index:2;box-shadow:-20px 0 50px -20px rgba(0,0,0,.4)}
.bw-nav--minimal .bw-nav-menu{flex-direction:column;align-items:flex-start;gap:16px;font-size:18px}
.bw-nav--minimal .bw-nav-close{display:block;position:absolute;top:16px;right:18px}
.bw-nav--minimal.bw-open .bw-nav-backdrop{display:block;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:1}
.bw-nav--managed .bw-dd-menu{color:var(--bw-text)}
"""

NAV_JS = r"""
  // Managed navbar: mobile menu, transparent → solid, hide on scroll down.
  document.querySelectorAll('[data-bw-nav]').forEach(function(nav){
    function setOpen(open){ nav.classList.toggle('bw-open', open); var t = nav.querySelector('.bw-nav-toggle'); if (t) t.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (nav.classList.contains('bw-nav--m-fullscreen')) document.documentElement.style.overflow = open ? 'hidden' : ''; }
    nav.querySelectorAll('[data-bw-nav-toggle]').forEach(function(b){ b.addEventListener('click', function(){ setOpen(!nav.classList.contains('bw-open')); }); });
    nav.querySelectorAll('.bw-nav-links a').forEach(function(a){ a.addEventListener('click', function(){ setOpen(false); }); });
    document.addEventListener('keydown', function(e){ if (e.key === 'Escape') setOpen(false); });
    var last = window.scrollY;
    function onScroll(){
      var y = window.scrollY;
      nav.classList.toggle('bw-scrolled', y > 40);
      if (nav.classList.contains('bw-nav--autohide')) nav.classList.toggle('bw-hidden', y > last && y > 120 && !nav.classList.contains('bw-open'));
      last = y;
    }
    window.addEventListener('scroll', onScroll, {passive: true}); onScroll();
  });
"""
