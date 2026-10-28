"""Animations for published pages, set per element as data attributes (no external libraries).

  data-bw-anim="fade-up"        entrance when scrolled into view (see ANIMS); -duration / -delay in ms;
  data-bw-anim-once="false"     replay every time it enters the screen
  data-bw-stagger="120"         on a container: children enter one after another (uses the container's anim)
  data-bw-hover="lift"          hover effect: lift | grow | glow | zoom-img | tilt | shine
  data-bw-count                 count up to the number in the element's text (keeps prefix/suffix, e.g. "1,200+")
  data-bw-typing="คำ1|คำ2"      type the words one after another (loops)
  data-bw-parallax="0.3"        background image moves slower than the page
  .bw-marquee / .bw-carousel    blocks (see sections.py)
Respects prefers-reduced-motion. The html.bw-anim class is set by a tiny inline script in <head>, so content
is never hidden when JavaScript is off.
"""

ANIMS = ["fade", "fade-up", "fade-down", "fade-left", "fade-right", "zoom-in", "zoom-out", "flip-up", "blur", "rise", "pop"]

ANIM_HEAD = ("<script>if(!matchMedia('(prefers-reduced-motion: reduce)').matches)"
             "document.documentElement.classList.add('bw-anim')</script>")

ANIM_CSS = """
html.bw-anim,html.bw-anim body{overflow-x:clip}
.bw-anim [data-bw-anim]{opacity:0;transition-property:opacity,transform,filter;transition-duration:var(--bw-d,700ms);transition-delay:var(--bw-delay,0ms);transition-timing-function:cubic-bezier(.2,.7,.2,1);will-change:opacity,transform}
.bw-anim [data-bw-anim="fade-up"]{transform:translateY(32px)}
.bw-anim [data-bw-anim="fade-down"]{transform:translateY(-32px)}
.bw-anim [data-bw-anim="fade-left"]{transform:translateX(40px)}
.bw-anim [data-bw-anim="fade-right"]{transform:translateX(-40px)}
.bw-anim [data-bw-anim="zoom-in"]{transform:scale(.88)}
.bw-anim [data-bw-anim="zoom-out"]{transform:scale(1.12)}
.bw-anim [data-bw-anim="flip-up"]{transform:perspective(800px) rotateX(18deg) translateY(20px);transform-origin:50% 100%}
.bw-anim [data-bw-anim="blur"]{filter:blur(12px)}
.bw-anim [data-bw-anim="rise"]{transform:translateY(80px)}
.bw-anim [data-bw-anim="pop"]{transform:scale(.6);transition-timing-function:cubic-bezier(.3,1.6,.5,1)}
.bw-anim [data-bw-anim].bw-in{opacity:1;transform:none;filter:none}
.bw-anim [data-bw-stagger]{opacity:1!important;transform:none!important;filter:none!important}
[data-bw-hover]{transition:transform .25s ease,box-shadow .25s ease,filter .25s ease}
[data-bw-hover="lift"]:hover{transform:translateY(-6px);box-shadow:0 22px 40px -22px rgba(0,0,0,.45)}
[data-bw-hover="grow"]:hover{transform:scale(1.04)}
[data-bw-hover="glow"]:hover{box-shadow:0 0 0 3px color-mix(in srgb,var(--bw-primary) 30%,transparent),0 18px 40px -16px var(--bw-primary)}
[data-bw-hover="zoom-img"]{overflow:hidden}
[data-bw-hover="zoom-img"] img{transition:transform .5s ease}
[data-bw-hover="zoom-img"]:hover img{transform:scale(1.08)}
[data-bw-hover="tilt"]{transform-style:preserve-3d}
[data-bw-hover="shine"]{position:relative;overflow:hidden}
[data-bw-hover="shine"]::after{content:"";position:absolute;inset:0;background:linear-gradient(110deg,transparent 30%,rgba(255,255,255,.45) 50%,transparent 70%);transform:translateX(-120%);transition:transform .7s ease;pointer-events:none}
[data-bw-hover="shine"]:hover::after{transform:translateX(120%)}
[data-bw-typing]::after{content:"|";margin-left:2px;animation:bw-caret 1s steps(1) infinite;color:var(--bw-primary)}
@keyframes bw-caret{50%{opacity:0}}
.bw-marquee{overflow:hidden;-webkit-mask-image:linear-gradient(90deg,transparent,#000 8%,#000 92%,transparent);mask-image:linear-gradient(90deg,transparent,#000 8%,#000 92%,transparent)}
.bw-marquee-track{display:flex;gap:56px;width:max-content;animation:bw-marquee var(--bw-speed,30s) linear infinite}
.bw-marquee:hover .bw-marquee-track{animation-play-state:paused}
@keyframes bw-marquee{to{transform:translateX(-50%)}}
.bw-carousel{position:relative}
.bw-carousel-track{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;scroll-behavior:smooth;scrollbar-width:none;border-radius:var(--bw-radius)}
.bw-carousel-track::-webkit-scrollbar{display:none}
.bw-carousel-track>*{flex:0 0 100%;scroll-snap-align:start}
.bw-carousel-btn{position:absolute;top:50%;transform:translateY(-50%);width:44px;height:44px;border-radius:50%;border:0;background:rgba(255,255,255,.9);color:#111;cursor:pointer;font-size:20px;box-shadow:0 6px 18px -8px rgba(0,0,0,.5);z-index:2}
.bw-carousel-btn.prev{left:14px}.bw-carousel-btn.next{right:14px}
.bw-carousel-dots{display:flex;justify-content:center;gap:8px;margin-top:14px}
.bw-carousel-dots button{width:9px;height:9px;border-radius:50%;border:0;background:#d1d5db;cursor:pointer;padding:0}
.bw-carousel-dots button.on{background:var(--bw-primary);width:24px;border-radius:9px}
@media (prefers-reduced-motion:reduce){.bw-marquee-track{animation:none}[data-bw-hover]{transition:none}}
"""

ANIM_JS = r"""
  // Animations: entrance on scroll, stagger, count-up, typing, parallax, tilt, carousel.
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  document.querySelectorAll('[data-bw-stagger]').forEach(function(box){
    var step = parseInt(box.getAttribute('data-bw-stagger'), 10) || 120;
    var anim = box.getAttribute('data-bw-anim') || 'fade-up';
    var base = parseInt(box.getAttribute('data-bw-anim-delay'), 10) || 0;
    Array.prototype.forEach.call(box.children, function(ch, i){
      if (!ch.hasAttribute('data-bw-anim')) ch.setAttribute('data-bw-anim', anim);
      ch.style.setProperty('--bw-delay', (base + i * step) + 'ms');
      if (box.hasAttribute('data-bw-anim-duration')) ch.setAttribute('data-bw-anim-duration', box.getAttribute('data-bw-anim-duration'));
    });
  });
  var animated = document.querySelectorAll('[data-bw-anim]:not([data-bw-stagger])');
  animated.forEach(function(el){
    var d = el.getAttribute('data-bw-anim-duration'), w = el.getAttribute('data-bw-anim-delay');
    if (d) el.style.setProperty('--bw-d', d + 'ms');
    if (w && !el.style.getPropertyValue('--bw-delay')) el.style.setProperty('--bw-delay', w + 'ms');
  });
  function countUp(el){
    if (el.dataset.bwCounted) return; el.dataset.bwCounted = '1';
    var m = (el.textContent || '').match(/^(\D*)([\d,]+(?:\.\d+)?)(.*)$/);
    if (!m) return;
    var pre = m[1], target = parseFloat(m[2].replace(/,/g, '')), post = m[3], dec = (m[2].split('.')[1] || '').length;
    var dur = parseInt(el.getAttribute('data-bw-count'), 10) || 1600, t0 = null;
    function frame(t){ if (!t0) t0 = t; var p = Math.min(1, (t - t0) / dur), v = target * (1 - Math.pow(1 - p, 3));
      el.textContent = pre + v.toLocaleString('en-US', {minimumFractionDigits: dec, maximumFractionDigits: dec}) + post;
      if (p < 1) requestAnimationFrame(frame); }
    requestAnimationFrame(frame);
  }
  function typing(el){
    if (el.dataset.bwTyping) return; el.dataset.bwTyping = '1';
    var words = (el.getAttribute('data-bw-typing') || el.textContent).split('|').map(function(s){ return s.trim(); }).filter(Boolean);
    var wi = 0, ci = 0, del = false;
    (function tick(){ var w = words[wi % words.length];
      el.textContent = w.slice(0, ci);
      if (!del && ci < w.length) { ci++; setTimeout(tick, 70); }
      else if (!del) { del = words.length > 1; setTimeout(tick, 1600); }
      else if (ci > 0) { ci--; setTimeout(tick, 35); }
      else { del = false; wi++; setTimeout(tick, 300); } })();
  }
  var specials = document.querySelectorAll('[data-bw-count],[data-bw-typing]');
  if ('IntersectionObserver' in window && !reduce) {
    var io = new IntersectionObserver(function(entries){
      entries.forEach(function(en){
        var el = en.target;
        if (en.isIntersecting) {
          if (el.hasAttribute('data-bw-anim')) el.classList.add('bw-in');
          if (el.hasAttribute('data-bw-count')) countUp(el);
          if (el.hasAttribute('data-bw-typing')) typing(el);
          if (el.getAttribute('data-bw-anim-once') !== 'false') io.unobserve(el);
        } else if (el.getAttribute('data-bw-anim-once') === 'false') el.classList.remove('bw-in');
      });
    }, {threshold: 0.15, rootMargin: '0px 0px -40px 0px'});
    animated.forEach(function(el){ io.observe(el); });
    specials.forEach(function(el){ io.observe(el); });
  } else {
    animated.forEach(function(el){ el.classList.add('bw-in'); });
    document.querySelectorAll('[data-bw-typing]').forEach(function(el){ el.textContent = (el.getAttribute('data-bw-typing') || el.textContent).split('|')[0]; });
  }
  if (!reduce) {
    var par = document.querySelectorAll('[data-bw-parallax]');
    if (par.length) {
      var onPar = function(){ par.forEach(function(el){ var r = el.getBoundingClientRect(), k = parseFloat(el.getAttribute('data-bw-parallax')) || 0.3;
        el.style.backgroundPosition = 'center ' + Math.round(-r.top * k) + 'px'; }); };
      window.addEventListener('scroll', onPar, {passive: true}); onPar();
    }
    document.querySelectorAll('[data-bw-hover="tilt"]').forEach(function(el){
      el.addEventListener('mousemove', function(e){ var r = el.getBoundingClientRect(), x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
        el.style.transform = 'perspective(700px) rotateY(' + (x * 10) + 'deg) rotateX(' + (-y * 10) + 'deg)'; });
      el.addEventListener('mouseleave', function(){ el.style.transform = ''; });
    });
  }
  document.querySelectorAll('.bw-carousel').forEach(function(c){
    var track = c.querySelector('.bw-carousel-track'); if (!track) return;
    var slides = track.children, n = slides.length, dots = c.querySelector('.bw-carousel-dots'), idx = 0;
    if (dots && !dots.children.length) for (var i = 0; i < n; i++) { (function(i){ var b = document.createElement('button'); b.setAttribute('aria-label', 'สไลด์ ' + (i + 1));
      b.addEventListener('click', function(){ go(i); }); dots.appendChild(b); })(i); }
    function go(i){ idx = (i + n) % n; track.scrollTo({left: track.clientWidth * idx}); mark(); }
    function mark(){ if (dots) Array.prototype.forEach.call(dots.children, function(b, i){ b.classList.toggle('on', i === idx); }); }
    track.addEventListener('scroll', function(){ idx = Math.round(track.scrollLeft / track.clientWidth); mark(); }, {passive: true});
    var p = c.querySelector('.prev'), nx = c.querySelector('.next');
    if (p) p.addEventListener('click', function(){ go(idx - 1); });
    if (nx) nx.addEventListener('click', function(){ go(idx + 1); });
    var auto = parseInt(c.getAttribute('data-bw-autoplay'), 10);
    if (auto && !reduce) { var timer = setInterval(function(){ go(idx + 1); }, auto);
      c.addEventListener('mouseenter', function(){ clearInterval(timer); }); }
    mark();
  });
"""
