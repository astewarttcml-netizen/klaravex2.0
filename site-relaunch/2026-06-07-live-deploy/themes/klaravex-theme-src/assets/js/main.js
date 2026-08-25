/**
 * Klaravex — Main JS
 * Scroll reveal · meter animation · mobile nav · smooth scroll
 */

document.addEventListener('DOMContentLoaded', () => {

  /* ── SCROLL REVEAL ── */
  const revealObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        revealObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });

  document.querySelectorAll('.reveal').forEach(el => revealObserver.observe(el));

  /* ── METER FILL ANIMATION ── */
  const meterFill = document.getElementById('meter-fill');
  if (meterFill) {
    const meterObserver = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          meterFill.classList.add('animate');
          meterObserver.unobserve(entry.target);
        }
      });
    }, { threshold: 0.5 });
    meterObserver.observe(document.getElementById('meter') || meterFill);
  }

  /* ── MOBILE NAV TOGGLE ── */
  const toggle = document.querySelector('.nav-toggle');
  const menu   = document.querySelector('.nav-menu');
  if (toggle && menu) {
    toggle.addEventListener('click', () => {
      const open = menu.classList.toggle('nav-menu--open');
      toggle.setAttribute('aria-expanded', open);
    });
    // Close on nav link click
    menu.querySelectorAll('a').forEach(a => {
      a.addEventListener('click', () => {
        menu.classList.remove('nav-menu--open');
        toggle.setAttribute('aria-expanded', 'false');
      });
    });
  }

  /* ── STICKY NAV SHADOW ON SCROLL ── */
  const nav = document.querySelector('.site-nav');
  if (nav) {
    window.addEventListener('scroll', () => {
      nav.classList.toggle('nav-scrolled', window.scrollY > 20);
    }, { passive: true });
  }

  /* ── PORTAL MOCK: HOVER INTERACTIONS ── */
  document.querySelectorAll('.mock-nav-item').forEach(item => {
    item.addEventListener('mouseenter', () => {
      document.querySelectorAll('.mock-nav-item').forEach(i => i.classList.remove('active'));
      item.classList.add('active');
    });
  });

});

/* ── MOBILE NAV OPEN STYLES (injected) ── */
const mobileNavStyle = document.createElement('style');
mobileNavStyle.textContent = `
  @media (max-width: 960px) {
    .nav-menu--open {
      display: flex !important;
      flex-direction: column;
      position: absolute;
      top: 62px; left: 0; right: 0;
      background: rgba(6,8,14,0.97);
      backdrop-filter: blur(20px);
      border-bottom: 1px solid rgba(240,244,255,0.08);
      padding: 16px 24px 24px;
      gap: 4px !important;
      z-index: 99;
    }
    .nav-menu--open a {
      padding: 10px 0;
      font-size: 15px !important;
      border-bottom: 1px solid rgba(240,244,255,0.06);
    }
    .nav-menu--open li:last-child a { border-bottom: none; }
    .nav-scrolled { box-shadow: 0 4px 24px rgba(0,0,0,0.4); }
  }
`;
document.head.appendChild(mobileNavStyle);
