/**
 * kvx-chat-widget.js
 * ─────────────────────────────
 * Klaravex AI chat widget.
 * Calls POST https://api.klaravex.com/api/v1/chat/message
 *
 * Deploy via WPCode (Klaravex WP admin → Code Snippets → Add Snippet →
 * JavaScript → Run site-wide → Active).
 */
(function () {
    'use strict';

    // Region + locale auto-detection:
    //   1. Default apiBase by hostname (don't trust the WPCode-injected
    //      KvxChatConfig.apiBase if the host says otherwise).
    //   2. All klaravex surfaces are EN / api.klaravex.com.
    //   3. No wp-json proxy — the chat endpoint is on api.klaravex.com.
    var host = (typeof window !== 'undefined' && window.location && window.location.hostname) || '';
    var hostL = host.toLowerCase();
    var isCom = hostL === 'klaravex.com' || hostL.endsWith('.klaravex.com')
             || hostL === 'klaravex.eu'  || hostL.endsWith('.klaravex.eu')
             || hostL === 'klaravex.io'  || hostL.endsWith('.klaravex.io');
    var isPersonal = hostL === 'personal.klaravex.com' || hostL.startsWith('personal.');
    var autoApiBase = 'https://llm.klaravex.com';
    var autoSource  = isPersonal ? 'personal' : 'chat';
    var autoLocale  = 'en';
    var autoPrivacyUrl = '/privacy-policy/';

    // ── Config ───────────────────────────────────────────────────────────────
    var defaults = {
        apiBase:        autoApiBase,
        primaryColor:   '#06B6D4',
        bubbleSize:     56,
        widgetWidth:    360,
        widgetHeight:   500,
        storageKey:     'klaravex_chat_session',
        gdprRequired:   true,
        locale:         autoLocale,
        // Quick-reply pills shown above the input. Each one is: { label, action }.
        // action: "send:<text>" sends <text> as if the user typed it;
        //         "url:<href>" opens <href> in a new tab;
        //         "intake:<sku>" opens the intake/booking flow for that SKU.
        // Defaults are minimal — set KvxChatConfig.quickReplies = [...] to override.
        quickReplies:   isPersonal ? [
                { label: 'Pricing', action: 'send:What do your plans cost?' },
                { label: 'Get help now', action: 'url:/support/' },
            ] : [
                { label: 'Pricing', action: 'send:What do your plans cost?' },
                { label: 'Book a free assessment', action: 'url:/contact/' },
            ],
        welcomeMessage: isPersonal ? 'Hi 👋 I\'m Klara, your friendly tech helper. Something broken, want to stay safe online, or just need a hand? Tell me what\'s going on.' : 'Hi! I\'m Klara, Klaravex\'s AI assistant. I can answer questions about our IT security and managed services. How can I help?',
        placeholder:    'Ask a question…',
        gdprText:       'I agree to the processing of my data per the <a href="' + autoPrivacyUrl + '" target="_blank">Privacy Policy</a>.',
        headerStatus:   'AI Assistant · Online',
        openLabel:      'Open chat',
        closeLabel:     'Close chat',
        sendLabel:      'Send',
        inputLabel:     'Enter your message',
        errorMsg:       'Sorry, there was a technical error. Please try again or email us at hello@klaravex.com.',
        // Notable change: no silent "Thank you, we\'ll be in touch" fallback.
        // That fallback masked broken plumbing for weeks (L5). On real failure
        // we now surface errorMsg so the user can see something went wrong.
        fallbackReply:  null,
    };
    var cfg = Object.assign(defaults, window.KvxChatConfig || {});

    // Safety override: force apiBase to llm.klaravex.com regardless of
    // any stale WPCode config. All surfaces route chat via the USA Hetzner ingress.
    if (cfg.apiBase) {
        var cb = cfg.apiBase.toLowerCase();
        if (cb.indexOf('llm.klaravex.com') === -1) {
            console.warn('[KvxChat] apiBase mismatch — overriding to llm.klaravex.com');
            cfg.apiBase = 'https://llm.klaravex.com';
        }
    }

    var API_URL   = cfg.apiBase + '/api/v1/chat/message';
    // L5: explicitly DO NOT use a WP proxy fallback. The previous fallback
    // legacy wp-json proxy doesn't exist on either WP and was eating
    // every real failure into a canned "Thank you" reply.
    var PROXY_URL = null;

    var _FALLBACK_PHRASES = [
        "thank you for your message. we'll be in touch",
    ];

    // ── State ────────────────────────────────────────────────────────────────
    var open          = false;
    var gdprConsented = false;
    var sessionToken  = sessionStorage.getItem(cfg.storageKey) || null;
    var sending       = false;

    // ── Styles ───────────────────────────────────────────────────────────────
    var css = '\n    #kvx-chat-bubble {\n        position: fixed;\n        bottom: 24px;\n        right: 24px;\n        width: ' + cfg.bubbleSize + 'px;\n        height: ' + cfg.bubbleSize + 'px;\n        border-radius: 50%;\n        background: ' + cfg.primaryColor + ';\n        box-shadow: 0 4px 18px rgba(0,0,0,0.25);\n        cursor: pointer;\n        display: flex;\n        align-items: center;\n        justify-content: center;\n        z-index: 999998;\n        transition: transform 0.2s ease, box-shadow 0.2s ease;\n        border: none;\n        outline: none;\n    }\n    #kvx-chat-bubble:hover {\n        transform: scale(1.08);\n        box-shadow: 0 6px 24px rgba(0,0,0,0.3);\n    }\n    #kvx-chat-bubble svg { width: 26px; height: 26px; fill: #fff; }\n\n    #kvx-chat-window {\n        position: fixed;\n        bottom: ' + (cfg.bubbleSize + 32) + 'px;\n        right: 24px;\n        width: ' + cfg.widgetWidth + 'px;\n        height: ' + cfg.widgetHeight + 'px;\n        background: #fff;\n        border-radius: 16px;\n        box-shadow: 0 8px 40px rgba(0,0,0,0.18);\n        display: flex;\n        flex-direction: column;\n        z-index: 999999;\n        font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif;\n        font-size: 14px;\n        overflow: hidden;\n        transform: translateY(20px);\n        opacity: 0;\n        pointer-events: none;\n        transition: opacity 0.22s ease, transform 0.22s ease;\n    }\n    #kvx-chat-window.kvx-open {\n        opacity: 1;\n        transform: translateY(0);\n        pointer-events: all;\n    }\n\n    #kvx-header {\n        background: ' + cfg.primaryColor + ';\n        color: #fff;\n        padding: 14px 16px;\n        display: flex;\n        align-items: center;\n        gap: 10px;\n        flex-shrink: 0;\n    }\n    #kvx-header-avatar {\n        width: 36px; height: 36px; border-radius: 50%;\n        background: rgba(255,255,255,0.2);\n        display: flex; align-items: center; justify-content: center;\n    }\n    #kvx-header-avatar svg { width: 20px; height: 20px; fill: #fff; }\n    #kvx-header-info { flex: 1; }\n    #kvx-header-name { font-weight: 600; font-size: 15px; }\n    #kvx-header-status { font-size: 11px; opacity: 0.85; }\n    #kvx-close-btn {\n        background: none; border: none; cursor: pointer;\n        color: #fff; opacity: 0.7; padding: 4px; line-height: 1;\n        font-size: 20px; transition: opacity 0.15s;\n    }\n    #kvx-close-btn:hover { opacity: 1; }\n\n    #kvx-messages {\n        flex: 1;\n        overflow-y: auto;\n        padding: 16px 12px;\n        display: flex;\n        flex-direction: column;\n        gap: 10px;\n        scroll-behavior: smooth;\n    }\n    #kvx-messages::-webkit-scrollbar { width: 4px; }\n    #kvx-messages::-webkit-scrollbar-thumb { background: #ddd; border-radius: 2px; }\n\n    .kvx-msg {\n        max-width: 82%;\n        padding: 9px 12px;\n        border-radius: 14px;\n        line-height: 1.45;\n        word-break: break-word;\n    }\n    .kvx-msg.kvx-bot {\n        background: #f2f4f8;\n        color: #1a1a2e;\n        align-self: flex-start;\n        border-bottom-left-radius: 4px;\n    }\n    .kvx-msg.kvx-bot a { color: ' + cfg.primaryColor + '; text-decoration: underline; }\n    .kvx-msg.kvx-user {\n        background: ' + cfg.primaryColor + ';\n        color: #fff;\n        align-self: flex-end;\n        border-bottom-right-radius: 4px;\n    }\n    .kvx-typing {\n        display: flex; align-items: center; gap: 4px;\n        padding: 10px 14px;\n    }\n    .kvx-typing span {\n        width: 7px; height: 7px; border-radius: 50%;\n        background: #bbb; display: inline-block;\n        animation: kvx-bounce 1.2s infinite ease-in-out;\n    }\n    .kvx-typing span:nth-child(2) { animation-delay: 0.2s; }\n    .kvx-typing span:nth-child(3) { animation-delay: 0.4s; }\n    @keyframes kvx-bounce {\n        0%, 80%, 100% { transform: scale(0.7); opacity: 0.5; }\n        40%            { transform: scale(1);   opacity: 1;   }\n    }\n\n    #kvx-gdpr-bar {\n        padding: 10px 14px;\n        background: #fffbea;\n        border-top: 1px solid #ffe58f;\n        font-size: 12px;\n        color: #555;\n        display: flex;\n        align-items: flex-start;\n        gap: 8px;\n        flex-shrink: 0;\n    }\n    #kvx-gdpr-bar a { color: ' + cfg.primaryColor + '; }\n    #kvx-gdpr-check { margin-top: 2px; accent-color: ' + cfg.primaryColor + '; cursor: pointer; }\n\n    #kvx-input-row {\n        border-top: 1px solid #eee;\n        padding: 10px 12px;\n        display: flex;\n        gap: 8px;\n        align-items: flex-end;\n        flex-shrink: 0;\n    }\n    #kvx-input {\n        flex: 1;\n        border: 1px solid #ddd;\n        border-radius: 10px;\n        padding: 8px 12px;\n        font-size: 14px;\n        resize: none;\n        max-height: 100px;\n        outline: none;\n        font-family: inherit;\n        color: #1a1a2e;\n        transition: border-color 0.15s;\n        line-height: 1.4;\n    }\n    #kvx-input:focus { border-color: ' + cfg.primaryColor + '; }\n    #kvx-input::placeholder { color: #aaa; }\n    #kvx-send-btn {\n        width: 36px; height: 36px; border-radius: 50%;\n        background: ' + cfg.primaryColor + '; border: none; cursor: pointer;\n        display: flex; align-items: center; justify-content: center;\n        flex-shrink: 0;\n        transition: background 0.15s, transform 0.1s;\n    }\n    #kvx-send-btn:hover { background: #0891B2; }\n    #kvx-send-btn:active { transform: scale(0.93); }\n    #kvx-send-btn:disabled { background: #aaa; cursor: default; }\n    #kvx-send-btn svg { width: 16px; height: 16px; fill: #fff; }\n\n    @media (max-width: 420px) {\n        #kvx-chat-window {\n            right: 0; bottom: 0;\n            width: 100vw;\n            height: 80vh;\n            border-radius: 16px 16px 0 0;\n        }\n        #kvx-chat-bubble { right: 16px; bottom: 16px; }\n    }\n    ';

    // ── SVG icons ────────────────────────────────────────────────────────────
    var ICON_CHAT  = '<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>';
    var ICON_BOT   = '<svg viewBox="0 0 24 24"><path d="M12 2a2 2 0 0 1 2 2 2 2 0 0 1-2 2 2 2 0 0 1-2-2 2 2 0 0 1 2-2m0 6c4.42 0 8 1.79 8 4v2H4v-2c0-2.21 3.58-4 8-4z"/></svg>';
    var ICON_SEND  = '<svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>';
    var ICON_CLOSE = '×';

    // ── DOM helpers ──────────────────────────────────────────────────────────
    function el(tag, attrs, children) {
        var node = document.createElement(tag);
        if (attrs) {
            Object.keys(attrs).forEach(function (k) {
                if (k === 'html') node.innerHTML = attrs[k];
                else if (k === 'class') node.className = attrs[k];
                else node.setAttribute(k, attrs[k]);
            });
        }
        if (children) {
            (Array.isArray(children) ? children : [children]).forEach(function (c) {
                if (c) node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
            });
        }
        return node;
    }

    // ── Build DOM ────────────────────────────────────────────────────────────
    function buildWidget() {
        var style = document.createElement('style');
        style.textContent = css;
        document.head.appendChild(style);

        var bubble = el('button', { id: 'kvx-chat-bubble', 'aria-label': cfg.openLabel, html: ICON_CHAT });
        bubble.addEventListener('click', toggleWidget);
        document.body.appendChild(bubble);

        var win = el('div', { id: 'kvx-chat-window', role: 'dialog', 'aria-label': 'Klaravex Chat' });

        var header = el('div', { id: 'kvx-header' });
        header.innerHTML = '<div id="kvx-header-avatar">' + ICON_BOT + '</div><div id="kvx-header-info"><div id="kvx-header-name">Klaravex</div><div id="kvx-header-status">' + cfg.headerStatus + '</div></div>';
        var closeBtn = el('button', { id: 'kvx-close-btn', 'aria-label': cfg.closeLabel, html: ICON_CLOSE });
        closeBtn.addEventListener('click', toggleWidget);
        header.appendChild(closeBtn);
        win.appendChild(header);

        var msgs = el('div', { id: 'kvx-messages', 'aria-live': 'polite' });
        win.appendChild(msgs);

        if (cfg.gdprRequired && !gdprConsented) {
            var gdprBar  = el('div', { id: 'kvx-gdpr-bar' });
            var checkbox = el('input', { id: 'kvx-gdpr-check', type: 'checkbox' });
            var label    = el('label', { 'for': 'kvx-gdpr-check', html: cfg.gdprText });
            checkbox.addEventListener('change', function () {
                gdprConsented = this.checked;
                document.getElementById('kvx-send-btn').disabled = !gdprConsented;
                if (gdprConsented) gdprBar.style.display = 'none';
            });
            gdprBar.appendChild(checkbox);
            gdprBar.appendChild(label);
            win.appendChild(gdprBar);
        } else {
            gdprConsented = true;
        }

        var inputRow = el('div', { id: 'kvx-input-row' });
        var textarea = el('textarea', { id: 'kvx-input', placeholder: cfg.placeholder, rows: '1', 'aria-label': cfg.inputLabel, maxlength: '4000' });
        textarea.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
        });
        textarea.addEventListener('input', function () {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 100) + 'px';
        });

        var sendBtn = el('button', { id: 'kvx-send-btn', 'aria-label': cfg.sendLabel, html: ICON_SEND });
        sendBtn.disabled = cfg.gdprRequired && !gdprConsented;
        sendBtn.addEventListener('click', sendMessage);

        inputRow.appendChild(textarea);
        inputRow.appendChild(sendBtn);
        win.appendChild(inputRow);
        document.body.appendChild(win);

        appendBotMessage(cfg.welcomeMessage);
        renderQuickReplies();
    }

    // ── Quick-reply pills (L5 fix) ───────────────────────────────────────────
    // Previously the WP page injected static "Book a session" buttons that
    // did nothing — they had no click handler. Now the widget renders them
    // itself from cfg.quickReplies and wires real actions.
    function renderQuickReplies() {
        var msgs = document.getElementById('kvx-messages');
        if (!msgs || !Array.isArray(cfg.quickReplies) || cfg.quickReplies.length === 0) return;

        // Remove any previously-rendered set (e.g., after a send).
        var existing = document.getElementById('kvx-quick-replies');
        if (existing) existing.remove();

        var bar = el('div', { id: 'kvx-quick-replies' });
        bar.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;padding:0 12px 6px;';

        cfg.quickReplies.forEach(function (qr) {
            if (!qr || !qr.label || !qr.action) return;
            var btn = el('button', { 'class': 'kvx-qr-btn', 'aria-label': qr.label });
            btn.textContent = qr.label;
            btn.style.cssText =
                'border:1px solid ' + cfg.primaryColor + ';' +
                'color:' + cfg.primaryColor + ';' +
                'background:#fff;border-radius:14px;padding:6px 12px;' +
                'font-size:12px;cursor:pointer;line-height:1;font-family:inherit;' +
                'transition:background 0.12s;';
            btn.addEventListener('mouseover', function () { btn.style.background = cfg.primaryColor; btn.style.color = '#fff'; });
            btn.addEventListener('mouseout',  function () { btn.style.background = '#fff'; btn.style.color = cfg.primaryColor; });
            btn.addEventListener('click', function () { handleQuickReply(qr); });
            bar.appendChild(btn);
        });
        msgs.appendChild(bar);
        scrollToBottom();
    }

    function handleQuickReply(qr) {
        var action = String(qr.action || '');
        var colon  = action.indexOf(':');
        if (colon < 0) return;
        var kind = action.substring(0, colon);
        var arg  = action.substring(colon + 1);

        // GDPR gate applies to all actions that talk to the API or capture
        // intent. Mirror the sendMessage() behaviour: flash the bar red.
        if (cfg.gdprRequired && !gdprConsented) {
            var bar = document.getElementById('kvx-gdpr-bar');
            if (bar) {
                bar.style.background  = '#fff0f0';
                bar.style.borderColor = '#ff7875';
                setTimeout(function () { bar.style.background = ''; bar.style.borderColor = ''; }, 1200);
            }
            return;
        }

        if (kind === 'send') {
            var textarea = document.getElementById('kvx-input');
            if (textarea) {
                textarea.value = arg;
                sendMessage();
            }
            return;
        }

        if (kind === 'url') {
            // Same-tab on mobile (better UX, lets the chat keep its session
            // via storageKey when the user comes back). New tab on desktop.
            var isMobile = window.matchMedia && window.matchMedia('(max-width: 480px)').matches;
            if (isMobile) {
                window.location.href = arg;
            } else {
                window.open(arg, '_blank', 'noopener,noreferrer');
            }
            return;
        }

        if (kind === 'intake') {
            // Stub for future intake-flow handoff. For now, redirect to the
            // sku's marketing page; the contact form there captures.
            var url = (autoLocale === 'de' ? '/de/kontakt/?sku=' : '/contact/?sku=') + encodeURIComponent(arg);
            window.location.href = url;
            return;
        }

        console.warn('[KvxChat] unknown quick-reply action kind:', kind);
    }

    // ── Widget open/close ─────────────────────────────────────────────────────
    function toggleWidget() {
        open = !open;
        var win    = document.getElementById('kvx-chat-window');
        var bubble = document.getElementById('kvx-chat-bubble');
        if (open) {
            win.classList.add('kvx-open');
            bubble.setAttribute('aria-label', cfg.closeLabel);
            bubble.innerHTML = ICON_CLOSE;
            document.getElementById('kvx-input').focus();
        } else {
            win.classList.remove('kvx-open');
            bubble.setAttribute('aria-label', cfg.openLabel);
            bubble.innerHTML = ICON_CHAT;
        }
    }

    // Public API for in-page CTAs (Chat-with-Klaravex-AI buttons on WP pages).
    // Idempotent: open() is safe to call whether the widget is already open or not.
    window.KvxChat = {
        open: function () { if (!open) toggleWidget(); },
        close: function () { if (open) toggleWidget(); },
        toggle: toggleWidget
    };

    // ── Message rendering ────────────────────────────────────────────────────
    function appendBotMessage(text) {
        var msgs = document.getElementById('kvx-messages');
        var div  = el('div', { 'class': 'kvx-msg kvx-bot' });
        div.innerHTML = escapeHtml(text)
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
        var msgs = document.getElementById('kvx-messages');
        var div  = el('div', { 'class': 'kvx-msg kvx-user' });
        div.textContent = text;
        msgs.appendChild(div);
        scrollToBottom();
    }

    function showTyping() {
        var msgs = document.getElementById('kvx-messages');
        var div  = el('div', { 'class': 'kvx-msg kvx-bot kvx-typing' });
        div.innerHTML = '<span></span><span></span><span></span>';
        div.id = 'kvx-typing-indicator';
        msgs.appendChild(div);
        scrollToBottom();
    }

    function hideTyping() {
        var indicator = document.getElementById('kvx-typing-indicator');
        if (indicator) indicator.remove();
    }

    function scrollToBottom() {
        var msgs = document.getElementById('kvx-messages');
        msgs.scrollTop = msgs.scrollHeight;
    }

    function escapeHtml(text) {
        return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    // ── Send message ──────────────────────────────────────────────────────────
    function sendMessage() {
        if (sending) return;
        var textarea = document.getElementById('kvx-input');
        var text     = textarea.value.trim();
        if (!text) return;

        if (cfg.gdprRequired && !gdprConsented) {
            var bar = document.getElementById('kvx-gdpr-bar');
            if (bar) {
                bar.style.background  = '#fff0f0';
                bar.style.borderColor = '#ff7875';
                setTimeout(function () { bar.style.background = ''; bar.style.borderColor = ''; }, 1200);
            }
            return;
        }

        textarea.value = '';
        textarea.style.height = 'auto';
        appendUserMessage(text);
        sending = true;
        document.getElementById('kvx-send-btn').disabled = true;
        showTyping();

        var payload = JSON.stringify({
            message:       text,
            session_token: sessionToken,
            gdpr_consent:  true,
            channel:       'widget',
            language:      cfg.locale || 'en',
            source:        cfg.source || autoSource,
        });

        // Timeout the fetch so a hung region (e.g. mis-pointed .com→.de) shows
        // a real error in <12s instead of leaving the user staring at the
        // typing dots forever. AbortController is supported in every browser
        // that runs WP admin in 2026.
        var controller = (typeof AbortController !== 'undefined') ? new AbortController() : null;
        var timeoutId  = controller ? setTimeout(function () { controller.abort(); }, 12000) : null;
        var fetchInit  = { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: payload };
        if (controller) fetchInit.signal = controller.signal;

        fetch(API_URL, fetchInit)
            .then(function (response) {
                if (timeoutId) clearTimeout(timeoutId);
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            })
            .then(function (data) {
                if (data.session_token) {
                    sessionToken = data.session_token;
                    sessionStorage.setItem(cfg.storageKey, sessionToken);
                }
                var candidate  = (data.reply || '').toLowerCase();
                var isFallback = _FALLBACK_PHRASES.some(function (p) { return candidate.indexOf(p) !== -1; });
                if (data.reply && !isFallback) return data.reply;
                // The API itself returned a canned "Thank you" — log so we can
                // see this in the audit log when it happens, and surface
                // errorMsg (NOT the silent fallback) to the user.
                console.warn('[KvxChat] backend returned fallback phrase; treating as error');
                return null;
            })
            .then(function (reply) {
                hideTyping();
                if (reply) {
                    appendBotMessage(reply);
                } else {
                    // L5 fix: do NOT mask backend failures with "Thank you,
                    // we'll be in touch shortly." Surface errorMsg so the
                    // user knows to email/call.
                    appendBotMessage(cfg.errorMsg);
                }
                // After each send, re-render the quick replies so the user
                // can take a one-tap next action.
                renderQuickReplies();
            })
            .catch(function (err) {
                if (timeoutId) clearTimeout(timeoutId);
                console.warn('[KvxChat] Error:', err && err.message ? err.message : err);
                hideTyping();
                appendBotMessage(cfg.errorMsg);
            })
            .finally(function () {
                sending = false;
                document.getElementById('kvx-send-btn').disabled = false;
                var inputEl = document.getElementById('kvx-input');
                if (inputEl) inputEl.focus();
            });
    }

    // ── Init ──────────────────────────────────────────────────────────────────
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', buildWidget);
    } else {
        buildWidget();
    }

})();
