/**
 * Klaravex Personal — Main JS
 * Scroll reveal · mobile nav · contact form
 */
document.addEventListener('DOMContentLoaded', () => {

  /* ── SCROLL REVEAL ── */
  const obs = new IntersectionObserver(entries => {
    entries.forEach(e => {
      if (e.isIntersecting) { e.target.classList.add('visible'); obs.unobserve(e.target); }
    });
  }, { threshold: 0.1 });
  document.querySelectorAll('.reveal').forEach(el => obs.observe(el));

  /* ── MOBILE NAV ── */
  const toggle = document.querySelector('.nav-toggle');
  const menu   = document.querySelector('.nav-menu');
  if (toggle && menu) {
    toggle.addEventListener('click', () => {
      const open = menu.classList.toggle('nav-menu--open');
      toggle.setAttribute('aria-expanded', open);
    });
    menu.querySelectorAll('a').forEach(a => {
      a.addEventListener('click', () => {
        menu.classList.remove('nav-menu--open');
        toggle.setAttribute('aria-expanded', 'false');
      });
    });
  }

  /* ── STICKY NAV SHADOW ── */
  const nav = document.querySelector('.site-nav');
  if (nav) {
    window.addEventListener('scroll', () => {
      nav.classList.toggle('nav--scrolled', window.scrollY > 20);
    }, { passive: true });
  }

  /* ── CTA → KLARAVEX AI CHAT ── */
  // Any element with data-chat-open starts the troubleshooting chat.
  // Falls back to KvxChat.open(), then to plain anchor scroll to #cta.
  document.addEventListener('click', (e) => {
    const trigger = e.target.closest('[data-chat-open]');
    if (!trigger) return;
    if (typeof window.klaravexStartIntake === 'function') {
      e.preventDefault();
      window.klaravexStartIntake(trigger.getAttribute('data-chat-open') || 'booking');
    } else if (window.KvxChat && typeof window.KvxChat.open === 'function') {
      e.preventDefault();
      window.KvxChat.open();
    }
  });

  /* ── CONTACT FORM ── */
  const form = document.getElementById('kvxp-contact-form');
  if (form) {
    form.addEventListener('submit', async e => {
      e.preventDefault();
      const btn = form.querySelector('[type="submit"]');
      const msg = document.getElementById('kvxp-form-message');
      btn.disabled = true;
      btn.textContent = 'Sending…';
      const data = new FormData(form);
      data.append('action', 'kvxp_contact');
      data.append('nonce', kvxpData.nonce);
      try {
        const res  = await fetch(kvxpData.ajaxUrl, { method: 'POST', body: data });
        const json = await res.json();
        msg.textContent = json.data.message;
        msg.className   = json.success ? 'form-success' : 'form-error';
        if (json.success) form.reset();
      } catch {
        msg.textContent = 'Something went wrong. Please email us directly.';
        msg.className   = 'form-error';
      }
      btn.disabled = false;
      btn.textContent = 'Send message';
    });
  }

});

/* ── MOBILE NAV STYLES ── */
const s = document.createElement('style');
s.textContent = `
  @media (max-width: 900px) {
    .nav-menu--open {
      display: flex !important;
      flex-direction: column;
      position: absolute;
      top: 62px; left: 0; right: 0;
      background: rgba(250,250,248,0.97);
      backdrop-filter: blur(16px);
      border-bottom: 1px solid rgba(28,28,26,0.1);
      padding: 16px 24px 24px;
      gap: 4px !important; z-index: 99;
    }
    .nav-menu--open a { padding: 10px 0; font-size: 15px !important; border-bottom: 1px solid rgba(28,28,26,0.07); }
    .nav-menu--open li:last-child a { border-bottom: none; }
    .nav--scrolled { box-shadow: 0 4px 24px rgba(28,28,26,0.08); }
    .form-success { color: #065F46; background: #D1FAE5; padding: 12px 16px; border-radius: 8px; font-size: 14px; font-weight: 500; margin-top: 12px; }
    .form-error   { color: #991B1B; background: #FEE2E2; padding: 12px 16px; border-radius: 8px; font-size: 14px; font-weight: 500; margin-top: 12px; }
  }
  .form-success { color: #065F46; background: #D1FAE5; padding: 12px 16px; border-radius: 8px; font-size: 14px; font-weight: 500; margin-top: 12px; }
  .form-error   { color: #991B1B; background: #FEE2E2; padding: 12px 16px; border-radius: 8px; font-size: 14px; font-weight: 500; margin-top: 12px; }
`;
document.head.appendChild(s);
