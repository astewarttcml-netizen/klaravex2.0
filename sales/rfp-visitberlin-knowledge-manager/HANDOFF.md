# What Loki built for you

Here is what Loki built and how to take it from here, in plain language - no code reading required.

## What you have now

You asked Loki to build this:

> # visitBerlin — Berlin Tourismus & Kongress GmbH

No file changes were recorded for this run.

## Is it working?

Not fully verified. Loki's honest verdict for this run is: NOT VERIFIED

In plain terms: Loki could not confirm this build works. Treat it as unfinished until the gaps below are resolved.

This means Loki is NOT telling you it is ready to ship. Here is what was not verified:

- tests - not_run; no test command recorded
- build - not_run; build not run
- git.diff - not_run; no file changes detected

This describes the last build Loki finished. If the code changed since then, this verdict is about the older version.
To confirm it still matches your current code, run: `loki proof verify run-20260627053925-31878-43`

## How to run it on your computer

To check it works:

```
# 1. Confirm every deliverable exists and has non-trivial content
ls -la proposal/ architecture/ architecture/adr/ compliance/ mockup/ pitch-deck/

# 2. Open the mockup in a browser and click through 7 screens (Home, Ask the bot,
#    Browse, Detail, Profile, Re-submission queue, Admin console). Switch persona
#    in the top-right to flip between Hannah and Konrad.
open mockup/index.html

# 3. Open the pitch deck and arrow-key through all 16 slides; press 'o' to see
#    the overview grid; press 'p' to verify the print export looks right.
open pitch-deck/deck.html

Expected: all six folders contain non-empty files; the mockup renders with a calm German-public-sector aesthetic and the persona switcher works; the pitch deck advances through 16 slides with keyboard navigation.
```

## How to put it online

This build has not been put online yet.

When you are ready, you have two options:

- `loki deploy` - deploy it using your own cloud account.
- `loki preview --public` - share a temporary public link to the version running on your computer.

## What a developer needs to know

No changed-file list was recorded for this run.

A developer should read USAGE.md (run/verify commands) and the developer handoff notes in .loki/memory/handoffs/.

## What is verified

Loki keeps a tamper-evident receipt of exactly what it did. Anyone can inspect or re-check it:

- `loki proof show run-20260627053925-31878-43` - read the full receipt.
- `loki proof verify run-20260627053925-31878-43` - confirm the receipt has not been altered.

## What you still need to do or decide

Work through these in order:

1. Review 16 assumptions Loki had to make where your spec was ambiguous (9 of them high-impact). See .loki/assumptions/ledger.md.
2. Address: tests (no test command recorded)
3. Address: build (build not run)
4. Address: git.diff (no file changes detected)
5. No pull request was opened. Open one when you are ready to merge the changes.
6. It is not deployed yet. Use `loki deploy` when you are ready.

