// ============================================================
// mcp-server-part2.ts
// vault_search tool: semantic similarity search over the vault.
// Generates a query embedding via OpenAI, then runs a cosine
// ANN query against vault_embeddings using pgvector.
// ============================================================

import {
  generateEmbedding,
  withClient,
  log,
  SearchResult,
  McpToolResult,
} from './mcp-server-part1';

export interface VaultSearchParams {
  query:     string;
  limit?:    number;
  threshold?: number;
}

export interface VaultSearchConfig {
  embeddingModel:   string;
  defaultLimit:     number;
  defaultThreshold: number;
}

export async function handleVaultSearch(
  params: VaultSearchParams,
  config: VaultSearchConfig
): Promise<McpToolResult> {
  const {
    query,
    limit     = config.defaultLimit,
    threshold = config.defaultThreshold,
  } = params;

  // --- input validation ---
  if (!query || typeof query !== 'string' || query.trim().length === 0) {
    return err('query must be a non-empty string.');
  }

  const safeLimit     = clamp(limit,     1,  50);
  const safeThreshold = clamp(threshold, 0,  1);

  log('info', 'vault_search called', {
    query:     query.slice(0, 120),
    limit:     safeLimit,
    threshold: safeThreshold,
  });

  // --- generate query embedding ---
  let queryEmbedding: number[];
  try {
    queryEmbedding = await generateEmbedding(query.trim(), config.embeddingModel);
  } catch (e) {
    log('error', 'vault_search: embedding generation failed', { error: String(e) });
    return err(`Failed to generate query embedding: ${String(e)}`);
  }

  // --- vector search ---
  try {
    const rows = await withClient(async (client) => {
      // pgvector cosine distance: 1 - (embedding <=> query) = cosine similarity
      const { rows } = await client.query<{
        id:         string;
        note_path:  string;
        note_title: string | null;
        content:    string;
        similarity: number;
        metadata:   Record<string, unknown>;
      }>(
        `SELECT
           id,
           note_path,
           note_title,
           content,
           (1 - (embedding <=> $1::vector))::float AS similarity,
           metadata
         FROM vault_embeddings
         WHERE embedding IS NOT NULL
           AND (1 - (embedding <=> $1::vector)) >= $2
         ORDER BY embedding <=> $1::vector   -- ascending distance = descending similarity
         LIMIT $3`,
        [
          `[${queryEmbedding.join(',')}]`,
          safeThreshold,
          safeLimit,
        ]
      );
      return rows;
    });

    const results: SearchResult[] = rows.map((r) => ({
      id:         r.id,
      notePath:   r.note_path,
      noteTitle:  r.note_title,
      // Truncate content in search results; use vault_read for the full text.
      content:    r.content.length > 2_000
                    ? r.content.slice(0, 2_000) + '\n…[truncated — use vault_read for full content]'
                    : r.content,
      similarity: Math.round(r.similarity * 1_000) / 1_000,
      metadata:   r.metadata,
    }));

    log('info', 'vault_search complete', {
      hits:     results.length,
      topScore: results[0]?.similarity ?? null,
    });

    const payload =
      results.length > 0
        ? { results, total: results.length }
        : {
            results: [],
            total:   0,
            message: `No notes found above similarity threshold (${safeThreshold}). Try a lower threshold or a different query.`,
          };

    return ok(JSON.stringify(payload, null, 2));
  } catch (e) {
    log('error', 'vault_search: DB query failed', { error: String(e) });
    return err(`Database query failed: ${String(e)}`);
  }
}

// -----------------------------------------------------------
// Local helpers
// -----------------------------------------------------------

function ok(text: string): McpToolResult {
  return { content: [{ type: 'text', text }] };
}

function err(message: string): McpToolResult {
  return {
    content: [{ type: 'text', text: JSON.stringify({ error: message }) }],
    isError: true,
  };
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}
