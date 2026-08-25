#!/usr/bin/env python3
import json, subprocess, re, sys

USER="astewarttcml_iw04eh9p"
APP="Avig wM7M lfkz S7ly yGD6 sfHc"
BASE="https://klaravex.com"
PARENT=141

PAGES = [
  ("out-article-microsoft-secure-score.html","microsoft-secure-score","What is a Microsoft Secure Score and how do you improve it?"),
  ("out-article-hipaa-small-practice.html","hipaa-small-practice","What HIPAA actually requires of a small medical practice"),
  ("out-cat-security.html","security","Security"),
  ("out-cat-microsoft-365.html","microsoft-365","Microsoft 365 & Cloud"),
  ("out-cat-business-it.html","business-it","Business IT"),
  ("out-cat-it-readiness.html","it-readiness","IT Readiness"),
]

def existing_id(slug):
    out = subprocess.run(["curl","-s","--max-time","15",
        f"{BASE}/wp-json/wp/v2/pages?slug={slug}&parent={PARENT}&_fields=id,slug&status=any",
        "-u",f"{USER}:{APP}"],capture_output=True,text=True).stdout
    try:
        d=json.loads(out)
        return d[0]["id"] if d else None
    except: return None

def upsert(fn, slug, title):
    content=open(fn).read()
    content='<!-- wp:html -->'+content+'<!-- /wp:html -->'  # bypass wpautop
    payload=json.dumps({"title":title,"slug":slug,"parent":PARENT,"status":"publish","content":content})
    eid=existing_id(slug)
    url=f"{BASE}/wp-json/wp/v2/pages/{eid}" if eid else f"{BASE}/wp-json/wp/v2/pages"
    res=subprocess.run(["curl","-s","--max-time","30","-X","POST",url,
        "-u",f"{USER}:{APP}","-H","Content-Type: application/json","-d","@-"],
        input=payload,capture_output=True,text=True).stdout
    try:
        d=json.loads(res)
        print(("UPDATED" if eid else "CREATED"), d.get("id"), slug, "->", d.get("link"))
    except:
        print("ERR", slug, res[:200])

for fn,slug,title in PAGES:
    upsert(fn,slug,title)
