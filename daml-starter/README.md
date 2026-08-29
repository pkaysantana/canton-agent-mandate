# Daml starter

Working code to copy from. Everything here builds and every test passes.

```bash
export JAVA_HOME=/opt/homebrew/opt/openjdk@21
export PATH="$HOME/.daml/bin:$JAVA_HOME/bin:$PATH"

daml build
daml test
```

```
daml/Test.daml:testMalformedMandates: ok, 7 active contracts, 14 transactions.
daml/Test.daml:testAllowList: ok, 1 active contracts, 7 transactions.
daml/Test.daml:testExpiry: ok, 2 active contracts, 7 transactions.
daml/Test.daml:testRevocation: ok, 0 active contracts, 8 transactions.
daml/Test.daml:testCapEnforcement: ok, 6 active contracts, 12 transactions.
daml/Test.daml:testAuditTrail: ok, 4 active contracts, 8 transactions.
daml/Test.daml:testAuthorisation: ok, 2 active contracts, 16 transactions.
daml/Test.daml:testMandateHappyPath: ok, 3 active contracts, 4 transactions.
daml/Test.daml:testIou: ok, 1 active contracts, 4 transactions.
daml/TestSettlement.daml:testNestedAuthority: ok, 7 active contracts, 9 transactions.
daml/TestSettlement.daml:testSettleDirect: ok, 7 active contracts, 6 transactions.
daml/TestSettlement.daml:testSettlePendingAborts: ok, 5 active contracts, 6 transactions.
daml/TestSettlement.daml:testSettleAdversarial: ok, 9 active contracts, 20 transactions.
daml/TestSettlement.daml:testSettleAfterRevocation: ok, 2 active contracts, 6 transactions.
daml/TestSettlement.daml:testSettleAfterExpiry: ok, 5 active contracts, 10 transactions.
```

`daml test` runs in memory in about a second. No node, no Docker, no network.
That is your development loop.

The `token-standard/` directory vendors the three official Token Standard
interface packages (`splice-api-token-*-v1`, Apache-2.0, from the Splice repo
at tag 0.6.8). `multi-package.yaml` makes `daml build` compile them first, so
a fresh clone builds with the one command above.

## What is here

**`Iou.daml`** is the smallest useful contract. Read it first. It shows the five
things that make up every Daml contract: `template`, `signatory`, `observer`,
`choice`, `controller`, plus `ensure` for invariants.

**`Mandate.daml`** is the starting point for the mandate task, which covers both
the direct debit and the AI agent wallet framing. Same contract, different story.

**`Test.daml`** shows how to prove your rules hold. `submitMustFail` is how you
test security: it asserts that something is *rejected*.

## The mandate

One party lets another spend up to a cap, until a deadline, revocable at any
time, and only to explicitly named counterparties.

```
MandateProposal          owner offers
   -> Accept             spender takes it up, creating a Mandate
Mandate
   -> Charge             authorise only: receipt, no value moved
   -> ChargeAndSettle    authorise AND move real Token Standard value,
                         in one transaction
   -> Adjust             change the cap. Needs BOTH signatures
   -> Reauthorise        change the allow-list. Needs BOTH signatures
   -> Revoke             owner stops it. Spender cannot block this
```

`Charge` is a consuming choice: it archives the current `Mandate` and creates
the next state with updated `spent` and `charges`. The returned
`ChargeReceipt` is an immutable audit record containing the recipient, amount,
sequence number, mandate identity, deadline, cap at charge time, and cumulative
spend. Receipts are signed by the owner and spender and visible to the
recipient as well as the mandate parties.

## Settlement

`ChargeAndSettle` is the point of this branch. The spender submits one
transaction containing one command; inside it, the mandate:

1. checks expiry, cap, allow-list and instrument against the fields of the
   `transfer : Transfer` argument, the actual Token Standard object;
2. nested-exercises `TransferFactory_Transfer` on the registry's factory
   with **that same object**.

There is no separate policy amount or recipient anywhere, so "what was
authorised" and "what was settled" cannot differ; there is one record, and
the whole thing commits or rolls back atomically.

The authority model that makes it work: `TransferFactory_Transfer` is
controlled by `transfer.sender`, which the mandate requires to be the owner.
The spender alone cannot exercise the factory (`testNestedAuthority` proves
it fails), but inside a Mandate choice the authority context is the mandate's
signatories, owner included. The mandate contract IS the owner's standing
authorisation.

Daml cannot do HTTP, so the registry preflight (factory id, choice context,
disclosed contracts) happens off-ledger before submission; see
`charge_and_settle` in `../c8lab.py`.

Receipts carry a `settlement` field that tells the truth about the money:

- `AuthorisedOnly`: `Charge`, nothing moved.
- `Settled`: the receiver holds the funds, paid in that same transaction.

There is deliberately no pending state. If the receiver has no preapproval
the registry can only create a pending `TransferInstruction`, so
`ChargeAndSettle` aborts instead: a committed settlement always means the
receiver was paid, and a refused one consumed no allowance. The Python
helper refuses before even submitting, with instructions to set up the
receiver's preapproval.

Two things the code states explicitly rather than hides:

- **Cap semantics under fees.** The cap bounds `transfer.amount`, what the
  recipient receives. Registries may take fees out of the input holdings on
  top (Amulet does), so the owner's gross debit can exceed the sum of
  receipted amounts. The cap limits what the agent directs at
  counterparties, not the owner's total outflow.
- **Completed is trusted, not re-fetched.** The mandate does not fetch the
  receiver's new holdings to double-check them: a fetch must be authorised
  by a stakeholder of the fetched contract, and those fresh holdings have
  only the receiver and the registry admin as stakeholders. That is the
  ledger model, not a missing package. `Completed` is the Token Standard's
  own guarantee, from the same vetted registry code that moved the money.

`TestToken.daml` is a mock registry implementing the real
`splice-api-token-*-v1` interfaces so `daml test` can prove all of this
in memory; the mandate code does not know it is talking to a mock.

The allow-list is part of the policy, not a UI convention. It must be non-empty
and unique, and it excludes both the owner and spender. Every charge checks
that its recipient is in that list. The thing that matters, and the thing you
will be asked about: **the cap and counterparties are enforced in the contract,
not in a backend.**

```daml
assertMsg "charge would exceed the cap" (spent + amount <= cap)
```

A cap checked in your API is a suggestion, because anyone who can reach the
ledger directly bypasses it. A cap in a choice body is a rule the network
enforces.

## Where to take it

- **Per-period caps.** "100 per month" rather than 100 in total. Harder than it
  looks because of date arithmetic. The total cap works; build on it.
- **Offer-path support.** Today the mandate settles direct transfers only and
  aborts when the receiver lacks a preapproval. Supporting pending
  instructions properly means deciding when allowance is consumed and
  refunded across accept/reject/withdraw - a real design task, not a patch.

## Three things that catch people

**Choices are consuming by default.** Calling one archives the contract it was
called on. That is why `Charge` returns a new `ContractId Mandate` instead of
mutating anything. Contracts never change: you archive and create.

**Authority does not flow into nested exercises.** Inside a choice body you have
the contract's signatories plus that choice's controllers. If you exercise a
choice on another contract, that body gets its own set, not yours. Most
authorization errors are this.

**Deadlines are not enforced for you.** `expiresAt` is just a field. If you do
not write `assertMsg "expired" (now < expiresAt)` in the body, nothing checks it.
A real audit finding on production Canton code was exactly this.
