# Agent Mandate — Cantor8 2026 deck · exact slide copy

Backup of every word on each slide of `Agent_Mandate_Cantor8_2026.pptx`.

---

## Slide 1 — Title

> **Agent Mandate**
>
> Financial authority for autonomous agents
>
> **The AI decides what it wants to do.**
> **The ledger decides what it is *allowed* to do.**

Motif: `AI intent → Daml authority → Canton`

Footer: `Cantor8 London Hackathon · Build on Canton · 29 August 2026`

---

## Slide 2 — Bounded authority

> **AI agents don't just need wallets.**
> **They need bounded authority.**

| THE AGENT MAY DECIDE | THE AGENT MUST NOT DECIDE |
|---|---|
| who it wants to pay | its own spending cap |
| how much it wants to send | its own recipient permissions |
| why it wants to pay | its own expiry |
| when to initiate | its own revocation |

Thesis: **Probabilistic intent ≠ financial authority**

---

## Slide 3 — Put the authority in Daml

Flow:

`Natural-language request → AI intent → Agent runtime → [ Daml Mandate ] → Canton Token Standard → Canton Coin`

The control boundary (under **Daml Mandate**):

- Recipient allowlist
- Cumulative cap
- Expiry
- Revocation

*Python deliberately does not enforce these policies.*

State transition:

`Mandate A —(successful payment)→ Mandate B` · successor automatically adopted

---

## Slide 4 — HERO

> **The wallet could afford it. The agent wasn't authorised.**

| FUNDS AVAILABLE | REQUESTED | DELEGATED AUTHORITY |
|---|---|---|
| **4.997 CC** | **0.008 CC** | **0.007 CC** remaining |
| ✓ sufficient | to approved Pharmacy | ✕ insufficient |

> **REJECTED**
>
> "charge would exceed the cap"
>
> **0 CC moved**

Checks:

- ✓ Recipient approved
- ✓ Wallet had sufficient funds
- ✓ Mandate active
- ✕ Exceeded delegated authority

Evidence: `Enforced by Mandate.ChargeAndSettle · Daml`

Thesis: *Having the funds is not the same as having the authority to spend them.*

---

## Slide 5 — Roadmap

> **From AI wallets to machine authority infrastructure**

**PROVEN TODAY**

- 5 CC funded on DevNet
- 3 real 0.001 CC settlements
- Atomic Canton Token Standard settlement
- Daml cap rejection
- Successor Mandate state

**NEXT**

- Procurement agents
- Treasury agents
- Recurring budgets
- Multi-party approvals
- Institutional audit + revocation

**WHY CANTON**

- Shared financial state
- Selective visibility
- Deterministic authority
- Atomic settlement

Closing: **AI intent. Deterministic financial authority.**

---

## Verified figures used (do not alter without re-verifying)

- Initial owner funding: 5 CC; three settled charges of 0.001 CC each.
- At the isolation test: owner 4.997 CC, receiver 0.003 CC; cap 0.010,
  spent 0.003, remaining 0.007.
- Isolation request: 0.008 CC to the approved Pharmacy (deterministic
  manual intent, not LLM-generated). Wallet could afford it; the request
  reached `Mandate.ChargeAndSettle`; ledger returned DAML_FAILURE with
  "charge would exceed the cap"; 0 CC moved; spent still 0.003 after.

## Rebuild

```
cd deck
npm install
node build.mjs
```
