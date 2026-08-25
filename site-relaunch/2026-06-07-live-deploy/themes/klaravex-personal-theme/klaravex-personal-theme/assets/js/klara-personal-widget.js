/**
 * klara-personal-white-widget.js
 * ───────────────────
 * Self-contained floating chat + contact widget for personal.klaravex.com (consumer, white theme).
 *
 * Two tabs:
 *   Chat       — AI conversation with Klaravex AI
 *   Contact Us — Name / Email / Phone / Message form → Klaravex lead pipeline
 *
 * API endpoints:
 *   Chat:    POST https://api.klaravex.com/api/v1/chat/message
 *   Contact: POST https://api.klaravex.com/api/v1/chat/message  (channel: contact_form)
 *
 * Embed in WordPress:
 *   wp_enqueue_script('klara-chat', get_template_directory_uri() . '/js/klara-personal-white-widget.js', [], '2.0', true);
 *
 * Optional config before loading:
 *   <script>window.LokiConfig = { apiBase: 'https://api.klaravex.com' };<\/script>
 */
(function () {
    'use strict';

    // ── Page suppression ─────────────────────────────────────────────────────
    const _path = window.location.pathname || '';
    const _bodyCls = (typeof document !== 'undefined' && document.body && document.body.className) || '';
    const _suppressPaths = ['/portal/'];
    const _suppressBodyClasses = ['page-id-138'];
    if (_suppressPaths.some(function (p) { return _path === p || _path.indexOf(p) === 0; })) return;
    if (_suppressBodyClasses.some(function (c) { return _bodyCls.indexOf(c) !== -1; })) return;

    // ── Language ─────────────────────────────────────────────────────────────
    const pageLang = 'en';

    // ── i18n ──────────────────────────────────────────────────────────────────
    const I18N = {
        en: {
            tabChat:           'Chat',
            tabContact:        'Contact Us',
            welcomeMessage:    'Hi 👋 I\'m Klara, your friendly tech helper. Something broken, want to stay safe online, or just need a hand? Tell me what\'s going on.',
            placeholder:       'Type your message…',
            gdprText:          'I agree to the processing of my data per the <a href="/privacy-policy" target="_blank">Privacy Policy</a>.',
            headerStatus:      'Online · replies instantly',
            trustRibbon:       '<strong>Patient, plain-English help</strong> — no judgment, no jargon.',
            chipBook:          'Book a session',
            chipPricing:       'See pricing',
            chipProblem:       "Something's broken",
            chipHuman:         'Talk to a person',
            footNote:          'Powered by <strong>Klaravex AI</strong> · Always labeled, never pretending to be human',
            openLabel:         'Open chat',
            closeLabel:        'Close chat',
            toastMessage:      'Got a question about pricing or setup? I\'m online.',
            toastDismiss:      'Dismiss',
            sendLabel:         'Send',
            inputLabel:        'Enter your message',
            errorMsg:          'Sorry, there was a technical error. Please try again or contact us at hello@klaravex.com.',
            fallbackReply:     'Thank you for your message. We\'ll be in touch shortly.',
            // Contact form
            contactHeading:    'Send us a message',
            contactSubtitle:   'We typically respond within one business day.',
            labelName:         'Full name *',
            labelEmail:        'Email address *',
            labelPhone:        'Phone (optional)',
            labelMessage:      'How can we help? *',
            placeholderName:   'Jane Smith',
            placeholderEmail:  'jane@company.com',
            placeholderPhone:  '+1 …',
            placeholderMsg:    'Describe your IT challenge…',
            submitBtn:         'Send Message',
            sending:           'Sending…',
            successHeading:    'Message sent!',
            successBody:       'Thanks for reaching out. Our team will review your inquiry and get back within one business day.',
            errorContact:      'Something went wrong. Please email us directly at hello@klaravex.com.',
            validName:         'Please enter your name.',
            validEmail:        'Please enter a valid email address.',
            validMessage:      'Please enter a message.',
            validGdpr:         'Please accept the privacy policy to continue.',
        },
    };
    const t = I18N[pageLang];

    // ── Config ───────────────────────────────────────────────────────────────
    // Auto-detect consumer support context from URL path.
    // Pages under /personal/ (e.g. /personal/it-help/) route to the consumer pipeline.
    // Can be overridden by window.LokiConfig = { source: '...' }.
    const _autoSource = (
        _path === '/personal/it-help/' ||

        _path.indexOf('/personal/support') === 0
    ) ? 'personal' : 'chat';

    const cfg = Object.assign({
        apiBase:        'https://llm.klaravex.com',
        primaryColor:   '#4F46E5',
        bubbleSize:     62,
        widgetWidth:    390,
        widgetHeight:   600,
        gdprRequired:   true,
        storageKey:     'loki_session',
        toastDelayMs:   8000,
        toastStorageKey:'loki_toast_shown',
        wpProxyUrl:     '/wp-json/loki/v1/chat',
        source:         'personal',
    }, window.LokiConfig || {});

    // ── Klaravex AI design tokens ────────────────────────────────────────────
    const KX = {
        bg:'#FFFFFF', surface:'#FFFFFF', lift:'#F5F3EE', lift2:'#ECE7DD',
        white:'#1C1C1A', dim:'rgba(28,28,26,0.62)', dim2:'rgba(28,28,26,0.42)',
        border:'rgba(28,28,26,0.10)', indigo:'#4F46E5', indigo2:'#6366F1',
        violet:'#7C3AED', green:'#10B981',
    };
    // AI assistant display name (user-facing). Internal IDs stay loki-* for backend compat.
    const AI_NAME = 'Klara';

    const API_URL   = cfg.apiBase + '/api/v1/chat/message';
    const START_URL = cfg.apiBase + '/api/v1/chat/start';
    const PROXY_URL = cfg.wpProxyUrl || null;
    const QUAL_TAG_RE = /\s*\[(QUALIFIED|NEEDS_MORE_INFO|NOT_A_FIT)\]/g;

    const _LOKI_FALLBACK_PHRASES = [
        "thank you for your message. we'll be in touch",

    ];

    // ── State ────────────────────────────────────────────────────────────────
    let open          = false;
    let activeTab     = 'chat';       // 'chat' | 'contact'
    let gdprConsented = false;
    let sessionToken  = sessionStorage.getItem(cfg.storageKey) || null;
    let sending       = false;
    let contactSent   = false;

    // ── Styles (Klaravex AI — dark / indigo glow) ────────────────────────────
    const css = `
    @import url('https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=Inter:wght@400;500;600&display=swap');

    #loki-chat-bubble {
        position: fixed; bottom: 90px; right: 24px;
        width: ${cfg.bubbleSize}px; height: ${cfg.bubbleSize}px;
        border-radius: 50%;
        background: linear-gradient(135deg, ${KX.indigo}, ${KX.violet});
        box-shadow: 0 0 0 1px rgba(99,102,241,0.4), 0 8px 32px rgba(99,102,241,0.4), 0 0 40px rgba(99,102,241,0.25);
        cursor: pointer; display: flex; align-items: center; justify-content: center;
        z-index: 999998; transition: transform 0.25s cubic-bezier(.16,1,.3,1), box-shadow 0.25s;
        border: none; outline: none;
    }
    #loki-chat-bubble:hover { transform: translateY(-3px) scale(1.04); box-shadow: 0 0 0 1px rgba(99,102,241,0.6), 0 12px 40px rgba(99,102,241,0.5), 0 0 56px rgba(99,102,241,0.35); }
    #loki-chat-bubble svg { width: 26px; height: 26px; fill: #fff; }
    #loki-bubble-ping {
        position: absolute; top: 0; right: 0;
        width: 15px; height: 15px; border-radius: 50%;
        background: ${KX.green}; border: 3px solid ${KX.bg};
        box-shadow: 0 0 8px rgba(34,197,94,0.7);
    }

    #loki-toast {
        position: fixed; bottom: ${90 + cfg.bubbleSize + 14}px; right: 24px;
        max-width: 260px;
        background: ${KX.surface};
        border: 1px solid ${KX.border}; border-radius: 14px;
        box-shadow: 0 0 0 1px rgba(99,102,241,0.12), 0 12px 32px rgba(0,0,0,0.18);
        padding: 12px 32px 12px 14px;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: 13px; line-height: 1.4; color: ${KX.white};
        cursor: pointer;
        z-index: 999997;
        transform: translateY(12px); opacity: 0; pointer-events: none;
        transition: opacity 0.3s ease, transform 0.3s ease;
    }
    #loki-toast.loki-toast-visible { opacity: 1; transform: translateY(0); pointer-events: all; }
    #loki-toast strong { color: ${KX.indigo2}; }
    #loki-toast-close {
        position: absolute; top: 6px; right: 8px;
        background: none; border: none; cursor: pointer;
        color: ${KX.dim}; font-size: 16px; line-height: 1; padding: 4px;
    }
    #loki-toast-close:hover { color: ${KX.white}; }

    #loki-chat-window {
        position: fixed; bottom: ${90 + cfg.bubbleSize + 14}px; right: 24px;
        width: ${cfg.widgetWidth}px; height: ${cfg.widgetHeight}px; max-height: 84vh;
        background: ${KX.surface};
        border: 1px solid ${KX.border}; border-radius: 20px;
        box-shadow: 0 0 0 1px rgba(99,102,241,0.12), 0 32px 80px rgba(28,28,26,0.16), 0 0 80px rgba(99,102,241,0.1);
        display: flex; flex-direction: column;
        z-index: 999999;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: 14px; overflow: hidden;
        transform: translateY(20px); opacity: 0; pointer-events: none;
        transition: opacity 0.22s ease, transform 0.22s ease;
    }
    #loki-chat-window.loki-open { opacity: 1; transform: translateY(0); pointer-events: all; }

    /* Header */
    #loki-header {
        background: linear-gradient(135deg, rgba(99,102,241,0.14), rgba(124,58,237,0.06)), ${KX.bg};
        color: ${KX.white}; border-bottom: 1px solid ${KX.border};
        padding: 16px; display: flex; align-items: center; gap: 12px; flex-shrink: 0;
    }
    #loki-header-avatar {
        width: 42px; height: 42px; border-radius: 12px; position: relative;
        background: linear-gradient(135deg, ${KX.indigo}, ${KX.violet});
        display: flex; align-items: center; justify-content: center;
        box-shadow: 0 0 20px rgba(99,102,241,0.4);
    }
    #loki-header-avatar svg { width: 22px; height: 22px; fill: #fff; }
    #loki-header-avatar::after {
        content: ''; position: absolute; bottom: -2px; right: -2px;
        width: 13px; height: 13px; border-radius: 50%;
        background: ${KX.green}; border: 2.5px solid ${KX.bg};
        box-shadow: 0 0 6px rgba(34,197,94,0.6);
        animation: loki-pulse 2s infinite;
    }
    @keyframes loki-pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
    #loki-header-info { flex: 1; }
    #loki-header-name {
        font-family: 'Syne', sans-serif; font-weight: 800; font-size: 16px;
        letter-spacing: -0.02em; display: flex; align-items: center; gap: 7px;
    }
    #loki-header-name .loki-ai-tag {
        font-family: 'Inter', sans-serif; font-size: 9px; font-weight: 700;
        letter-spacing: 0.06em; text-transform: uppercase;
        background: rgba(99,102,241,0.2); color: ${KX.indigo2};
        padding: 2px 7px; border-radius: 5px;
    }
    #loki-header-status { font-size: 11px; color: ${KX.dim}; margin-top: 2px; }
    #loki-close-btn {
        background: rgba(28,28,26,0.06); border: 1px solid ${KX.border};
        width: 30px; height: 30px; border-radius: 8px; cursor: pointer;
        color: ${KX.dim}; line-height: 1; font-size: 18px;
        display: flex; align-items: center; justify-content: center;
        transition: all 0.15s;
    }
    #loki-close-btn:hover { background: rgba(28,28,26,0.1); color: ${KX.white}; }

    /* Trust ribbon */
    #loki-trust-ribbon {
        padding: 8px 16px; background: rgba(99,102,241,0.06);
        border-bottom: 1px solid ${KX.border};
        font-size: 11px; color: ${KX.dim}; flex-shrink: 0;
        display: flex; align-items: center; gap: 7px;
    }
    #loki-trust-ribbon svg { width: 13px; height: 13px; fill: ${KX.indigo2}; flex-shrink: 0; }
    #loki-trust-ribbon strong { color: ${KX.white}; font-weight: 600; }

    /* Tab bar */
    #loki-tab-bar {
        display: flex; border-bottom: 1px solid ${KX.border}; flex-shrink: 0; background: ${KX.surface};
    }
    .loki-tab {
        flex: 1; padding: 11px 0; background: none; border: none;
        border-bottom: 2px solid transparent; cursor: pointer;
        font-size: 13px; font-weight: 500; color: ${KX.dim};
        font-family: inherit; transition: color 0.15s, border-color 0.15s;
    }
    .loki-tab:hover { color: ${KX.white}; }
    .loki-tab.loki-tab-active { color: ${KX.white}; border-bottom-color: ${KX.indigo}; }

    /* Chat pane */
    #loki-chat-pane { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
    #loki-messages {
        flex: 1; overflow-y: auto; padding: 18px 16px;
        display: flex; flex-direction: column; gap: 12px; scroll-behavior: smooth;
    }
    #loki-messages::-webkit-scrollbar { width: 5px; }
    #loki-messages::-webkit-scrollbar-thumb { background: rgba(28,28,26,0.1); border-radius: 3px; }

    .loki-msg {
        max-width: 84%; padding: 11px 14px; border-radius: 14px;
        line-height: 1.55; word-break: break-word; font-size: 13.5px;
    }
    .loki-msg.loki-bot {
        background: ${KX.lift}; color: ${KX.white};
        border: 1px solid ${KX.border};
        align-self: flex-start; border-bottom-left-radius: 4px;
    }
    .loki-msg.loki-user {
        background: linear-gradient(135deg, ${KX.indigo}, ${KX.violet}); color: #fff;
        align-self: flex-end; border-bottom-right-radius: 4px;
        box-shadow: 0 4px 16px rgba(99,102,241,0.3);
    }
    .loki-msg.loki-bot strong { color: ${KX.white}; font-weight: 600; }
    .loki-typing { display: flex; align-items: center; gap: 4px; padding: 13px 14px; }
    .loki-typing span {
        width: 6px; height: 6px; border-radius: 50%; background: ${KX.dim}; display: inline-block;
        animation: loki-bounce 1.4s infinite ease-in-out;
    }
    .loki-typing span:nth-child(2) { animation-delay: 0.2s; }
    .loki-typing span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes loki-bounce {
        0%, 60%, 100% { transform: translateY(0);    opacity: 0.3; }
        30%           { transform: translateY(-3px); opacity: 1;   }
    }

    /* Quick-reply chips */
    #loki-quick-replies {
        display: flex; flex-wrap: wrap; gap: 7px; padding: 0 16px 14px;
    }
    .loki-chip {
        font-family: inherit; font-size: 12px; font-weight: 500;
        background: ${KX.lift}; border: 1px solid ${KX.border};
        color: ${KX.white}; padding: 8px 13px; border-radius: 20px;
        cursor: pointer; transition: all 0.2s;
        display: inline-flex; align-items: center; gap: 6px;
    }
    .loki-chip:hover { border-color: rgba(99,102,241,0.5); background: ${KX.lift2}; transform: translateY(-1px); }
    .loki-chip svg { width: 13px; height: 13px; fill: ${KX.indigo2}; }

    #loki-gdpr-bar {
        padding: 10px 16px; background: rgba(99,102,241,0.06); border-top: 1px solid ${KX.border};
        font-size: 11.5px; color: ${KX.dim};
        display: flex; align-items: flex-start; gap: 8px; flex-shrink: 0;
    }
    #loki-gdpr-bar a { color: ${KX.indigo2}; }
    #loki-gdpr-check { margin-top: 2px; accent-color: ${KX.indigo}; cursor: pointer; }

    #loki-input-row {
        border-top: 1px solid ${KX.border}; padding: 12px 14px; background: ${KX.bg};
        display: flex; gap: 9px; align-items: center; flex-shrink: 0;
    }
    #loki-input {
        flex: 1; border: 1px solid ${KX.border}; border-radius: 12px; padding: 10px 14px;
        font-size: 13.5px; resize: none; max-height: 100px; outline: none;
        font-family: inherit; color: ${KX.white}; background: ${KX.lift};
        transition: border-color 0.15s; line-height: 1.4;
    }
    #loki-input:focus { border-color: rgba(99,102,241,0.5); }
    #loki-input::placeholder { color: ${KX.dim2}; }
    #loki-send-btn {
        width: 40px; height: 40px; border-radius: 11px;
        background: linear-gradient(135deg, ${KX.indigo}, ${KX.violet});
        border: none; cursor: pointer; display: flex; align-items: center; justify-content: center;
        flex-shrink: 0; transition: transform 0.15s, box-shadow 0.15s;
        box-shadow: 0 0 20px rgba(99,102,241,0.3);
    }
    #loki-send-btn:hover { transform: scale(1.05); box-shadow: 0 0 28px rgba(99,102,241,0.5); }
    #loki-send-btn:active { transform: scale(0.93); }
    #loki-send-btn:disabled { opacity: 0.45; cursor: default; box-shadow: none; }
    #loki-send-btn svg { width: 18px; height: 18px; fill: #fff; }

    /* Contact pane */
    #loki-contact-pane {
        flex: 1; overflow-y: auto; padding: 20px 16px 16px;
        display: none; flex-direction: column; gap: 0;
    }
    #loki-contact-pane::-webkit-scrollbar { width: 5px; }
    #loki-contact-pane::-webkit-scrollbar-thumb { background: rgba(28,28,26,0.1); border-radius: 3px; }
    #loki-contact-pane.loki-pane-active { display: flex; }
    #loki-contact-heading { font-family: 'Syne', sans-serif; font-size: 16px; font-weight: 800; letter-spacing: -0.02em; color: ${KX.white}; margin: 0 0 4px; }
    #loki-contact-subtitle { font-size: 12px; color: ${KX.dim}; margin: 0 0 18px; }

    .loki-field { display: flex; flex-direction: column; gap: 5px; margin-bottom: 13px; }
    .loki-field label { font-size: 12px; font-weight: 600; color: ${KX.dim}; }
    .loki-field input, .loki-field textarea {
        border: 1px solid ${KX.border}; border-radius: 10px; padding: 10px 12px;
        font-size: 13px; font-family: inherit; color: ${KX.white}; outline: none;
        transition: border-color 0.15s; background: ${KX.lift};
    }
    .loki-field input:focus, .loki-field textarea:focus { border-color: rgba(99,102,241,0.5); }
    .loki-field input::placeholder, .loki-field textarea::placeholder { color: ${KX.dim2}; }
    .loki-field textarea { resize: none; min-height: 72px; line-height: 1.45; }
    .loki-field-error { display: none; font-size: 11px; color: #f87171; margin-top: 2px; }
    .loki-field.loki-has-error input,
    .loki-field.loki-has-error textarea { border-color: #f87171; }
    .loki-field.loki-has-error .loki-field-error { display: block; }

    #loki-contact-gdpr {
        display: flex; align-items: flex-start; gap: 8px;
        font-size: 11.5px; color: ${KX.dim}; margin-bottom: 14px; line-height: 1.4;
    }
    #loki-contact-gdpr a { color: ${KX.indigo2}; }
    #loki-contact-gdpr-check { margin-top: 2px; accent-color: ${KX.indigo}; cursor: pointer; flex-shrink: 0; }
    #loki-contact-gdpr-error { display: none; font-size: 11px; color: #f87171; width: 100%; margin-top: -10px; margin-bottom: 10px; }
    #loki-contact-gdpr-error.loki-shown { display: block; }

    #loki-submit-btn {
        width: 100%; padding: 12px 0;
        background: linear-gradient(135deg, ${KX.indigo}, ${KX.violet}); color: #fff;
        border: none; border-radius: 12px; font-size: 14px; font-weight: 600;
        cursor: pointer; font-family: inherit; transition: transform 0.15s, box-shadow 0.15s, opacity 0.15s;
        box-shadow: 0 0 24px rgba(99,102,241,0.3);
    }
    #loki-submit-btn:hover { transform: translateY(-1px); box-shadow: 0 0 32px rgba(99,102,241,0.45); }
    #loki-submit-btn:disabled { opacity: 0.6; cursor: default; box-shadow: none; }

    #loki-contact-error {
        display: none; margin-top: 10px; padding: 10px 12px;
        background: rgba(248,113,113,0.1); border: 1px solid rgba(248,113,113,0.3); border-radius: 8px;
        font-size: 12px; color: #f87171; text-align: center;
    }
    #loki-contact-error.loki-shown { display: block; }

    /* Success state */
    #loki-contact-success {
        display: none; flex-direction: column; align-items: center; justify-content: center;
        flex: 1; text-align: center; padding: 24px 16px; gap: 12px;
    }
    #loki-contact-success.loki-shown { display: flex; }
    #loki-contact-success svg { width: 52px; height: 52px; }
    #loki-success-heading { font-family: 'Syne', sans-serif; font-size: 17px; font-weight: 800; color: ${KX.white}; margin: 0; }
    #loki-success-body { font-size: 13px; color: ${KX.dim}; margin: 0; line-height: 1.5; }

    /* Footer note */
    #loki-foot-note { text-align: center; font-size: 10px; color: ${KX.dim2}; padding: 0 16px 12px; background: ${KX.bg}; flex-shrink: 0; }
    #loki-foot-note strong { color: ${KX.dim}; font-weight: 600; }

    /* Responsive */
    @media (max-width: 420px) {
        #loki-chat-window {
            right: 0; bottom: 0; width: 100vw;
            height: 88vh; border-radius: 20px 20px 0 0;
        }
        #loki-chat-bubble { right: 16px; bottom: 82px; }
        #loki-toast { right: 16px; }
    }
    `;

    // ── Icons ────────────────────────────────────────────────────────────────
    // Sparkle mark — matches the new Klaravex AI brand
    const ICON_CHAT  = `<svg viewBox="0 0 256 256"><path d="M208 144a15.78 15.78 0 0 1-10.42 14.94l-51.65 19-19 51.61a15.92 15.92 0 0 1-29.88 0L78 178l-51.62-19a15.92 15.92 0 0 1 0-29.88l51.65-19 19-51.61a15.92 15.92 0 0 1 29.88 0l19 51.65 51.61 19A15.78 15.78 0 0 1 208 144Z"/></svg>`;
    const ICON_BOT   = ICON_CHAT;
    const ICON_SEND  = `<svg viewBox="0 0 256 256"><path d="m223.87 114.52-176-104A16 16 0 0 0 24.6 29.94L51.83 128 24.6 226.06a16 16 0 0 0 23.27 19.42l176-104a16 16 0 0 0 0-26.96Z"/></svg>`;
    const ICON_BOLT  = `<svg viewBox="0 0 256 256"><path d="M215.79 118.17a8 8 0 0 0-5-5.66L153.18 90.9l14.66-73.33a8 8 0 0 0-13.69-7l-112 120a8 8 0 0 0 3.49 13l57.63 21.61-14.62 73.34a8 8 0 0 0 13.69 7l112-120a8 8 0 0 0 1.45-7.95Z"/></svg>`;
    const ICON_CHECK = `<svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="12" fill="#22c55e"/><path d="M7 12.5l3.5 3.5 6.5-7" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
    // Quick-reply chip icons
    const ICON_CAL   = `<svg viewBox="0 0 256 256"><path d="M208 32h-24v-8a8 8 0 0 0-16 0v8H88v-8a8 8 0 0 0-16 0v8H48a16 16 0 0 0-16 16v160a16 16 0 0 0 16 16h160a16 16 0 0 0 16-16V48a16 16 0 0 0-16-16Zm0 176H48V96h160v112Z"/></svg>`;
    const ICON_TAG   = `<svg viewBox="0 0 256 256"><path d="M243.31 136 144 36.69A15.86 15.86 0 0 0 132.69 32H40a8 8 0 0 0-8 8v92.69A15.86 15.86 0 0 0 36.69 144L136 243.31a16 16 0 0 0 22.63 0l84.68-84.68a16 16 0 0 0 0-22.63ZM84 96a12 12 0 1 1 12-12 12 12 0 0 1-12 12Z"/></svg>`;
    const ICON_WRENCH= `<svg viewBox="0 0 256 256"><path d="M226.76 69a8 8 0 0 0-12.84-2.88l-40.3 37.19-17.23-3.7-3.7-17.23 37.19-40.3A8 8 0 0 0 184 29.24a72 72 0 0 0-99 96.16l-95.7 95.7a24 24 0 0 0 33.94 33.94l95.71-95.71A72 72 0 0 0 226.76 69Z"/></svg>`;
    const ICON_USER  = `<svg viewBox="0 0 256 256"><path d="M230.92 212c-15.23-26.33-38.7-45.21-66.09-54.16a72 72 0 1 0-73.66 0c-27.39 8.94-50.86 27.82-66.09 54.16a8 8 0 1 0 13.85 8c18.84-32.56 52.14-52 89.07-52s70.23 19.44 89.07 52a8 8 0 1 0 13.85-8Z"/></svg>`;

    // ── DOM helper ───────────────────────────────────────────────────────────
    function el(tag, attrs, ...children) {
        const node = document.createElement(tag);
        Object.entries(attrs || {}).forEach(([k, v]) => {
            if (k === 'html') node.innerHTML = v;
            else if (k === 'class') node.className = v;
            else node.setAttribute(k, v);
        });
        children.forEach(c => { if (c) node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
        return node;
    }

    // ── Build DOM ─────────────────────────────────────────────────────────────
    function buildWidget() {
        const style = document.createElement('style');
        style.textContent = css;
        document.head.appendChild(style);

        // Bubble (with online ping)
        const bubble = el('button', { id: 'loki-chat-bubble', 'aria-label': t.openLabel, html: ICON_CHAT + '<span id="loki-bubble-ping"></span>' });
        bubble.addEventListener('click', function (e) { e.stopPropagation(); hideToast(); toggleWidget(); });
        document.body.appendChild(bubble);

        // Proactive toast — shows once per browser session, dismissible
        const toast = el('div', { id: 'loki-toast', role: 'status' });
        toast.innerHTML = `<button id="loki-toast-close" aria-label="${t.toastDismiss}">×</button>👋 <strong>${AI_NAME}:</strong> ${t.toastMessage}`;
        toast.addEventListener('click', function () { hideToast(); if (!open) toggleWidget(); });
        toast.querySelector('#loki-toast-close').addEventListener('click', function (e) {
            e.stopPropagation(); hideToast();
        });
        document.body.appendChild(toast);
        if (!sessionStorage.getItem(cfg.toastStorageKey)) {
            setTimeout(function () {
                if (!open) toast.classList.add('loki-toast-visible');
            }, cfg.toastDelayMs);
        }

        // Window
        const win = el('div', { id: 'loki-chat-window', role: 'dialog', 'aria-label': 'Klaravex Chat' });

        // Header
        const header = el('div', { id: 'loki-header' });
        header.innerHTML = `
            <div id="loki-header-avatar">${ICON_BOT}</div>
            <div id="loki-header-info">
                <div id="loki-header-name">${AI_NAME} <span class="loki-ai-tag">AI</span></div>
                <div id="loki-header-status">${t.headerStatus}</div>
            </div>`;
        const closeBtn = el('button', { id: 'loki-close-btn', 'aria-label': t.closeLabel, html: '×' });
        closeBtn.addEventListener('click', function (e) { e.stopPropagation(); toggleWidget(); });
        header.appendChild(closeBtn);
        win.appendChild(header);

        // Trust ribbon — reinforces the "89% resolved by AI" promise
        const ribbon = el('div', { id: 'loki-trust-ribbon' });
        ribbon.innerHTML = ICON_BOLT + ' ' + t.trustRibbon;
        win.appendChild(ribbon);

        // Tab bar
        const tabBar = el('div', { id: 'loki-tab-bar' });
        const tabChat    = el('button', { class: 'loki-tab loki-tab-active', 'data-tab': 'chat' }, t.tabChat);
        const tabContact = el('button', { class: 'loki-tab', 'data-tab': 'contact' }, t.tabContact);
        tabChat.addEventListener('click', function () { switchTab('chat'); });
        tabContact.addEventListener('click', function () { switchTab('contact'); });
        tabBar.appendChild(tabChat);
        // Contact Us tab removed per Anthony directive 2026-08-24 — chat only.
        tabBar.style.display = 'none';
        win.appendChild(tabBar);

        // ── Chat pane ──────────────────────────────────────────────────────
        const chatPane = el('div', { id: 'loki-chat-pane' });

        const msgs = el('div', { id: 'loki-messages', 'aria-live': 'polite' });
        chatPane.appendChild(msgs);

        // Quick-reply chips — one-tap intents
        const quick = el('div', { id: 'loki-quick-replies' });
        // Quick-reply chips disabled per Anthony directive 2026-08-24 —
        // the "Talk to a person" label also violated the consumer voice policy.
        const chips = [];
        chips.forEach(function (c) {
            const chip = el('button', { class: 'loki-chip', html: c.icon + ' ' + c.label });
            chip.addEventListener('click', function () {
                quick.style.display = 'none';
                startIntakeConversation(c.src);
            });
            quick.appendChild(chip);
        });
        chatPane.appendChild(quick);

        if (cfg.gdprRequired && !gdprConsented) {
            const gdprBar = el('div', { id: 'loki-gdpr-bar' });
            const checkbox = el('input', { id: 'loki-gdpr-check', type: 'checkbox' });
            const label = el('label', { for: 'loki-gdpr-check', html: t.gdprText });
            checkbox.addEventListener('change', function () {
                gdprConsented = this.checked;
                document.getElementById('loki-send-btn').disabled = !gdprConsented;
                if (gdprConsented) gdprBar.style.display = 'none';
            });
            gdprBar.appendChild(checkbox);
            gdprBar.appendChild(label);
            chatPane.appendChild(gdprBar);
        } else {
            gdprConsented = true;
        }

        const inputRow = el('div', { id: 'loki-input-row' });
        const textarea = el('textarea', {
            id: 'loki-input', placeholder: t.placeholder,
            rows: '1', 'aria-label': t.inputLabel, maxlength: '4000',
        });
        textarea.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
        });
        textarea.addEventListener('input', function () {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 100) + 'px';
        });
        const sendBtn = el('button', { id: 'loki-send-btn', 'aria-label': t.sendLabel, html: ICON_SEND });
        sendBtn.disabled = cfg.gdprRequired && !gdprConsented;
        sendBtn.addEventListener('click', sendMessage);
        inputRow.appendChild(textarea);
        inputRow.appendChild(sendBtn);
        chatPane.appendChild(inputRow);

        // Footer note — transparency commitment (AI Act / GDPR)
        const footNote = el('div', { id: 'loki-foot-note', html: t.footNote });
        chatPane.appendChild(footNote);

        win.appendChild(chatPane);

        // ── Contact pane ───────────────────────────────────────────────────
        const contactPane = el('div', { id: 'loki-contact-pane' });

        // Success state (hidden initially)
        const successDiv = el('div', { id: 'loki-contact-success' });
        successDiv.innerHTML = `${ICON_CHECK}<p id="loki-success-heading">${t.successHeading}</p><p id="loki-success-body">${t.successBody}</p>`;
        contactPane.appendChild(successDiv);

        // Form
        const form = el('form', { id: 'loki-contact-form', novalidate: 'true' });
        form.innerHTML = `
            <p id="loki-contact-heading">${t.contactHeading}</p>
            <p id="loki-contact-subtitle">${t.contactSubtitle}</p>
            <div class="loki-field" id="lf-name-wrap">
                <label for="lf-name">${t.labelName}</label>
                <input type="text" id="lf-name" name="name" placeholder="${t.placeholderName}" maxlength="200" autocomplete="name">
                <span class="loki-field-error" id="lf-name-err">${t.validName}</span>
            </div>
            <div class="loki-field" id="lf-email-wrap">
                <label for="lf-email">${t.labelEmail}</label>
                <input type="email" id="lf-email" name="email" placeholder="${t.placeholderEmail}" maxlength="254" autocomplete="email">
                <span class="loki-field-error" id="lf-email-err">${t.validEmail}</span>
            </div>
            <div class="loki-field">
                <label for="lf-phone">${t.labelPhone}</label>
                <input type="tel" id="lf-phone" name="phone" placeholder="${t.placeholderPhone}" maxlength="30" autocomplete="tel">
            </div>
            <div class="loki-field" id="lf-msg-wrap">
                <label for="lf-msg">${t.labelMessage}</label>
                <textarea id="lf-msg" name="message" placeholder="${t.placeholderMsg}" maxlength="2000"></textarea>
                <span class="loki-field-error" id="lf-msg-err">${t.validMessage}</span>
            </div>
            <div id="loki-contact-gdpr">
                <input type="checkbox" id="loki-contact-gdpr-check">
                <label for="loki-contact-gdpr-check" html="">${t.gdprText}</label>
            </div>
            <div id="loki-contact-gdpr-error">${t.validGdpr}</div>
            <button type="submit" id="loki-submit-btn">${t.submitBtn}</button>
            <div id="loki-contact-error">${t.errorContact}</div>
        `;
        // Fix the GDPR label innerHTML (el() won't help here since we're using innerHTML)
        const cgLabel = form.querySelector('label[for="loki-contact-gdpr-check"]');
        if (cgLabel) cgLabel.innerHTML = t.gdprText;

        form.addEventListener('submit', submitContact);
        contactPane.appendChild(form);
        win.appendChild(contactPane);

        document.body.appendChild(win);
        appendBotMessage(t.welcomeMessage);
    }

    // ── Tab switching ─────────────────────────────────────────────────────────
    function switchTab(tab) {
        activeTab = tab;
        document.querySelectorAll('.loki-tab').forEach(function (btn) {
            btn.classList.toggle('loki-tab-active', btn.getAttribute('data-tab') === tab);
        });
        const chatPane    = document.getElementById('loki-chat-pane');
        const contactPane = document.getElementById('loki-contact-pane');
        if (tab === 'chat') {
            chatPane.style.display    = '';
            contactPane.classList.remove('loki-pane-active');
            document.getElementById('loki-input') && document.getElementById('loki-input').focus();
        } else {
            chatPane.style.display    = 'none';
            contactPane.classList.add('loki-pane-active');
            if (!contactSent) {
                const first = document.getElementById('lf-name');
                if (first) first.focus();
            }
        }
    }

    // ── Widget open/close ─────────────────────────────────────────────────────
    function hideToast() {
        const toast = document.getElementById('loki-toast');
        if (toast) toast.classList.remove('loki-toast-visible');
        sessionStorage.setItem(cfg.toastStorageKey, '1');
    }

    function toggleWidget() {
        open = !open;
        const win    = document.getElementById('loki-chat-window');
        const bubble = document.getElementById('loki-chat-bubble');
        if (open) {
            hideToast();
            win.classList.add('loki-open');
            bubble.setAttribute('aria-label', t.closeLabel);
            bubble.innerHTML = '×';
            bubble.style.fontSize = '24px';
            bubble.style.color = '#fff';
            if (activeTab === 'chat') document.getElementById('loki-input').focus();
        } else {
            win.classList.remove('loki-open');
            bubble.setAttribute('aria-label', t.openLabel);
            bubble.innerHTML = ICON_CHAT + '<span id="loki-bubble-ping"></span>';
            bubble.style.fontSize = '';
            bubble.style.color = '';
        }
    }

    // ── Chat messaging ────────────────────────────────────────────────────────
    function appendBotMessage(text) {
        const msgs = document.getElementById('loki-messages');
        const div  = el('div', { class: 'loki-msg loki-bot' });
        div.innerHTML = escapeHtml(text.replace(QUAL_TAG_RE, '').trim())
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/\n/g, '<br>')
            .replace(/(https?:\/\/[^\s<]+)/g, function (url) {
                var trail = '';
                var m = url.match(/[.,;:!?)\]]+$/);
                if (m) { trail = m[0]; url = url.slice(0, -trail.length); }
                return '<a href="' + url + '" target="_blank" rel="noopener noreferrer">' + url + '</a>' + trail;
            });
        msgs.appendChild(div);
        scrollToBottom();
        return div;
    }
    function appendUserMessage(text) {
        const msgs = document.getElementById('loki-messages');
        const div  = el('div', { class: 'loki-msg loki-user' });
        div.textContent = text;
        msgs.appendChild(div);
        scrollToBottom();
    }
    function showTyping() {
        const msgs = document.getElementById('loki-messages');
        const div  = el('div', { class: 'loki-msg loki-bot loki-typing', id: 'loki-typing-indicator' });
        div.innerHTML = '<span></span><span></span><span></span>';
        msgs.appendChild(div);
        scrollToBottom();
    }
    function hideTyping() {
        const el = document.getElementById('loki-typing-indicator');
        if (el) el.remove();
    }
    function scrollToBottom() {
        const msgs = document.getElementById('loki-messages');
        msgs.scrollTop = msgs.scrollHeight;
    }
    function escapeHtml(text) {
        return text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    async function sendMessage() {
        if (sending) return;
        const textarea = document.getElementById('loki-input');
        const text = textarea.value.trim();
        if (!text) return;
        if (cfg.gdprRequired && !gdprConsented) {
            const bar = document.getElementById('loki-gdpr-bar');
            if (bar) {
                bar.style.background = '#fff0f0'; bar.style.borderColor = '#ff7875';
                setTimeout(() => { bar.style.background = ''; bar.style.borderColor = ''; }, 1200);
            }
            return;
        }
        textarea.value = ''; textarea.style.height = 'auto';
        appendUserMessage(text);
        sending = true;
        document.getElementById('loki-send-btn').disabled = true;
        showTyping();
        try {
            // Backend only persists history for tokens minted by /chat/start —
            // fetch one before the first message so the conversation keeps state.
            if (!sessionToken) {
                try {
                    const sresp = await fetch(START_URL, {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ source: cfg.source, language: pageLang, gdpr_consent: true }),
                    });
                    if (sresp.ok) {
                        const sdata = await sresp.json();
                        if (sdata.session_token) {
                            sessionToken = sdata.session_token;
                            sessionStorage.setItem(cfg.storageKey, sessionToken);
                        }
                    }
                } catch (e) { /* stateless fallback */ }
            }
            let reply = null;
            try {
                const response = await fetch(API_URL, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text, session_token: sessionToken, gdpr_consent: true, channel: 'widget', language: pageLang, source: cfg.source }),
                });
                if (response.ok) {
                    const data = await response.json();
                    if (data.session_token) { sessionToken = data.session_token; sessionStorage.setItem(cfg.storageKey, sessionToken); }
                    const candidate = (data.reply || '').toLowerCase();
                    if (data.reply && !_LOKI_FALLBACK_PHRASES.some(p => candidate.includes(p))) reply = data.reply;
                }
            } catch (e) { /* try proxy */ }
            if (!reply && PROXY_URL) {
                try {
                    const r = await fetch(PROXY_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: text, gdpr_consent: true, language: pageLang }) });
                    if (r.ok) { const d = await r.json(); reply = d.reply || null; }
                } catch (e) { /* swallow */ }
            }
            hideTyping();
            appendBotMessage(reply || t.fallbackReply);
        } catch (err) {
            hideTyping(); appendBotMessage(t.errorMsg);
        } finally {
            sending = false;
            document.getElementById('loki-send-btn').disabled = false;
            document.getElementById('loki-input').focus();
        }
    }

    // ── Proactive intake — called by CTA buttons ──────────────────────────────
    async function startIntakeConversation(source) {
        if (!open) toggleWidget();

        // Clear chat history and start a fresh session
        const msgs = document.getElementById('loki-messages');
        msgs.innerHTML = '';
        sessionToken = null;
        sessionStorage.removeItem(cfg.storageKey);

        // CTA click implies GDPR consent
        gdprConsented = true;
        var gdprBar = document.getElementById('loki-gdpr-bar');
        if (gdprBar) gdprBar.style.display = 'none';
        var sendBtn = document.getElementById('loki-send-btn');
        if (sendBtn) sendBtn.disabled = false;

        showTyping();
        try {
            var resp = await fetch(START_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ source: source || 'discovery_call', language: pageLang, gdpr_consent: true }),
            });
            hideTyping();
            if (resp.ok) {
                var data = await resp.json();
                if (data.session_token) {
                    sessionToken = data.session_token;
                    sessionStorage.setItem(cfg.storageKey, sessionToken);
                }
                appendBotMessage(data.reply || t.welcomeMessage);
            } else {
                appendBotMessage(t.welcomeMessage);
            }
        } catch (e) {
            hideTyping();
            appendBotMessage(t.welcomeMessage);
        }
        var input = document.getElementById('loki-input');
        if (input) input.focus();
    }

    // ── Contact form submission ───────────────────────────────────────────────
    async function submitContact(e) {
        e.preventDefault();
        if (contactSent) return;

        const nameVal  = (document.getElementById('lf-name').value || '').trim();
        const emailVal = (document.getElementById('lf-email').value || '').trim();
        const phoneVal = (document.getElementById('lf-phone').value || '').trim();
        const msgVal   = (document.getElementById('lf-msg').value || '').trim();
        const gdprOk   = document.getElementById('loki-contact-gdpr-check').checked;

        // Validate
        let valid = true;
        function setErr(wrapId, show) {
            document.getElementById(wrapId).classList.toggle('loki-has-error', show);
            if (show) valid = false;
        }
        setErr('lf-name-wrap',  !nameVal);
        setErr('lf-email-wrap', !emailVal || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(emailVal));
        setErr('lf-msg-wrap',   !msgVal);

        const gdprErrEl = document.getElementById('loki-contact-gdpr-error');
        gdprErrEl.classList.toggle('loki-shown', !gdprOk);
        if (!gdprOk) valid = false;

        if (!valid) return;

        const submitBtn = document.getElementById('loki-submit-btn');
        const errBanner = document.getElementById('loki-contact-error');
        submitBtn.disabled = true;
        submitBtn.textContent = t.sending;
        errBanner.classList.remove('loki-shown');

        // Build message body for the lead pipeline
        const messageBody = [
            nameVal + (phoneVal ? ' · ' + phoneVal : ''),
            '',
            msgVal,
        ].join('\n');

        try {
            const response = await fetch(API_URL, {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message:       messageBody,
                    name:          nameVal,
                    email:         emailVal,
                    gdpr_consent:  true,
                    channel:       'contact_form',
                    language:      pageLang,
                }),
            });
            if (!response.ok) throw new Error('HTTP ' + response.status);

            // Success
            contactSent = true;
            document.getElementById('loki-contact-form').style.display = 'none';
            document.getElementById('loki-contact-success').classList.add('loki-shown');

        } catch (err) {
            submitBtn.disabled = false;
            submitBtn.textContent = t.submitBtn;
            errBanner.classList.add('loki-shown');
        }
    }

    // ── Init ──────────────────────────────────────────────────────────────────
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', buildWidget);
    } else {
        buildWidget();
    }

    // Expose for CTA intercept snippet
    window.klaravexStartIntake = function (source) {
        startIntakeConversation(source || 'discovery_call');
    };

})();
