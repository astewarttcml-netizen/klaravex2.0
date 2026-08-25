# Klaravex — Pricing Spec & Financial Model Review
Date: 2026-06-09 · Reviewer: enterprise-architect pass · Scope: `B2B-Managed-Pricing-SPEC.md` + `Klaravex-Financial-Model.xlsx`
Method: model reimplemented cell-for-cell in Python (the workbook ships with **no cached values** — every figure below is recomputed, not read off the sheet).

---

## Executive summary
The pricing *structure* (per-seat + floor + anchor tier) is sound and standard. The **financial model is internally inconsistent with the GTM narrative and is fragile on the one assumption the whole business rests on (AI deflection × ticket volume).** Three things need to be fixed before this model is used to justify pricing, targets, or spend:

1. **The B2B account is margin-negative below ~69% deflection and only ~18% gross margin at the stated base (75%).** The "75–80% gross margin" claim in the synthesis is **not reproducible** from the model's own inputs. It requires ~82%+ deflection *and* ~2 tickets/seat/mo — neither of which the model assumes.
2. **The model contradicts the strategy.** It generates **87% of M12 MRR from B2C** (2,785 members vs 85 B2B accounts) and bakes in **$8k/mo ad spend + 120 new B2C/mo**, while the strategy (and `CLAUDE.md`) says B2C is *passive, no paid acquisition, B2B-first*. The model is effectively pricing a different company than the one you're building.
3. **The headline outputs are ~7× the stated targets.** Synthesis target: M12 MRR $25–40k, ~$576k ARR. Model base case: **$253k MRR, $3.04M ARR**. Both can't be the plan. The growth inputs (4→13 B2B closes/mo *and* 120+ B2C/mo, solo, no paid B2B) are not achievable on the described 50-emails/week motion.

Net: keep the pricing tiers, **rebuild the model's demand and cost assumptions to match the actual B2B-first, partner-led, solo-bootstrapped motion**, and treat deflection-at-volume as a hard gating metric, not a north star you hope to hit.

---

## Part 1 — Recomputed model outputs (as written, all three scenarios)

| Metric (M12) | Conservative | Base | Aggressive |
|---|---|---|---|
| Active B2B accounts | 29 | 85 | 250 |
| Active B2C members | 875 | 2,785 | 9,989 |
| Total MRR | $80.6k | **$253.5k** | $887.3k |
| ARR run-rate | $968k | **$3.04M** | $10.6M |
| Blended gross margin % | 24.1% | 40.5% | 56.6% |
| **B2B gross margin / account** | **−3.4%** | **17.8%** | 39.0% |
| B2B LTV:CAC | **−0.5×** | 2.7× | 6.7× |
| B2B payback | never | 12.2 mo | 5.0 mo |
| Breakeven month | none in 12 | M6 | M3 |

Read the bold row first. **In the Conservative case every B2B account loses money** (LTV is *negative*), and the blended margin only looks positive because B2C subsidizes it. A managed-IT business whose flagship product has negative unit margin in the downside case is not yet investable or safely scalable.

---

## Part 2 — The core finding: the margin-death line

B2B ARPU = `max($245 floor, $49 × 8 seats)` = **$392/account/mo**. Variable cost = `tickets × [deflection×$0.35 + (1−deflection)×$60×0.5hr]`. At the stated **40 tickets/account**:

| Deflection | Var cost/acct | GM/acct | GM% |
|---|---|---|---|
| 60% | $488 | −$108 | −27.6% |
| 68% (Conservative) | $394 | −$13 | −3.4% |
| **69.1% (breakeven)** | **$392** | **$0** | **0%** |
| 75% (Base / North Star) | $310 | +$70 | 17.8% |
| 82% (Aggressive) | $227 | +$153 | 39.0% |
| 90% | $133 | +$248 | 63.2% |

**Your North-Star target (≥75%) sits ~6 points above the margin-death line (69%).** That is almost no buffer. The synthesis already names the tripwire ("tickets/customer/mo >5") — but the **base case is set at exactly 40/8 = 5.0 tickets/seat**, i.e. the model is calibrated *on the tripwire itself*. One bad month of deflection or one heavy-usage client and the B2B book is underwater.

### Two assumptions that make it worse than shown
1. **Escalation handle time of 0.5 hr is optimistic.** A senior engineer owning an escalated ticket end-to-end (diagnose → fix → document → client comms) is realistically 0.75–1.5 hr fully loaded. Re-running at 75% deflection / 40 tickets:
   - 0.75 hr → **−20.5% GM** · 1.0 hr → **−58.7% GM**. The margin is *entirely* hostage to this single input, and it's set at the floor of plausibility.
2. **Tickets are modeled flat at 40/account regardless of tier**, but the pricing spec sells a **fair-use cap of ~3 tickets/seat** on Essential (= 24/account). The model and the spec disagree with each other. If you actually enforce 3/seat at 75% deflection, GM jumps to **49.5%**; if you don't enforce it, Essential at $29/seat is deeply underwater.

### What 75% gross margin actually requires
To hit the claimed 75% GM on a B2B account at 0.5 hr/escalation: **82% deflection AND ≤1.9 tickets/seat/mo**, or **90% deflection AND ≤3.3 tickets/seat**. The "MSP-grade margin at solo cost" thesis is real **only** in a high-deflection, hard-capped-usage regime. That needs to be the explicit operating target, designed into product and contract — not assumed.

---

## Part 3 — Errors and inconsistencies (fix list)

| # | Location | Issue | Fix |
|---|---|---|---|
| 1 | `Drivers!B8` ("Human escalation rate = 1−B6") | References **B6 (AI cost/session = 0.80)**, not deflection. Yields 0.20 instead of 0.25. Dead cell (downstream uses E51), but wrong and misleading. | `=1−B7` (or `=1−E51`). |
| 2 | Pricing spec claim: "$245 floor so no account is margin-negative" | **False.** Floor binds on *seat count* (<5 seats); margin death comes from *deflection × volume*. An 8-seat account at $392 is still −3.4% at 68% deflection. | Reword: floor protects against tiny accounts only; margin protection = deflection SLA + usage caps. |
| 3 | Synthesis "75–80% gross margin" | Not reproducible. Model base B2B GM = 17.8%; blended = 40.5%. | Restate margin claim with the deflection/usage regime it depends on. |
| 4 | Model demand inputs vs strategy | B2C dominates MRR (87%) and assumes paid acquisition ($8k/mo ads, 120/mo) the strategy forbids. | Zero or sharply cut B2C new-adds; remove B2C paid CAC; make B2B the primary driver. |
| 5 | Targets mismatch | Model base ($253k MRR) ≈ 7× synthesis target ($25–40k). | Reconcile to one plan. For a solo, partner-led motion the realistic M12 B2B is ~10–25 accounts, not 85. |
| 6 | `B36` tickets/account = 40 (= tripwire) | Base usage is set at the stated danger threshold. | Lower to enforced fair-use (24/acct = 3/seat) and model overage separately. |
| 7 | Escalation = 0.5 hr | Optimistic; margin is hypersensitive to it. | Use 0.75 hr base, run 0.5/1.0 as the sensitivity band. |

---

## Part 4 — Compliance / risk flags (from `CLAUDE.md`)

- **Wording:** Secure+ tier text uses **"compliance reporting"** repeatedly. `CLAUDE.md` rule: *never use "compliance" in marketing — use "readiness/preparation/advisory."* Fine in an internal spec; **must be scrubbed before it reaches any pricing page.**
- **E&O gating:** Secure+ sells HIPAA/SOC 2/GDPR work. `CLAUDE.md`: *E&O must be bound before first compliance engagement* — and the formation checklist still shows E&O **unbound**. **Do not sell or deliver Secure+ until E&O is in force.** Consider hiding Secure+ from the public page until then.
- **EU/DE:** Spec mirrors prices in € on `klaravex.com`. Per `CLAUDE.md`, NIS2/DORA/German-regulatory positioning belongs to **klaravex.com**, and an EU entity is **not** to be implied. Keep the pricing page light-touch (EU data residency + GDPR DPA line only), not a regulated-vertical pitch.

---

## Part 5 — Recommendations (ranked)

1. **Re-baseline the model to the real motion before using it for anything.** B2B-first, partner/cold-email sourced, solo. Realistic M12 = ~10–25 active B2B accounts, modest passive B2C. Expect M12 MRR in the **$15–45k** range — which *matches the synthesis target and contradicts the spreadsheet*. The spreadsheet is the outlier.
2. **Make deflection-at-capped-volume a contractual and product design constraint, not a hope.** Bake the ~3-tickets/seat fair-use cap into the plan terms and enforce overage→tier-up. This is what moves base GM from 18% to ~50%.
3. **Fix the escalation-cost assumption and stress it.** Run the model at 0.75 hr base. If margins only work at 0.5 hr, the thesis is not yet proven.
4. **Add a true minimum viable deflection covenant:** if a cohort's deflection drops below ~72%, that cohort is margin-negative — instrument and alert on it per-account, not just in aggregate.
5. **Pull Secure+ from public pricing until E&O is bound** and scrub "compliance" → "readiness/advisory" everywhere customer-facing.
6. **Keep the tier structure and anchor logic as-is** — that part is good. The problem is the *numbers behind* it, not the *shape* of it.

---

### Bottom line
The pricing tiers are fine. The model is not yet a decision-grade artifact: it overstates margin, overstates growth ~7×, and quietly relies on a B2C paid-acquisition engine your strategy rules out. Before it drives a single pricing or spend decision, rebuild it B2B-first with enforced usage caps and a realistic escalation cost, and treat 69% deflection as the line below which the flagship product loses money.
