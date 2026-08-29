# Agent Mandate

> **The AI decides what it wants to do. The ledger decides what it is allowed
> to do.**

Agent Mandate is a Canton-native delegated financial authority layer for AI
agents. An owner can let an agent propose and settle payments without giving
the model responsibility for financial policy. The application turns language
into a narrow payment intent; a Daml contract decides whether that exact intent
has authority and, if it does, settles Canton Coin atomically through the
Canton Token Standard.

This is a focused Cantor8 D1 hackathon submission, not a claim that every AI
payment needs Canton. It targets the harder case where several organisations
need shared settlement and shared state while retaining selective visibility
and deterministic authority boundaries.

## The authority model

The owner and agent create a Daml `Mandate` that records:

- allowed recipient parties;
- a cumulative gross-debit spending cap;
- an expiry time;
- owner-controlled revocation, re-authorisation and adjustment;
- the pinned Canton Token Standard instrument and `TransferFactory`.

The LLM/parser proposes only three strings:

```text
recipient
amount
reason
```

Python validates program shape—valid JSON/schema, a decimal string and an alias
that resolves to a Canton Party—but deliberately does **not** enforce the
allow-list, cap, expiry or revocation state. A forbidden intent is allowed to
reach Daml so the ledger-enforced boundary is visible.

The agent runtime has one value-moving application path:
`c8lab.charge_and_settle()`. It prepares the Token Standard registry context and
submits `Mandate.ChargeAndSettle`. That Daml choice validates the transfer
against the current Mandate and, in the same Canton transaction, invokes the
owner-pinned Token Standard `TransferFactory`. A failed assertion aborts the
whole transaction: no payment and no consumed mandate allowance.

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

Inference is an intent parser, not a security boundary. The model receives no
shell, general Python, participant administration or arbitrary Ledger API tool.
It can propose a bad payment; it cannot change what the Mandate authorises.

## Stateful authority across sequential actions

Daml contracts are consumed and recreated. Each successful settlement archives
the Mandate that was exercised and creates a successor with updated cumulative
spend:

```text
Mandate A
    ↓ successful ChargeAndSettle
Mandate A archived
    ↓
Mandate B created with updated cumulative spend
```

`agent_session.py` automatically adopts Mandate B after a committed settlement.
The next request therefore exercises current authority rather than accidentally
reusing Mandate A's stale contract ID. A rejection or pre-submission failure
does not advance the session. If a settlement result lacks a successor CID, the
session halts instead of guessing.

## Verified Cantor8 DevNet result — 29 August 2026

The end-to-end path has been exercised against the shared Cantor8 DevNet with
real Canton Coin and the official Canton Token Standard packages.

| Measurement | Verified value |
|---|---:|
| Initial owner funding | 5 CC |
| Successful settled charges | 3 |
| Amount per successful charge | 0.001 CC |
| Owner final balance | 4.997 CC |
| Receiver final balance | 0.003 CC |
| Mandate cap | 0.010 CC |
| Mandate cumulative spend | 0.003 CC |
| Mandate remaining authority | 0.007 CC |
| Canton Coin transfer fee in these settlements | 0 CC |

The owner/receiver balance movement and successor Mandate state agreed after
all three settlements.

## Live policy-isolation proof

The strongest live test separated wallet balance from delegated authority:

| Fact | Live observation |
|---|---:|
| Owner wallet balance | 4.997 CC |
| Requested payment | 0.008 CC |
| Recipient allowed and preapproved | yes |
| Remaining Mandate authority | 0.007 CC |
| Request reached `Mandate.ChargeAndSettle` | yes |
| Ledger result | `DAML_FAILURE` |
| Daml assertion | `charge would exceed the cap` |
| Value moved | 0 CC |
| Mandate spend after rejection | 0.003 CC |

The owner had enough money, and the receiver was a valid direct-settlement
counterparty. The transaction still failed because the agent had only 0.007 CC
of remaining delegated authority.

**Having the funds is not the same as having the authority to spend them.**

This 0.008 CC policy test used `--manual-intent`; it was not claimed to be
LLM-generated. Deterministic input made the authority-isolation result
repeatable while leaving the Daml path unchanged.

## Demo modes

### Interactive natural-language session

With live Canton and an inference provider configured:

```powershell
python agent_session.py
```

Each line is parsed into a `PaymentIntent`, submitted under the current
Mandate, and—only after success—the session adopts the returned successor CID.
Enter `state` to show the session's current CID and `exit` to stop.

### Deterministic no-LLM fallback

```powershell
python agent_session.py --demo-sequence
```

The built-in sequence supplies deterministic intents without calling an LLM.
It first proposes 0.001 CC to the allowed, preapproved pharmacy, then proposes
0.011 CC to that same recipient. The owner wallet can fund either request, so
the second rejection isolates the Mandate cap. Deterministic mode bypasses
inference only. It does **not** bypass alias resolution, `charge_and_settle()`,
Daml policy, the Token Standard or Canton settlement.

## Offline rehearsal — no secrets and no network

These commands require no LLM key, Keycloak credential, Canton configuration
or network access:

```powershell
python agent_session.py --demo-sequence --dry-run
python agent_demo.py --dry-run --manual-intent pharmacy 0.001 medicine
python agent_demo.py --dry-run --manual-intent eve 100 "prompt injected"
python -m unittest -v
```

Dry-run mode uses clearly labelled synthetic aliases and session identifiers.
Those values are rejected outside dry-run and can never become live Party IDs
or Mandate contract IDs. Dry-run resolves and displays the proposed actions but
never authenticates, queries the registry/ledger or submits a command.

## Cantor8 DevNet configuration

Use environment configuration only. The placeholders below are not usable
credentials or Party IDs:

```powershell
$env:C8_BASE = "<Cantor8 DevNet Ledger API base URL>"
$env:C8_IDP = "<Cantor8 Keycloak base URL>"
$env:C8_CLIENT_ID = "<Keycloak client ID>"
$env:C8_CLIENT_SECRET = "<Keycloak client secret>"
$env:C8_REGISTRY = "<Canton Coin registry base URL>"
$env:C8_USER = "validator-backend@clients"
$env:C8_ADMIN_USER = "validator-backend@clients"
$env:C8_ADMIN_PARTY = "<Canton Coin admin / DSO Party ID>"

$env:D1_OWNER = "<owner Party ID>"
$env:D1_SPENDER = "<agent/spender Party ID>"
$env:D1_MANDATE_CID = "<current active Mandate contract ID>"
$env:D1_RECIPIENTS_JSON = '{"pharmacy":"<receiver Party ID>","eve":"<test Party ID>"}'

$env:GROQ_API_KEY = "<inference provider key>" # interactive mode only
```

Authentication on this DevNet uses Keycloak client credentials. In the tested
shared environment both `C8_USER` and `C8_ADMIN_USER` are
`validator-backend@clients`.

Direct Canton Coin settlement also requires an accepted receiver
`TransferPreapproval`. Without one, the Token Standard registry returns an
offer/pending flow; `ChargeAndSettle` refuses that path rather than recording a
payment that has not settled.

Do not run `python c8lab.py check` against the shared DevNet: it traverses
thousands of known parties and is not a useful health check there. Use targeted
inspection for known identifiers instead, for example:

```powershell
python c8lab.py holdings "<owner Party ID>"
python c8lab.py holdings "<receiver Party ID>"
```

Inspect the known current Mandate CID and settlement receipt/update returned by
the session rather than enumerating the participant. `C8_ADMIN_PARTY` may need
to be set explicitly because the shared ledger user cannot enumerate the DSO
party.

## Trust boundary and limitations

- Inference is intentionally **not** a security boundary. It may faithfully
  produce malicious or policy-violating intent; Daml must reject it.
- The shared hackathon DevNet credential has broad participant rights. This
  demonstration does **not** prove least-privilege infrastructure credentials.
- Package vetting and participant administration remain trusted
  infrastructure.
- `C8_ADMIN_PARTY` may be required explicitly on shared DevNet because the
  shared user cannot enumerate the DSO party.
- Free LLM availability and capacity are external and unreliable. The
  deterministic demo exists so inference outages do not block judging.
- A production deployment would use dedicated service identities and rights,
  durable session state, monitoring, recovery procedures and stronger
  operational key management.

The intended production identity has act-as authority for the agent/spender and
read access needed for the owner's holdings, but not owner act-as authority.
The shared hackathon credential does not establish that deployment property.

## Why Canton

This design benefits from Canton when authority and settlement cross
organisational boundaries. Daml gives all participants one deterministic state
transition for authorisation, cumulative spend and settlement, while Canton's
privacy model avoids turning every participant's financial state into a global
broadcast. The relevant value is not “blockchain for every agent action”; it is
shared settlement and verifiable delegated authority without making the model,
one application server or one organisation the sole source of truth.

## Repository map

| Path | Role |
|---|---|
| [`daml-starter/mandate/daml/Mandate.daml`](daml-starter/mandate/daml/Mandate.daml) | Mandate policy, lifecycle, receipts and atomic `ChargeAndSettle` choice |
| [`c8lab.py`](c8lab.py) | Cantor8/Canton transport, Token Standard registry preparation and bounded `charge_and_settle()` path |
| [`agent_demo.py`](agent_demo.py) | Provider-neutral intent parser, manual intent mode, alias resolution and single-action UX |
| [`agent_session.py`](agent_session.py) | Sequential runtime that tracks the successor Mandate CID |
| [`test_agent_demo.py`](test_agent_demo.py) | Hermetic intent, provider-fallback and financial-boundary tests |
| [`test_agent_session.py`](test_agent_session.py) | Hermetic consume/recreate session-state and failure-path tests |
| [`test_c8lab.py`](test_c8lab.py) | Hermetic authentication precedence tests |
| [`daml-starter/daml/Test.daml`](daml-starter/daml/Test.daml) | Daml Mandate policy tests |
| [`daml-starter/daml/TestSettlement.daml`](daml-starter/daml/TestSettlement.daml) | Atomic Token Standard settlement and adversarial accounting tests |

Supporting setup and implementation notes remain in
[`AGENT_RUNTIME.md`](AGENT_RUNTIME.md), [`SETUP.md`](SETUP.md),
[`API.md`](API.md) and [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).
