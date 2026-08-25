#!/usr/bin/env bun
/**
 * atera-session-link.ts
 *
 * Attempts to generate an Atera Splashtop SOS attended-session link for a
 * given customer email address.
 *
 * Usage:
 *   bun tools/atera-session-link.ts customer@example.com
 *
 * API key resolution order:
 *   1. ATERA_API_KEY environment variable
 *   2. /tmp/klaravex_session_keys/atera_key (local dev cache)
 *   3. /opt/loki/envs/.env.klaravex (Hetzner production env file)
 *
 * IMPORTANT — Atera API / Splashtop SOS limitation:
 *   The Atera REST API v3 (app.atera.com/api/v3) does NOT expose an endpoint
 *   for generating Splashtop SOS attended-session links programmatically.
 *   SOS link generation is a UI-only action inside the Atera technician portal.
 *
 *   This script:
 *   - Resolves the customer's Atera Contact record via the Contacts API
 *   - Prints the Atera UI deep-link to start a Splashtop SOS session for that
 *     contact (opens in the Atera app, where you click "Start SOS session")
 *   - Prints the manual steps Anthony should follow if the deep-link is not
 *     sufficient
 *
 *   If Atera ever exposes a native SOS API endpoint, replace the section
 *   marked "TODO: SOS API" below.
 */

const ATERA_BASE = "https://app.atera.com/api/v3";

// ---------------------------------------------------------------------------
// Resolve API key
// ---------------------------------------------------------------------------
async function resolveApiKey(): Promise<string> {
  // 1. Env var (set by shell or Docker)
  if (process.env.ATERA_API_KEY) {
    return process.env.ATERA_API_KEY.trim();
  }

  // 2. Local dev cache
  const localKeyPath = "/tmp/klaravex_session_keys/atera_key";
  const localFile = Bun.file(localKeyPath);
  if (await localFile.exists()) {
    return (await localFile.text()).trim();
  }

  // 3. Hetzner env file — parse .env format
  const hetznerEnvPath = "/opt/loki/envs/.env.klaravex";
  const hetznerFile = Bun.file(hetznerEnvPath);
  if (await hetznerFile.exists()) {
    const envText = await hetznerFile.text();
    for (const line of envText.split("\n")) {
      const match = line.match(/^ATERA_API_KEY\s*=\s*["']?(.+?)["']?\s*$/);
      if (match) return match[1].trim();
    }
  }

  throw new Error(
    "ATERA_API_KEY not found. Set via:\n" +
      "  export ATERA_API_KEY=<your-key>   (or)\n" +
      "  echo '<key>' > /tmp/klaravex_session_keys/atera_key   (or)\n" +
      "  add ATERA_API_KEY=<key> to /opt/loki/envs/.env.klaravex\n\n" +
      "Retrieve your key from: app.atera.com → Admin → API (top-right avatar menu)"
  );
}

// ---------------------------------------------------------------------------
// Atera API helpers
// ---------------------------------------------------------------------------
async function ateraGet(path: string, apiKey: string): Promise<unknown> {
  const res = await fetch(`${ATERA_BASE}${path}`, {
    headers: {
      "X-API-KEY": apiKey,
      Accept: "application/json",
    },
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "(no body)");
    throw new Error(`Atera API ${path} → HTTP ${res.status}: ${body}`);
  }

  return res.json();
}

// ---------------------------------------------------------------------------
// Find contact by email
// ---------------------------------------------------------------------------
interface AteraContact {
  CustomerID: number;
  CustomerName: string;
  ContactID: number;
  Firstname: string;
  Lastname: string;
  Email: string;
}

async function findContactByEmail(
  email: string,
  apiKey: string
): Promise<AteraContact | null> {
  // Atera v3 Contacts endpoint — search by email
  // GET /api/v3/contacts?email=<email>
  const data = (await ateraGet(
    `/contacts?email=${encodeURIComponent(email)}`,
    apiKey
  )) as { items?: AteraContact[]; totalPages?: number };

  const items = data?.items ?? [];
  return items.length > 0 ? items[0] : null;
}

// ---------------------------------------------------------------------------
// TODO: SOS API — placeholder for future native endpoint
//
// As of June 2026, Atera v3 does NOT expose an SOS session-link endpoint.
// When/if Atera adds one (expected endpoint shape based on Atera community
// requests):
//
//   POST /api/v3/remotesessions/sos
//   Body: { ContactEmail: string, CustomerID: number }
//   Response: { SessionCode: string, SessionUrl: string, ExpiresAt: string }
//
// Replace the printManualSteps() call below with that API call.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Print manual steps (current approach until Atera exposes SOS API)
// ---------------------------------------------------------------------------
function printManualSteps(email: string, contact: AteraContact | null): void {
  console.log("");
  console.log("=".repeat(70));
  console.log("DIRECTIVE — Atera Splashtop SOS session for: " + email);
  console.log("=".repeat(70));
  console.log("");
  console.log(
    "The Atera REST API v3 does NOT support programmatic SOS link generation."
  );
  console.log(
    "SOS (attended remote session) links are created inside the Atera UI only."
  );
  console.log("");

  if (contact) {
    console.log(
      `Contact found: ${contact.Firstname} ${contact.Lastname} (${contact.Email})`
    );
    console.log(`  Customer: ${contact.CustomerName} (ID: ${contact.CustomerID})`);
    console.log(`  Contact ID: ${contact.ContactID}`);
    console.log("");
    console.log("Atera UI deep-links (open in browser while logged in):");
    console.log(
      `  Customer record:  https://app.atera.com/#/customer/${contact.CustomerID}`
    );
    console.log(
      `  Contact record:   https://app.atera.com/#/contact/${contact.ContactID}`
    );
    console.log("");
  } else {
    console.log(
      `No Atera contact found for email: ${email}`
    );
    console.log(
      "  You may need to create a contact first at app.atera.com → Customers."
    );
    console.log("");
  }

  console.log("Manual steps to generate a Splashtop SOS attended-session link:");
  console.log("  1. Open app.atera.com and log in as a technician.");
  console.log("  2. Go to the customer/contact record (links above if found).");
  console.log(
    '  3. Click the "Remote Access" button → "Splashtop SOS" → "Start Session".'
  );
  console.log(
    "  4. A 9-digit SOS code is generated. Share it with the customer OR"
  );
  console.log(
    '     click "Send via Email" to send the session link directly to their inbox.'
  );
  console.log("  5. Customer downloads sos.exe / SOS app, enters the code, clicks Join.");
  console.log("");
  console.log("Alternative — email the customer a pre-built SOS download link:");
  console.log("  Splashtop SOS download: https://www.splashtop.com/sos");
  console.log("  (Customer downloads, runs, reads code to you OR you see it in Atera.)");
  console.log("");
  console.log(
    "If you need this automated in future: upvote the Atera feature request at"
  );
  console.log("  https://community.atera.com → Feature Requests → 'SOS API'");
  console.log("  or contact Atera support to request a /remotesessions/sos endpoint.");
  console.log("=".repeat(70));
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
async function main(): Promise<void> {
  const email = process.argv[2];

  if (!email || !email.includes("@")) {
    console.error(
      "Usage: bun tools/atera-session-link.ts customer@example.com"
    );
    process.exit(1);
  }

  console.log(`Klaravex — Atera Splashtop SOS session generator`);
  console.log(`Customer email: ${email}`);
  console.log("");

  let apiKey: string;
  try {
    apiKey = await resolveApiKey();
    console.log("API key: resolved ✓");
  } catch (err) {
    console.error("ERROR resolving API key:");
    console.error((err as Error).message);
    process.exit(1);
  }

  let contact: AteraContact | null = null;
  try {
    console.log("Looking up contact in Atera...");
    contact = await findContactByEmail(email, apiKey);
    if (contact) {
      console.log(
        `Contact: ${contact.Firstname} ${contact.Lastname} (ID: ${contact.ContactID})`
      );
    } else {
      console.log(`No contact found for ${email} in Atera.`);
    }
  } catch (err) {
    console.warn(
      `Warning: could not query Atera contacts — ${(err as Error).message}`
    );
    console.warn("Continuing with manual-steps output...");
  }

  // TODO: SOS API — when Atera exposes a native endpoint, call it here
  // and print the session URL directly instead of printManualSteps().
  printManualSteps(email, contact);
}

main().catch((err) => {
  console.error("Unhandled error:", err);
  process.exit(1);
});
