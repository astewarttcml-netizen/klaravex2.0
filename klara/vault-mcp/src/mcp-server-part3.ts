// ============================================================
// mcp-server-part3.ts
// vault_read, vault_submit_note tools + HTTP server bootstrap.
// This is the entry point compiled to dist/mcp-server-part3.js.
// ============================================================

import { Server }                        from '@modelcontextprotocol/sdk/server/index.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';
import express, { Request, Response, NextFunction } from 'express';
import { randomUUID } from 'crypto';
import {
  loadConfig,
  initDb,
  setLogLevel,
  withClient,
  healthCheck,
  generateEmbedding,
  contentHash,
  log,
  McpToolResult,
} from './mcp-server-part1';
import { handleVaultSearch, VaultSearchParams } from './mcp-server-part2';

// -----------------------------------------------------------
// Tool: vault_read
// Retrieves the full content of a vault note by ID or path.
// -----------------------------------------------------------

async function handleVaultRead(params: {
  note_id?:   string;
  note_path?: string;
}): Promise<McpToolResult> {
  const { note_id, note_path } = params;

  if (!note_id && !note_path) {
    return mkErr('Provide either note_id (UUID) or note_path.');
  }

  log('info', 'vault_read called', { note_id, note_path });

  try {
    const row = await withClient(async (client) => {
      const sql = note_id
        ? 'SELECT id, note_path, note_title, content, metadata, created_at, updated_at FROM vault_embeddings WHERE id = $1'
        : 'SELECT id, note_path, note_title, content, metadata, created_at, updated_at FROM vault_embeddings WHERE note_path = $1';

      const { rows } = await client.query<{
        id:         string;
        note_path:  string;
        note_title: string | null;
        content:    string;
        metadata:   Record<string, unknown>;
        created_at: string;
        updated_at: string;
      }>(sql, [note_id ?? note_path]);

      return rows[0] ?? null;
    });

    if (!row) {
      return mkErr(`Note not found — id: ${note_id ?? '(none)'}, path: ${note_path ?? '(none)'}`);
    }

    return mkOk(JSON.stringify({
      id:         row.id,
      notePath:   row.note_path,
      noteTitle:  row.note_title,
      content:    row.content,
      metadata:   row.metadata,
      createdAt:  row.created_at,
      updatedAt:  row.updated_at,
    }, null, 2));
  } catch (e) {
    log('error', 'vault_read: DB error', { error: String(e) });
    return mkErr(`Database error: ${String(e)}`);
  }
}

// -----------------------------------------------------------
// Tool: vault_submit_note
// Upserts a note into vault_embeddings with an embedding.
// Falls back to the async queue if embedding generation fails.
// -----------------------------------------------------------

async function handleVaultSubmitNote(params: {
  content:    string;
  note_path?: string;
  note_title?: string;
  metadata?:  Record<string, unknown>;
}): Promise<McpToolResult> {
  const { content, note_path, note_title, metadata = {} } = params;

  if (!content || typeof content !== 'string' || content.trim().length === 0) {
    return mkErr('content must be a non-empty string.');
  }

  const config  = loadConfig();
  const trimmed = content.trim();
  const hash    = contentHash(trimmed);

  log('info', 'vault_submit_note called', { note_path, contentLength: trimmed.length });

  try {
    // --- fast path: note_path provided, try inline upsert ---
    if (note_path) {
      // Skip if content is identical
      const existing = await withClient(async (c) => {
        const { rows } = await c.query<{ content_hash: string }>(
          'SELECT content_hash FROM vault_embeddings WHERE note_path = $1',
          [note_path]
        );
        return rows[0] ?? null;
      });

      if (existing?.content_hash === hash) {
        return mkOk(JSON.stringify({
          status:    'unchanged',
          message:   'Note content unchanged — skipping re-index.',
          note_path,
        }));
      }

      // Generate embedding inline
      let embedding: number[] | null = null;
      try {
        embedding = await generateEmbedding(trimmed, config.embeddingModel);
      } catch (e) {
        log('warn', 'Inline embedding failed, falling back to queue', { error: String(e) });
      }

      if (embedding) {
        await withClient(async (client) => {
          await client.query(
            `INSERT INTO vault_embeddings
               (note_path, note_title, content, content_hash, embedding, metadata)
             VALUES ($1, $2, $3, $4, $5::vector, $6)
             ON CONFLICT (note_path) DO UPDATE SET
               note_title   = EXCLUDED.note_title,
               content      = EXCLUDED.content,
               content_hash = EXCLUDED.content_hash,
               embedding    = EXCLUDED.embedding,
               metadata     = EXCLUDED.metadata,
               updated_at   = NOW()`,
            [
              note_path,
              note_title ?? null,
              trimmed,
              hash,
              `[${embedding.join(',')}]`,
              JSON.stringify(metadata),
            ]
          );
        });

        log('info', 'vault_submit_note: upserted with embedding', { note_path });
        return mkOk(JSON.stringify({
          status:    'indexed',
          message:   'Note indexed successfully.',
          note_path,
        }));
      }
    }

    // --- slow path: queue for background worker ---
    const submissionId = await withClient(async (client) => {
      const { rows } = await client.query<{ id: string }>(
        `INSERT INTO note_submissions (content, metadata, status)
         VALUES ($1, $2, 'pending')
         RETURNING id`,
        [
          trimmed,
          JSON.stringify({ note_path: note_path ?? null, note_title: note_title ?? null, ...metadata }),
        ]
      );
      return rows[0].id;
    });

    log('info', 'vault_submit_note: queued for background processing', { submissionId });
    return mkOk(JSON.stringify({
      status:       'queued',
      submissionId,
      message:      'Note queued for background embedding (no inline embedding available). It will appear in search results within ~10 seconds.',
    }));
  } catch (e) {
    log('error', 'vault_submit_note: error', { error: String(e) });
    return mkErr(`Failed to submit note: ${String(e)}`);
  }
}

// -----------------------------------------------------------
// Background embedding worker
// Drains note_submissions queue in batches of 5.
// Uses SELECT ... FOR UPDATE SKIP LOCKED for concurrent-safe dequeue.
// -----------------------------------------------------------

async function runEmbeddingWorker(config: ReturnType<typeof loadConfig>): Promise<void> {
  try {
    // Claim a batch
    const rows = await withClient(async (client) => {
      const { rows } = await client.query<{
        id:       string;
        content:  string;
        metadata: Record<string, unknown>;
      }>(
        `UPDATE note_submissions
         SET status = 'processing'
         WHERE id IN (
           SELECT id FROM note_submissions
           WHERE status = 'pending'
           ORDER BY created_at
           LIMIT 5
           FOR UPDATE SKIP LOCKED
         )
         RETURNING id, content, metadata`
      );
      return rows;
    });

    if (rows.length === 0) return; // nothing to do

    log('info', 'Embedding worker: processing batch', { count: rows.length });

    await Promise.allSettled(
      rows.map(async (row) => {
        try {
          const embedding = await generateEmbedding(row.content, config.embeddingModel);
          const meta      = row.metadata as { note_path?: string; note_title?: string };
          const hash      = contentHash(row.content);

          await withClient(async (client) => {
            // Upsert into vault_embeddings if a path is known
            if (meta.note_path) {
              await client.query(
                `INSERT INTO vault_embeddings
                   (note_path, note_title, content, content_hash, embedding, metadata)
                 VALUES ($1, $2, $3, $4, $5::vector, $6)
                 ON CONFLICT (note_path) DO UPDATE SET
                   content      = EXCLUDED.content,
                   content_hash = EXCLUDED.content_hash,
                   embedding    = EXCLUDED.embedding,
                   metadata     = EXCLUDED.metadata,
                   updated_at   = NOW()`,
                [
                  meta.note_path,
                  meta.note_title ?? null,
                  row.content,
                  hash,
                  `[${embedding.join(',')}]`,
                  JSON.stringify(row.metadata),
                ]
              );
            }

            await client.query(
              `UPDATE note_submissions
               SET status = 'completed', processed_at = NOW()
               WHERE id = $1`,
              [row.id]
            );
          });
        } catch (e) {
          log('error', 'Worker: failed to process submission', { id: row.id, error: String(e) });
          await withClient((c) =>
            c.query(
              `UPDATE note_submissions
               SET status = 'failed', error_message = $2
               WHERE id = $1`,
              [row.id, String(e)]
            )
          ).catch(() => void 0);
        }
      })
    );
  } catch (e) {
    log('error', 'Embedding worker: unexpected error', { error: String(e) });
  }
}

// -----------------------------------------------------------
// MCP Server definition
// -----------------------------------------------------------

function buildMcpServer(readOnly: boolean = false): Server {
  const server = new Server(
    { name: 'loki-vault', version: '1.0.0' },
    { capabilities: { tools: {} } }
  );

  // Tool manifest
  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: [
      {
        name:        'vault_search',
        description: 'Semantic similarity search across the Klara AI vault. Returns ranked notes by cosine similarity to the query. Use for knowledge retrieval, context lookup, and finding related notes.',
        inputSchema: {
          type:       'object',
          properties: {
            query:     { type: 'string',  description: 'Natural language search query' },
            limit:     { type: 'number',  description: 'Max results to return (1–50). Default: 10.' },
            threshold: { type: 'number',  description: 'Minimum cosine similarity 0.0–1.0. Lower = broader. Default: 0.70.' },
          },
          required: ['query'],
        },
      },
      {
        name:        'vault_read',
        description: 'Retrieve the full text content of a specific vault note. Provide either note_id (UUID from vault_search) or note_path.',
        inputSchema: {
          type:       'object',
          properties: {
            note_id:   { type: 'string', description: 'UUID of the note (from vault_search results)' },
            note_path: { type: 'string', description: 'Relative file path, e.g. "Projects/Klara AI/overview.md"' },
          },
        },
      },
      {
        name:        'vault_submit_note',
        description: 'Submit a note to the vault for indexing. The note becomes searchable via vault_search within seconds. Use to persist new knowledge, decisions, or context.',
        inputSchema: {
          type:       'object',
          properties: {
            content:    { type: 'string', description: 'Full text content of the note (Markdown supported)' },
            note_path:  { type: 'string', description: 'Relative path, e.g. "Inbox/2026-05-29.md"' },
            note_title: { type: 'string', description: 'Human-readable title' },
            metadata:   { type: 'object', description: 'Arbitrary key-value metadata (tags, source, links, etc.)' },
          },
          required: ['content'],
        },
      },
    ],
  }));

  // Tool dispatcher
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  server.setRequestHandler(CallToolRequestSchema, async (req): Promise<any> => {
    const { name, arguments: args = {} } = req.params;
    const config = loadConfig();

    switch (name) {
      case 'vault_search':
        return handleVaultSearch(args as unknown as VaultSearchParams, {
          embeddingModel:   config.embeddingModel,
          defaultLimit:     config.vectorSearchLimit,
          defaultThreshold: config.vectorSimilarityThreshold,
        });

      case 'vault_read':
        return handleVaultRead(args as unknown as { note_id?: string; note_path?: string });

      case 'vault_submit_note':
        if (readOnly) {
          return mkErr('vault_submit_note is not permitted for this API key (read-only access).');
        }
        return handleVaultSubmitNote(args as unknown as {
          content:     string;
          note_path?:  string;
          note_title?: string;
          metadata?:   Record<string, unknown>;
        });

      default:
        return mkErr(`Unknown tool: ${name}`);
    }
  });

  return server;
}

// -----------------------------------------------------------
// HTTP server bootstrap
// -----------------------------------------------------------

async function main(): Promise<void> {
  const config = loadConfig();
  setLogLevel(config.logLevel);

  log('info', '=== Klara AI Vault MCP Server starting ===', { port: config.port });

  initDb(config.dbUrl);

  // Fail fast if DB is unreachable
  const h = await healthCheck();
  if (!h.db) {
    log('error', 'Cannot connect to database at startup. Exiting.');
    process.exit(1);
  }
  log('info', 'DB connected', { latencyMs: h.latencyMs });

  const app = express();
  app.use(express.json({ limit: '10mb' }));

  // CORS — required for browser-based and Electron-based MCP clients
  app.use((req, res, next) => {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-API-Key, Authorization, mcp-session-id, Accept');
    res.setHeader('Access-Control-Expose-Headers', 'mcp-session-id');
    if (req.method === 'OPTIONS') { res.status(204).end(); return; }
    next();
  });

  // --- Optional Bearer / X-API-Key auth ---
  // Two tiers: config.apiKey (full read/write) and config.apiKeyReadOnly
  // (read-only — vault_search/vault_read only, vault_submit_note blocked).
  // If config.apiKey is unset, auth is disabled entirely (unchanged behavior).
  const requireAuth = (req: Request, res: Response, next: NextFunction): void => {
    if (!config.apiKey) { next(); return; }
    const token =
      (req.headers['x-api-key'] as string | undefined) ??
      (req.headers['authorization'] as string | undefined)?.replace(/^Bearer\s+/i, '');
    if (token === config.apiKey) {
      (req as any).authLevel = 'write';
      next();
      return;
    }
    if (config.apiKeyReadOnly && token === config.apiKeyReadOnly) {
      (req as any).authLevel = 'readonly';
      next();
      return;
    }
    res.status(401).json({ error: 'Unauthorized' });
  };

  // --- Health endpoint (no auth) ---
  app.get('/health', async (_req, res) => {
    const h = await healthCheck();
    res.status(h.db ? 200 : 503).json({
      status:     h.db ? 'healthy' : 'degraded',
      db:         h.db,
      dbLatencyMs: h.latencyMs,
      poolTotal:  h.poolTotal,
      poolIdle:   h.poolIdle,
      uptime:     process.uptime(),
      timestamp:  new Date().toISOString(),
    });
  });

  // --- MCP Streamable HTTP transport (MCP spec 2024-11-05) ---
  // POST /mcp   → initialize new session or route to existing session
  // GET  /mcp   → SSE notification stream for an existing session
  // DELETE /mcp → explicit session teardown
  interface McpSession { transport: StreamableHTTPServerTransport; server: Server; }
  const sessions = new Map<string, McpSession>();

  app.post('/mcp', requireAuth, async (req, res) => {
    const sessionId = req.headers['mcp-session-id'] as string | undefined;

    // Existing session: route to its transport
    if (sessionId) {
      const session = sessions.get(sessionId);
      if (!session) { res.status(404).json({ error: `Session ${sessionId} not found or expired` }); return; }
      await session.transport.handleRequest(req, res, req.body);
      return;
    }

    // New session
    const authLevel = (req as any).authLevel as ('write' | 'readonly' | undefined);
    const mcpServer = buildMcpServer(authLevel === 'readonly');
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: () => randomUUID(),
      onsessioninitialized: (sid) => {
        sessions.set(sid, { transport, server: mcpServer });
        log('info', 'MCP session opened', { sessionId: sid, ip: req.ip });
      },
    });

    transport.onclose = () => {
      if (transport.sessionId) {
        sessions.delete(transport.sessionId);
        log('info', 'MCP session closed', { sessionId: transport.sessionId });
      }
    };

    await mcpServer.connect(transport);
    await transport.handleRequest(req, res, req.body);
  });

  // GET /mcp — SSE notification stream for an already-initialized session
  app.get('/mcp', requireAuth, async (req, res) => {
    const sessionId = req.headers['mcp-session-id'] as string | undefined;
    if (!sessionId) { res.status(400).json({ error: 'mcp-session-id header required' }); return; }
    const session = sessions.get(sessionId);
    if (!session) { res.status(404).json({ error: `Session ${sessionId} not found` }); return; }
    await session.transport.handleRequest(req, res);
  });

  // DELETE /mcp — explicit session teardown
  app.delete('/mcp', requireAuth, async (req, res) => {
    const sessionId = req.headers['mcp-session-id'] as string | undefined;
    if (sessionId) {
      const session = sessions.get(sessionId);
      if (session) {
        sessions.delete(sessionId);
        await session.transport.close();
        await session.server.close();
        log('info', 'MCP session deleted', { sessionId });
      }
    }
    res.status(200).end();
  });

  // --- Manual reindex trigger (used by sync.sh after git pull) ---
  app.post('/reindex', requireAuth, (_req, res) => {
    log('info', 'Manual reindex triggered via /reindex');
    runEmbeddingWorker(config).catch((e) =>
      log('error', 'Reindex worker error', { error: String(e) })
    );
    res.json({ status: 'triggered', timestamp: new Date().toISOString() });
  });

  // --- Submission status check ---
  app.get('/submission/:id', requireAuth, async (req, res) => {
    try {
      const row = await withClient(async (c) => {
        const { rows } = await c.query(
          'SELECT id, status, error_message, created_at, processed_at FROM note_submissions WHERE id = $1',
          [req.params.id]
        );
        return rows[0] ?? null;
      });
      if (!row) { res.status(404).json({ error: 'Submission not found' }); return; }
      res.json(row);
    } catch (e) {
      res.status(500).json({ error: String(e) });
    }
  });

  // Start listening
  const httpServer = app.listen(config.port, '0.0.0.0', () => {
    log('info', `Klara AI Vault MCP Server ready`, { port: config.port });
    log('info', `  Health:  http://0.0.0.0:${config.port}/health`);
    log('info', `  MCP:     http://0.0.0.0:${config.port}/mcp  (Streamable HTTP)`);
    log('info', `  Auth:    ${config.apiKey ? 'enabled (X-API-Key)' : 'disabled'}`);
  });

  // Background embedding worker — runs every workerIntervalMs
  const workerInterval = setInterval(() => {
    runEmbeddingWorker(config).catch((e) =>
      log('error', 'Background worker tick error', { error: String(e) })
    );
  }, config.workerIntervalMs);

  // Graceful shutdown
  const shutdown = async (signal: string): Promise<void> => {
    log('info', `${signal} received — shutting down gracefully`);
    clearInterval(workerInterval);
    httpServer.close(() => {
      log('info', 'HTTP server closed');
      process.exit(0);
    });
    setTimeout(() => process.exit(1), 10_000); // force-kill after 10 s
  };

  process.on('SIGTERM', () => shutdown('SIGTERM'));
  process.on('SIGINT',  () => shutdown('SIGINT'));
}

// -----------------------------------------------------------
// Local helpers
// -----------------------------------------------------------

function mkOk(text: string): McpToolResult {
  return { content: [{ type: 'text', text }] };
}

function mkErr(message: string): McpToolResult {
  return {
    content: [{ type: 'text', text: JSON.stringify({ error: message }) }],
    isError: true,
  };
}

// -----------------------------------------------------------
// Entry point
// -----------------------------------------------------------

main().catch((err) => {
  process.stderr.write(JSON.stringify({
    ts:  new Date().toISOString(),
    lvl: 'error',
    msg: 'Fatal startup error',
    error: String(err),
    stack: err instanceof Error ? err.stack : undefined,
  }) + '\n');
  process.exit(1);
});
