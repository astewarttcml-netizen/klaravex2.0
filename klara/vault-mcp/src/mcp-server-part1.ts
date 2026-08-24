// ============================================================
// mcp-server-part1.ts
// Core infrastructure: config, structured logging,
// PostgreSQL connection pool, and Ollama embedding service.
// ============================================================

import { Pool, PoolClient } from 'pg';
import crypto from 'crypto';

// -----------------------------------------------------------
// Config
// -----------------------------------------------------------

export interface ServerConfig {
  port: number;
  dbUrl: string;
  ollamaHost: string;
  ollamaModel: string;
  embeddingModel: string;       // alias for ollamaModel (used by part2/part3)
  embeddingDimensions: number;
  vectorSearchLimit: number;
  vectorSimilarityThreshold: number;
  apiKey: string | null;
  apiKeyReadOnly: string | null;
  logLevel: string;
  workerIntervalMs: number;
}

let _config: ServerConfig | null = null;

export function loadConfig(): ServerConfig {
  if (_config) return _config;

  const required = (key: string): string => {
    const val = process.env[key];
    if (!val) throw new Error(`Missing required environment variable: ${key}`);
    return val;
  };

  const ollamaModel = process.env.OLLAMA_MODEL ?? 'nomic-embed-text';

  _config = {
    port:                      parseInt(process.env.VAULT_PORT                    ?? '3141', 10),
    dbUrl:                     required('DATABASE_URL'),
    ollamaHost:                process.env.OLLAMA_HOST                            ?? 'http://ollama:11434',
    ollamaModel,
    embeddingModel:            ollamaModel,            // kept for call-site compatibility
    embeddingDimensions:       parseInt(process.env.EMBEDDING_DIMENSIONS          ?? '768',  10),
    vectorSearchLimit:         parseInt(process.env.VECTOR_SEARCH_LIMIT           ?? '10',   10),
    vectorSimilarityThreshold: parseFloat(process.env.VECTOR_SIMILARITY_THRESHOLD ?? '0.70'),
    apiKey:                    process.env.MCP_API_KEY                            || null,
    apiKeyReadOnly:            process.env.MCP_API_KEY_READONLY                   || null,
    logLevel:                  process.env.LOG_LEVEL                              ?? 'info',
    workerIntervalMs:          parseInt(process.env.WORKER_INTERVAL_MS            ?? '10000', 10),
  };

  return _config;
}

// -----------------------------------------------------------
// Logging
// -----------------------------------------------------------

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

const LOG_LEVEL_RANK: Record<LogLevel, number> = {
  debug: 0, info: 1, warn: 2, error: 3,
};

let _activeLogLevel: LogLevel = 'info';

export function setLogLevel(level: string): void {
  _activeLogLevel = (level as LogLevel) ?? 'info';
}

export function log(
  level: LogLevel,
  msg: string,
  meta?: Record<string, unknown>
): void {
  if (LOG_LEVEL_RANK[level] < LOG_LEVEL_RANK[_activeLogLevel]) return;
  const entry = JSON.stringify({ ts: new Date().toISOString(), lvl: level, msg, ...(meta ?? {}) });
  if (level === 'error' || level === 'warn') process.stderr.write(entry + '\n');
  else process.stdout.write(entry + '\n');
}

// -----------------------------------------------------------
// PostgreSQL connection pool
// -----------------------------------------------------------

let _pool: Pool | null = null;

export function initDb(dbUrl: string): Pool {
  _pool = new Pool({
    connectionString:        dbUrl,
    max:                     10,
    min:                     2,
    idleTimeoutMillis:       30_000,
    connectionTimeoutMillis: 5_000,
  });

  _pool.on('error', (err) => log('error', 'Unexpected DB pool error', { error: err.message }));
  return _pool;
}

export function getPool(): Pool {
  if (!_pool) throw new Error('DB pool not initialized — call initDb() first.');
  return _pool;
}

export async function withClient<T>(fn: (client: PoolClient) => Promise<T>): Promise<T> {
  const client = await getPool().connect();
  try { return await fn(client); }
  finally { client.release(); }
}

export async function healthCheck(): Promise<{
  db: boolean; latencyMs: number; poolTotal: number; poolIdle: number;
}> {
  const start = Date.now();
  try {
    await withClient((c) => c.query('SELECT 1'));
    const pool = getPool() as Pool & { totalCount: number; idleCount: number };
    return { db: true, latencyMs: Date.now() - start, poolTotal: pool.totalCount ?? 0, poolIdle: pool.idleCount ?? 0 };
  } catch (err) {
    log('error', 'Health check DB failed', { error: String(err) });
    return { db: false, latencyMs: Date.now() - start, poolTotal: 0, poolIdle: 0 };
  }
}

// -----------------------------------------------------------
// Ollama embedding service
// Uses the local Ollama instance — no external API key needed.
// Model: nomic-embed-text (768-dim, ~274MB, CPU-friendly)
// -----------------------------------------------------------

/**
 * Generate a semantic embedding vector via Ollama.
 * Falls back gracefully — throws on connection error so the
 * caller can decide to queue the note for retry.
 */
export async function generateEmbedding(
  text: string,
  model?: string
): Promise<number[]> {
  const config      = loadConfig();
  const targetModel = model ?? config.ollamaModel;
  const ollamaHost  = config.ollamaHost;
  // nomic-embed-text default num_ctx in Ollama is 2048 tokens.
  // Technical markdown tokenizes dense (~3 chars/token), so cap at 6000 chars
  // and explicitly request num_ctx 8192 to use the model's full capacity.
  const maxChars    = parseInt(process.env.EMBEDDING_MAX_CHARS ?? '6000', 10);
  const truncated   = text.trim().slice(0, maxChars);

  if (!truncated) throw new Error('Cannot embed empty text.');

  const response = await fetch(`${ollamaHost}/api/embeddings`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ model: targetModel, prompt: truncated, options: { num_ctx: 8192 } }),
    signal:  AbortSignal.timeout(30_000),
  });

  if (!response.ok) {
    const body = await response.text().catch(() => '');
    throw new Error(`Ollama /api/embeddings HTTP ${response.status}: ${body}`);
  }

  const data = await response.json() as { embedding?: number[] };
  if (!Array.isArray(data.embedding)) {
    throw new Error(`Ollama response missing embedding field: ${JSON.stringify(data)}`);
  }

  return data.embedding;
}

/**
 * Probe Ollama liveness and confirm the embedding model is available.
 * Returns { ready: true } if the model is loaded, or an error string.
 */
export async function checkOllama(): Promise<{ ready: boolean; error?: string }> {
  const config = loadConfig();
  try {
    const res = await fetch(`${config.ollamaHost}/api/tags`, { signal: AbortSignal.timeout(5_000) });
    if (!res.ok) return { ready: false, error: `Ollama /api/tags HTTP ${res.status}` };
    const data = await res.json() as { models?: Array<{ name: string }> };
    const models = (data.models ?? []).map((m) => m.name);
    const loaded = models.some((n) => n.startsWith(config.ollamaModel));
    if (!loaded) return { ready: false, error: `Model ${config.ollamaModel} not pulled yet. Run: docker exec loki-ollama ollama pull ${config.ollamaModel}` };
    return { ready: true };
  } catch (err) {
    return { ready: false, error: String(err) };
  }
}

// -----------------------------------------------------------
// Utilities
// -----------------------------------------------------------

export function contentHash(text: string): string {
  return crypto.createHash('sha256').update(text, 'utf8').digest('hex');
}

// -----------------------------------------------------------
// Shared types
// -----------------------------------------------------------

export interface SearchResult {
  id:         string;
  notePath:   string;
  noteTitle:  string | null;
  content:    string;
  similarity: number;
  metadata:   Record<string, unknown>;
}

export interface McpToolResult {
  content:  Array<{ type: 'text'; text: string }>;
  isError?: boolean;
}
