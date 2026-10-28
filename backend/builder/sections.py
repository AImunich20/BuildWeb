"""Ready-made sections (drag-and-drop blocks in the editor) and starter site templates built from them.

Each section is HTML with an embedded <style>; GrapesJS turns the <style> into editable CSS rules.
Colors and fonts use the site theme variables (--bw-primary, --bw-font-heading, ...), so changing the
theme restyles every section at once.
"""
from base64 import b64encode


def placeholder(label="รูปภาพ", w=800, h=520, c1="#c4b5fd", c2="#67e8f9"):
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{c1}"/>'
        f'<stop offset="1" stop-color="{c2}"/></linearGradient></defs><rect width="100%" height="100%" fill="url(#g)"/>'
        f'<text x="50%" y="50%" fill="#ffffff" font-family="sans-serif" font-size="{max(18, w // 18)}" '
        f'text-anchor="middle" dominant-baseline="middle">{label}</text></svg>'
    )
    return "data:image/svg+xml;base64," + b64encode(svg.encode()).decode()


IMG = placeholder()
IMG_SQ = placeholder("รูปภาพ", 600, 600, "#fbcfe8", "#c4b5fd")
AVATAR = placeholder("👤", 200, 200, "#ddd6fe", "#a5f3fc")

SECTIONS = [
    {
        "id": "navbar",
        "label": "แถบเมนู",
        "category": "ส่วนหัว/ท้าย",
        "icon": "menu",
        "html": """<header class="bw-nav"><div class="bw-container bw-nav-in">
<a href="index.html" class="bw-logo">แบรนด์ของคุณ</a>
<button class="bw-nav-toggle" data-bw-menu-toggle=".bw-nav-links" aria-label="เมนู">☰</button>
<nav class="bw-nav-links"><span class="bw-nav-auto" data-bw-auto-nav><a href="index.html">หน้าแรก</a><a href="about.html">เกี่ยวกับเรา</a><a href="contact.html">ติดต่อ</a></span>
<a href="contact.html" class="bw-btn">ติดต่อเรา</a></nav></div></header>""",
        "css": """.bw-nav{position:sticky;top:0;z-index:50;background:rgba(255,255,255,.9);backdrop-filter:blur(10px);border-bottom:1px solid #eee}
.bw-nav-in{display:flex;align-items:center;justify-content:space-between;min-height:68px;gap:16px}
.bw-logo{font-family:var(--bw-font-heading);font-weight:700;font-size:22px;color:var(--bw-text);text-decoration:none}
.bw-nav-links{display:flex;align-items:center;gap:26px}
.bw-nav-auto{display:contents}
.bw-nav-links a{color:var(--bw-text);text-decoration:none;font-weight:500}
.bw-nav-links a.active{color:var(--bw-primary)}
.bw-nav-links a.bw-btn{color:#fff;padding:9px 20px}
.bw-nav-toggle{display:none;background:none;border:0;font-size:26px;cursor:pointer;color:var(--bw-text)}
@media (max-width:768px){.bw-nav-toggle{display:block}.bw-nav-links{display:none;position:absolute;left:0;right:0;top:68px;
flex-direction:column;background:#fff;padding:16px 20px;border-bottom:1px solid #eee;align-items:flex-start}
.bw-nav-links.open{display:flex}}""",
    },
    {
        "id": "hero",
        "label": "ฮีโร่ (หัวเว็บ)",
        "category": "เนื้อหา",
        "icon": "star",
        "html": f"""<section class="bw-hero"><div class="bw-container bw-hero-in">
<div class="bw-hero-text"><span class="bw-badge">✨ ใหม่ล่าสุด</span>
<h1>สร้างสิ่งที่ยอดเยี่ยม<br>ให้ลูกค้าของคุณ</h1>
<p>บอกเล่าเรื่องราวธุรกิจของคุณในหนึ่งประโยค ให้ผู้เข้าชมรู้ทันทีว่าคุณช่วยอะไรเขาได้</p>
<div class="bw-hero-actions"><a href="contact.html" class="bw-btn">ติดต่อเรา</a><a href="#features" class="bw-btn bw-btn-outline">ดูเพิ่มเติม</a></div></div>
<img class="bw-hero-img" src="{IMG}" alt="ภาพประกอบ"></div></section>""",
        "css": """.bw-hero{padding:90px 0;background:linear-gradient(135deg,var(--bw-surface),#fff 60%)}
.bw-hero-in{display:grid;grid-template-columns:1.1fr 1fr;gap:48px;align-items:center}
.bw-hero h1{font-size:clamp(34px,5vw,56px);font-weight:700}
.bw-hero p{font-size:19px;color:var(--bw-muted);max-width:520px}
.bw-badge{display:inline-block;background:#fff;color:var(--bw-primary);padding:6px 14px;border-radius:999px;font-weight:600;
font-size:14px;margin-bottom:18px;box-shadow:0 4px 14px -6px rgba(0,0,0,.15)}
.bw-hero-actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:24px}
.bw-hero-img{width:100%;border-radius:var(--bw-radius);box-shadow:0 30px 60px -30px rgba(0,0,0,.35)}
@media (max-width:768px){.bw-hero{padding:56px 0}.bw-hero-in{grid-template-columns:1fr}}""",
    },
    {
        "id": "hero-center",
        "label": "ฮีโร่ตรงกลาง",
        "category": "เนื้อหา",
        "icon": "target",
        "html": """<section class="bw-hero2"><div class="bw-container">
<h1>ทุกอย่างที่คุณต้องการ<br>อยู่ในที่เดียว</h1>
<p>คำอธิบายสั้นๆ ที่ดึงดูดให้ผู้คนอยากอ่านต่อ</p>
<a href="contact.html" class="bw-btn">เริ่มต้นใช้งานฟรี</a></div></section>""",
        "css": """.bw-hero2{padding:120px 0;text-align:center;color:#fff;background:linear-gradient(135deg,var(--bw-primary),var(--bw-secondary))}
.bw-hero2 h1{font-size:clamp(34px,5vw,60px)}
.bw-hero2 p{font-size:20px;opacity:.9;margin-bottom:30px}
.bw-hero2 .bw-btn{background:#fff;color:var(--bw-primary);border-color:#fff}""",
    },
    {
        "id": "features",
        "label": "จุดเด่น 3 ช่อง",
        "category": "เนื้อหา",
        "icon": "grid",
        "html": """<section class="bw-features" id="features"><div class="bw-container">
<div class="bw-sec-head"><h2>ทำไมต้องเลือกเรา</h2><p>สามเหตุผลที่ลูกค้าไว้วางใจ</p></div>
<div class="bw-grid3">
<div class="bw-card"><div class="bw-icon">⚡</div><h3>รวดเร็ว</h3><p>อธิบายจุดเด่นข้อแรกของคุณให้ชัดเจนและกระชับ</p></div>
<div class="bw-card"><div class="bw-icon">🛡️</div><h3>ปลอดภัย</h3><p>อธิบายจุดเด่นข้อที่สองที่ทำให้คุณแตกต่าง</p></div>
<div class="bw-card"><div class="bw-icon">💜</div><h3>ใส่ใจ</h3><p>อธิบายจุดเด่นข้อที่สามที่ลูกค้าชื่นชอบ</p></div>
</div></div></section>""",
        "css": """.bw-features{padding:90px 0}
.bw-sec-head{text-align:center;max-width:640px;margin:0 auto 48px}
.bw-sec-head h2{font-size:clamp(28px,3.5vw,40px)}
.bw-sec-head p{color:var(--bw-muted);font-size:18px}
.bw-grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:24px}
.bw-card{background:#fff;border:1px solid #eee;border-radius:var(--bw-radius);padding:30px;transition:transform .2s,box-shadow .2s}
.bw-card:hover{transform:translateY(-4px);box-shadow:0 20px 40px -24px rgba(0,0,0,.25)}
.bw-icon{width:52px;height:52px;border-radius:14px;background:var(--bw-surface);display:flex;align-items:center;justify-content:center;font-size:26px;margin-bottom:16px}
.bw-card p{color:var(--bw-muted);margin:0}
@media (max-width:768px){.bw-grid3{grid-template-columns:1fr}}""",
    },
    {
        "id": "about",
        "label": "เกี่ยวกับ + รูป",
        "category": "เนื้อหา",
        "icon": "columns",
        "html": f"""<section class="bw-about"><div class="bw-container bw-about-in">
<img src="{IMG_SQ}" alt="เกี่ยวกับเรา">
<div><h2>เรื่องราวของเรา</h2>
<p>เล่าที่มา ความตั้งใจ และสิ่งที่ทำให้ธุรกิจของคุณพิเศษ ผู้คนชอบเชื่อมโยงกับเรื่องราวที่จริงใจ</p>
<ul class="bw-checks"><li>ประสบการณ์มากกว่า 10 ปี</li><li>ทีมงานมืออาชีพ</li><li>บริการหลังการขายดีเยี่ยม</li></ul>
<a href="about.html" class="bw-btn">อ่านต่อ</a></div></div></section>""",
        "css": """.bw-about{padding:90px 0;background:var(--bw-surface)}
.bw-about-in{display:grid;grid-template-columns:1fr 1fr;gap:56px;align-items:center}
.bw-about img{width:100%;border-radius:var(--bw-radius)}
.bw-about h2{font-size:clamp(28px,3.5vw,40px)}
.bw-about p{color:var(--bw-muted);font-size:17px}
.bw-checks{list-style:none;padding:0;margin:0 0 26px}
.bw-checks li{padding:6px 0 6px 30px;position:relative}
.bw-checks li::before{content:"✓";position:absolute;left:0;color:var(--bw-primary);font-weight:700}
@media (max-width:768px){.bw-about-in{grid-template-columns:1fr}}""",
    },
    {
        "id": "stats",
        "label": "ตัวเลขสถิติ",
        "category": "เนื้อหา",
        "icon": "hash",
        "html": """<section class="bw-stats"><div class="bw-container bw-stats-in">
<div><strong>1,200+</strong><span>ลูกค้า</span></div><div><strong>98%</strong><span>ความพึงพอใจ</span></div>
<div><strong>24/7</strong><span>ดูแลตลอด</span></div><div><strong>15</strong><span>รางวัล</span></div></div></section>""",
        "css": """.bw-stats{padding:60px 0;background:var(--bw-text);color:#fff}
.bw-stats-in{display:grid;grid-template-columns:repeat(4,1fr);gap:20px;text-align:center}
.bw-stats strong{display:block;font-family:var(--bw-font-heading);font-size:42px;color:var(--bw-secondary)}
.bw-stats span{opacity:.8}
@media (max-width:768px){.bw-stats-in{grid-template-columns:repeat(2,1fr)}}""",
    },
    {
        "id": "gallery",
        "label": "แกลเลอรี",
        "category": "สื่อ",
        "icon": "images",
        "html": "<section class=\"bw-gallery\"><div class=\"bw-container\"><div class=\"bw-sec-head\"><h2>ผลงานของเรา</h2></div>"
        "<div class=\"bw-gal-grid\">"
        + "".join(
            f'<img src="{placeholder(f"ผลงาน {i}", 600, 450, c1, c2)}" alt="ผลงาน {i}">'
            for i, (c1, c2) in enumerate(
                [("#c4b5fd", "#67e8f9"), ("#fbcfe8", "#fde68a"), ("#a7f3d0", "#93c5fd"),
                 ("#fde68a", "#fca5a5"), ("#93c5fd", "#c4b5fd"), ("#fca5a5", "#fbcfe8")], 1)
        )
        + "</div></div></section>",
        "css": """.bw-gallery{padding:90px 0}
.bw-gal-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.bw-gal-grid img{width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:var(--bw-radius);transition:transform .25s}
.bw-gal-grid img:hover{transform:scale(1.03)}
@media (max-width:768px){.bw-gal-grid{grid-template-columns:repeat(2,1fr)}}""",
    },
    {
        "id": "pricing",
        "label": "ตารางราคา",
        "category": "ขาย",
        "icon": "tag",
        "html": """<section class="bw-pricing"><div class="bw-container">
<div class="bw-sec-head"><h2>แพ็กเกจราคา</h2><p>เลือกแพ็กเกจที่เหมาะกับคุณ</p></div>
<div class="bw-grid3">
<div class="bw-price"><h3>เริ่มต้น</h3><div class="bw-amount">฿290<small>/เดือน</small></div><ul><li>ฟีเจอร์พื้นฐาน</li><li>ผู้ใช้ 1 คน</li><li>อีเมลซัพพอร์ต</li></ul><a href="contact.html" class="bw-btn bw-btn-outline">เลือกแพ็กเกจ</a></div>
<div class="bw-price bw-price-hot"><span class="bw-tag">ยอดนิยม</span><h3>มืออาชีพ</h3><div class="bw-amount">฿890<small>/เดือน</small></div><ul><li>ทุกอย่างในแพ็กเริ่มต้น</li><li>ผู้ใช้ 5 คน</li><li>ซัพพอร์ตด่วน</li></ul><a href="contact.html" class="bw-btn">เลือกแพ็กเกจ</a></div>
<div class="bw-price"><h3>องค์กร</h3><div class="bw-amount">฿2,490<small>/เดือน</small></div><ul><li>ทุกอย่างในแพ็กมืออาชีพ</li><li>ผู้ใช้ไม่จำกัด</li><li>ผู้ดูแลส่วนตัว</li></ul><a href="contact.html" class="bw-btn bw-btn-outline">ติดต่อฝ่ายขาย</a></div>
</div></div></section>""",
        "css": """.bw-pricing{padding:90px 0;background:var(--bw-surface)}
.bw-price{position:relative;background:#fff;border-radius:var(--bw-radius);padding:34px;text-align:center;border:2px solid transparent}
.bw-price-hot{border-color:var(--bw-primary);transform:scale(1.03);box-shadow:0 24px 50px -28px var(--bw-primary)}
.bw-tag{position:absolute;top:-13px;left:50%;transform:translateX(-50%);background:var(--bw-primary);color:#fff;padding:4px 14px;border-radius:999px;font-size:13px;font-weight:600}
.bw-amount{font-family:var(--bw-font-heading);font-size:44px;font-weight:700;color:var(--bw-primary);margin:8px 0 16px}
.bw-amount small{font-size:16px;color:var(--bw-muted);font-weight:400}
.bw-price ul{list-style:none;padding:0;margin:0 0 26px;color:var(--bw-muted)}
.bw-price li{padding:7px 0;border-bottom:1px dashed #eee}""",
    },
    {
        "id": "testimonials",
        "label": "รีวิวลูกค้า",
        "category": "ขาย",
        "icon": "quote",
        "html": f"""<section class="bw-testi"><div class="bw-container">
<div class="bw-sec-head"><h2>เสียงจากลูกค้า</h2></div><div class="bw-grid3">
<figure class="bw-quote"><blockquote>“บริการดีมาก ประทับใจตั้งแต่ครั้งแรก แนะนำเลยค่ะ”</blockquote><figcaption><img src="{AVATAR}" alt="">คุณสมหญิง<br><small>เจ้าของร้าน</small></figcaption></figure>
<figure class="bw-quote"><blockquote>“ทีมงานเป็นมืออาชีพ งานเสร็จตรงเวลา คุ้มค่ามาก”</blockquote><figcaption><img src="{AVATAR}" alt="">คุณสมชาย<br><small>ผู้จัดการ</small></figcaption></figure>
<figure class="bw-quote"><blockquote>“ใช้มาหลายปีแล้ว ไม่เคยผิดหวังเลยครับ”</blockquote><figcaption><img src="{AVATAR}" alt="">คุณวิชัย<br><small>ลูกค้าประจำ</small></figcaption></figure>
</div></div></section>""",
        "css": """.bw-testi{padding:90px 0}
.bw-quote{margin:0;background:#fff;border:1px solid #eee;border-radius:var(--bw-radius);padding:28px}
.bw-quote blockquote{margin:0 0 18px;font-size:17px}
.bw-quote figcaption{display:flex;align-items:center;gap:12px;font-weight:600;line-height:1.3}
.bw-quote figcaption img{width:46px;height:46px;border-radius:50%}
.bw-quote small{color:var(--bw-muted);font-weight:400}""",
    },
    {
        "id": "team",
        "label": "ทีมงาน",
        "category": "เนื้อหา",
        "icon": "users",
        "html": "<section class=\"bw-team\"><div class=\"bw-container\"><div class=\"bw-sec-head\"><h2>ทีมของเรา</h2></div><div class=\"bw-team-grid\">"
        + "".join(
            f'<div class="bw-member"><img src="{AVATAR}" alt="{n}"><h3>{n}</h3><p>{r}</p></div>'
            for n, r in [("อรุณี", "ผู้ก่อตั้ง"), ("ธนพล", "นักออกแบบ"), ("ปิยะ", "นักพัฒนา"), ("มาลี", "การตลาด")]
        )
        + "</div></div></section>",
        "css": """.bw-team{padding:90px 0;background:var(--bw-surface)}
.bw-team-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:24px;text-align:center}
.bw-member img{width:140px;height:140px;border-radius:50%;margin-bottom:12px;border:4px solid #fff}
.bw-member h3{margin:0}.bw-member p{color:var(--bw-muted)}
@media (max-width:768px){.bw-team-grid{grid-template-columns:repeat(2,1fr)}}""",
    },
    {
        "id": "faq",
        "label": "คำถามที่พบบ่อย",
        "category": "เนื้อหา",
        "icon": "help",
        "html": """<section class="bw-faq"><div class="bw-container bw-faq-in"><div class="bw-sec-head"><h2>คำถามที่พบบ่อย</h2></div>
<details open><summary>ใช้เวลานานแค่ไหน?</summary><p>โดยทั่วไปใช้เวลา 3-5 วันทำการ ขึ้นอยู่กับรายละเอียดงาน</p></details>
<details><summary>ชำระเงินได้ทางไหนบ้าง?</summary><p>รองรับโอนเงิน พร้อมเพย์ และบัตรเครดิต</p></details>
<details><summary>มีบริการหลังการขายไหม?</summary><p>มีทีมงานดูแลตลอดการใช้งาน ติดต่อได้ทุกวัน</p></details>
</div></section>""",
        "css": """.bw-faq{padding:90px 0}
.bw-faq-in{max-width:760px}
.bw-faq details{border:1px solid #eee;border-radius:12px;padding:18px 22px;margin-bottom:12px;background:#fff}
.bw-faq summary{font-weight:600;cursor:pointer;font-size:17px}
.bw-faq details p{margin:12px 0 0;color:var(--bw-muted)}""",
    },
    {
        "id": "cta",
        "label": "ชวนให้ติดต่อ (CTA)",
        "category": "ขาย",
        "icon": "arrow",
        "html": """<section class="bw-cta"><div class="bw-container bw-cta-in">
<div><h2>พร้อมเริ่มต้นแล้วหรือยัง?</h2><p>ปรึกษาฟรี ไม่มีค่าใช้จ่าย</p></div>
<a href="contact.html" class="bw-btn">คุยกับเราเลย</a></div></section>""",
        "css": """.bw-cta{padding:70px 0}
.bw-cta-in{display:flex;align-items:center;justify-content:space-between;gap:24px;flex-wrap:wrap;color:#fff;
background:linear-gradient(120deg,var(--bw-primary),var(--bw-secondary));border-radius:calc(var(--bw-radius) * 2);padding:48px}
.bw-cta h2{margin:0}.bw-cta p{margin:6px 0 0;opacity:.9}
.bw-cta .bw-btn{background:#fff;color:var(--bw-primary);border-color:#fff}""",
    },
    {
        "id": "contact",
        "label": "ฟอร์มติดต่อ",
        "category": "ฟอร์ม",
        "icon": "mail",
        "html": """<section class="bw-contact"><div class="bw-container bw-contact-in">
<div><h2>ติดต่อเรา</h2><p>ฝากข้อความไว้ แล้วเราจะติดต่อกลับโดยเร็วที่สุด</p>
<p>📍 กรุงเทพมหานคร<br>📞 02-123-4567<br>✉️ hello@example.com</p></div>
<form class="bw-form" name="contact" data-bw-success="ขอบคุณ! เราได้รับข้อความแล้ว">
<label>ชื่อ<input name="name" required placeholder="ชื่อของคุณ"></label>
<label>อีเมล<input name="email" type="email" required placeholder="you@example.com"></label>
<label>เบอร์โทร<input name="phone" type="tel" placeholder="08x-xxx-xxxx"></label>
<label>ข้อความ<textarea name="message" rows="4" placeholder="พิมพ์ข้อความ..."></textarea></label>
<button type="submit" class="bw-btn">ส่งข้อความ</button></form></div></section>""",
        "css": """.bw-contact{padding:90px 0}
.bw-contact-in{display:grid;grid-template-columns:1fr 1.2fr;gap:48px}
.bw-contact p{color:var(--bw-muted)}
.bw-form{display:grid;gap:14px;background:#fff;border:1px solid #eee;border-radius:var(--bw-radius);padding:30px}
.bw-form label{display:grid;gap:6px;font-weight:600;font-size:15px}
.bw-form input,.bw-form textarea,.bw-form select{font:inherit;padding:12px 14px;border:1px solid #ddd;border-radius:10px;font-weight:400}
.bw-form input:focus,.bw-form textarea:focus{outline:2px solid var(--bw-primary);border-color:transparent}
.bw-form button{justify-self:start;cursor:pointer;font:inherit;font-weight:600}
@media (max-width:768px){.bw-contact-in{grid-template-columns:1fr}}""",
    },
    {
        "id": "map",
        "label": "แผนที่",
        "category": "สื่อ",
        "icon": "pin",
        "html": """<section class="bw-map"><iframe title="แผนที่" src="https://maps.google.com/maps?q=Bangkok&z=13&output=embed" loading="lazy"></iframe></section>""",
        "css": """.bw-map iframe{display:block;width:100%;height:380px;border:0}""",
    },
    {
        "id": "video",
        "label": "วิดีโอ YouTube",
        "category": "สื่อ",
        "icon": "play",
        "html": """<section class="bw-video"><div class="bw-container"><div class="bw-video-box">
<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ" title="วิดีโอ" allowfullscreen></iframe></div></div></section>""",
        "css": """.bw-video{padding:70px 0}
.bw-video-box{position:relative;aspect-ratio:16/9;border-radius:var(--bw-radius);overflow:hidden}
.bw-video-box iframe{position:absolute;inset:0;width:100%;height:100%;border:0}""",
    },
    {
        "id": "menu-list",
        "label": "เมนู/สินค้า",
        "category": "ขาย",
        "icon": "coffee",
        "html": "<section class=\"bw-menu\"><div class=\"bw-container\"><div class=\"bw-sec-head\"><h2>เมนูแนะนำ</h2></div><div class=\"bw-menu-grid\">"
        + "".join(
            f'<div class="bw-menu-item"><img src="{placeholder(n, 400, 300, "#fde68a", "#fca5a5")}" alt="{n}"><div><h3>{n}</h3><p>{d}</p><strong>฿{p}</strong></div></div>'
            for n, d, p in [("ลาเต้", "นมสดหอมมัน กาแฟคั่วกลาง", 65), ("ชาไทย", "ชาไทยสูตรเข้มข้น", 55),
                            ("ครัวซองต์", "อบสดใหม่ทุกเช้า", 75), ("ชีสเค้ก", "นุ่มละมุน หวานกำลังดี", 95)]
        )
        + "</div></div></section>",
        "css": """.bw-menu{padding:90px 0}
.bw-menu-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:20px}
.bw-menu-item{display:flex;gap:18px;align-items:center;background:#fff;border:1px solid #eee;border-radius:var(--bw-radius);padding:14px}
.bw-menu-item img{width:120px;height:96px;object-fit:cover;border-radius:10px}
.bw-menu-item h3{margin:0 0 4px}.bw-menu-item p{margin:0 0 6px;color:var(--bw-muted)}
.bw-menu-item strong{color:var(--bw-primary);font-size:18px}
@media (max-width:768px){.bw-menu-grid{grid-template-columns:1fr}}""",
    },
    {
        "id": "page-header",
        "label": "หัวข้อหน้า",
        "category": "เนื้อหา",
        "icon": "heading",
        "html": """<section class="bw-phead"><div class="bw-container"><h1>ชื่อหน้า</h1><p>คำอธิบายสั้นๆ ของหน้านี้</p></div></section>""",
        "css": """.bw-phead{padding:80px 0 60px;text-align:center;background:var(--bw-surface)}
.bw-phead h1{font-size:clamp(32px,4.5vw,50px)}.bw-phead p{color:var(--bw-muted);font-size:18px;margin:0}""",
    },
    {
        "id": "text-block",
        "label": "บทความ",
        "category": "เนื้อหา",
        "icon": "text",
        "html": """<section class="bw-article"><div class="bw-container bw-article-in"><h2>หัวข้อบทความ</h2>
<p>เริ่มเขียนเนื้อหาที่นี่ ดับเบิลคลิกเพื่อแก้ไขข้อความ คุณสามารถเพิ่มย่อหน้า ลิงก์ ตัวหนา หรือตัวเอียงได้</p>
<p>ย่อหน้าที่สองสำหรับรายละเอียดเพิ่มเติม เขียนให้อ่านง่าย แบ่งเป็นช่วงสั้นๆ</p></div></section>""",
        "css": """.bw-article{padding:70px 0}.bw-article-in{max-width:760px;font-size:18px}""",
    },
    {
        "id": "footer",
        "label": "ส่วนท้าย",
        "category": "ส่วนหัว/ท้าย",
        "icon": "panel-bottom",
        "html": """<footer class="bw-footer"><div class="bw-container bw-footer-in">
<div><a href="index.html" class="bw-logo">แบรนด์ของคุณ</a><p>สร้างประสบการณ์ที่ดีที่สุดให้ลูกค้า</p></div>
<div><h4>เมนู</h4><nav class="bw-footer-links" data-bw-auto-nav><a href="index.html">หน้าแรก</a><a href="about.html">เกี่ยวกับเรา</a><a href="contact.html">ติดต่อ</a></nav></div>
<div><h4>ติดตามเรา</h4><a href="#">Facebook</a><a href="#">Instagram</a><a href="#">LINE</a></div>
</div><div class="bw-container bw-copy">© 2026 แบรนด์ของคุณ สงวนลิขสิทธิ์</div></footer>""",
        "css": """.bw-footer{background:#111827;color:#d1d5db;padding:60px 0 24px}
.bw-footer-in{display:grid;grid-template-columns:2fr 1fr 1fr;gap:32px}
.bw-footer .bw-logo{color:#fff}
.bw-footer h4{color:#fff;margin-bottom:12px}
.bw-footer a{display:block;color:#d1d5db;text-decoration:none;padding:3px 0}
.bw-footer a:hover{color:#fff}
.bw-copy{border-top:1px solid #374151;margin-top:36px;padding-top:20px;font-size:14px;color:#9ca3af}
@media (max-width:768px){.bw-footer-in{grid-template-columns:1fr}}""",
    },
]

BY_ID = {s["id"]: s for s in SECTIONS}


def block_content(section):
    return f"{section['html']}<style>{section['css']}</style>"


SHARED_IDS = {"navbar", "footer"}


def compose(ids, shared=True):
    """HTML + CSS for a page made of the given sections. With ``shared`` the navbar/footer are left out,
    because the site's shared header/footer are rendered around every page."""
    if shared:
        ids = [i for i in ids if i not in SHARED_IDS]
    html = "\n".join(BY_ID[i]["html"] for i in ids)
    css = "\n".join(BY_ID[i]["css"] for i in dict.fromkeys(ids))
    return html, css


# Starter templates: theme overrides + pages (title, slug, sections).
TEMPLATES = [
    {
        "id": "blank",
        "name": "หน้าว่าง",
        "description": "เริ่มจากศูนย์ ลากวางเองทั้งหมด",
        "preview": "linear-gradient(135deg,#f3f4f6,#e5e7eb)",
        "theme": {},
        "pages": [("หน้าแรก", "home", [])],
    },
    {
        "id": "business",
        "name": "ธุรกิจ / บริษัท",
        "description": "หน้าแรก เกี่ยวกับเรา บริการ และติดต่อ",
        "preview": "linear-gradient(135deg,#7c3aed,#06b6d4)",
        "theme": {},
        "pages": [
            ("หน้าแรก", "home", ["navbar", "hero", "features", "about", "stats", "testimonials", "cta", "footer"]),
            ("เกี่ยวกับเรา", "about", ["navbar", "page-header", "about", "team", "footer"]),
            ("บริการ", "services", ["navbar", "page-header", "features", "pricing", "faq", "footer"]),
            ("ติดต่อ", "contact", ["navbar", "page-header", "contact", "map", "footer"]),
        ],
    },
    {
        "id": "cafe",
        "name": "ร้านอาหาร / คาเฟ่",
        "description": "เมนู แกลเลอรี และแผนที่ร้าน",
        "preview": "linear-gradient(135deg,#b45309,#f59e0b)",
        "theme": {"primary": "#b45309", "secondary": "#f59e0b", "surface": "#fffbeb", "font_heading": "Mitr"},
        "pages": [
            ("หน้าแรก", "home", ["navbar", "hero-center", "menu-list", "gallery", "testimonials", "footer"]),
            ("เกี่ยวกับเรา", "about", ["navbar", "page-header", "about", "footer"]),
            ("ติดต่อ", "contact", ["navbar", "page-header", "contact", "map", "footer"]),
        ],
    },
    {
        "id": "portfolio",
        "name": "พอร์ตโฟลิโอ",
        "description": "โชว์ผลงานและประวัติส่วนตัว",
        "preview": "linear-gradient(135deg,#111827,#ec4899)",
        "theme": {"primary": "#ec4899", "secondary": "#8b5cf6", "surface": "#fdf2f8", "font_heading": "Kanit"},
        "pages": [
            ("หน้าแรก", "home", ["navbar", "hero", "gallery", "stats", "cta", "footer"]),
            ("เกี่ยวกับเรา", "about", ["navbar", "page-header", "about", "text-block", "footer"]),
            ("ติดต่อ", "contact", ["navbar", "page-header", "contact", "footer"]),
        ],
    },
    {
        "id": "landing",
        "name": "หน้าขายสินค้า (Landing)",
        "description": "หน้าเดียวจบ เน้นปิดการขาย",
        "preview": "linear-gradient(135deg,#059669,#22d3ee)",
        "theme": {"primary": "#059669", "secondary": "#0ea5e9", "surface": "#ecfdf5"},
        "pages": [
            ("หน้าแรก", "home", ["navbar", "hero", "features", "video", "pricing", "testimonials", "faq", "contact", "footer"]),
        ],
    },
]

TEMPLATE_BY_ID = {t["id"]: t for t in TEMPLATES}

# Page layouts offered by "เพิ่มหน้า".
PAGE_LAYOUTS = [
    {"id": "blank", "name": "หน้าว่าง", "sections": []},
    {"id": "basic", "name": "เมนู + หัวข้อ + ส่วนท้าย", "sections": ["navbar", "page-header", "text-block", "footer"]},
    {"id": "about", "name": "เกี่ยวกับเรา", "sections": ["navbar", "page-header", "about", "team", "footer"]},
    {"id": "services", "name": "บริการ/ราคา", "sections": ["navbar", "page-header", "features", "pricing", "faq", "footer"]},
    {"id": "contact", "name": "ติดต่อ", "sections": ["navbar", "page-header", "contact", "map", "footer"]},
    {"id": "gallery", "name": "แกลเลอรี", "sections": ["navbar", "page-header", "gallery", "footer"]},
    {"id": "landing", "name": "แลนดิ้งเต็มรูปแบบ", "sections": ["navbar", "hero", "features", "testimonials", "cta", "footer"]},
]
LAYOUT_BY_ID = {p["id"]: p for p in PAGE_LAYOUTS}
