import { test, expect } from "bun:test";
import { existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { loadChecklist, createFileCache, runCheck } from "../src/checklist.ts";

const ROOT = join(dirname(import.meta.dir), ".");
const CHECKLIST_PATH = join(ROOT, ".loki/checklist/checklist.json");

const checklist = loadChecklist(CHECKLIST_PATH);
const readCached = createFileCache(ROOT);

for (const cat of checklist.categories) {
  for (const item of cat.items) {
    test(`${item.id} [${item.priority}] ${item.title}`, () => {
      for (const check of item.checks) {
        const result = runCheck(check, ROOT, readCached);
        expect(result.passed, result.message).toBe(true);
      }
    });
  }
}

test("ADR 0001-0010 files exist", () => {
  const adrDir = "architecture/adr";
  const expected = [
    "adr-0001-azure-germany-region.md",
    "adr-0002-permission-filter-at-retrieval.md",
    "adr-0003-no-copy-tourism-data-hub.md",
    "adr-0004-audit-log-two-tier.md",
    "adr-0005-azure-openai-not-openai.md",
    "adr-0006-entra-id-for-roles.md",
    "adr-0007-mailbox-opt-in-only.md",
    "adr-0008-hybrid-retrieval.md",
    "adr-0009-bicep-over-terraform.md",
    "adr-0010-backend-runtime-bun.md",
  ];
  for (const name of expected) {
    const p = join(ROOT, adrDir, name);
    expect(existsSync(p), `${name} should exist`).toBe(true);
  }
});

test("Iteration-2 review fixes are present", () => {
  const arch = readCached("architecture/architecture.md")!;
  expect(arch).toContain("TTFT subtotal");
  expect(arch).toContain("Full-answer wall-clock");
  expect(arch).toContain("hit-rate target ≥95");
  expect(arch).toContain("Per-mode budgets");
  expect(arch).toContain("semantic-ranker-v2");

  const residency = readCached("compliance/data-residency.md")!;
  expect(residency).toContain("France-Central");
  expect(residency).toContain("~15–20 ms");

  const adr10 = readCached("architecture/adr/adr-0010-backend-runtime-bun.md")!;
  expect(adr10).toContain("Klaravex internal benchmark");
  expect(adr10).toContain("Bun 1.2.x median 180 ms");

  const decisions = readCached("DECISIONS.md")!;
  expect(decisions).toContain("Circuit breaker");
  expect(decisions).toContain("Per-request timeout: 800 ms");
});
