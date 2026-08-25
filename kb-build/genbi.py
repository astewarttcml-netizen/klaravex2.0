#!/usr/bin/env python3
"""Bilingual (DE-default + EN toggle) KB page assembler for klaravex.com."""
import json, html
STYLE = open('_style.html').read()
SITE = "https://klaravex.com"

LANGSW_CSS = """
<style>
.kba-langsw{display:flex;justify-content:center;gap:8px;padding:20px 0 0}
.kba-langsw button{font:600 12px/1 Inter,sans-serif;letter-spacing:.05em;color:#64748B;background:#111827;border:1px solid #1E293B;border-radius:999px;padding:7px 16px;cursor:pointer;transition:.15s}
.kba-langsw button.on{color:#fff;background:linear-gradient(135deg,#6366F1,#7C3AED);border-color:transparent}
</style>"""

LANGSW_HTML = ('<div class="kba-langsw"><button data-l="de">Deutsch</button>'
               '<button data-l="en">English</button></div>')

TOGGLE_JS = """
<script>(function(){function set(l){document.querySelectorAll('.kbabi').forEach(function(e){e.style.display=e.classList.contains('kbabi-'+l)?'':'none';});document.querySelectorAll('.kba-langsw button').forEach(function(b){b.classList.toggle('on',b.dataset.l===l);});}var p=new URLSearchParams(location.search);set(p.get('lang')==='en'?'en':'de');document.querySelectorAll('.kba-langsw button').forEach(function(b){b.addEventListener('click',function(){set(b.dataset.l);var u=new URL(location);u.searchParams.set('lang',b.dataset.l);history.replaceState({},'',u);});});})();</script>"""

def esc(s): return html.escape(s, quote=False)

def breadcrumb(title, slug):
    d={"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[
        {"@type":"ListItem","position":1,"name":"Wissensdatenbank","item":f"{SITE}/knowledge-base/"},
        {"@type":"ListItem","position":2,"name":title,"item":f"{SITE}/knowledge-base/{slug}/"}]}
    return '<script type="application/ld+json">'+json.dumps(d)+'</script>'

def bipage(de_inner, en_inner, title, slug):
    return (STYLE + LANGSW_CSS + '<div class="kba-wrap">' + LANGSW_HTML +
            f'<div class="kbabi kbabi-de">{de_inner}</div>'
            f'<div class="kbabi kbabi-en" style="display:none">{en_inner}</div>'
            '</div>' + TOGGLE_JS + breadcrumb(title, slug))

def article_page(slug, title_de):
    de=open(f'src-de/{slug}.html').read()
    en=open(f'src-en/{slug}.html').read()
    return bipage(de, en, title_de, slug)

# ---- category + home builders ----
def hero(eyebrow, h1, sub):
    return (f'<div class="kba-hero"><div class="kba-eyebrow">{esc(eyebrow)}</div>'
            f'<h1>{esc(h1)}</h1><p class="kba-hero-sub">{esc(sub)}</p></div>')

def cards(items):
    return '<div class="kba-body"><div class="kba-section"><div class="kba-choose-grid" style="grid-template-columns:1fr">' + ''.join(
        f'<a href="{h}" class="kba-choose-card" style="text-decoration:none;display:block;margin-bottom:14px">'
        f'<div class="kba-choose-header">{esc(t)}</div>'
        f'<p style="color:#64748B;font-size:.9375rem;margin:8px 0 0">{esc(d)}</p>'
        f'<span style="color:#818CF8;font-size:.875rem;font-weight:600;display:inline-block;margin-top:12px">{esc(more)} &rarr;</span></a>'
        for t,d,h,more in items) + '</div></div></div>'

def category_page(slug, de, en):
    de_inner = hero(de['eyebrow'], de['h1'], de['sub']) + cards(de['cards']) + back('de')
    en_inner = hero(en['eyebrow'], en['h1'], en['sub']) + cards(en['cards']) + back('en')
    return bipage(de_inner, en_inner, de['h1'], slug)

def back(l):
    txt = 'Zurück zu allen Themen' if l=='de' else 'Back to all topics'
    return f'<div class="kba-body"><p style="text-align:center;margin:8px 0 40px"><a href="/knowledge-base/" style="color:#818CF8;font-weight:600;text-decoration:none">&larr; {txt}</a></p></div>'

def home_page(de, en):
    de_inner = hero(de['eyebrow'], de['h1'], de['sub']) + cards(de['cards'])
    en_inner = hero(en['eyebrow'], en['h1'], en['sub']) + cards(en['cards'])
    return bipage(de_inner, en_inner, de['h1'], '')
