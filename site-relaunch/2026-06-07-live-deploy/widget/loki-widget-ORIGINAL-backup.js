/**
 * loki-chat-widget.js
 * ───────────────────
 * Self-contained floating chat + contact widget for klaravex.com.
 *
 * Two tabs:
 *   Chat       — AI conversation with Loki
 *   Contact Us — Name / Email / Phone / Message form → Loki lead pipeline
 *
 * API endpoints:
 *   Chat:    POST https://api.klaravex.com/api/v1/chat/message
 *   Contact: POST https://api.klaravex.com/api/v1/chat/message  (channel: contact_form)
 *
 * Embed in WordPress:
 *   wp_enqueue_script('loki-chat', get_template_directory_uri() . '/js/loki-chat-widget.js', [], '2.0', true);
 *
 * Optional config before loading:
 *   <script>window.LokiConfig = { apiBase: 'https://api.klaravex.com' };<\/script>
 */
(function () {
    'use strict';

    // ── Page suppression ─────────────────────────────────────────────────────
    const _path = window.location.pathname || '';
    const _bodyCls = (typeof document !== 'undefined' && document.body && document.body.className) || '';
    const _suppressPaths = ['/portal/', '/de/portal/'];
    const _suppressBodyClasses = ['page-id-138'];
    if (_suppressPaths.some(function (p) { return _path === p || _path.indexOf(p) === 0; })) return;
    if (_suppressBodyClasses.some(function (c) { return _bodyCls.indexOf(c) !== -1; })) return;

    // ── Language detection ───────────────────────────────────────────────────
    const pageLang = window.location.pathname.startsWith('/de/') ? 'de' : 'en';

    // ── i18n ──────────────────────────────────────────────────────────────────
    const I18N = {
        en: {
            tabChat:           'Chat',
            tabContact:        'Contact Us',
            welcomeMessage:    'Hello! I\'m your AI assistant from Klaravex. How can I help you today?',
            placeholder:       'Your question…',
            gdprText:          'I agree to the processing of my data per the <a href="/privacy-policy" target="_blank">Privacy Policy</a>.',
            headerStatus:      'AI Assistant · Online',
            openLabel:         'Open chat',
            closeLabel:        'Close chat',
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
            placeholderPhone:  '+49 30 …',
            placeholderMsg:    'Describe your IT challenge…',
            submitBtn:         'Send Message',
            sending:           'Sending…',
            successHeading:    'Message sent!',
            successBody:       'Thanks for reaching out. Anthony will review your enquiry and reply by email within one business day.',
            errorContact:      'Something went wrong. Please email us directly at hello@klaravex.com.',
            validName:         'Please enter your name.',
            validEmail:        'Please enter a valid email address.',
            validMessage:      'Please enter a message.',
            validGdpr:         'Please accept the privacy policy to continue.',
        },
        de: {
            tabChat:           'Chat',
            tabContact:        'Kontakt',
            welcomeMessage:    'Guten Tag! Ich bin Ihr KI-Assistent von Klaravex. Wie kann ich Ihnen helfen?',
            placeholder:       'Ihre Frage …',
            gdprText:          'Ich stimme der Verarbeitung meiner Daten gemäß der <a href="/datenschutz" target="_blank">Datenschutzerklärung</a> zu.',
            headerStatus:      'KI-Assistent · Online',
            openLabel:         'Chat öffnen',
            closeLabel:        'Chat schließen',
            sendLabel:         'Senden',
            inputLabel:        'Nachricht eingeben',
            errorMsg:          'Entschuldigung, es gab einen technischen Fehler. Bitte versuchen Sie es erneut oder kontaktieren Sie uns direkt unter hello@klaravex.com.',
            fallbackReply:     'Danke für Ihre Nachricht. Wir melden uns in Kürze.',
            // Kontaktformular
            contactHeading:    'Nachricht senden',
            contactSubtitle:   'Wir antworten in der Regel innerhalb eines Werktages.',
            labelName:         'Vollständiger Name *',
            labelEmail:        'E-Mail-Adresse *',
            labelPhone:        'Telefon (optional)',
            labelMessage:      'Wie können wir helfen? *',
            placeholderName:   'Max Mustermann',
            placeholderEmail:  'max@unternehmen.de',
            placeholderPhone:  '+49 30 …',
            placeholderMsg:    'Beschreiben Sie Ihr IT-Anliegen…',
            submitBtn:         'Nachricht senden',
            sending:           'Wird gesendet…',
            successHeading:    'Nachricht gesendet!',
            successBody:       'Vielen Dank für Ihre Anfrage. Anthony wird Ihre Nachricht prüfen und innerhalb eines Werktages per E-Mail antworten.',
            errorContact:      'Etwas ist schiefgelaufen. Bitte schreiben Sie uns direkt an hello@klaravex.com.',
            validName:         'Bitte geben Sie Ihren Namen ein.',
            validEmail:        'Bitte geben Sie eine gültige E-Mail-Adresse ein.',
            validMessage:      'Bitte geben Sie eine Nachricht ein.',
            validGdpr:         'Bitte stimmen Sie der Datenschutzerklärung zu.',
        },
    };
    const t = I18N[pageLang];

    // ── Config ───────────────────────────────────────────────────────────────
    // Auto-detect consumer support context from URL path.
    // Pages under /personal/ (e.g. /personal/it-help/) route to the consumer pipeline.
    // Can be overridden by window.LokiConfig = { source: '...' }.
    const _autoSource = (
        _path === '/personal/it-help/' ||
        _path === '/de/personal/it-help/' ||
        _path.indexOf('/personal/support') === 0
    ) ? 'personal' : 'chat';

    const cfg = Object.assign({
        apiBase:        'https://api.klaravex.com',
        primaryColor:   '#0057A8',
        bubbleSize:     56,
        widgetWidth:    360,
        widgetHeight:   520,
        gdprRequired:   true,
        storageKey:     'loki_session',
        wpProxyUrl:     '/wp-json/loki/v1/chat',
        source:         _autoSource,
    }, window.LokiConfig || {});

    const API_URL   = cfg.apiBase + '/api/v1/chat/message';
    const START_URL = cfg.apiBase + '/api/v1/chat/start';
    const PROXY_URL = cfg.wpProxyUrl || null;
    const QUAL_TAG_RE = /\s*\[(QUALIFIED|NEEDS_MORE_INFO|NOT_A_FIT)\]/g;

    const _LOKI_FALLBACK_PHRASES = [
        "thank you for your message. we'll be in touch",
        "danke für ihre nachricht. wir melden uns",
    ];

    // ── State ────────────────────────────────────────────────────────────────
    let open          = false;
    let activeTab     = 'chat';       // 'chat' | 'contact'
    let gdprConsented = false;
    let sessionToken  = sessionStorage.getItem(cfg.storageKey) || null;
    let sending       = false;
    let contactSent   = false;

    // ── Styles ───────────────────────────────────────────────────────────────
    const css = `
    #loki-chat-bubble {
        position: fixed; bottom: 24px; right: 24px;
        width: ${cfg.bubbleSize}px; height: ${cfg.bubbleSize}px;
        border-radius: 50%; background: ${cfg.primaryColor};
        box-shadow: 0 4px 18px rgba(0,0,0,0.25); cursor: pointer;
        display: flex; align-items: center; justify-content: center;
        z-index: 999998; transition: transform 0.2s ease, box-shadow 0.2s ease;
        border: none; outline: none;
    }
    #loki-chat-bubble:hover { transform: scale(1.08); box-shadow: 0 6px 24px rgba(0,0,0,0.3); }
    #loki-chat-bubble svg { width: 26px; height: 26px; fill: #fff; }

    #loki-chat-window {
        position: fixed; bottom: ${cfg.bubbleSize + 32}px; right: 24px;
        width: ${cfg.widgetWidth}px; height: ${cfg.widgetHeight}px;
        background: #fff; border-radius: 16px;
        box-shadow: 0 8px 40px rgba(0,0,0,0.18);
        display: flex; flex-direction: column;
        z-index: 999999;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: 14px; overflow: hidden;
        transform: translateY(20px); opacity: 0; pointer-events: none;
        transition: opacity 0.22s ease, transform 0.22s ease;
    }
    #loki-chat-window.loki-open { opacity: 1; transform: translateY(0); pointer-events: all; }

    /* Header */
    #loki-header {
        background: ${cfg.primaryColor}; color: #fff;
        padding: 14px 16px; display: flex; align-items: center; gap: 10px; flex-shrink: 0;
    }
    #loki-header-avatar {
        width: 36px; height: 36px; border-radius: 50%;
        background: rgba(255,255,255,0.2); display: flex; align-items: center; justify-content: center;
    }
    #loki-header-avatar svg { width: 20px; height: 20px; fill: #fff; }
    #loki-header-info { flex: 1; }
    #loki-header-name { font-weight: 600; font-size: 15px; }
    #loki-header-status { font-size: 11px; opacity: 0.85; }
    #loki-close-btn {
        background: none; border: none; cursor: pointer;
        color: #fff; opacity: 0.7; padding: 4px; line-height: 1;
        font-size: 20px; transition: opacity 0.15s;
    }
    #loki-close-btn:hover { opacity: 1; }

    /* Tab bar */
    #loki-tab-bar {
        display: flex; border-bottom: 1px solid #eee; flex-shrink: 0; background: #fff;
    }
    .loki-tab {
        flex: 1; padding: 10px 0; background: none; border: none;
        border-bottom: 2px solid transparent; cursor: pointer;
        font-size: 13px; font-weight: 500; color: #888;
        font-family: inherit; transition: color 0.15s, border-color 0.15s;
    }
    .loki-tab:hover { color: ${cfg.primaryColor}; }
    .loki-tab.loki-tab-active { color: ${cfg.primaryColor}; border-bottom-color: ${cfg.primaryColor}; }

    /* Chat pane */
    #loki-chat-pane { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
    #loki-messages {
        flex: 1; overflow-y: auto; padding: 16px 12px;
        display: flex; flex-direction: column; gap: 10px; scroll-behavior: smooth;
    }
    #loki-messages::-webkit-scrollbar { width: 4px; }
    #loki-messages::-webkit-scrollbar-thumb { background: #ddd; border-radius: 2px; }

    .loki-msg {
        max-width: 82%; padding: 9px 12px; border-radius: 14px;
        line-height: 1.45; word-break: break-word;
    }
    .loki-msg.loki-bot { background: #f2f4f8; color: #1a1a2e; align-self: flex-start; border-bottom-left-radius: 4px; }
    .loki-msg.loki-user { background: ${cfg.primaryColor}; color: #fff; align-self: flex-end; border-bottom-right-radius: 4px; }
    .loki-typing { display: flex; align-items: center; gap: 4px; padding: 10px 14px; }
    .loki-typing span {
        width: 7px; height: 7px; border-radius: 50%; background: #bbb; display: inline-block;
        animation: loki-bounce 1.2s infinite ease-in-out;
    }
    .loki-typing span:nth-child(2) { animation-delay: 0.2s; }
    .loki-typing span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes loki-bounce {
        0%, 80%, 100% { transform: scale(0.7); opacity: 0.5; }
        40%            { transform: scale(1);   opacity: 1;   }
    }

    #loki-gdpr-bar {
        padding: 10px 14px; background: #fffbea; border-top: 1px solid #ffe58f;
        font-size: 12px; color: #555;
        display: flex; align-items: flex-start; gap: 8px; flex-shrink: 0;
    }
    #loki-gdpr-bar a { color: ${cfg.primaryColor}; }
    #loki-gdpr-check { margin-top: 2px; accent-color: ${cfg.primaryColor}; cursor: pointer; }

    #loki-input-row {
        border-top: 1px solid #eee; padding: 10px 12px;
        display: flex; gap: 8px; align-items: flex-end; flex-shrink: 0;
    }
    #loki-input {
        flex: 1; border: 1px solid #ddd; border-radius: 10px; padding: 8px 12px;
        font-size: 14px; resize: none; max-height: 100px; outline: none;
        font-family: inherit; color: #1a1a2e; transition: border-color 0.15s; line-height: 1.4;
    }
    #loki-input:focus { border-color: ${cfg.primaryColor}; }
    #loki-input::placeholder { color: #aaa; }
    #loki-send-btn {
        width: 36px; height: 36px; border-radius: 50%; background: ${cfg.primaryColor};
        border: none; cursor: pointer; display: flex; align-items: center; justify-content: center;
        flex-shrink: 0; transition: background 0.15s, transform 0.1s;
    }
    #loki-send-btn:hover { background: #0047a0; }
    #loki-send-btn:active { transform: scale(0.93); }
    #loki-send-btn:disabled { background: #aaa; cursor: default; }
    #loki-send-btn svg { width: 16px; height: 16px; fill: #fff; }

    /* Contact pane */
    #loki-contact-pane {
        flex: 1; overflow-y: auto; padding: 20px 16px 16px;
        display: none; flex-direction: column; gap: 0;
    }
    #loki-contact-pane.loki-pane-active { display: flex; }
    #loki-contact-heading { font-size: 15px; font-weight: 700; color: #1a1a2e; margin: 0 0 4px; }
    #loki-contact-subtitle { font-size: 12px; color: #888; margin: 0 0 16px; }

    .loki-field { display: flex; flex-direction: column; gap: 4px; margin-bottom: 12px; }
    .loki-field label { font-size: 12px; font-weight: 600; color: #444; }
    .loki-field input, .loki-field textarea {
        border: 1px solid #ddd; border-radius: 8px; padding: 8px 10px;
        font-size: 13px; font-family: inherit; color: #1a1a2e; outline: none;
        transition: border-color 0.15s; background: #fff;
    }
    .loki-field input:focus, .loki-field textarea:focus { border-color: ${cfg.primaryColor}; }
    .loki-field input::placeholder, .loki-field textarea::placeholder { color: #bbb; }
    .loki-field textarea { resize: none; min-height: 72px; line-height: 1.45; }
    .loki-field-error { display: none; font-size: 11px; color: #e53e3e; margin-top: 2px; }
    .loki-field.loki-has-error input,
    .loki-field.loki-has-error textarea { border-color: #e53e3e; }
    .loki-field.loki-has-error .loki-field-error { display: block; }

    #loki-contact-gdpr {
        display: flex; align-items: flex-start; gap: 8px;
        font-size: 12px; color: #555; margin-bottom: 14px; line-height: 1.4;
    }
    #loki-contact-gdpr a { color: ${cfg.primaryColor}; }
    #loki-contact-gdpr-check { margin-top: 2px; accent-color: ${cfg.primaryColor}; cursor: pointer; flex-shrink: 0; }
    #loki-contact-gdpr-error { display: none; font-size: 11px; color: #e53e3e; width: 100%; margin-top: -10px; margin-bottom: 10px; }
    #loki-contact-gdpr-error.loki-shown { display: block; }

    #loki-submit-btn {
        width: 100%; padding: 11px 0; background: ${cfg.primaryColor}; color: #fff;
        border: none; border-radius: 10px; font-size: 14px; font-weight: 600;
        cursor: pointer; font-family: inherit; transition: background 0.15s, opacity 0.15s;
    }
    #loki-submit-btn:hover { background: #0047a0; }
    #loki-submit-btn:disabled { opacity: 0.6; cursor: default; }

    #loki-contact-error {
        display: none; margin-top: 10px; padding: 10px 12px;
        background: #fff5f5; border: 1px solid #fed7d7; border-radius: 8px;
        font-size: 12px; color: #c53030; text-align: center;
    }
    #loki-contact-error.loki-shown { display: block; }

    /* Success state */
    #loki-contact-success {
        display: none; flex-direction: column; align-items: center; justify-content: center;
        flex: 1; text-align: center; padding: 24px 16px; gap: 12px;
    }
    #loki-contact-success.loki-shown { display: flex; }
    #loki-contact-success svg { width: 52px; height: 52px; }
    #loki-success-heading { font-size: 16px; font-weight: 700; color: #1a1a2e; margin: 0; }
    #loki-success-body { font-size: 13px; color: #666; margin: 0; line-height: 1.5; }

    /* Responsive */
    @media (max-width: 420px) {
        #loki-chat-window {
            right: 0; bottom: 0; width: 100vw;
            height: 85vh; border-radius: 16px 16px 0 0;
        }
        #loki-chat-bubble { right: 16px; bottom: 16px; }
    }
    `;

    // ── Icons ────────────────────────────────────────────────────────────────
    const ICON_CHAT  = `<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>`;
    const ICON_BOT   = `<svg viewBox="0 0 24 24"><path d="M12 2a2 2 0 0 1 2 2 2 2 0 0 1-2 2 2 2 0 0 1-2-2 2 2 0 0 1 2-2m0 6c4.42 0 8 1.79 8 4v2H4v-2c0-2.21 3.58-4 8-4z"/></svg>`;
    const ICON_SEND  = `<svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>`;
    const ICON_CHECK = `<svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="12" fill="#48BB78"/><path d="M7 12.5l3.5 3.5 6.5-7" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

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

        // Bubble
        const bubble = el('button', { id: 'loki-chat-bubble', 'aria-label': t.openLabel, html: ICON_CHAT });
        bubble.addEventListener('click', function (e) { e.stopPropagation(); toggleWidget(); });
        document.body.appendChild(bubble);

        // Window
        const win = el('div', { id: 'loki-chat-window', role: 'dialog', 'aria-label': 'Klaravex Chat' });

        // Header
        const header = el('div', { id: 'loki-header' });
        header.innerHTML = `
            <div id="loki-header-avatar">${ICON_BOT}</div>
            <div id="loki-header-info">
                <div id="loki-header-name">Klaravex</div>
                <div id="loki-header-status">${t.headerStatus}</div>
            </div>`;
        const closeBtn = el('button', { id: 'loki-close-btn', 'aria-label': t.closeLabel, html: '×' });
        closeBtn.addEventListener('click', function (e) { e.stopPropagation(); toggleWidget(); });
        header.appendChild(closeBtn);
        win.appendChild(header);

        // Tab bar
        const tabBar = el('div', { id: 'loki-tab-bar' });
        const tabChat    = el('button', { class: 'loki-tab loki-tab-active', 'data-tab': 'chat' }, t.tabChat);
        const tabContact = el('button', { class: 'loki-tab', 'data-tab': 'contact' }, t.tabContact);
        tabChat.addEventListener('click', function () { switchTab('chat'); });
        tabContact.addEventListener('click', function () { switchTab('contact'); });
        tabBar.appendChild(tabChat);
        tabBar.appendChild(tabContact);
        win.appendChild(tabBar);

        // ── Chat pane ──────────────────────────────────────────────────────
        const chatPane = el('div', { id: 'loki-chat-pane' });

        const msgs = el('div', { id: 'loki-messages', 'aria-live': 'polite' });
        chatPane.appendChild(msgs);

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
    function toggleWidget() {
        open = !open;
        const win    = document.getElementById('loki-chat-window');
        const bubble = document.getElementById('loki-chat-bubble');
        if (open) {
            win.classList.add('loki-open');
            bubble.setAttribute('aria-label', t.closeLabel);
            bubble.innerHTML = '×';
            bubble.style.fontSize = '24px';
            bubble.style.color = '#fff';
            if (activeTab === 'chat') document.getElementById('loki-input').focus();
        } else {
            win.classList.remove('loki-open');
            bubble.setAttribute('aria-label', t.openLabel);
            bubble.innerHTML = ICON_CHAT;
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
            .replace(/\n/g, '<br>');
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
