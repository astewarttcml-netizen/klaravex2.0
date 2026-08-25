#!/usr/bin/env python3
"""Klaravex KB generator — renders articles + category pages in the .kba- design system."""
import html, re, json

STYLE = open('_style.html').read()
SITE = "https://klaravex.com"

def esc(s): return html.escape(s, quote=False)

def section(eyebrow, title, body_html):
    return (f'<div class="kba-section">'
            f'<div class="kba-section-eyebrow">{esc(eyebrow)}</div>'
            f'<div class="kba-section-title">{esc(title)}</div>'
            f'{body_html}</div>')

def callout(title, body):
    return (f'<div class="kba-callout"><div class="kba-callout-title">{esc(title)}</div>'
            f'<p>{body}</p></div>')

def faq(items):
    rows = ''.join(
        f'<div class="kba-faq-item"><div class="kba-faq-q">{esc(q)}</div>'
        f'<div class="kba-faq-a">{a}</div></div>' for q, a in items)
    return (section('Common questions', 'FAQ',
            f'<div class="kba-faq">{rows}</div>'))

def cta(h3, p):
    return (f'<div class="kba-cta-block"><h3>{esc(h3)}</h3><p>{p}</p>'
            f'<a href="/free-assessment/" class="kba-cta-btn">Get a Free IT Assessment &rarr;</a></div>')

def breadcrumb(title, slug):
    data = {"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[
        {"@type":"ListItem","position":1,"name":"Knowledge Base","item":f"{SITE}/knowledge-base/"},
        {"@type":"ListItem","position":2,"name":title,"item":f"{SITE}/knowledge-base/{slug}/"}]}
    return ('<!-- KLX-BREADCRUMB --><script type="application/ld+json">'
            + json.dumps(data, indent=2) + '</script><!-- /KLX-BREADCRUMB -->')

def article(eyebrow, title, sub, slug, sections_html, faq_items, cta_h3, cta_p):
    body = sections_html + faq(faq_items)
    return (STYLE + '<div class="kba-wrap">'
            f'<div class="kba-hero"><div class="kba-eyebrow">{esc(eyebrow)}</div>'
            f'<h1>{esc(title)}</h1><p class="kba-hero-sub">{esc(sub)}</p></div>'
            f'<div class="kba-body">{body}{cta(cta_h3, cta_p)}</div></div>'
            + breadcrumb(title, slug))

def category(eyebrow, title, sub, slug, cards):
    """cards: list of (article_title, desc, href)"""
    items = ''.join(
        f'<a href="{href}" class="kba-choose-card" style="text-decoration:none;display:block;margin-bottom:14px">'
        f'<div class="kba-choose-header">{esc(t)}</div>'
        f'<p style="color:#64748B;font-size:.9375rem;margin:8px 0 0">{esc(d)}</p>'
        f'<span style="color:#06B6D4;font-size:.875rem;font-weight:600;display:inline-block;margin-top:12px">Read article &rarr;</span></a>'
        for t, d, href in cards)
    body = (f'<div class="kba-section">'
            f'<div class="kba-section-eyebrow">{esc(eyebrow)}</div>'
            f'<div class="kba-section-title">{len(cards)} guide{"s" if len(cards)!=1 else ""} in this topic</div>'
            f'<div class="kba-choose-grid" style="grid-template-columns:1fr">{items}</div></div>')
    return (STYLE + '<div class="kba-wrap">'
            f'<div class="kba-hero"><div class="kba-eyebrow">Knowledge Base</div>'
            f'<h1>{esc(title)}</h1><p class="kba-hero-sub">{esc(sub)}</p></div>'
            f'<div class="kba-body">{body}'
            f'<p style="text-align:center;margin:32px 0"><a href="/knowledge-base/" style="color:#06B6D4;font-weight:600;text-decoration:none">&larr; Back to all topics</a></p>'
            f'</div></div>')

if __name__ == '__main__':
    import importlib, content
    importlib.reload(content)
    for name, fn in content.PAGES.items():
        out = fn()
        open(f'out-{name}.html', 'w').write(out)
        print(f'wrote out-{name}.html ({len(out)} bytes)')
