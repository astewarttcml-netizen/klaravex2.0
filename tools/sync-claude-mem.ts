#!/usr/bin/env bun
/**
 * sync-claude-mem.ts - Refresh Loki's semantic memory from claude-mem.
 *
 * Strategy: claude-mem is a stdio MCP server (not HTTP), so this tool runs in
 * one of three modes:
 *
 *   1. `--status` (default)
 *      Read memory-context.json. Report counts, last sync time, whether a sync
 *      is overdue (>24h since last_synced_at), and emit a JSON "sync brief"
 *      that an agent can use to do the actual claude-mem MCP search and
 *      append the results.
 *
 *   2. `--ingest <file.json>`
 *      Read a JSON file produced by an agent that ran the claude-mem MCP
 *      queries and emitted new patterns / anti-patterns / episodes in this
 *      tool's expected format. Merge them into patterns.json, anti-patterns.json,
 *      .loki/memory/episodic/, dedupe by id (skip if id already exists), and
 *      update memory-context.json + events.jsonl.
 *
 *   3. `--touch`
 *      Bump last_synced_at to now and next_sync_due to now+24h without
 *      otherwise modifying memory. Use when you've verified there are no
 *      new observations to ingest.
 *
 * The "ingest" file shape:
 *
 *   {
 *     "synced_at": "2026-06-10T09:52:31Z",
 *     "new_patterns": [{...same shape as patterns.json entries...}],
 *     "new_anti_patterns": [{...}],
 *     "new_episodes": [{...same shape as episodic/<file>.json...}]
 *   }
 *
 * READ-ONLY against claude-mem. Pure pull. No writes to claude-mem.
 */

import { resolve, dirname, join } from "node:path";

const ROOT = resolve(import.meta.dir, "..");
const CTX_PATH = join(ROOT, ".loki/state/memory-context.json");
const PATTERNS_PATH = join(ROOT, ".loki/memory/semantic/patterns.json");
const ANTI_PATTERNS_PATH = join(ROOT, ".loki/memory/semantic/anti-patterns.json");
const EPISODIC_DIR = join(ROOT, ".loki/memory/episodic");
const EVENTS_LOG = join(ROOT, ".loki/events.jsonl");

type Pattern = {
  id: string;
  title: string;
  summary: string;
  applies_to: string[];
  evidence_observation_ids: number[];
  discovered_at: string;
  uses_count: number;
  last_used: string | null;
};

type AntiPattern = {
  id: string;
  title: string;
  summary: string;
  symptoms: string[];
  preventive_action: string;
  evidence_observation_ids: number[];
  discovered_at: string;
  uses_count: number;
  last_used: string | null;
};

type Episode = {
  id: string;
  occurred_at: string;
  title: string;
  narrative: string;
  outcome: "success" | "failure" | "mixed";
  evidence_observation_ids: number[];
  tags: string[];
};

type MemoryContext = {
  schema_version: string;
  available: boolean;
  patterns_file: string;
  anti_patterns_file: string;
  episodic_dir: string;
  patterns_count: number;
  anti_patterns_count: number;
  episodes_count: number;
  last_synced_at: string;
  source: string;
  next_sync_due: string;
  sync_tool?: string;
  readme?: string;
  skill_integration_recommendation?: string;
};

type IngestPayload = {
  synced_at?: string;
  new_patterns?: Pattern[];
  new_anti_patterns?: AntiPattern[];
  new_episodes?: Episode[];
};

function nowISO(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

function addHoursISO(iso: string, hours: number): string {
  const d = new Date(iso);
  d.setUTCHours(d.getUTCHours() + hours);
  return d.toISOString().replace(/\.\d{3}Z$/, "Z");
}

async function readJSON<T>(path: string): Promise<T> {
  return JSON.parse(await Bun.file(path).text()) as T;
}

async function writeJSON(path: string, data: unknown): Promise<void> {
  await Bun.write(path, JSON.stringify(data, null, 2) + "\n");
}

async function appendEvent(event: Record<string, unknown>): Promise<void> {
  const line = JSON.stringify({ ts: nowISO(), ...event }) + "\n";
  const existing = (await Bun.file(EVENTS_LOG).exists())
    ? await Bun.file(EVENTS_LOG).text()
    : "";
  await Bun.write(EVENTS_LOG, existing + line);
}

async function ensureCtx(): Promise<MemoryContext> {
  if (!(await Bun.file(CTX_PATH).exists())) {
    const fresh: MemoryContext = {
      schema_version: "1.0",
      available: true,
      patterns_file: ".loki/memory/semantic/patterns.json",
      anti_patterns_file: ".loki/memory/semantic/anti-patterns.json",
      episodic_dir: ".loki/memory/episodic/",
      patterns_count: 0,
      anti_patterns_count: 0,
      episodes_count: 0,
      last_synced_at: nowISO(),
      source: "claude-mem MCP bridge",
      next_sync_due: addHoursISO(nowISO(), 24),
    };
    await writeJSON(CTX_PATH, fresh);
    return fresh;
  }
  return readJSON<MemoryContext>(CTX_PATH);
}

async function recomputeCounts(): Promise<{
  patterns: number;
  anti_patterns: number;
  episodes: number;
}> {
  const patternsDoc = await readJSON<{ patterns: Pattern[] }>(PATTERNS_PATH);
  const antiDoc = await readJSON<{ anti_patterns: AntiPattern[] }>(ANTI_PATTERNS_PATH);
  const glob = new Bun.Glob("*.json");
  let epCount = 0;
  for await (const _ of glob.scan({ cwd: EPISODIC_DIR })) epCount++;
  return {
    patterns: patternsDoc.patterns.length,
    anti_patterns: antiDoc.anti_patterns.length,
    episodes: epCount,
  };
}

async function cmdStatus(): Promise<void> {
  const ctx = await ensureCtx();
  const overdue = new Date(ctx.next_sync_due).getTime() <= Date.now();
  const counts = await recomputeCounts();

  const brief = {
    last_synced_at: ctx.last_synced_at,
    next_sync_due: ctx.next_sync_due,
    overdue,
    counts,
    sync_brief: {
      mcp_server: "mcp__plugin_claude-mem_mcp-search",
      suggested_calls: [
        `search({ query: "klaravex", dateStart: "${ctx.last_synced_at}", limit: 100 })`,
        `search({ query: "itexperts-berlin", dateStart: "${ctx.last_synced_at}", limit: 50 })`,
      ],
      then: "Filter for project == 'klaravex' or matches in title/narrative, fetch full details via get_observations([ids]), categorize into pattern / anti-pattern / episodic / noise, write a JSON file matching the ingest payload shape, then run: bun tools/sync-claude-mem.ts --ingest <file.json>",
    },
  };
  console.log(JSON.stringify(brief, null, 2));
}

async function cmdTouch(): Promise<void> {
  const ctx = await ensureCtx();
  const counts = await recomputeCounts();
  const ts = nowISO();
  const next: MemoryContext = {
    ...ctx,
    last_synced_at: ts,
    next_sync_due: addHoursISO(ts, 24),
    patterns_count: counts.patterns,
    anti_patterns_count: counts.anti_patterns,
    episodes_count: counts.episodes,
  };
  await writeJSON(CTX_PATH, next);
  await appendEvent({
    kind: "memory.sync.touch",
    counts,
    last_synced_at: ts,
    next_sync_due: next.next_sync_due,
  });
  console.log(`Touched. last_synced_at=${ts} next_sync_due=${next.next_sync_due}`);
}

async function cmdIngest(file: string): Promise<void> {
  const payload = await readJSON<IngestPayload>(resolve(file));
  const patternsDoc = await readJSON<{
    version: string;
    source: string;
    generated_at: string;
    notes?: string;
    patterns: Pattern[];
  }>(PATTERNS_PATH);
  const antiDoc = await readJSON<{
    version: string;
    source: string;
    generated_at: string;
    notes?: string;
    anti_patterns: AntiPattern[];
  }>(ANTI_PATTERNS_PATH);

  const existingP = new Set(patternsDoc.patterns.map((p) => p.id));
  const existingA = new Set(antiDoc.anti_patterns.map((a) => a.id));

  let addedP = 0;
  let addedA = 0;
  let addedE = 0;
  let skippedP = 0;
  let skippedA = 0;
  let skippedE = 0;

  for (const p of payload.new_patterns ?? []) {
    if (existingP.has(p.id)) {
      skippedP++;
      continue;
    }
    patternsDoc.patterns.push(p);
    existingP.add(p.id);
    addedP++;
  }

  for (const a of payload.new_anti_patterns ?? []) {
    if (existingA.has(a.id)) {
      skippedA++;
      continue;
    }
    antiDoc.anti_patterns.push(a);
    existingA.add(a.id);
    addedA++;
  }

  for (const e of payload.new_episodes ?? []) {
    const day = (e.occurred_at || nowISO()).slice(0, 10).replace(/-/g, "");
    const slug = (e.id || e.title)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 60);
    const path = join(EPISODIC_DIR, `${day}-${slug}.json`);
    if (await Bun.file(path).exists()) {
      skippedE++;
      continue;
    }
    await writeJSON(path, e);
    addedE++;
  }

  if (addedP > 0) {
    patternsDoc.generated_at = nowISO();
    await writeJSON(PATTERNS_PATH, patternsDoc);
  }
  if (addedA > 0) {
    antiDoc.generated_at = nowISO();
    await writeJSON(ANTI_PATTERNS_PATH, antiDoc);
  }

  const counts = await recomputeCounts();
  const ts = payload.synced_at ?? nowISO();
  const ctx = await ensureCtx();
  const next: MemoryContext = {
    ...ctx,
    last_synced_at: ts,
    next_sync_due: addHoursISO(ts, 24),
    patterns_count: counts.patterns,
    anti_patterns_count: counts.anti_patterns,
    episodes_count: counts.episodes,
  };
  await writeJSON(CTX_PATH, next);

  await appendEvent({
    kind: "memory.sync.ingest",
    source_file: file,
    added: { patterns: addedP, anti_patterns: addedA, episodes: addedE },
    skipped_duplicates: { patterns: skippedP, anti_patterns: skippedA, episodes: skippedE },
    counts,
  });

  console.log(
    JSON.stringify(
      {
        added: { patterns: addedP, anti_patterns: addedA, episodes: addedE },
        skipped_duplicates: {
          patterns: skippedP,
          anti_patterns: skippedA,
          episodes: skippedE,
        },
        counts,
        last_synced_at: ts,
        next_sync_due: next.next_sync_due,
      },
      null,
      2,
    ),
  );
}

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  const cmd = args[0] ?? "--status";
  switch (cmd) {
    case "--status":
      await cmdStatus();
      break;
    case "--touch":
      await cmdTouch();
      break;
    case "--ingest": {
      const file = args[1];
      if (!file) {
        console.error("Usage: bun tools/sync-claude-mem.ts --ingest <file.json>");
        process.exit(2);
      }
      await cmdIngest(file);
      break;
    }
    case "-h":
    case "--help":
      console.log(`
sync-claude-mem.ts - refresh Loki's semantic memory from claude-mem

USAGE
  bun tools/sync-claude-mem.ts [--status]                 Print status + sync brief
  bun tools/sync-claude-mem.ts --ingest <file.json>       Merge new memories from file
  bun tools/sync-claude-mem.ts --touch                    Bump last_synced_at only

The ingest file shape is documented in the file header.
`);
      break;
    default:
      console.error(`Unknown command: ${cmd}. Try --help.`);
      process.exit(2);
  }
}

await main();
