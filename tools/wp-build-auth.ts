#!/usr/bin/env bun
// PRD Phase 0 — Auth probe + slug inventory for klaravex.com WordPress.
// Resolves a usable {username, app_password} pair, verifies edit_pages capability,
// inventories existing page slugs, and writes .loki/wp-auth.json.
// No page POSTs happen here — Phase 2 is a separate runner.

import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const WP_BASE = "https://klaravex.com/wp-json/wp/v2";
const PROJECT_ROOT = new URL("..", import.meta.url).pathname.replace(/\/$/, "");
const LOKI_DIR = join(PROJECT_ROOT, ".loki");
const SCRATCH = join(LOKI_DIR, ".wp_app_pass.scratch");
const AUTH_OUT = join(LOKI_DIR, "wp-auth.json");

const USERNAME_CANDIDATES = [
  "loki",
  "loki-app",
  "loki_app",
  "loki-api",
  "klaravex",
  "kvx_6e383878",
  "astewart",
  "anthony",
  "anthonystewart",
  "astewart.tcml@gmail.com",
];

type MeResponse = {
  id: number;
  username?: string;
  slug?: string;
  name?: string;
  capabilities?: Record<string, boolean>;
};

type PageRow = { id: number; slug: string; status: string; link: string };

async function fetchAppPassword(): Promise<string> {
  if (process.env.WP_APP_PASS) {
    return process.env.WP_APP_PASS.trim();
  }
  if (existsSync(SCRATCH)) {
    const pw = readFileSync(SCRATCH, "utf8").trim();
    rmSync(SCRATCH);
    return pw;
  }
  // 1Password CLI path — last resort. Will throw on vault-locked timeout.
  const proc = Bun.spawn(
    [
      "op",
      "item",
      "get",
      "2b2i27eib6v43bsogeaydmagbu",
      "--fields",
      "password",
      "--reveal",
    ],
    { stdout: "pipe", stderr: "pipe" },
  );
  const code = await proc.exited;
  if (code !== 0) {
    const err = await new Response(proc.stderr).text();
    throw new Error(`op CLI failed (exit ${code}): ${err.trim()}`);
  }
  return (await new Response(proc.stdout).text()).trim();
}

function basicAuth(user: string, pass: string): string {
  return "Basic " + Buffer.from(`${user}:${pass}`).toString("base64");
}

async function probeUser(
  user: string,
  pass: string,
): Promise<{ ok: boolean; status: number; me?: MeResponse }> {
  const res = await fetch(`${WP_BASE}/users/me?context=edit`, {
    headers: { Authorization: basicAuth(user, pass) },
  });
  if (res.status !== 200) return { ok: false, status: res.status };
  const me = (await res.json()) as MeResponse;
  return { ok: true, status: 200, me };
}

async function inventoryPages(
  user: string,
  pass: string,
): Promise<PageRow[]> {
  const rows: PageRow[] = [];
  for (let page = 1; page <= 20; page++) {
    const url = `${WP_BASE}/pages?per_page=100&status=any&page=${page}&context=edit&_fields=id,slug,status,link`;
    const res = await fetch(url, { headers: { Authorization: basicAuth(user, pass) } });
    if (res.status === 400) break; // wp returns 400 for empty pages beyond total
    if (!res.ok) throw new Error(`inventory page ${page} failed: HTTP ${res.status}`);
    const batch = (await res.json()) as PageRow[];
    rows.push(...batch);
    if (batch.length < 100) break;
  }
  return rows;
}

async function main(): Promise<void> {
  if (!existsSync(LOKI_DIR)) mkdirSync(LOKI_DIR, { recursive: true });

  console.log("Phase 0 — Auth & inventory");
  let appPass: string;
  try {
    appPass = await fetchAppPassword();
  } catch (e) {
    console.error("FATAL: could not fetch App Password.");
    console.error(String(e));
    console.error("");
    console.error("Recovery options (run one, then re-run this script):");
    console.error(
      "  1) Unlock 1Password (any `op` command, e.g. `op vault list`) — biometric prompt",
    );
    console.error(
      "  2) export WP_APP_PASS='<paste from 1Password item 2b2i27eib6v43bsogeaydmagbu>'",
    );
    console.error(
      `  3) umask 077; printf '%s' '<paste>' > ${SCRATCH}  (will be auto-deleted)`,
    );
    process.exit(2);
  }

  if (!appPass || appPass.length < 20) {
    console.error(
      `FATAL: App Password looks invalid (length ${appPass.length}).`,
    );
    process.exit(2);
  }
  console.log(`  app_password: <fetched, ${appPass.length} chars>`);

  console.log("  probing usernames...");
  const tried: { username: string; status: number }[] = [];
  let winner: { username: string; me: MeResponse } | null = null;
  for (const user of USERNAME_CANDIDATES) {
    const r = await probeUser(user, appPass);
    tried.push({ username: user, status: r.status });
    console.log(`    ${user} -> HTTP ${r.status}`);
    if (r.ok && r.me) {
      winner = { username: user, me: r.me };
      break;
    }
  }

  if (!winner) {
    console.error("FATAL: no username candidate authenticated.");
    console.error("Verify the actual WP user at:");
    console.error("  https://klaravex.com/wp-admin/users.php");
    writeFileSync(
      AUTH_OUT,
      JSON.stringify(
        { status: "FAILED", candidates_tried: tried, timestamp: new Date().toISOString() },
        null,
        2,
      ),
    );
    process.exit(3);
  }

  const caps = winner.me.capabilities ?? {};
  const editPages = caps.edit_pages === true;
  console.log(
    `  winner: ${winner.username} (wp_id=${winner.me.id}, edit_pages=${editPages})`,
  );
  if (!editPages) {
    console.error("FATAL: authenticated user lacks edit_pages capability.");
    writeFileSync(
      AUTH_OUT,
      JSON.stringify(
        {
          status: "INSUFFICIENT_CAPS",
          username: winner.username,
          wp_id: winner.me.id,
          capabilities: caps,
          candidates_tried: tried,
          timestamp: new Date().toISOString(),
        },
        null,
        2,
      ),
    );
    process.exit(4);
  }

  console.log("  inventorying existing page slugs...");
  const pages = await inventoryPages(winner.username, appPass);
  console.log(`  existing pages: ${pages.length}`);

  const authRecord = {
    status: "READY",
    username: winner.username,
    wp_id: winner.me.id,
    wp_slug: winner.me.slug,
    wp_name: winner.me.name,
    capabilities: {
      edit_pages: caps.edit_pages ?? false,
      publish_pages: caps.publish_pages ?? false,
      edit_others_pages: caps.edit_others_pages ?? false,
    },
    candidates_tried: tried,
    existing_slugs: pages.map((p) => ({ id: p.id, slug: p.slug, status: p.status })),
    rest_base: WP_BASE,
    timestamp: new Date().toISOString(),
  };
  writeFileSync(AUTH_OUT, JSON.stringify(authRecord, null, 2));
  console.log(`  wrote ${AUTH_OUT}`);
  console.log("Phase 0 OK.");
}

main().catch((e) => {
  console.error("UNCAUGHT:", e);
  process.exit(1);
});
