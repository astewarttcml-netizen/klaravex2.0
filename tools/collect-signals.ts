#!/usr/bin/env bun
/**
 * Klaravex Business Signal Collector
 * ──────────────────────────────────
 * Read-only collector that polls Stripe / Smartlead / Atera / Postgres /
 * Azure / Healthchecks / local TASKS+SUMMARY and writes the populated
 * .loki/state/business-signals.json snapshot every ~15 min.
 *
 * Loki (autonomous mode) reads that file at the top of each iteration to
 * prioritise growth tasks against actual market response, not guesswork.
 *
 * Hard rules:
 *   - READ-ONLY against production. Local writes only: business-signals.json,
 *     events.jsonl append, and the fallback note_submissions JSONL.
 *   - Every external call is wrapped in try/catch; failures populate
 *     collector_errors[] but never crash the whole run.
 *   - No secrets are read from the vault by this script. Anthony injects
 *     keys via env vars or pre-cached /tmp files (see KEY DISCOVERY below).
 *
 * Usage:
 *   bun tools/collect-signals.ts                    # full collect, write file
 *   bun tools/collect-signals.ts --dry-run          # collect, print to stdout
 *   bun tools/collect-signals.ts --only=stripe,db   # collect only listed sources
 *   bun tools/collect-signals.ts --verbose          # log every step to stderr
 */

import { existsSync, mkdirSync, appendFileSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { homedir } from "node:os";

// ─────────────────────────────────────────────────────────────────────────
// Paths & constants
// ─────────────────────────────────────────────────────────────────────────
const PROJECT_ROOT  = resolve(import.meta.dir, "..");
const STATE_FILE    = resolve(PROJECT_ROOT, ".loki/state/business-signals.json");
const EVENTS_FILE   = resolve(PROJECT_ROOT, ".loki/events.jsonl");
const SUMMARY_FILE  = resolve(PROJECT_ROOT, "SUMMARY.md");
const FALLBACK_NOTE = resolve(homedir(), ".claude/note-submissions-fallback.jsonl");

const STRIPE_BASE     = "https://api.stripe.com/v1";
const SMARTLEAD_BASE  = "https://server.smartlead.ai/api/v1";
const ATERA_BASE      = "https://app.atera.com/api/v3";
const KLARAVEX_API    = "https://api.klaravex.com";
const HEALTHCHECKS_RO = "https://healthchecks.io/api/v2/checks/";

// Campaigns (from CLAUDE.md / SUMMARY.md)
const CAMPAIGN_IDS: Record<string, number> = {
  klx_01: 3462139,
  klx_02: 3462147,
  klx_03: 3462150,
  klx_04: 3462420,
};

// ─────────────────────────────────────────────────────────────────────────
// CLI args
// ─────────────────────────────────────────────────────────────────────────
const argv = Bun.argv.slice(2);
const FLAGS = {
  dryRun:  argv.includes("--dry-run"),
  verbose: argv.includes("--verbose") || argv.includes("-v"),
  only:    (argv.find(a => a.startsWith("--only="))?.split("=")[1] ?? "")
             .split(",").map(s => s.trim()).filter(Boolean),
};
const wants = (src: string) => FLAGS.only.length === 0 || FLAGS.only.includes(src);
const log   = (...m: unknown[]) => { if (FLAGS.verbose) console.error("[collect-signals]", ...m); };

// ─────────────────────────────────────────────────────────────────────────
// Key discovery — graceful, never throws
// ─────────────────────────────────────────────────────────────────────────
function readCachedKey(name: string): string | null {
  // Try /tmp/klaravex_session_keys/<name> (the convention used by other tools)
  const p = `/tmp/klaravex_session_keys/${name}`;
  try {
    if (existsSync(p)) {
      const v = readFileSync(p, "utf8").trim();
      return v || null;
    }
  } catch { /* ignore */ }
  return null;
}
function key(envName: string, cacheName?: string): string | null {
  const v = process.env[envName];
  if (v && v.length > 0) return v;
  if (cacheName) return readCachedKey(cacheName);
  return null;
}

const KEYS = {
  stripe:      key("STRIPE_SECRET_KEY", "stripe_key"),
  smartlead:   key("SMARTLEAD_API_KEY", "smartlead_key"),
  atera:       key("ATERA_API_KEY"),
  databaseUrl: key("DATABASE_URL"),           // Cloud86 Postgres
  databaseUrlUs: key("DATABASE_URL_US"),      // Azure Postgres (klaravex_us)
  healthchecks: key("HEALTHCHECKS_API_KEY"),
};

// ─────────────────────────────────────────────────────────────────────────
// Result container
// ─────────────────────────────────────────────────────────────────────────
const NOW = new Date();
const out = JSON.parse(readFileSync(STATE_FILE, "utf8"));
out.collected_at        = NOW.toISOString();
out.next_collection_due = new Date(NOW.getTime() + (out.collection_interval_minutes ?? 15) * 60_000).toISOString();
out.collector_status    = "running";
out.collector_errors    = [];
out.data_sources_available = {
  stripe:           !!KEYS.stripe,
  smartlead:        !!KEYS.smartlead,
  atera:            !!KEYS.atera,
  postgres_cloud86: !!KEYS.databaseUrl,
  postgres_azure_us:!!KEYS.databaseUrlUs,
  azure_cli:        await haveAzCli(),
  healthchecks:     !!KEYS.healthchecks,
  summary_md:       existsSync(SUMMARY_FILE),
};

function addError(source: string, msg: string, detail?: unknown) {
  out.collector_errors.push({
    source,
    message: msg,
    detail: detail instanceof Error ? detail.message : detail,
    at: new Date().toISOString(),
  });
  log("ERROR", source, msg, detail);
}

async function haveAzCli(): Promise<boolean> {
  try {
    const proc = Bun.spawn(["az", "--version"], { stdout: "pipe", stderr: "pipe" });
    const code = await proc.exited;
    return code === 0;
  } catch { return false; }
}

// ─────────────────────────────────────────────────────────────────────────
// Time helpers
// ─────────────────────────────────────────────────────────────────────────
const TS_24H = Math.floor((NOW.getTime() - 24 * 3600_000) / 1000);
const TS_7D  = Math.floor((NOW.getTime() -  7 * 86400_000) / 1000);
const TS_MTD = Math.floor(new Date(NOW.getUTCFullYear(), NOW.getUTCMonth(), 1).getTime() / 1000);

// ─────────────────────────────────────────────────────────────────────────
// 1. STRIPE — revenue + sku breakdown + subs
// ─────────────────────────────────────────────────────────────────────────
async function stripeGet<T = any>(path: string, params: Record<string, any> = {}): Promise<T> {
  const url = new URL(`${STRIPE_BASE}${path}`);
  for (const [k, v] of Object.entries(params)) {
    if (v == null) continue;
    if (Array.isArray(v)) v.forEach((x, i) => url.searchParams.append(`${k}[${i}]`, String(x)));
    else if (typeof v === "object") {
      for (const [kk, vv] of Object.entries(v)) url.searchParams.append(`${k}[${kk}]`, String(vv));
    } else url.searchParams.set(k, String(v));
  }
  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${KEYS.stripe}` },
  });
  if (!res.ok) throw new Error(`Stripe ${path} → ${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

async function collectStripe(): Promise<void> {
  if (!KEYS.stripe) { addError("stripe", "no Stripe key (set STRIPE_SECRET_KEY or cache /tmp/klaravex_session_keys/stripe_key)"); return; }

  // Build sku ← price_id map from the locally cached products
  const skuByPrice = new Map<string, string>();
  for (const seg of ["consumer", "b2b"]) {
    const f = resolve(PROJECT_ROOT, `.loki/stripe-products-${seg}.json`);
    if (!existsSync(f)) continue;
    try {
      const arr = JSON.parse(readFileSync(f, "utf8")) as Array<{sku:string; price_id?:string}>;
      for (const p of arr) if (p.price_id) skuByPrice.set(p.price_id, p.sku);
    } catch (e) { addError("stripe", `parse ${f} failed`, e); }
  }

  // 1a. Charges since MTD start (paginate, but cap pages defensively)
  try {
    let mtdUsd = 0, mtdCount = 0;
    let usd24h = 0, usd7d = 0;
    const bySku = out.revenue.by_sku as Record<string, any>;

    let starting_after: string | undefined = undefined;
    let pages = 0;
    while (pages < 20) {
      const res = await stripeGet<{ data: any[]; has_more: boolean }>(
        "/charges",
        { limit: 100, "created[gte]": TS_MTD, starting_after }
      );
      for (const c of res.data) {
        if (c.status !== "succeeded" || c.refunded) continue;
        const usd = (c.amount_captured ?? c.amount) / 100;
        mtdUsd += usd; mtdCount += 1;
        if (c.created >= TS_24H) usd24h += usd;
        if (c.created >= TS_7D)  usd7d  += usd;

        // sku attribution via metadata.sku (best) or invoice line items (TODO)
        const sku = c.metadata?.sku;
        if (sku && bySku[sku]) {
          bySku[sku].count_mtd += 1;
          bySku[sku].mtd_usd   += usd;
          if (c.created >= TS_7D)  bySku[sku]["7d_usd"]  += usd;
          if (c.created >= TS_24H) bySku[sku]["24h_usd"] += usd;
        }
      }
      if (!res.has_more) break;
      starting_after = res.data.at(-1)?.id;
      if (!starting_after) break;
      pages += 1;
    }
    out.revenue.stripe_mtd_usd   = round(mtdUsd);
    out.revenue.stripe_mtd_count = mtdCount;
    out.revenue.stripe_7d_usd    = round(usd7d);
    out.revenue.stripe_24h_usd   = round(usd24h);
  } catch (e) { addError("stripe.charges", "charges fetch failed", e); }

  // 1b. Subscriptions snapshot (active + recent churn)
  try {
    let mrrUsd = 0, activeSubs = 0;
    const bySku = out.revenue.by_sku as Record<string, any>;
    let starting_after: string | undefined = undefined;
    let pages = 0;
    while (pages < 10) {
      const res = await stripeGet<{ data: any[]; has_more: boolean }>(
        "/subscriptions",
        { limit: 100, status: "active", starting_after }
      );
      for (const s of res.data) {
        activeSubs += 1;
        for (const item of s.items?.data ?? []) {
          const unitAmt = item.price?.unit_amount ?? 0;
          const interval = item.price?.recurring?.interval ?? "month";
          const monthly = interval === "year" ? unitAmt / 12 : unitAmt;
          const qty = item.quantity ?? 1;
          mrrUsd += (monthly * qty) / 100;
          const sku = skuByPrice.get(item.price?.id);
          if (sku && bySku[sku]) bySku[sku].active_subs += 1;
        }
      }
      if (!res.has_more) break;
      starting_after = res.data.at(-1)?.id;
      if (!starting_after) break;
      pages += 1;
    }
    out.revenue.active_subs_total = activeSubs;
    out.revenue.mrr_usd = round(mrrUsd);
    out.revenue.arr_usd = round(mrrUsd * 12);
  } catch (e) { addError("stripe.subs", "subs fetch failed", e); }

  // 1c. New + churned subs in last 24h (events API)
  try {
    const types = ["customer.subscription.created", "customer.subscription.deleted"];
    const ev = await stripeGet<{ data: any[] }>("/events", { limit: 100, "created[gte]": TS_24H, types });
    let created = 0, deleted = 0;
    for (const e of ev.data) {
      if (e.type === "customer.subscription.created") created += 1;
      if (e.type === "customer.subscription.deleted") deleted += 1;
    }
    out.revenue.new_subs_24h     = created;
    out.revenue.churned_subs_24h = deleted;
  } catch (e) { addError("stripe.events", "events fetch failed", e); }
}

// ─────────────────────────────────────────────────────────────────────────
// 2. SMARTLEAD — per-campaign stats
// ─────────────────────────────────────────────────────────────────────────
async function smartleadGet<T = any>(path: string, params: Record<string, any> = {}): Promise<T> {
  const url = new URL(`${SMARTLEAD_BASE}${path}`);
  url.searchParams.set("api_key", KEYS.smartlead!);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, String(v));
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Smartlead ${path} → ${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

async function collectSmartlead(): Promise<void> {
  if (!KEYS.smartlead) { addError("smartlead", "no SMARTLEAD_API_KEY (cache or env)"); return; }

  for (const [name, id] of Object.entries(CAMPAIGN_IDS)) {
    const slot = (out.campaigns as Record<string, any>)[name];
    if (!slot) continue;
    try {
      // Campaign meta
      const meta = await smartleadGet<any>(`/campaigns/${id}`);
      slot.status = meta?.status ?? slot.status;

      // Aggregate stats (lifetime)
      const stats = await smartleadGet<any>(`/campaigns/${id}/analytics`);
      slot.leads_total = stats?.total_leads ?? stats?.leads_count ?? slot.leads_total;
      slot.sent_total  = stats?.sent_count  ?? stats?.emails_sent_count ?? slot.sent_total;
      const opens   = stats?.open_count    ?? stats?.unique_open_count ?? null;
      const replies = stats?.reply_count   ?? stats?.unique_reply_count ?? null;
      const bounces = stats?.bounce_count  ?? null;
      if (slot.sent_total && opens != null)   slot.open_rate   = round(opens   / slot.sent_total, 4);
      if (slot.sent_total && replies != null) slot.reply_rate  = round(replies / slot.sent_total, 4);
      if (slot.sent_total && bounces != null) slot.bounce_rate = round(bounces / slot.sent_total, 4);

      // Daily slice for 24h windows
      try {
        const daily = await smartleadGet<any>(`/campaigns/${id}/analytics-by-date`, {
          start_date: new Date(NOW.getTime() - 24*3600_000).toISOString().slice(0,10),
          end_date:   NOW.toISOString().slice(0,10),
        });
        const day = (daily?.data ?? daily ?? [])[0] ?? {};
        slot.sent_24h    = day.sent_count    ?? null;
        slot.opens_24h   = day.open_count    ?? null;
        slot.replies_24h = day.reply_count   ?? null;
        slot.bounces_24h = day.bounce_count  ?? null;
      } catch (e) { /* daily endpoint variant — non-fatal */ }
    } catch (e) {
      addError(`smartlead.${name}`, `campaign ${id} fetch failed`, e);
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────
// 3. ATERA — open tickets + critical + MTTR
// ─────────────────────────────────────────────────────────────────────────
async function ateraGet<T = any>(path: string, params: Record<string, any> = {}): Promise<T> {
  const url = new URL(`${ATERA_BASE}${path}`);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, String(v));
  const res = await fetch(url, {
    headers: { "X-API-KEY": KEYS.atera!, Accept: "application/json" },
  });
  if (!res.ok) throw new Error(`Atera ${path} → ${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

async function collectAtera(): Promise<void> {
  if (!KEYS.atera) {
    addError("atera", "ATERA_API_KEY not set — see SUMMARY.md §2 #16");
    return;
  }
  try {
    const open = await ateraGet<any>("/tickets", { ticketStatus: "Open", itemsInPage: 50 });
    const items = open.items ?? [];
    out.support.atera_open_tickets = open.totalItemCount ?? items.length;
    out.support.atera_critical = items.filter((t: any) =>
      (t.TicketPriority ?? "").toLowerCase() === "critical" ||
      (t.TicketImpact   ?? "").toLowerCase() === "critical"
    ).length;
  } catch (e) { addError("atera.open", "open tickets fetch failed", e); }

  try {
    // MTTR (24h): resolved tickets where resolution-time was set in last 24h
    const resolved = await ateraGet<any>("/tickets", { ticketStatus: "Resolved", itemsInPage: 50 });
    const items = (resolved.items ?? []).filter((t: any) => {
      const closed = t.TicketClosedDate ?? t.LastModified;
      return closed && new Date(closed).getTime() >= NOW.getTime() - 86400_000;
    });
    if (items.length > 0) {
      const hours = items.map((t: any) => {
        const opened = new Date(t.TicketCreatedDate ?? t.Created).getTime();
        const closed = new Date(t.TicketClosedDate  ?? t.LastModified).getTime();
        return (closed - opened) / 3600_000;
      });
      out.support.atera_mttr_24h_hours = round(hours.reduce((a: number,b: number)=>a+b,0) / hours.length, 2);
    } else {
      out.support.atera_mttr_24h_hours = 0;
    }
  } catch (e) { addError("atera.mttr", "MTTR fetch failed", e); }
}

// ─────────────────────────────────────────────────────────────────────────
// 4. POSTGRES — Loki chat audit, tickets, call_transcripts, KB
// ─────────────────────────────────────────────────────────────────────────
async function collectPostgres(): Promise<void> {
  if (!KEYS.databaseUrl) {
    addError("postgres", "DATABASE_URL not set — collector cannot query Cloud86 Postgres");
    return;
  }
  // Use Bun.sql per CLAUDE.md preference
  let sql: any;
  try {
    sql = (Bun as any).sql;
    if (typeof sql !== "function" && !sql) throw new Error("Bun.sql not available — Bun ≥1.2 required");
  } catch (e) { addError("postgres.driver", "Bun.sql unavailable", e); return; }

  // Configure connection
  process.env.DATABASE_URL = KEYS.databaseUrl;

  // 4a. Loki chat stats from klaravex_loki_audit (last 24h, chat path)
  try {
    const rows = await sql`
      SELECT
        COUNT(*) FILTER (WHERE path LIKE '/api/v1/chat/%')                                    AS chat_sessions,
        COUNT(*) FILTER (WHERE path = '/api/v1/voice/escalate')                               AS chat_escalations,
        COUNT(*) FILTER (WHERE path LIKE '/api/v1/chat/%' AND response_status >= 500)         AS chat_errors
      FROM klaravex_loki_audit
      WHERE timestamp >= now() - interval '24 hours'
    `;
    const r = rows[0] ?? {};
    out.support.loki_chat_sessions_24h    = Number(r.chat_sessions    ?? 0);
    out.support.loki_chat_escalations_24h = Number(r.chat_escalations ?? 0);
    if (out.support.loki_chat_sessions_24h > 0) {
      out.support.loki_chat_escalation_rate =
        round(out.support.loki_chat_escalations_24h / out.support.loki_chat_sessions_24h, 4);
    }
  } catch (e) { addError("pg.audit", "klaravex_loki_audit query failed", e); }

  // 4b. Tickets open / resolved
  try {
    const rows = await sql`
      SELECT
        COUNT(*) FILTER (WHERE status IN ('open','in_progress','waiting_client'))                                AS open_total,
        COUNT(*) FILTER (WHERE status IN ('open','in_progress','waiting_client') AND source LIKE 'intake_b2b%')   AS open_b2b,
        COUNT(*) FILTER (WHERE status IN ('open','in_progress','waiting_client') AND source LIKE 'intake_consumer%') AS open_consumer,
        COUNT(*) FILTER (WHERE resolved_at >= now() - interval '24 hours')                                       AS resolved_24h
      FROM klaravex_tickets
    `;
    const r = rows[0] ?? {};
    out.support.tickets_open_total    = Number(r.open_total    ?? 0);
    out.support.tickets_open_b2b      = Number(r.open_b2b      ?? 0);
    out.support.tickets_open_consumer = Number(r.open_consumer ?? 0);
    out.support.tickets_resolved_24h  = Number(r.resolved_24h  ?? 0);
  } catch (e) { addError("pg.tickets", "klaravex_tickets query failed", e); }

  // 4c. Voice / call_transcripts
  try {
    const rows = await sql`
      SELECT
        COUNT(*)                                                                              AS total,
        COUNT(*) FILTER (WHERE outcome = 'payment_completed')                                 AS paid,
        COUNT(*) FILTER (WHERE outcome = 'escalated')                                         AS escalated,
        COUNT(*) FILTER (WHERE outcome = 'abandoned')                                         AS abandoned,
        COUNT(*) FILTER (WHERE outcome = 'resolved')                                          AS resolved,
        AVG(duration_seconds) FILTER (WHERE duration_seconds > 0)                             AS avg_dur
      FROM klaravex_call_transcripts
      WHERE created_at >= now() - interval '24 hours'
    `;
    const r = rows[0] ?? {};
    out.voice.calls_24h            = Number(r.total     ?? 0);
    out.voice.calls_paid_24h       = Number(r.paid      ?? 0);
    out.voice.calls_escalated_24h  = Number(r.escalated ?? 0);
    out.voice.calls_abandoned_24h  = Number(r.abandoned ?? 0);
    out.voice.calls_resolved_24h   = Number(r.resolved  ?? 0);
    out.voice.avg_duration_seconds = r.avg_dur != null ? Number(r.avg_dur) : null;
  } catch (e) { addError("pg.calls", "klaravex_call_transcripts query failed", e); }

  // 4d. KB top-cited (citation counts) — best-effort: look at tickets.history JSON
  // for chunk_id references in the last 7d. The audit_log doesn't yet record KB
  // citations directly (TODO: add migration); use tickets.metadata->'kb_citations'
  // when available.
  try {
    const rows = await sql`
      SELECT source_title, source_url, COUNT(*) AS cited
      FROM klaravex_kb_chunks c
      JOIN klaravex_tickets t
        ON t.metadata->'kb_citations' @> to_jsonb(ARRAY[c.id])
      WHERE t.updated_at >= now() - interval '7 days'
      GROUP BY source_title, source_url
      ORDER BY cited DESC
      LIMIT 5
    `;
    out.support.kb_top_5_cited = (rows ?? []).map((r: any) => ({
      title: r.source_title, url: r.source_url, cited_7d: Number(r.cited),
    }));
  } catch (e) {
    // Non-fatal — schema may not have kb_citations yet. Leave [] and record.
    addError("pg.kb_cited", "kb citation join not available (TODO: add citation tracking)", e);
  }

  // 4e. KB zero-result queries (24h) — heuristic from audit.request_summary
  try {
    const rows = await sql`
      SELECT request_summary
      FROM klaravex_loki_audit
      WHERE timestamp >= now() - interval '24 hours'
        AND path LIKE '/api/v1/chat/%'
        AND (request_summary ILIKE '%no kb match%' OR request_summary ILIKE '%no results%' OR request_summary ILIKE '%fallback%')
      ORDER BY timestamp DESC
      LIMIT 25
    `;
    out.support.kb_zero_result_queries_24h = (rows ?? []).map((r: any) => r.request_summary).filter(Boolean);
  } catch (e) { addError("pg.kb_zero", "kb zero-result heuristic failed", e); }

  // 4f. Anthony load — escalations pending
  try {
    const rows = await sql`
      SELECT
        COUNT(*)                                                            AS pending,
        EXTRACT(EPOCH FROM (now() - MIN(created_at)))/60.0                  AS oldest_min
      FROM klaravex_escalations
      WHERE acknowledged_at IS NULL
    `;
    const r = rows[0] ?? {};
    out.anthony_load.escalations_pending        = Number(r.pending ?? 0);
    out.anthony_load.escalations_oldest_minutes = r.oldest_min != null ? round(Number(r.oldest_min), 1) : null;
  } catch (e) { addError("pg.escalations", "escalations query failed", e); }

  try { await sql.end?.(); } catch { /* ignore */ }
}

// ─────────────────────────────────────────────────────────────────────────
// 5. INFRA — Azure metrics + healthchecks + API uptime + watchdog
// ─────────────────────────────────────────────────────────────────────────
async function collectInfra(): Promise<void> {
  // 5a. API health probe (zero-cost: hit /health on the live API)
  try {
    const t0 = performance.now();
    const res = await fetch(`${KLARAVEX_API}/health`, { signal: AbortSignal.timeout(5000) });
    const ms = performance.now() - t0;
    out.infrastructure.watchdog_status = res.ok ? "ok" : `http_${res.status}`;
    out.infrastructure.watchdog_last_success = res.ok ? NOW.toISOString() : out.infrastructure.watchdog_last_success;
    out.infrastructure.api_p95_ms = round(ms, 1); // single-sample proxy
  } catch (e) {
    out.infrastructure.watchdog_status = "unreachable";
    addError("infra.health", "API /health probe failed", e);
  }

  // 5b. Healthchecks.io read-only (status + last_ping)
  if (KEYS.healthchecks) {
    try {
      const res = await fetch(HEALTHCHECKS_RO, { headers: { "X-Api-Key": KEYS.healthchecks } });
      if (res.ok) {
        const data: any = await res.json();
        const checks: any[] = data.checks ?? [];
        const klx = checks.find(c => /klaravex/i.test(c.name ?? ""));
        if (klx) {
          out.infrastructure.watchdog_status = klx.status;
          if (klx.last_ping) out.infrastructure.watchdog_last_success = klx.last_ping;
        }
      }
    } catch (e) { addError("infra.healthchecks", "healthchecks.io fetch failed", e); }
  }

  // 5c. Azure replicas + CPU via `az` CLI if available (read-only, may need login)
  if (out.data_sources_available.azure_cli) {
    try {
      const proc = Bun.spawn(
        ["az", "containerapp", "show", "-n", "klaravex-api", "-g", "klaravex-prod",
         "--query", "{replicas: properties.template.scale, prov: properties.provisioningState}", "-o", "json"],
        { stdout: "pipe", stderr: "pipe" }
      );
      const code = await proc.exited;
      if (code === 0) {
        const json = await new Response(proc.stdout).json();
        out.infrastructure.azure_replicas_current = json?.replicas?.minReplicas ?? null;
      } else {
        const err = await new Response(proc.stderr).text();
        addError("infra.azure", "az containerapp show failed", err.slice(0, 200));
      }
    } catch (e) { addError("infra.azure", "az spawn failed", e); }
  }

  // OpenAI token spend: not exposed via free API → leave null, document as TODO.
  // (Spend is in OpenAI dashboard. Could be added via a usage-export cron later.)
}

// ─────────────────────────────────────────────────────────────────────────
// 6. ANTHONY LOAD — parse SUMMARY.md §2 for open T-prefixed directives
// ─────────────────────────────────────────────────────────────────────────
function collectAnthonyLoad(): void {
  if (!existsSync(SUMMARY_FILE)) { addError("summary", "SUMMARY.md missing"); return; }
  try {
    const md = readFileSync(SUMMARY_FILE, "utf8");
    // Slice §2 only
    const start = md.indexOf("## 2. Manual Follow-ups for Anthony");
    const end   = start >= 0 ? md.indexOf("\n## ", start + 5) : -1;
    if (start < 0) { addError("summary", "section §2 not found"); return; }
    const section = end > 0 ? md.slice(start, end) : md.slice(start);

    // T-id pattern: e.g. "**1. T8.6 — HIPAA …**" or "**2. T8.2 — E&O …**"
    // Track items whose line does NOT contain a clear "✅ DONE"/"BOUND ✅" closure
    // and whose T-id has not been struck through.
    const lines = section.split("\n");
    const open: string[] = [];
    for (const line of lines) {
      const m = line.match(/\*\*\s*\d+\.\s*(T[0-9]+(?:\.[0-9]+)*)\s*[—-]/);
      if (!m) continue;
      const tid = m[1];
      // Heuristic for "closed": header line contains DONE, COMPLETE, ✅ alone (not "BOUND ✅" mid-line)
      const closedRe = /\b(DONE|COMPLETE|RESOLVED)\b/i;
      const headerLine = line;
      if (closedRe.test(headerLine)) continue;
      open.push(tid);
    }
    out.anthony_load.open_directives_count = open.length;
    out.anthony_load.open_directive_ids    = open;
    // Oldest = first T-id encountered (SUMMARY tends to list oldest at top of §2)
    out.anthony_load.oldest_open_directive_id = open[0] ?? null;
    // We don't have per-directive timestamps in SUMMARY; leave null and document.
    out.anthony_load.oldest_open_directive_days = null;
  } catch (e) { addError("summary.parse", "SUMMARY.md parse failed", e); }
}

// ─────────────────────────────────────────────────────────────────────────
// 7. ANOMALY DETECTION + GROWTH PRIORITY SUGGESTIONS
// ─────────────────────────────────────────────────────────────────────────
function detectAnomalies(): void {
  const anomalies: { signal: string; severity: "info"|"warn"|"crit"; detail: string }[] = [];
  const priorities: string[] = [];

  const rev   = out.revenue;
  const camp  = out.campaigns;
  const sup   = out.support;
  const voc   = out.voice;
  const inf   = out.infrastructure;
  const load  = out.anthony_load;

  // Revenue
  if (rev.stripe_24h_usd != null && rev.stripe_24h_usd === 0) {
    anomalies.push({ signal: "revenue.stripe_24h_usd", severity: "warn", detail: "Zero Stripe revenue in last 24h" });
    priorities.push("[revenue] Push consumer Stripe links — last 24h is $0. Re-evaluate landing-page CTAs and Smartlead reply-to-checkout funnel.");
  }
  if (rev.churned_subs_24h != null && rev.churned_subs_24h > 0) {
    anomalies.push({ signal: "revenue.churned_subs_24h", severity: "warn", detail: `${rev.churned_subs_24h} subs churned in 24h` });
    priorities.push("[retention] Send winback to churned-24h cohort; review cancellation-intercept flow (migration 010).");
  }
  if (rev.mrr_usd != null && rev.mrr_usd > 0 && rev.arr_usd != null && rev.arr_usd < 50_000) {
    priorities.push("[scale] ARR < $50K — Klaravex remains on shared Hetzner per CLAUDE.md. Reassess dedicated VPS at $50K.");
  }

  // Campaigns
  for (const [name, c] of Object.entries(camp) as [string, any][]) {
    if (c.status === "active" && (c.sent_24h ?? 0) === 0) {
      anomalies.push({ signal: `campaigns.${name}`, severity: "warn", detail: "active but 0 sends in last 24h" });
      priorities.push(`[outreach] ${name} active but silent — check Smartlead schedule + warmup % for astewart@klaravex.com.`);
    }
    if (c.bounce_rate != null && c.bounce_rate > 0.05) {
      anomalies.push({ signal: `campaigns.${name}.bounce_rate`, severity: "crit", detail: `bounce ${(c.bounce_rate*100).toFixed(1)}% > 5% threshold` });
      priorities.push(`[deliverability] ${name} bounce rate ${(c.bounce_rate*100).toFixed(1)}% — PAUSE campaign, audit list quality.`);
    }
    if (c.reply_rate != null && c.reply_rate > 0.05 && (c.calendly_clicks ?? 0) === 0) {
      priorities.push(`[funnel] ${name} replies are warm but no Calendly clicks — tighten CTA in reply email.`);
    }
  }

  // Support
  if (sup.atera_critical != null && sup.atera_critical > 0) {
    anomalies.push({ signal: "support.atera_critical", severity: "crit", detail: `${sup.atera_critical} critical open ticket(s)` });
    priorities.push(`[support] ${sup.atera_critical} CRITICAL Atera ticket(s) open — Anthony attention required NOW.`);
  }
  if (sup.loki_chat_escalation_rate != null && sup.loki_chat_escalation_rate > 0.30) {
    anomalies.push({ signal: "support.escalation_rate", severity: "warn", detail: `escalation ${(sup.loki_chat_escalation_rate*100).toFixed(0)}% > 30%` });
    priorities.push("[loki-quality] Escalation rate >30% — review last 24h failed chats, add KB articles for top fallback topics.");
  }
  if (sup.kb_zero_result_queries_24h && sup.kb_zero_result_queries_24h.length > 10) {
    priorities.push(`[kb] ${sup.kb_zero_result_queries_24h.length} KB zero-result queries in 24h — author new KB article(s) for top topics.`);
  }

  // Voice
  if (voc.calls_abandoned_24h != null && voc.calls_24h != null && voc.calls_24h > 0) {
    const abrate = voc.calls_abandoned_24h / voc.calls_24h;
    if (abrate > 0.25) {
      anomalies.push({ signal: "voice.abandon_rate", severity: "warn", detail: `${(abrate*100).toFixed(0)}% abandoned` });
      priorities.push("[voice] >25% call abandonment — check Vapi assistant prompt + hold-music behaviour.");
    }
  }

  // Infrastructure
  if (inf.watchdog_status && !["ok","up"].includes(String(inf.watchdog_status))) {
    anomalies.push({ signal: "infra.watchdog", severity: "crit", detail: `watchdog status=${inf.watchdog_status}` });
    priorities.push("[infra] API watchdog unhealthy — investigate Azure Container App + DB connectivity FIRST.");
  }
  if (inf.api_p95_ms != null && inf.api_p95_ms > 1500) {
    anomalies.push({ signal: "infra.api_p95_ms", severity: "warn", detail: `p95 ${inf.api_p95_ms}ms > 1500ms` });
  }

  // Anthony load
  if (load.open_directives_count != null && load.open_directives_count > 10) {
    anomalies.push({ signal: "anthony_load.directives", severity: "warn", detail: `${load.open_directives_count} open directives` });
    priorities.push(`[anthony] ${load.open_directives_count} open T-directives in SUMMARY §2 — Loki should NOT spawn new directives this cycle; clear backlog.`);
  }
  if (load.escalations_pending != null && load.escalations_pending > 0) {
    priorities.push(`[escalation] ${load.escalations_pending} unacknowledged escalations in DB — surface to Anthony before any new outreach.`);
  }

  // Always-on guidance
  if (priorities.length === 0) {
    priorities.push("[steady] No anomalies detected. Continue current task queue from TASKS.md; consider running /retro at end of week.");
  }

  out.anomalies = anomalies;
  out.growth_priorities_suggested = priorities;
}

// ─────────────────────────────────────────────────────────────────────────
// Utility
// ─────────────────────────────────────────────────────────────────────────
function round(n: number, decimals = 2): number {
  const p = 10 ** decimals;
  return Math.round(n * p) / p;
}

// ─────────────────────────────────────────────────────────────────────────
// note_submissions logging
// ─────────────────────────────────────────────────────────────────────────
function logNoteSubmission(summary: string, payload: Record<string, unknown>): void {
  // TODO: When the vault MCP is wired into background scripts, swap this
  // fallback for a direct INSERT into note_submissions via vault.
  // For now: ALWAYS write the fallback row (CLAUDE.md policy: every action
  // logs; falling back is acceptable but must be flushed by Anthony later).
  const row = {
    agent_id: "claude-host-session/sub:collect-signals",
    topic: "observation",
    summary,
    payload,
    submitted_at: NOW.toISOString(),
  };
  try {
    mkdirSync(dirname(FALLBACK_NOTE), { recursive: true });
    appendFileSync(FALLBACK_NOTE, JSON.stringify(row) + "\n");
  } catch (e) {
    // Last-resort: leave a marker in collector_errors
    addError("note_submissions", "fallback file write failed", e);
  }
}

// ─────────────────────────────────────────────────────────────────────────
// Run
// ─────────────────────────────────────────────────────────────────────────
async function run(): Promise<void> {
  log("starting collect — flags:", FLAGS);

  const tasks: Array<[string, () => Promise<void> | void]> = [
    ["stripe",    collectStripe],
    ["smartlead", collectSmartlead],
    ["atera",     collectAtera],
    ["db",        collectPostgres],
    ["infra",     collectInfra],
    ["summary",   collectAnthonyLoad],
  ];

  for (const [name, fn] of tasks) {
    if (!wants(name)) { log("skip", name); continue; }
    log("run", name);
    try { await fn(); }
    catch (e) { addError(name, "unexpected throw", e); }
  }

  detectAnomalies();
  out.collector_status = out.collector_errors.length === 0 ? "ok" : "ok_with_errors";

  // Write
  if (FLAGS.dryRun) {
    console.log(JSON.stringify(out, null, 2));
  } else {
    await Bun.write(STATE_FILE, JSON.stringify(out, null, 2) + "\n");
    log("wrote", STATE_FILE);

    // events.jsonl append
    const ev = {
      timestamp: NOW.toISOString(),
      type: "business_signals_collected",
      data: {
        sources_ok: Object.entries(out.data_sources_available).filter(([,v]) => v).map(([k]) => k),
        errors:     out.collector_errors.length,
        mrr_usd:    out.revenue.mrr_usd,
        anomalies:  out.anomalies.length,
        priorities: out.growth_priorities_suggested.length,
      },
    };
    try {
      mkdirSync(dirname(EVENTS_FILE), { recursive: true });
      appendFileSync(EVENTS_FILE, JSON.stringify(ev) + "\n");
    } catch (e) { addError("events.jsonl", "append failed", e); }

    // note_submissions fallback row
    logNoteSubmission(
      `business-signals collected: ${out.anomalies.length} anomalies, ${out.growth_priorities_suggested.length} priorities, ${out.collector_errors.length} errors`,
      {
        collected_at: out.collected_at,
        mrr_usd: out.revenue.mrr_usd,
        anomalies: out.anomalies,
        sources_available: out.data_sources_available,
      },
    );
  }

  log("done");
}

run().catch((e) => {
  console.error("collect-signals fatal:", e);
  // Even on fatal error, try to write the partial state so Loki can see we tried
  out.collector_status = "fatal";
  out.collector_errors.push({ source: "main", message: String(e), at: new Date().toISOString() });
  try { Bun.write(STATE_FILE, JSON.stringify(out, null, 2) + "\n"); } catch { /* swallow */ }
  process.exit(1);
});
