# Founder Under Attack: An Operator's After-Action Report

## Setup

Our team provides managed security operations for early-stage founders and small executive teams — the segment most likely to hold concentrated asset risk with the least institutional security support. The client in this engagement was a solo technical founder running a seed-stage SaaS company. He managed his own infrastructure access, held sole custody of company financial accounts, and used a personal mobile number as the primary MFA factor across nearly every critical service. No dedicated IT staff. No incident response retainer. Standard founder posture.

We had completed an initial asset inventory and threat-model session with this client roughly six weeks prior to the incident. That prior engagement meant we had a baseline: known account inventory, registered device list, and a documented map of which phone number and email addresses were tied to which services. That baseline proved essential. When the call came in at 9:47 PM on a Tuesday, we were not starting from zero.

---

## Adversary Signal

The client reported an abrupt flood of SMS messages — promotional codes, verification pings, newsletter confirmations — arriving in rapid, irregular bursts. He described it as "spam" and was inclined to ignore it. We did not share that assessment.

SMS flooding at that volume and timing is a recognized precursor technique. The adversary objective is not annoyance; it is **signal burial**. A legitimate one-time passcode sent by a bank, an exchange, or a cloud provider becomes invisible inside 300 promotional messages arriving in the same two-minute window. The founder's attention is fragmented precisely when it needs to be focused.

Within the same window, the client received a phone call from a caller identifying themselves as support staff from his primary cloud infrastructure provider. The caller referenced a "suspicious login attempt" on his account and offered to walk him through a verification process. This is the second stage of the pattern: the SMS flood manufactures urgency and confusion; the inbound social engineering call arrives as apparent relief. The adversary presents as the solution to the problem they created.

We recognized the combined pattern immediately — SMS bombing paired with a vishing recovery scam is a documented TTP used against high-value individual targets, particularly those with cryptocurrency holdings or infrastructure admin access. The client had both.

---

## Containment

First priority was stopping the bleeding before confirming the wound.

We instructed the client to **end the call immediately** without providing any information, then place his phone face-down and take no further action on it. We pulled up his account inventory from the prior engagement and began working through critical services in order of blast radius: cloud infrastructure, financial accounts, domain registrar, email provider.

We initiated out-of-band verification directly through official portals — not through any link or number provided by the caller. No anomalous logins were confirmed in the first sweep, which told us the adversary had not yet achieved access. The flood and the call were the attempt, not the aftermath. Containment had caught the intrusion at the threshold.

We placed temporary step-up authentication holds on the two financial accounts that supported it, and flagged the client's mobile carrier account for a SIM-swap hold — a standard follow-on vector when this pattern fails on the first attempt.

---

## Eradication

With the immediate threat contained, we moved to close the structural vulnerabilities the adversary had been probing.

The client's phone number was removed as a primary MFA factor on every critical account and replaced with hardware token or authenticator-app TOTP where supported. Where SMS MFA was the only option offered by a given service, we documented that service as elevated-risk and flagged it for migration or replacement in the next planning cycle.

We submitted a formal SIM-swap protection request with the carrier and established a carrier-level PIN. We rotated credentials on the cloud infrastructure account and audited active API keys and session tokens, revoking anything that could not be positively attributed to a known workflow.

The client's personal mobile number was also removed from public-facing company pages and replaced with a role-based contact address. Reducing the surface area for number harvesting is unglamorous work, but it raises the adversary's reconnaissance cost on the next attempt.

---

## Service-Line Implication

This engagement reinforced a principle we build every founder engagement around: **the asset inventory and threat model completed before an incident is the only one that matters.** The six-week-old baseline we held on this client compressed our response time from hours to minutes. We knew what existed. We knew what was critical. We knew what was exposed.

Founders who engage with security only after an incident are negotiating from the worst possible position. The adversary has already chosen the terrain, the timing, and the technique. Our value is highest — and the client's risk is lowest — when the map exists before the attack begins.
