import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

export type FileExistsCheck = { type: "file_exists"; path: string };
export type FileContainsCheck = { type: "file_contains"; path: string; pattern: string };
export type Check = FileExistsCheck | FileContainsCheck;

export type ChecklistItem = { id: string; title: string; priority: string; checks: Check[] };
export type ChecklistCategory = { id: string; title: string; items: ChecklistItem[] };
export type Checklist = { categories: ChecklistCategory[] };

export function loadChecklist(path: string): Checklist {
  return JSON.parse(readFileSync(path, "utf8"));
}

export function createFileCache(root: string): (p: string) => string | null {
  const cache = new Map<string, string>();
  return (p: string): string | null => {
    const abs = join(root, p);
    if (!existsSync(abs)) return null;
    if (cache.has(abs)) return cache.get(abs)!;
    const t = readFileSync(abs, "utf8");
    cache.set(abs, t);
    return t;
  };
}

export function runCheck(check: Check, root: string, readCached: (p: string) => string | null): { passed: boolean; message: string } {
  if (check.type === "file_exists") {
    const exists = existsSync(join(root, check.path));
    return { passed: exists, message: `${check.path} should exist` };
  }
  const text = readCached(check.path);
  if (text === null) return { passed: false, message: `${check.path} should exist` };
  const passed = text.includes(check.pattern);
  return { passed, message: `${check.path} should contain "${check.pattern}"` };
}
