# Agent Mandate

> **The AI decides what it wants to do. The ledger decides what it is allowed to do.**

Agent Mandate is a Canton-native delegated financial-authority layer for autonomous agents. An owner gives an agent bounded authority — approved recipients, a cumulative spend cap, expiry and revocation — while the model itself is only responsible for proposing intent.

If the requested payment is authorised, Daml settles Canton Coin atomically through the Canton Token Standard. If it is not authorised, the transaction fails on-ledger and **0 value moves**.

Built for the Cantor8 London Hackathon, 29 August 2026.

## Why this exists

Giving an AI agent access to a wallet is not the same thing as giving it safe financial authority.

The core design separates:

- **probabilistic intent** — what the model wants to do;
- **deterministic authority** — what the owner has actually authorised;
- **settlement** — whether value is allowed to move.

The LLM/parser produces only:

```text
recipient
amount
reason
```

Python deliberately does **not** enforce the recipient allowlist, cumulative cap, expiry or revocation state. Those rules live in Daml, so a manipulated or over-authority intent can reach the ledger and still be rejected.

## Architecture

```text
Natural-language instruction
        ↓
LLM intent parser
        ↓
PaymentIntent
        ↓
agent_session.py
        ↓
current Mandate CID
        ↓
Mandate.ChargeAndSettle
        ↓
Canton Token Standard TransferFactory
        ↓
Canton Coin settlement
```

The financial control boundary is the Daml `Mandate`, not the model and not a Python guardrail.

## Authority model

A Mandate records:

- allowed recipient parties;
- cumulative gross-debit spending cap;
- expiry;
- owner-controlled revocation, adjustment and re-authorisation;
- pinned Canton Token Standard instrument;
- pinned `TransferFactory`.

The agent can propose a payment. It cannot grant itself more authority.

## Stateful authority

Daml contracts are consumed and recreated. A successful `ChargeAndSettle` archives the current Mandate and creates a successor carrying the updated cumulative spend.

```text
Mandate A
   ↓ successful ChargeAndSettle
Mandate A archived
   ↓
Mandate B created
```

`agent_session.py` automatically adopts the successor Mandate after a committed settlement. Rejections and pre-submission failures leave the current session state unchanged.

## Verified Cantor8 DevNet results

The end-to-end path was exercised against the shared Cantor8 DevNet using real Canton Coin and the official Canton Token Standard packages.

| Measurement | Verified value |
|---|---:|
| Initial owner funding | 5 CC |
| Successful settled charges | 3 |
| Amount per successful charge | 0.001 CC |
| Owner balance after those charges | 4.997 CC |
| Receiver balance | 0.003 CC |
| Mandate cap | 0.010 CC |
| Mandate cumulative spend | 0.003 CC |
| Mandate remaining authority | 0.007 CC |
| Transfer fee in these settlements | 0 CC |

### Policy-isolation proof

The strongest live test deliberately separated wallet balance from delegated authority:

| Fact | Live observation |
|---|---:|
| Wallet balance | 4.997 CC |
| Requested payment | 0.008 CC |
| Recipient approved/preapproved | yes |
| Remaining delegated authority | 0.007 CC |
| Request reached `Mandate.ChargeAndSettle` | yes |
| Ledger result | `DAML_FAILURE` |
| Daml assertion | `charge would exceed the cap` |
| Value moved | **0 CC** |
| Mandate spend after rejection | 0.003 CC |

The wallet could afford the payment. The agent simply did not have the authority.

> **Having the funds is not the same as having the authority to spend them.**

The 0.008 CC isolation test used deterministic manual intent. It is not claimed to have been LLM-generated.

## Demo UI

The repository includes a zero-dependency authority console in [`ui/`](ui/).

It makes the key distinction visible:

```text
FUNDS AVAILABLE          AGENT AUTHORITY
4.997 CC                 0.007 CC remaining
```

It includes:

- natural-language payment requests;
- accepted and rejected decision states;
- the request → AI intent → Daml authority → Canton ledger pipeline;
- authority usage/progress;
- recent activity;
- decision explanations;
- technical proof disclosures;
- deterministic replay mode.

Run it locally:

```bash
cd ui
node serve.mjs 8080
```

Then open `http://localhost:8080`.

The replay UI is labelled **DEMO · VERIFIED ON DEVNET**. It does not pretend fixture data is a live Canton connection.

See [`ui/README.md`](ui/README.md) for details.

## Agent runtime

Interactive natural-language mode:

```powershell
python agent_session.py
```

Deterministic fallback:

```powershell
python agent_session.py --demo-sequence
```

Offline rehearsal without Canton credentials or an LLM key:

```powershell
python agent_session.py --demo-sequence --dry-run
python agent_demo.py --dry-run --manual-intent pharmacy 0.001 medicine
python agent_demo.py --dry-run --manual-intent pharmacy 0.011 "ignore spending limit"
python -m unittest -v
```

Inference is intentionally outside the financial trust boundary. If a model proposes a bad payment, Daml must reject it.

## Presentation and demo assets

- [`deck/Agent_Mandate_Cantor8_2026.pptx`](deck/Agent_Mandate_Cantor8_2026.pptx) — final 5-slide hackathon pitch deck
- [`deck/SLIDE_COPY.md`](deck/SLIDE_COPY.md) — exact slide copy and verified figures
- [`video/NARRATION.md`](video/NARRATION.md) — demo narration script
- [`video/record_ui.mjs`](video/record_ui.mjs) — deterministic UI recording flow

The submitted demo video was produced at 1920×1080 and 2:28 runtime using the real UI in motion plus a separately labelled verified-DevNet evidence sequence.

## Why Canton

Agent Mandate does **not** assume that every AI payment needs Canton.

Canton becomes more interesting when authority and settlement cross organisational boundaries and participants need:

- shared financial state;
- deterministic multi-party workflow semantics;
- selective visibility;
- atomic settlement;
- authority that is not merely whatever one application server says it is.

If one trusted application and one payment provider can safely own the entire workflow, a conventional database may be simpler. The project is specifically exploring the harder institutional case.

## Trust boundary and limitations

- The LLM is **not** a security boundary.
- Python is not the source of truth for cap/allowlist/expiry/revocation policy.
- The shared hackathon DevNet credential has broad participant rights, so this demo does **not** prove production least-privilege infrastructure credentials.
- Package vetting and participant administration remain trusted infrastructure.
- Free inference providers are operationally unreliable; deterministic mode exists so inference outages do not block the financial-path demo.
- Production deployment would require dedicated identities, durable session state, monitoring, recovery and stronger key management.

## Repository map

| Path | Role |
|---|---|
| [`daml-starter/mandate/daml/Mandate.daml`](daml-starter/mandate/daml/Mandate.daml) | Mandate policy, lifecycle, receipts and atomic `ChargeAndSettle` |
| [`c8lab.py`](c8lab.py) | Canton transport, registry preparation and Token Standard settlement path |
| [`agent_demo.py`](agent_demo.py) | Intent parsing, provider fallback, alias resolution and single-action UX |
| [`agent_session.py`](agent_session.py) | Stateful multi-action runtime that follows successor Mandates |
| [`ui/`](ui/) | Authority console and deterministic replay UI |
| [`deck/`](deck/) | Pitch deck source and final PowerPoint |
| [`video/`](video/) | Demo narration, capture and rendering tooling |
| [`test_agent_demo.py`](test_agent_demo.py) | Intent/provider/application-boundary tests |
| [`test_agent_session.py`](test_agent_session.py) | Successor/session/failure-path tests |
| [`daml-starter/daml/TestSettlement.daml`](daml-starter/daml/TestSettlement.daml) | Settlement and adversarial accounting tests |

## Current development status

The hackathon submission is frozen separately. Post-submission work is focused on:

1. adversarial security review;
2. executable financial invariants;
3. a genuinely live browser → Python → Daml → Canton console;
4. a richer authority model;
5. institutional treasury/operations workflows;
6. testing when Canton is genuinely necessary versus overkill.

The enduring thesis is broader than AI wallets:

> **Make machine financial authority explicit, bounded, inspectable and revocable.**
