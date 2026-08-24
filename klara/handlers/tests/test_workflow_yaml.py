"""
Validate every workflow YAML in infra/loki-flows/ — must parse and have the
required top-level keys.

Run as a script:
    python3 infra/loki-handlers/tests/test_workflow_yaml.py
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


FLOWS_DIR = Path(__file__).resolve().parent.parent.parent / "loki-flows"
REQUIRED_KEYS = {"id", "name", "segment", "states", "triggers"}


def main() -> int:
    if yaml is None:  # pragma: no cover
        print("SKIP  pyyaml not installed — pip install pyyaml")
        return 0

    if not FLOWS_DIR.exists():
        print(f"FAIL  flows dir missing: {FLOWS_DIR}")
        return 1

    failures = 0
    files = sorted(FLOWS_DIR.glob("*.yaml"))
    if len(files) < 8:
        print(f"FAIL  expected at least 8 archetype flows, found {len(files)}")
        failures += 1

    seen_archetypes: set[str] = set()
    for path in files:
        try:
            with open(path) as fh:
                doc = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            failures += 1
            print(f"FAIL  {path.name} :: YAML parse error: {exc}")
            continue

        missing = REQUIRED_KEYS - set(doc.keys())
        if missing:
            failures += 1
            print(f"FAIL  {path.name} :: missing keys {missing}")
            continue

        # id must look like A1..A8
        arch_id = str(doc["id"]).strip()
        if not (len(arch_id) == 2 and arch_id.startswith("A") and arch_id[1].isdigit()):
            failures += 1
            print(f"FAIL  {path.name} :: id {arch_id!r} not A1..A8")
            continue
        seen_archetypes.add(arch_id)

        # Every trigger's entry_state must exist in states.
        states = doc.get("states") or {}
        triggers = doc.get("triggers") or {}
        bad_entry = None
        for tname, tdef in triggers.items():
            entry = (tdef or {}).get("entry_state")
            if entry and entry not in states:
                bad_entry = f"{tname} -> {entry}"
                break
        if bad_entry:
            failures += 1
            print(f"FAIL  {path.name} :: trigger entry_state not found in states ({bad_entry})")
            continue

        if doc["segment"] not in ("consumer", "b2b"):
            failures += 1
            print(f"FAIL  {path.name} :: segment {doc['segment']!r} must be consumer|b2b")
            continue

        print(f"PASS  {path.name} ({arch_id} {doc['name']!r}, {len(states)} states, {len(triggers)} triggers)")

    expected = {f"A{i}" for i in range(1, 9)}
    if seen_archetypes != expected:
        failures += 1
        print(f"FAIL  archetype coverage incomplete: got {sorted(seen_archetypes)}, want {sorted(expected)}")

    total = len(files)
    print(f"\n{total - failures}/{total} flows valid; archetypes covered: {sorted(seen_archetypes)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
