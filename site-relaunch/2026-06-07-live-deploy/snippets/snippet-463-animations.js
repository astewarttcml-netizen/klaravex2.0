/* Klaravex — Site-wide animation layer (defensive: never hides content if JS fails) */
(function(){
  'use strict';
  if (window.__kxAnim) return; window.__kxAnim = true;

  // Respect reduced-motion
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  var doc = document.documentElement;

  // ── Inject styles ──
  var css = ''
  + '.kx-anim-on .kx-reveal{opacity:0;transform:translateY(22px);transition:opacity .7s cubic-bezier(.16,1,.3,1),transform .7s cubic-bezier(.16,1,.3,1)}'
  + '.kx-anim-on .kx-reveal.kx-in{opacity:1;transform:none}'
  /* page load fade */
  + '.kx-anim-on body{animation:kxFadeIn .5s ease both}'
  + '@keyframes kxFadeIn{from{opacity:0}to{opacity:1}}'
  /* hover micro-interactions */
  + '.kx-anim-on a.wp-block-button__link,.kx-anim-on button,.kx-anim-on .wp-block-button__link{transition:transform .18s ease,box-shadow .18s ease,filter .18s ease}'
  + '.kx-anim-on a.wp-block-button__link:hover,.kx-anim-on .wp-block-button__link:hover{transform:translateY(-2px);box-shadow:0 8px 28px rgba(99,102,241,0.35)}'
  + '.kx-anim-on .wp-block-column:hover,.kx-anim-on .wp-block-group.has-background:hover{transition:transform .25s ease}'
  + '@media(prefers-reduced-motion:reduce){.kx-anim-on *{animation:none!important;transition:none!important}}';
  var st = document.createElement('style'); st.id = 'kx-anim-css'; st.textContent = css;
  document.head.appendChild(st);

  doc.classList.add('kx-anim-on');

  function ready(fn){ if(document.readyState!=='loading') fn(); else document.addEventListener('DOMContentLoaded', fn); }

  ready(function(){
    // ── Tag reveal targets (major content blocks, not everything) ──
    var sel = '.entry-content > *, .wp-block-columns, .wp-block-group, .wp-block-heading, section > .wp-block-group';
    var nodes = Array.prototype.slice.call(document.querySelectorAll(sel));
    // de-dupe nested: only tag top-level-ish blocks
    var seen = [];
    nodes.forEach(function(n){
      if (n.closest('.kx-reveal')) return;           // skip if inside an already-tagged reveal
      if (n.offsetHeight === 0) return;               // skip hidden
      n.classList.add('kx-reveal'); seen.push(n);
    });

    // ── IntersectionObserver reveal ──
    var io;
    if ('IntersectionObserver' in window){
      io = new IntersectionObserver(function(entries){
        entries.forEach(function(e){ if(e.isIntersecting){ e.target.classList.add('kx-in'); io.unobserve(e.target); }});
      }, { threshold: 0.08, rootMargin: '0px 0px -5% 0px' });
      seen.forEach(function(n){ io.observe(n); });
    } else {
      seen.forEach(function(n){ n.classList.add('kx-in'); });
    }

    // SAFETY: reveal anything still hidden after 2.5s no matter what
    setTimeout(function(){
      document.querySelectorAll('.kx-reveal:not(.kx-in)').forEach(function(n){ n.classList.add('kx-in'); });
    }, 2500);

    // ── Count-up for numeric stats ──
    function countUp(el){
      var raw = el.getAttribute('data-kx-num');
      var suffix = el.getAttribute('data-kx-suffix') || '';
      var target = parseFloat(raw); if (isNaN(target)) return;
      var dur = 1100, start = null;
      function step(ts){
        if(!start) start = ts;
        var p = Math.min((ts-start)/dur, 1);
        var ease = 1 - Math.pow(1-p, 3);
        var val = Math.round(target * ease);
        el.textContent = val + suffix;
        if(p<1) requestAnimationFrame(step); else el.textContent = raw + suffix;
      }
      requestAnimationFrame(step);
    }
    // Auto-detect pure-number stat headings like "89%", "32", "15+"
    var statNodes = document.querySelectorAll('h2,h3,.wp-block-heading,strong');
    var statObs = ('IntersectionObserver' in window) ? new IntersectionObserver(function(es){
      es.forEach(function(e){ if(e.isIntersecting){ countUp(e.target); statObs.unobserve(e.target); }});
    }, { threshold: 0.6 }) : null;
    Array.prototype.slice.call(statNodes).forEach(function(el){
      var m = (el.textContent||'').trim().match(/^(\d{1,3})(%|\+)?$/);
      if (!m) return;
      el.setAttribute('data-kx-num', m[1]);
      el.setAttribute('data-kx-suffix', m[2]||'');
      el.textContent = '0' + (m[2]||'');
      if (statObs) statObs.observe(el); else countUp(el);
    });
  });
})();
