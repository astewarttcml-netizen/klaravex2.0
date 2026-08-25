#!/usr/bin/env python3
"""T-AC-06 recipe step 6 — wire GA4 tags for client-side secondary events into
GTM containers via the Tag Manager v2 API.

Builds, in each target container's Default Workspace:
  - GA4 Configuration tag (per-stream measurement ID)
  - GA4 Event tags for the 5 client-side secondary conversions
    (readiness_assessment_completed, readiness_checklist_downloaded,
     contact_form_submitted, chat_conversation_started, newsletter_subscribed)
  - Custom HTML helper that mirrors the server-side primary fires (§6.7)
  - DLV variables, built-ins (Page Path / Form ID / Form Class),
    Custom JS dedup flag, and all triggers
Then creates + publishes a container version.

phone_call_qualified is intentionally SKIPPED (§6.4 — server-side via MP).

Usage:
  GA4_TOKEN=$(cat /tmp/klx_token) python3 tac06_gtm_wire.py [container_public_id...]
  (no args = wire ALL four containers)
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

TOKEN = os.environ["GA4_TOKEN"]
API = "https://www.googleapis.com/tagmanager/v2"
ACC = "6362046954"

CONTAINERS = {
    "klaravex.com": {"cid": "256106916", "mid": "G-GD0J1YFXHG", "currency": "USD"},
    "personal.klaravex.com": {"cid": "260687094", "mid": "G-00Z64W6WBD", "currency": "USD"},
}

DEDUP_JS = (
    "function() {\n"
    "  try {\n"
    "    var t = sessionStorage.getItem('klx_recent_readiness_booking');\n"
    "    if (!t) return 'false';\n"
    "    return (Date.now() - Number(t)) < 1800000 ? 'true' : 'false';\n"
    "  } catch(e) { return 'false'; }\n"
    "}"
)

HELPER_HTML = (
    "<script>\n"
    "  try {\n"
    "    sessionStorage.setItem('klx_recent_readiness_booking', String(Date.now()));\n"
    "  } catch(e) {}\n"
    "</script>"
)


def api(method, path, body=None):
    url = f"{API}/{path.lstrip('/')}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    if data:
        req.add_header("Content-Type", "application/json")
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode()
            if e.code == 409 and attempt < 3:  # optimistic concurrency
                time.sleep(1)
                continue
            if e.code == 429 and attempt < 5:  # per-user QPM rate limit
                time.sleep(3 * (attempt + 1))  # 3s, 6s, 9s, 12s, 15s backoff
                continue
            raise RuntimeError(f"{method} {url} -> {e.code}: {detail}")
    raise RuntimeError(f"{method} {url} exhausted retries")


def ws(cid):
    return f"accounts/{ACC}/containers/{cid}/workspaces/2"


def existing_objs(cid, kind):
    out = {}
    id_field = {"variables": "variableId", "triggers": "triggerId",
                "tags": "tagId"}.get(kind, "id")
    try:
        body = api("GET", f"{ws(cid)}/{kind}")
        # list responses key by the SINGULAR entity name ("variable", not "variables")
        items = body.get(kind, body.get(kind[:-1], []))
    except RuntimeError:
        return out
    for it in items:
        out.setdefault(it["name"], it[id_field])
    return out


def create(cid, kind, payload):
    return api("POST", f"{ws(cid)}/{kind}", payload)


def enable_builtins(cid):
    # v2 API: built_in_variables has no update (PUT) method — only create (POST)
    # with `type` as a repeated query parameter. Skip types already present.
    types = {"PAGE_PATH": "pagePath", "PAGE_URL": "pageUrl",
             "FORM_ID": "formId", "FORM_CLASS": "formClasses"}
    present = {b["type"] for b in
               api("GET", f"{ws(cid)}/built_in_variables")["builtInVariable"]}
    wanted = [v for v in types.values() if v not in present]
    if wanted:
        qs = "&".join(f"type={t}" for t in wanted)
        api("POST", f"{ws(cid)}/built_in_variables?{qs}", None)


def variables(cid, currency):
    created = {}
    existing = existing_objs(cid, "variables")
    for name, var_type, params in [
        # "v" = Data Layer Variable (verified via probe, row 19597/19598)
        ("DLV - score", "v", [("name", "score"), ("dataLayerVersion", "2")]),
        ("DLV - red_domains", "v", [("name", "red_domains"), ("dataLayerVersion", "2")]),
        ("DLV - chat_topic", "v", [("name", "chat_topic"), ("dataLayerVersion", "2")]),
        ("Recent readiness booking flag", "jsm", [("javascript", DEDUP_JS)]),
    ]:
        if name in existing:
            created[name] = existing[name]
            continue
        payload = {"name": name, "type": var_type,
                   "parameter": [{"key": k, "type": "TEMPLATE", "value": v}
                                 for k, v in params]}
        created[name] = create(cid, "variables", payload)["variableId"]
    return created


def triggers(cid, vids):
    created = {}
    existing = existing_objs(cid, "triggers")

    def trig(name, ttype, params=None, filt=None, cev=None):
        if name in existing:
            created[name] = existing[name]
            return
        payload = {"name": name, "type": ttype}
        if params:
            payload["parameter"] = [{"key": k, "type": "TEMPLATE", "value": v}
                                    for k, v in params]
        if cev:  # customEvent trigger: event name must be a customEventFilter
            payload["customEventFilter"] = [{"type": "equals", "parameter": [
                {"key": "arg0", "type": "TEMPLATE", "value": "{{_event}}"},
                {"key": "arg1", "type": "TEMPLATE", "value": cev}]}]
        if filt:
            payload["filter"] = filt
        created[name] = create(cid, "triggers", payload)["triggerId"]

    # Explicit All Pages trigger (no filter = every pageview). The reserved
    # built-in id "1" is rejected as an unknown trigger via the v2 API.
    trig("All Pages - pageview", "pageview")
    trig("PV - readiness checklist thanks", "pageview",
         filt=[{"type": "matchRegex", "parameter": [
             {"key": "arg0", "type": "TEMPLATE", "value": "{{Page Path}}"},
             {"key": "arg1", "type": "TEMPLATE", "value": "/thanks/readiness-checklist$"}]}])
    trig("CE - readiness_score_submitted", "customEvent", cev="readiness_score_submitted")
    trig("CE - linkedin_lead_form_submit", "customEvent", cev="linkedin_lead_form_submit")
    trig("CE - klaravex_chat_started", "customEvent", cev="klaravex_chat_started")
    trig("CE - readiness_booking_success", "customEvent", cev="readiness_booking_success")
    trig("FS - contact", "formSubmission",
         params=[("waitForTags", "true"), ("checkValidation", "true"),
                 ("waitForTagsTimeout", "2000")],
         filt=[{"type": "matchRegex", "parameter": [
             {"key": "arg0", "type": "TEMPLATE", "value": "{{Page Path}}"},
             {"key": "arg1", "type": "TEMPLATE", "value": "/contact"}]}])
    trig("FS - newsletter subscribe", "formSubmission",
         params=[("formClass", "newsletter-subscribe")])
    trig("BLOCK - recent readiness booking", "customEvent", cev="gtm.formSubmit",
         filt=[{"type": "equals", "parameter": [
             {"key": "arg0", "type": "TEMPLATE", "value": "{{Recent readiness booking flag}}"},
             {"key": "arg1", "type": "TEMPLATE", "value": "true"}]}])
    return created


def tags(cid, mid, currency, vids, trids):
    created = {}
    existing = existing_objs(cid, "tags")

    def ga4_event(name, event, params, firing, blocking=None):
        if name in existing:
            created[name] = existing[name]
            return
        ev_params = [{"type": "MAP", "map": [
            {"key": "parameter", "type": "TEMPLATE", "value": pn},
            {"key": "parameterValue", "type": "TEMPLATE", "value": pv}]}
            for pn, pv in params]
        payload = {
            "name": name, "type": "gaawe",
            "firingTriggerId": [trids[t] for t in firing],
            "parameter": [
                {"key": "eventName", "type": "TEMPLATE", "value": event},
                {"key": "measurementIdOverride", "type": "TEMPLATE", "value": mid},
                {"key": "eventSettingsTable", "type": "LIST", "list": ev_params},
            ],
        }
        if blocking:
            payload["blockingTriggerId"] = [trids[t] for t in blocking]
        created[name] = create(cid, "tags", payload)["tagId"]

    # GA4 Configuration tag (fires on all pageviews via explicit All Pages trigger)
    if "GA4 Config" in existing:
        created["GA4 Config"] = existing["GA4 Config"]
    else:
        created["GA4 Config"] = create(cid, "tags", {
            "name": "GA4 Config", "type": "gaawc",
            "firingTriggerId": [trids["All Pages - pageview"]],
            "parameter": [{"key": "measurementId", "type": "TEMPLATE", "value": mid}],
        })["tagId"]

    ga4_event("GA4 Event - readiness_assessment_completed",
              "readiness_assessment_completed",
              [("value", "50"), ("currency", currency),
               ("score", "{{DLV - score}}"), ("red_domains", "{{DLV - red_domains}}")],
              firing=["CE - readiness_score_submitted"])

    ga4_event("GA4 Event - readiness_checklist_downloaded",
              "readiness_checklist_downloaded",
              [("value", "30"), ("currency", currency), ("download_source", "site")],
              firing=["PV - readiness checklist thanks", "CE - linkedin_lead_form_submit"])

    ga4_event("GA4 Event - contact_form_submitted",
              "contact_form_submitted",
              [("value", "75"), ("currency", currency),
               ("form_id", "{{Form ID}}"), ("source_page", "{{Page Path}}")],
              firing=["FS - contact"],
              blocking=["BLOCK - recent readiness booking"])

    ga4_event("GA4 Event - chat_conversation_started",
              "chat_conversation_started",
              [("value", "40"), ("currency", currency),
               ("topic", "{{DLV - chat_topic}}")],
              firing=["CE - klaravex_chat_started"])

    ga4_event("GA4 Event - newsletter_subscribed",
              "newsletter_subscribed",
              [("value", "5"), ("currency", currency),
               ("source_page", "{{Page Path}}")],
              firing=["FS - newsletter subscribe"])

    # §6.7 sessionStorage helper mirrors server-side primary fires
    if "Readiness booking sessionStorage helper" in existing:
        created["Readiness booking sessionStorage helper"] = existing["Readiness booking sessionStorage helper"]
    else:
        created["Readiness booking sessionStorage helper"] = create(cid, "tags", {
            "name": "Readiness booking sessionStorage helper", "type": "html",
            "firingTriggerId": [trids["CE - readiness_booking_success"]],
            "parameter": [{"key": "html", "type": "TEMPLATE", "value": HELPER_HTML}],
        })["tagId"]
    return created


def publish(cid):
    # create_version is a WORKSPACE-level op (creates a version from the entities
    # in the workspace, then populates the container with it). If the workspace
    # was already submitted (previous run published it), treat as no-op.
    ver = api("POST", f"{ws(cid)}:create_version",
              {"name": "T-AC-06 step 6 — client-side secondary conversions",
               "options": {"includeVariableValues": False}})
    ver_path = ver["containerVersion"]["path"]
    pub = api("POST", f"{ver_path}:publish")
    return pub["containerVersion"]["containerVersionId"]


def publish_idempotent(cid):
    """Publish a container, tolerating 'workspace already submitted' (400)
    from a previous run — return the live version id in that case."""
    try:
        return publish(cid)
    except RuntimeError as e:
        if "Workspace is already submitted" in str(e):
            print("  (already published — skipping create_version)")
            return "already-published"
        raise


def wire(name, cfg):
    cid = cfg["cid"]
    print(f"--- wiring {name} (container {cid}, {cfg['mid']}, {cfg['currency']}) ---")
    enable_builtins(cid)
    vids = variables(cid, cfg["currency"])
    print(f"  variables: {', '.join(vids)}")
    trids = triggers(cid, vids)
    print(f"  triggers: {', '.join(trids)}")
    tag_ids = tags(cid, cfg["mid"], cfg["currency"], vids, trids)
    print(f"  tags: {', '.join(tag_ids)}")
    version = publish_idempotent(cid)
    print(f"  PUBLISHED version {version}")
    return version


def main():
    targets = sys.argv[1:]
    for name, cfg in CONTAINERS.items():
        if targets and name not in targets:
            continue
        wire(name, cfg)


if __name__ == "__main__":
    main()
