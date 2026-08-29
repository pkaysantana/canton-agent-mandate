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
```

`daml test` runs in memory in about a second. No node, no Docker, no network.
That is your development loop.

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
   -> Charge             spender spends to an allowed party, within the cap
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

This branch records charge authorisations but does not move any money. Real
Token Standard settlement is intentionally out of scope here and will be
integrated separately once the DevNet architecture is confirmed with Cantor8.
Nothing in `ChargeReceipt` pretends that value has moved.

- **Move real value.** Make `Charge` exercise a token standard transfer instead
  of only recording an authorisation. See `../README.md` for how transfers work
  and `c8lab.py` for a working one; integrate it only after the DevNet
  architecture is confirmed with Cantor8.
- **Per-period caps.** "100 per month" rather than 100 in total. Harder than it
  looks because of date arithmetic. Get the total cap working first.

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
