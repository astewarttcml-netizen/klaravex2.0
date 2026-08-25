# Social media reboot — directives (2026-06-11 ~06:00 GMT+2)

## Brand voice
**AI-native MSP authority** — third-person brand voice. Educational, opinionated,
slightly contrarian. Best for LinkedIn company + thought leadership. Drives B2B leads.

## Platforms (all 7, in priority order)
1. LinkedIn personal (@anthonystewart, existing handler)
2. LinkedIn company (/company/klaravex, existing handler)
3. **X / Twitter** — current handle NOT klaravex-named; Anthony to rename to @klaravex (or @klaravexllc if taken). Handler exists, needs creds after rename.
4. Facebook page (existing handler)
5. **Instagram** — handle: **@klaravexllc**. Token stored, needs publish handler built.
6. **Reddit** — current account NOT klaravex-named; Anthony to rename / create u/klaravex. No handler, no creds yet.
7. TikTok — handle TBD, no handler, no creds yet.
8. **YouTube** — channel renamed to @klaravex ✅ (2026-06-11). No handler, no API creds yet.

## Anthony's account-admin to-do (cannot be automated)
- [x] Rename **YouTube** channel → `@klaravex` ✅ done
- [ ] Rename / create **Reddit** account → `u/klaravex` (or available variant)
- [ ] Rename **X / Twitter** → `@klaravex` (or `@klaravexllc` if `@klaravex` is taken)
- [ ] Once renamed, paste new handles + API tokens into 1Password Klaravex vault and tell Loki

## Sample post status (2026-06-11)
- Generated one LinkedIn company sample with Higgsfield image (job id `ee2e97e4-…`)
- Voice: third-person AI-native MSP authority, contrarian
- Image: dark empty office at night, monitor with green-node world map, server racks behind glass
- Awaiting Anthony's sign-off before scaling to full 7-platform daily generation

## Image strategy
**Higgsfield is the image generator** for all social posts. Use `mcp__claude_ai_higgsfield__generate_image`
via MCP. NOT DALL-E, NOT Midjourney, NOT stock photos. Style guide TBD — calibrate after
first 5 posts based on engagement.

## Approval flow
- Single approval dashboard at `klaravex.com/admin/social-queue` (TO BE BUILT)
- One daily generation run produces drafts across all platforms
- Anthony reviews + approves in batches
- Approved posts publish on staggered schedule

## Decisions explicitly made tonight
- Truncated `klaravex_social_drafts` table (21 stale pending drafts deleted)
- Confirmed all 7 platform target list
- Confirmed Higgsfield as sole image generator
