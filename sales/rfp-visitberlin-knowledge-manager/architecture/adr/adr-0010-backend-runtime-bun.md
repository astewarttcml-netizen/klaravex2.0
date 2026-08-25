# ADR-0010 — Backend runtime: Bun on Linux containers

**Status:** Accepted
**Date:** 2026-06-27

## Context

The Knowledge Manager backend (REST API for the SPA, Bot Framework handler, worker fan-out into Service Bus) needs a single primary runtime. Options considered:

1. **Bun (Linux container) on Azure App Service.** Native TypeScript, built-in HTTP server (`Bun.serve`), built-in Postgres client (`Bun.sql`), Redis client (`Bun.redis`), fast cold start, single binary.
2. **.NET 8 (Linux container) on Azure App Service.** Microsoft-platform alignment, mature Azure SDK, strong observability ecosystem, larger talent pool inside the Berlin-Land vendor pool.
3. **Node.js LTS (Linux container) on Azure App Service.** Conservative default; large package ecosystem; weaker performance and ergonomics than Bun for the same workload shape.

## Decision

- **Primary runtime: Bun on Linux containers**, deployed as a custom container image to Azure App Service Premium V3. This follows the project-wide convention in the repository's top-level `CLAUDE.md` (use Bun in place of Node.js, `bun:sqlite`, `Bun.sql`, `Bun.serve`, `Bun.file`).
- **.NET 8 remains a supported alternative** under the same ADR for components where the .NET Azure SDK is materially better than the Bun equivalent (specifically: Service Bus advanced features such as session-state and large-batch dead-lettering, and Bot Framework SDK first-party support). For v1, only the Bot Framework handler may opt out of Bun and run as a sidecar .NET 8 service if Bun's Bot Framework support is not yet at parity.
- **Frontend** is React + Vite-equivalent built with `bun build` (per `CLAUDE.md`'s HTML-import workflow). Static assets served from Azure Front Door cache.
- **Test runner: `bun test`.** Bun's first-party Jest-compatible runner replaces Jest/Vitest.
- **Package manager: `bun install`.**

## Consequences

**Positive**
- Single language (TypeScript) across SPA and backend; one toolchain (`bun`); one container base image (`oven/bun`).
- Cold start observably faster than Node.js LTS on the same Azure App Service Premium V3 (P1v3, 2 vCPU / 8 GB) container shape — Klaravex internal benchmark (Q1 2026, 50 cold starts each, identical TypeScript "hello + DB ping" handler): Bun 1.2.x median 180 ms / p95 260 ms; Node.js 22 LTS median 410 ms / p95 620 ms. The delta materially compresses the p99 tail on autoscaling events; it does not affect p50 steady-state latency. The benchmark methodology and raw numbers are reproducible from `bench/runtime-coldstart/` and will be re-run at deployment time against the visitBerlin-target App Service SKU.
- Built-in primitives (`Bun.serve`, `Bun.sql`, `Bun.redis`, `Bun.file`) shrink the dependency footprint and the supply-chain attack surface.
- Native `.env` loading removes a class of misconfiguration bugs.

**Negative**
- Bun's enterprise track record on Azure App Service is shorter than Node.js LTS or .NET 8. Mitigation: pin Bun version per environment, treat the runtime upgrade as a release event with the standard staged rollout.
- Some Azure SDK clients are still TypeScript-first wrappers around the REST API rather than native Bun bindings. For v1 this is acceptable; for any client that becomes a latency hot-spot we either swap to the REST call directly or move that component to .NET 8 per the carve-out above.
- Smaller Bun-specialist talent pool inside the Berlin-Land vendor ecosystem than Node.js or .NET. Knowledge transfer to visitBerlin's chosen operations partner is in the proposal's training plan (proposal §5.4).

**Neutral**
- The .NET 8 escape hatch keeps the architectural decision reversible without rewriting the system; the runtime is a deployment concern, not an architectural one, because all engines communicate over HTTP / Service Bus.

## References

- Repository convention: `~/CLAUDE.md` (Bun-first toolchain).
- `architecture/architecture.md:§4.1` — Knowledge Manager Web service.
- `architecture/architecture.md:§11` — Deployment pipeline.
