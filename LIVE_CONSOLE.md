# Agent Mandate — live console architecture

The authority console runs in two modes. The mode is chosen by URL and
displayed honestly in the header badge; nothing else may set it.

| URL | Data path | Badge |
|---|---|---|
| `ui/?mode=replay` (default) | `FixtureDataSource`, deterministic in-browser replay | `DEMO · VERIFIED ON DEVNET` |
| `ui/?mode=live` | `LiveDataSource` → `bridge.py` → Canton | `CANTON DEVNET · LIVE` — only after `/api/health` **and** `/api/state` both succeed |

## Live architecture

```
Browser (ui/, ?mode=live)
    | localhost HTTP, JSON — one header, one field, no credentials
bridge.py                     (thin transport glue, loopback only)
    | in-process
agent_session.SessionState    (owns the CURRENT successor Mandate cid)
    |
c8lab.charge_and_settle       (the only value-moving call)
    |
Mandate.ChargeAndSettle       (Daml: cap, allow-list, expiry, revocation)
    |
Canton Token Standard settlement
```

The bridge implements **no policy**. Cap, recipient allow-list, expiry
and revocation are checked by the Daml `Mandate` on the ledger for every
charge. What the bridge does: parse text into `{recipient, amount,
reason}`, resolve the recipient alias to a Party (address book, not
policy), forward the charge, report Canton's decision, and keep the
session's successor contract id straight.

### API (loopback only, default `127.0.0.1:8917`)

- `GET /api/health` — `{ok, mode:"live", stale, lastLedgerContact}`
- `GET /api/state` — authority snapshot from the ledger: wallet balance
  (owner's spendable holdings), cap/spent/remaining and allow-list from
  the active `Mandate` contract. Read-only: a browser refresh never
  changes ledger state.
- `GET /api/activity` — this session's recent decisions (starts empty:
  the bridge does not fabricate history).
- `POST /api/intent` — `{"text": "Pay pharmacy 0.001 CC for medicine"}` →
  `{intent, decision, settledAmount?/reason?, before, after, proof}`.

### Session and failure semantics

- One charge in flight at a time (`409` otherwise).
- A committed charge advances the in-memory successor Mandate cid
  (`SessionState`), exactly as `agent_session.py` does.
- A ledger **rejection** changes nothing; the response's `after`
  snapshot is re-read from the ledger to prove it.
- An **ambiguous** failure (network error while a submission may have
  committed) is **never retried**. The bridge returns
  `{decision:"error", ambiguous:true}`, marks the session stale, and the
  next `/api/state` re-resolves the current Mandate through its stable
  `mandateId` (which survives the archive/recreate chain).
- The UI's connection state is `connecting | live | degraded |
  disconnected | replay`; the LIVE badge is bound to exactly one of
  them.

### What never reaches the browser

Keycloak client secrets, bearer tokens, Canton credentials, LLM API
keys. They live in the bridge process's environment; every error string
passes through `agent_demo._safe_error_text` (secret redaction) before
being serialised. The browser sends exactly one header (`Content-Type`)
and one body field (`text`). CORS is restricted to
`http://localhost[:port]` / `http://127.0.0.1[:port]`; the bridge binds
loopback unless `--host` says otherwise; bodies are capped at 4 KiB.

The `checks` list the console renders in live mode is *display*,
derived in the browser from the pre-charge snapshot; the authoritative
verdict is always the bridge's `decision`/`reason` from the ledger.

## Run

```
# terminal 1 — the bridge (needs the usual C8_*/D1_* environment of
# c8lab.py / agent_session.py: C8_HOST/C8_IDP/C8_CLIENT_ID/
# C8_CLIENT_SECRET (or C8_ACCESS_TOKEN), C8_REGISTRY, D1_OWNER,
# D1_SPENDER, D1_MANDATE_CID, D1_RECIPIENTS_JSON)
python bridge.py

# terminal 2 — the UI
cd ui && node serve.mjs 8080
# replay: http://localhost:8080/
# live:   http://localhost:8080/?mode=live
```

## Tests

```
python test_bridge.py                 # 14 offline tests, fake ledger
node --test ui/test/mandate.test.mjs  # fixture + presenter honesty
node --test ui/test/live.test.mjs     # LiveDataSource vs mock bridge
```

## One controlled DevNet validation

With credentials exported in the bridge's shell and a funded mandate:

```
python bridge.py
# then in the live UI, submit ONE small in-cap charge and check
# spent/remaining advanced and the receipt/update id in Technical proof.
```

Spend deliberately; every accepted charge moves real DevNet Canton Coin.

## Known limitations

- Wallet/authority figures are displayed as decimal strings; the UI's
  tween rounds to 0.001 CC for animation, so sub-mil fee dust shows in
  the figures but not in the bar animation.
- `/api/activity` is per-bridge-process memory, not a ledger query.
- The bridge parses intents deterministically (same grammar as the
  replay console); LLM inference stays in `agent_session.py`'s
  interactive mode and is not exposed through the bridge yet.
- One mandate chain per bridge process (the one `D1_MANDATE_CID` points
  into).
