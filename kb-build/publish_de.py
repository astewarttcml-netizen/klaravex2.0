#!/usr/bin/env python3
import json, subprocess, re
from genbi import article_page, category_page, home_page

USER="astewarttcml_oi93saoy"; APP="x8XR zIai gD2l 9fXH Ebl1 tIBu"
BASE="https://klaravex.com"; PARENT=328

ARTICLES = [
 ("what-to-do-if-hacked","Was tun bei einem vermuteten Hack?"),
 ("multi-factor-authentication-setup","Multi-Faktor-Authentifizierung auf jedem Konto einrichten"),
 ("microsoft-secure-score","Microsoft Secure Score verstehen und verbessern"),
 ("m365-vs-google-workspace","Microsoft 365 vs. Google Workspace: Was passt zu Ihrem Unternehmen?"),
 ("email-setup","E-Mail einrichten: Outlook, Gmail und iPhone"),
 ("vpn-setup","VPN unter Windows und Mac einrichten und Fehler beheben"),
 ("hipaa-small-practice","Was HIPAA von einer kleinen Arztpraxis verlangt"),
]

CATS = {
 "security": (
   {"eyebrow":"Sicherheit","h1":"Sicherheit","sub":"Passwörter, MFA, Phishing — und was Ihre Konten und Daten wirklich schützt.","cards":[
     ("Was tun bei einem vermuteten Hack?","Ein ruhiger Schritt-für-Schritt-Plan für die ersten 60 Minuten.","/knowledge-base/what-to-do-if-hacked/?lang=de","Artikel lesen"),
     ("Multi-Faktor-Authentifizierung einrichten","MFA richtig umgesetzt — über Microsoft 365, Google, Apple und LinkedIn.","/knowledge-base/multi-factor-authentication-setup/?lang=de","Artikel lesen"),
     ("Microsoft Secure Score verbessern","Verstehen Sie die M365-Sicherheitsbewertung und die wirkungsvollsten Maßnahmen.","/knowledge-base/microsoft-secure-score/?lang=de","Artikel lesen")]},
   {"eyebrow":"Security","h1":"Security","sub":"Passwords, MFA, phishing — and what actually protects your accounts and data.","cards":[
     ("What to do if you think you've been hacked","A calm, step-by-step response for the first 60 minutes.","/knowledge-base/what-to-do-if-hacked/?lang=en","Read article"),
     ("How to set up multi-factor authentication","MFA done right across Microsoft 365, Google, Apple, and LinkedIn.","/knowledge-base/multi-factor-authentication-setup/?lang=en","Read article"),
     ("Improve your Microsoft Secure Score","Understand the M365 security rating and the highest-impact actions.","/knowledge-base/microsoft-secure-score/?lang=en","Read article")]}),
 "microsoft-365": (
   {"eyebrow":"Microsoft 365 & Cloud","h1":"Microsoft 365 & Cloud","sub":"Einrichtung, Migration und das Beste aus M365 und Google Workspace herausholen.","cards":[
     ("Microsoft 365 vs. Google Workspace","Ein neutraler Vergleich über die fünf entscheidenden Dimensionen.","/knowledge-base/m365-vs-google-workspace/?lang=de","Artikel lesen"),
     ("E-Mail einrichten: Outlook, Gmail, iPhone","Geschäftliche E-Mail auf jedem Gerät korrekt einrichten.","/knowledge-base/email-setup/?lang=de","Artikel lesen")]},
   {"eyebrow":"Microsoft 365 & Cloud","h1":"Microsoft 365 & Cloud","sub":"Setup, migration, and getting the most out of M365 and Google Workspace.","cards":[
     ("Microsoft 365 vs. Google Workspace","A no-agenda comparison across the five dimensions that matter.","/knowledge-base/m365-vs-google-workspace/?lang=en","Read article"),
     ("Setting up email on Outlook, Gmail, iPhone","Get business email working correctly on every device.","/knowledge-base/email-setup/?lang=en","Read article")]}),
 "business-it": (
   {"eyebrow":"Business-IT","h1":"Business-IT","sub":"Die alltäglichen Lösungen, die Ihr Unternehmen am Laufen halten — Netzwerke, Geräte, Zugriff.","cards":[
     ("VPN einrichten und Fehler beheben","Sicherer Fernzugriff, der zuverlässig verbindet.","/knowledge-base/vpn-setup/?lang=de","Artikel lesen")]},
   {"eyebrow":"Business IT","h1":"Business IT","sub":"The everyday fixes that keep a business running — networks, devices, and access.","cards":[
     ("Setting up and troubleshooting VPN","Secure remote access that actually connects.","/knowledge-base/vpn-setup/?lang=en","Read article")]}),
 "it-readiness": (
   {"eyebrow":"IT-Compliance","h1":"IT-Compliance & Readiness","sub":"HIPAA, SOC 2, Cyberversicherung — was kleine und mittlere Unternehmen wirklich brauchen.","cards":[
     ("Was HIPAA von einer kleinen Praxis verlangt","Die Kernanforderungen in verständlichem Deutsch — und was Sie ignorieren können.","/knowledge-base/hipaa-small-practice/?lang=de","Artikel lesen")]},
   {"eyebrow":"IT Readiness","h1":"IT Readiness","sub":"HIPAA, SOC 2, cyber insurance — what small and mid-sized businesses really need.","cards":[
     ("What HIPAA requires of a small practice","The core safeguards in plain English — and what to ignore.","/knowledge-base/hipaa-small-practice/?lang=en","Read article")]}),
}

HOME = (
 {"eyebrow":"Wissensdatenbank","h1":"Antworten auf häufige IT-Fragen","sub":"Verständliche Anleitungen für Unternehmen, die ihre Technik verstehen wollen — nicht nur anrufen, wenn etwas kaputtgeht.","cards":[
   ("Sicherheit","Passwörter, MFA, Phishing und echter Schutz.","/knowledge-base/security/?lang=de","Themen ansehen"),
   ("Microsoft 365 & Cloud","Einrichtung, Migration und Best Practices.","/knowledge-base/microsoft-365/?lang=de","Themen ansehen"),
   ("Business-IT","Netzwerke, Geräte und Zugriff im Alltag.","/knowledge-base/business-it/?lang=de","Themen ansehen"),
   ("IT-Compliance","HIPAA, SOC 2 und Cyberversicherung.","/knowledge-base/it-readiness/?lang=de","Themen ansehen")]},
 {"eyebrow":"Knowledge Base","h1":"Answers to common IT questions","sub":"Plain-English guides for businesses that want to understand their technology — not just call someone when it breaks.","cards":[
   ("Security","Passwords, MFA, phishing, and real protection.","/knowledge-base/security/?lang=en","Browse topics"),
   ("Microsoft 365 & Cloud","Setup, migration, and best practices.","/knowledge-base/microsoft-365/?lang=en","Browse topics"),
   ("Business IT","Networks, devices, and access.","/knowledge-base/business-it/?lang=en","Browse topics"),
   ("IT Readiness","HIPAA, SOC 2, and cyber insurance.","/knowledge-base/it-readiness/?lang=en","Browse topics")]})

def find_id(slug, parent=PARENT):
    out=subprocess.run(["curl","-s","--max-time","15",
      f"{BASE}/wp-json/wp/v2/pages?slug={slug}&parent={parent}&status=any&_fields=id","-u",f"{USER}:{APP}"],
      capture_output=True,text=True).stdout
    try: d=json.loads(out); return d[0]["id"] if d else None
    except: return None

def upsert(slug, title, content, pid=None, parent=PARENT):
    content = '<!-- wp:html -->' + content + '<!-- /wp:html -->'  # bypass wpautop
    eid = pid or find_id(slug)
    body={"title":title,"slug":slug,"status":"publish","content":content}
    if parent is not None: body["parent"]=parent
    payload=json.dumps(body)
    url=f"{BASE}/wp-json/wp/v2/pages/{eid}" if eid else f"{BASE}/wp-json/wp/v2/pages"
    res=subprocess.run(["curl","-s","--max-time","30","-X","POST",url,"-u",f"{USER}:{APP}",
      "-H","Content-Type: application/json","-d","@-"],input=payload,capture_output=True,text=True).stdout
    try: d=json.loads(res); print(("UPD" if eid else "NEW"),d.get("id"),slug)
    except: print("ERR",slug,res[:160])

# articles
for slug,title in ARTICLES:
    upsert(slug,title,article_page(slug,title))
# categories
for slug,(de,en) in CATS.items():
    upsert(slug,de['h1'],category_page(slug,de,en))
# home (page 328)
upsert("knowledge-base","Wissensdatenbank",home_page(*HOME),pid=328,parent=0)
print("done")
