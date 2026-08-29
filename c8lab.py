#!/usr/bin/env python3
"""Canton hackathon lab. Stdlib only, no pip install.

LocalNet (default):
    python3 c8lab.py check

DevNet:
    export C8_BASE=https://api.validator.dev.digik.cantor8.tech/api/ledger
    export C8_IDP=https://auth.dev.digik.cantor8.tech
    export C8_CLIENT_ID=hackathon
    export C8_CLIENT_SECRET=...
    export C8_REGISTRY=https://<registry-host>        # needed for transfers
    python3 c8lab.py check

Canton Coin on DevNet is served by the SV scan proxy, which uses the plain
Splice paths and the DSO as admin, so it needs nothing extra:
    export C8_REGISTRY=https://sv-proxy.dev.digik.cantor8.tech

The Cantor8 tokens (c8ETH, c8BTC, c8TEST) live on a different registry that
prefixes every route, and their admin is not the DSO:
    export C8_REGISTRY=https://token-registry.dev.digik.cantor8.tech
    export C8_REGISTRY_PREFIX=/api/c8
    export C8_ADMIN_PARTY=cantor8-digik-1::1220...
    python3 c8lab.py transfer alice bob 5 --instrument c8TEST
"""
import argparse, base64, datetime, hmac, hashlib, json, os, sys, uuid
import urllib.error, urllib.parse, urllib.request

BASE     = os.environ.get("C8_BASE", "http://localhost:2975")
IDP      = os.environ.get("C8_IDP")                    # set => DevNet mode
CID      = os.environ.get("C8_CLIENT_ID", "hackathon")
CSEC     = os.environ.get("C8_CLIENT_SECRET")
SECRET   = os.environ.get("C8_JWT_SECRET", "unsafe").encode()
AUD      = os.environ.get("C8_AUD", "https://canton.network.global")
USER     = os.environ.get("C8_USER", "ledger-api-user")
ADMIN    = os.environ.get("C8_ADMIN_USER", "participant_admin")

# LocalNet serves the registry from the scan app behind nginx, routed by Host.
# On DevNet set C8_REGISTRY, and only set C8_REGISTRY_HOST if it needs one.
REGISTRY      = os.environ.get("C8_REGISTRY",
                               "http://localhost:4000" if not IDP else "")
REGISTRY_HOST = os.environ.get("C8_REGISTRY_HOST",
                               "scan.localhost" if not IDP else "")
# Splice registries serve /registry/...; the Cantor8 one serves /api/c8/registry/...
REGISTRY_PREFIX = os.environ.get("C8_REGISTRY_PREFIX", "")
# The DSO issues Amulet. Every other registry has its own admin party.
ADMIN_PARTY = os.environ.get("C8_ADMIN_PARTY", "")

HOLDING = "#splice-api-token-holding-v1:Splice.Api.Token.HoldingV1:Holding"
TRANSFER_FACTORY = ("#splice-api-token-transfer-instruction-v1:"
                    "Splice.Api.Token.TransferInstructionV1:TransferFactory")
TRANSFER_INSTRUCTION = ("#splice-api-token-transfer-instruction-v1:"
                        "Splice.Api.Token.TransferInstructionV1:TransferInstruction")
PREAPPROVAL_PROPOSAL = ("#splice-wallet:Splice.Wallet.TransferPreapproval:"
                        "TransferPreapprovalProposal")
MANDATE          = "#daml-starter:Mandate:Mandate"
MANDATE_PROPOSAL = "#daml-starter:Mandate:MandateProposal"

_tok = {}


class LabError(Exception):
    """Something went wrong in a way worth reading, not a stack trace."""


def token(sub=USER):
    if IDP:
        if not CSEC:
            raise LabError("C8_IDP is set but C8_CLIENT_SECRET is not.")
        if "t" not in _tok:
            data = urllib.parse.urlencode({
                "grant_type": "client_credentials",
                "client_id": CID, "client_secret": CSEC}).encode()
            url = f"{IDP}/realms/master/protocol/openid-connect/token"
            try:
                _tok["t"] = json.loads(urllib.request.urlopen(
                    urllib.request.Request(url, data=data), timeout=30
                ).read())["access_token"]
            except Exception as e:
                raise LabError(f"could not get a token from {IDP}: {e}")
        return _tok["t"]
    b = lambda x: base64.urlsafe_b64encode(x).rstrip(b"=")
    h = b(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    p = b(json.dumps({"sub": sub, "aud": AUD}, separators=(",", ":")).encode())
    s = b(hmac.new(SECRET, h + b"." + p, hashlib.sha256).digest())
    return (h + b"." + p + b"." + s).decode()


def _request(url, body=None, headers=None, method=None, timeout=30):
    """One place for every HTTP call, so failures read like sentences."""
    req = urllib.request.Request(
        url, method=method or ("POST" if body is not None else "GET"),
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers or {})
    try:
        raw = urllib.request.urlopen(req, timeout=timeout).read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:600]
        raise LabError(f"HTTP {e.code} from {url}\n  {detail}")
    except urllib.error.URLError as e:
        raise LabError(f"cannot reach {url}: {e.reason}")
    except (TimeoutError, OSError) as e:
        raise LabError(f"network error calling {url}: {e}")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw.decode(errors="replace")[:600]}


def call(path, body=None, sub=USER, method=None):
    """Ledger API call."""
    return _request(BASE + path, body,
                    {"Authorization": f"Bearer {token(sub)}",
                     "Content-Type": "application/json"}, method)


def registry(path, body=None, method=None):
    """Token registry call. Public on most deployments, no token."""
    if not REGISTRY:
        raise LabError("C8_REGISTRY is not set. Transfers need the token "
                       "registry. On LocalNet it defaults to localhost:4000.")
    headers = {"Content-Type": "application/json"}
    if REGISTRY_HOST:
        headers["Host"] = REGISTRY_HOST
    return _request(REGISTRY + REGISTRY_PREFIX + path, body, headers, method)


def ledger_end(sub=USER):
    return call("/v2/state/ledger-end", sub=sub)["offset"]


def parties(sub=ADMIN):
    return call("/v2/parties", sub=sub).get("partyDetails", [])


def local_parties(sub=ADMIN):
    return [p["party"] for p in parties(sub) if p.get("isLocal")]


def find_party(prefix, sub=ADMIN):
    for p in local_parties(sub):
        if p.split("::")[0] == prefix or p.startswith(prefix):
            return p
    raise LabError(f"no local party matching '{prefix}'. Local parties:\n  " +
                   "\n  ".join(local_parties(sub)) or "  (none)")


def dso_party(sub=ADMIN):
    for p in parties(sub):
        if p["party"].startswith("DSO::"):
            return p["party"]
    raise LabError("could not find the DSO party. On LocalNet it appears once "
                   "the network has bootstrapped; wait and retry.")


def admin_party(sub=ADMIN):
    """Who issues the instrument. Defaults to the DSO, which is right for
    Amulet and wrong for every other token."""
    return ADMIN_PARTY or dso_party(sub)


def grant_act_as(user_id, party, sub=ADMIN):
    return call(f"/v2/users/{user_id}/rights",
                {"userId": user_id, "identityProviderId": "",
                 "rights": [{"kind": {"CanActAs": {"value": {"party": party}}}}]},
                sub=sub)


def allocate_party(hint, sub=ADMIN, grant_to=USER):
    """Allocate, or reuse if it already exists, then grant act-as rights.

    Without the grant you allocate a party you cannot submit as, and every
    later call returns 403 with a valid token.
    """
    for p in local_parties(sub):
        if p.split("::")[0] == hint:
            party = p
            break
    else:
        party = call("/v2/parties", {"partyIdHint": hint},
                     sub=sub)["partyDetails"]["party"]
    if grant_to:
        grant_act_as(grant_to, party, sub=sub)
    return party


def holdings(party, sub=USER):
    """Holding is an INTERFACE. TemplateFilter matches nothing and returns an
    empty list with HTTP 200, which looks exactly like a zero balance."""
    body = {"filter": {"filtersByParty": {party: {"cumulative": [
                {"identifierFilter": {"InterfaceFilter": {"value": {
                    "interfaceId": HOLDING,
                    "includeInterfaceView": True,
                    "includeCreatedEventBlob": False}}}}]}}},
            "verbose": False, "activeAtOffset": ledger_end(sub)}
    out = []
    for item in call("/v2/state/active-contracts", body, sub=sub):
        ev = item.get("contractEntry", {}).get("JsActiveContract", {}).get("createdEvent", {})
        for iv in ev.get("interfaceViews", []):
            v = iv.get("viewValue", {})
            out.append({"contractId": ev.get("contractId"),
                        "amount": v.get("amount"),
                        "instrument": v.get("instrumentId", {}).get("id"),
                        "admin": v.get("instrumentId", {}).get("admin"),
                        "locked": v.get("lock") is not None})
    return out


def submit(commands, act_as, sub=USER, disclosed=None, command_id=None,
           want_transaction=False, read_as=None):
    body = {"commands": commands,
            "commandId": command_id or f"c8lab-{uuid.uuid4()}",
            "actAs": act_as if isinstance(act_as, list) else [act_as],
            "userId": sub}
    if read_as:
        body["readAs"] = read_as if isinstance(read_as, list) else [read_as]
    if disclosed:
        body["disclosedContracts"] = [
            {"templateId": c["templateId"], "contractId": c["contractId"],
             "createdEventBlob": c["createdEventBlob"],
             "synchronizerId": c.get("synchronizerId", "")} for c in disclosed]
    path = ("/v2/commands/submit-and-wait-for-transaction" if want_transaction
            else "/v2/commands/submit-and-wait")
    if want_transaction:
        body = {"commands": body}
    return call(path, body, sub=sub)


def create_preapproval_proposal(receiver, provider, dso=None, sub=USER):
    """Step 3. Creates a PROPOSAL, not a live preapproval.

    The provider's automation accepts it a moment later. Until it does,
    transfers to you come back as `offer`, not `direct`.
    """
    return submit([{"CreateCommand": {
        "templateId": PREAPPROVAL_PROPOSAL,
        "createArguments": {"receiver": receiver, "provider": provider,
                            "expectedDso": dso or dso_party()}}}],
        act_as=receiver, sub=sub)


def transfer(sender, receiver, amount, instrument="Amulet", sub=USER, hours=24):
    """Step 6. Token standard transfer, both phases.

    1. Ask the registry for the factory plus a choice context. Privacy means you
       cannot see the issuer's config contracts, so it hands them over as
       disclosed contracts for this one transaction.
    2. Exercise TransferFactory_Transfer with those attached.

    Returns transferKind: 'direct' (receiver preapproved, money moved),
    'offer' (a TransferInstruction was created, receiver must accept), or
    'self'.
    """
    if not REGISTRY:
        raise LabError("transfers need C8_REGISTRY. See README.md.")
    try:
        amt = float(amount)
    except ValueError:
        raise LabError(f"amount '{amount}' is not a number")
    if amt <= 0:
        raise LabError("amount must be greater than zero")

    admin = admin_party()
    hs = holdings(sender, sub=sub)
    # Same instrument, same admin, and not locked. Locked holdings show in your
    # balance but cannot be spent until the lock expires.
    spendable = [h for h in hs
                 if not h["locked"] and h["instrument"] == instrument
                 and h["admin"] == admin]
    total = sum(float(h["amount"]) for h in spendable)
    if not spendable:
        locked = sum(1 for h in hs if h["locked"])
        raise LabError(f"sender has no spendable {instrument}. "
                       f"{len(hs)} holding(s), {locked} locked.")
    if total < amt:
        raise LabError(f"sender has {total} spendable {instrument}, needs {amt}")

    t0 = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    args = {"expectedAdmin": admin,
            "transfer": {"sender": sender, "receiver": receiver,
                         "amount": str(amount),
                         "instrumentId": {"admin": admin, "id": instrument},
                         "requestedAt": t0.strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "executeBefore": (t0 + datetime.timedelta(hours=hours)
                                           ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "inputHoldingCids": [h["contractId"] for h in spendable],
                         "meta": {"values": {}}},
            "extraArgs": {"context": {"values": {}}, "meta": {"values": {}}}}

    fac = registry("/registry/transfer-instruction/v1/transfer-factory",
                   {"choiceArguments": args})
    cc = fac.get("choiceContext", {})
    args["extraArgs"]["context"] = cc.get("choiceContextData", {})
    res = submit([{"ExerciseCommand": {
                    "templateId": TRANSFER_FACTORY,
                    "contractId": fac["factoryId"],
                    "choice": "TransferFactory_Transfer",
                    "choiceArgument": args}}],
                 act_as=sender, sub=sub,
                 disclosed=cc.get("disclosedContracts", []),
                 want_transaction=True)
    return {"transferKind": fac.get("transferKind"),
            "instructionCid": _find_instruction_cid(res),
            "result": res}


def _find_instruction_cid(res):
    """Dig the pending TransferInstruction cid out of the transaction tree.
    You need it to accept an offer, and submit-and-wait alone will not give
    it to you."""
    for ev in res.get("transaction", {}).get("events", []):
        created = ev.get("CreatedTreeEvent", {}).get("value") or ev.get("CreatedEvent")
        if not created:
            continue
        if "TransferInstruction" in str(created.get("templateId", "")):
            return created.get("contractId")
    return None


def accept_transfer(instruction_cid, receiver, sub=USER):
    """Accept a pending offer. Same two-phase shape as transfer():
    ask the registry for the choice context, then exercise."""
    # GetChoiceContextRequest.meta is a flat string map, NOT {"values": {...}}.
    # Sending the wrapped form gives "DecodingFailure at .meta.values".
    ctx = registry(f"/registry/transfer-instruction/v1/{instruction_cid}"
                   "/choice-contexts/accept", {"meta": {}})
    return submit([{"ExerciseCommand": {
                    "templateId": TRANSFER_INSTRUCTION,
                    "contractId": instruction_cid,
                    "choice": "TransferInstruction_Accept",
                    "choiceArgument": {"extraArgs": {
                        "context": ctx.get("choiceContextData", {}),
                        "meta": {"values": {}}}}}}],
                 act_as=receiver, sub=sub,
                 disclosed=ctx.get("disclosedContracts", []))


def _iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def mandate_propose(owner, spender, allowed, cap, hours=24,
                    instrument="Amulet", sub=USER):
    """D1 step 1: the owner proposes a spend mandate to the agent.

    The cap is denominated in `instrument`; the mandate pins the instrument
    so the agent cannot settle a different token of the owner's under it.
    """
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    return submit([{"CreateCommand": {
        "templateId": MANDATE_PROPOSAL,
        "createArguments": {
            "owner": owner, "spender": spender, "allowed": allowed,
            "cap": str(cap),
            "expiresAt": _iso(now + datetime.timedelta(hours=hours)),
            "instrument": {"admin": admin_party(), "id": instrument}}}}],
        act_as=owner, sub=sub, want_transaction=True)


def mandate_accept(proposal_cid, spender, sub=USER):
    """D1 step 2: the agent accepts, creating the Mandate."""
    return submit([{"ExerciseCommand": {
        "templateId": MANDATE_PROPOSAL, "contractId": proposal_cid,
        "choice": "Accept", "choiceArgument": {}}}],
        act_as=spender, sub=sub, want_transaction=True)


def charge_and_settle(mandate_cid, owner, spender, receiver, amount,
                      instrument="Amulet", sub=USER, hours=24):
    """D1 settlement: ONE Canton transaction in which the Mandate validates
    the exact Token Standard transfer it then executes.

    Everything up to `submit` is off-ledger preparation, because Daml cannot
    do HTTP:
      1. read the OWNER's spendable holdings from the ACS,
      2. ask the registry for a transfer factory + choice context; privacy
         means the issuer's config contracts arrive as disclosed contracts.
    Then one submission, signed by the SPENDER alone: exercise
    Mandate.ChargeAndSettle, which checks cap/expiry/allow-list/instrument
    against the `transfer` record and nested-exercises
    TransferFactory_Transfer on that same record. The registry cannot be
    lied to about what was authorised, because there is only one object.

    CREDENTIALS: the agent service needs CanActAs(spender) and, to read the
    owner's holdings, CanReadAs(owner). It must NOT have CanActAs(owner) -
    with that it could transfer directly and the mandate would be decoration.
    The owner's authority to move funds comes from the mandate contract, not
    from this submission.

    Only the direct path is supported: if the registry says the receiver has
    no preapproval ('offer'), this refuses before submitting, because the
    mandate would abort the transaction anyway rather than record a pending
    transfer as if money had moved.

    Returns the receipt and successor mandate contract ids.
    """
    if not REGISTRY:
        raise LabError("settlement needs C8_REGISTRY. See README.md.")
    amt = float(amount)
    if amt <= 0:
        raise LabError("amount must be greater than zero")

    admin = admin_party()
    spendable = [h for h in holdings(owner, sub=sub)
                 if not h["locked"] and h["instrument"] == instrument
                 and h["admin"] == admin]
    total = sum(float(h["amount"]) for h in spendable)
    if total < amt:
        raise LabError(f"owner has {total} spendable {instrument}, needs {amt}")

    t0 = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    transfer = {"sender": owner, "receiver": receiver, "amount": str(amount),
                "instrumentId": {"admin": admin, "id": instrument},
                "requestedAt": _iso(t0),
                "executeBefore": _iso(t0 + datetime.timedelta(hours=hours)),
                "inputHoldingCids": [h["contractId"] for h in spendable],
                "meta": {"values": {}}}

    # HTTP ends here: the registry hands back the factory id, the choice
    # context and the disclosed contracts for this one transaction.
    fac = registry("/registry/transfer-instruction/v1/transfer-factory",
                   {"choiceArguments": {
                       "expectedAdmin": admin, "transfer": transfer,
                       "extraArgs": {"context": {"values": {}},
                                     "meta": {"values": {}}}}})
    if fac.get("transferKind") == "offer":
        raise LabError(
            f"receiver {receiver} has no accepted TransferPreapproval, so "
            "this would only create a pending offer and the mandate refuses "
            "those. Fix:\n"
            f"  python3 c8lab.py preapproval {receiver}\n"
            "wait a moment for the validator to accept it, then retry.")
    cc = fac.get("choiceContext", {})

    # Daml begins here: one command, one transaction, policy and settlement
    # contractually linked inside Mandate.ChargeAndSettle.
    res = submit([{"ExerciseCommand": {
                    "templateId": MANDATE,
                    "contractId": mandate_cid,
                    "choice": "ChargeAndSettle",
                    "choiceArgument": {
                        "factoryCid": fac["factoryId"],
                        "transfer": transfer,
                        "extraArgs": {
                            "context": cc.get("choiceContextData", {}),
                            "meta": {"values": {}}}}}}],
                 act_as=spender, read_as=owner, sub=sub,
                 disclosed=cc.get("disclosedContracts", []),
                 want_transaction=True)
    return {"transferKind": fac.get("transferKind"),
            "receiptCid": _find_created(res, "Mandate:ChargeReceipt"),
            "mandateCid": _find_created(res, "Mandate:Mandate"),
            "result": res}


def _find_created(res, template_suffix):
    for ev in res.get("transaction", {}).get("events", []):
        created = ev.get("CreatedTreeEvent", {}).get("value") or ev.get("CreatedEvent")
        if created and template_suffix in str(created.get("templateId", "")):
            return created.get("contractId")
    return None


def check():
    """Run this first when something is broken."""
    print(f"base       {BASE}")
    print(f"mode       {'DevNet / Keycloak' if IDP else 'LocalNet / unsafe HS256'}")
    print(f"registry   {(REGISTRY + REGISTRY_PREFIX) if REGISTRY else '(not set, transfers will fail)'}")
    if IDP or ADMIN_PARTY:
        print(f"admin      {ADMIN_PARTY or '(DSO, correct for Amulet only)'}")
    token()
    print("token      ok")
    print(f"ledger end {ledger_end()}")
    ps = local_parties()
    print(f"local parties ({len(ps)}):")
    for p in ps:
        print("   ", p)
    for p in ps:
        name = p.split("::")[0]
        try:
            h = holdings(p)
        except LabError as e:
            # A 403 here is normal: the token's user has no rights over this
            # party. It is not a broken environment, it is someone else's party.
            why = "no act-as rights" if "403" in str(e) else str(e).split("\n")[0]
            print(f"\nholdings for {name}: skipped ({why})")
            continue
        if h:
            total = sum(float(x["amount"] or 0) for x in h)
            locked = sum(1 for x in h if x["locked"])
            print(f"\nholdings for {name}: {len(h)} contract(s), total {total}"
                  + (f", {locked} locked, only the unlocked ones are spendable"
                     if locked else ""))
            for x in h:
                print("   ", x)
    print("\nchecked: auth, ledger, parties, balances.")
    print("NOT checked: registry reachability, act-as rights on every party,")
    print("preapproval acceptance, or DevNet party allocation.")


def main():
    ap = argparse.ArgumentParser(description="Canton hackathon lab")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("check")
    p = sub.add_parser("party");       p.add_argument("hint")
    p = sub.add_parser("holdings");    p.add_argument("party")
    p = sub.add_parser("grant");       p.add_argument("user"); p.add_argument("party")
    p = sub.add_parser("preapproval"); p.add_argument("party"); p.add_argument("provider", nargs="?")
    p = sub.add_parser("transfer")
    p.add_argument("sender"); p.add_argument("receiver"); p.add_argument("amount")
    p.add_argument("--instrument", default="Amulet")
    p = sub.add_parser("accept");      p.add_argument("instruction_cid"); p.add_argument("receiver")
    p = sub.add_parser("mandate-propose")
    p.add_argument("owner"); p.add_argument("spender")
    p.add_argument("allowed", help="comma-separated party hints")
    p.add_argument("cap")
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--instrument", default="Amulet")
    p = sub.add_parser("mandate-accept")
    p.add_argument("proposal_cid"); p.add_argument("spender")
    p = sub.add_parser("mandate-settle")
    p.add_argument("mandate_cid"); p.add_argument("owner"); p.add_argument("spender")
    p.add_argument("receiver"); p.add_argument("amount")
    p.add_argument("--instrument", default="Amulet")
    a = ap.parse_args()

    try:
        if a.cmd in (None, "check"):
            check()
        elif a.cmd == "party":
            print(allocate_party(a.hint))
        elif a.cmd == "holdings":
            print(json.dumps(holdings(find_party(a.party)), indent=2))
        elif a.cmd == "grant":
            print(json.dumps(grant_act_as(a.user, find_party(a.party)), indent=2))
        elif a.cmd == "preapproval":
            me = find_party(a.party)
            prov = find_party(a.provider) if a.provider else find_party("app_user")
            print(json.dumps(create_preapproval_proposal(me, prov), indent=2))
            print("\nThis is a PROPOSAL. The provider's automation accepts it a")
            print("moment later. Until then, transfers to you will be 'offer'.")
        elif a.cmd == "transfer":
            out = transfer(find_party(a.sender), find_party(a.receiver),
                           a.amount, instrument=a.instrument)
            print(json.dumps(out, indent=2)[:1200])
            if out["transferKind"] == "offer":
                print(f"\nThis is an OFFER, the money has not moved yet.")
                print(f"Accept it with:\n  python3 c8lab.py accept "
                      f"{out['instructionCid']} {a.receiver}")
        elif a.cmd == "accept":
            print(json.dumps(accept_transfer(a.instruction_cid,
                                             find_party(a.receiver)), indent=2))
        elif a.cmd == "mandate-propose":
            res = mandate_propose(find_party(a.owner), find_party(a.spender),
                                  [find_party(x) for x in a.allowed.split(",")],
                                  a.cap, hours=a.hours, instrument=a.instrument)
            cid = _find_created(res, "Mandate:MandateProposal")
            print(f"proposal {cid}")
            print(f"\nThe SPENDER accepts it with:\n  python3 c8lab.py "
                  f"mandate-accept {cid} {a.spender}")
        elif a.cmd == "mandate-accept":
            res = mandate_accept(a.proposal_cid, find_party(a.spender))
            print(f"mandate {_find_created(res, 'Mandate:Mandate')}")
        elif a.cmd == "mandate-settle":
            out = charge_and_settle(a.mandate_cid, find_party(a.owner),
                                    find_party(a.spender), find_party(a.receiver),
                                    a.amount, instrument=a.instrument)
            print(f"transferKind {out['transferKind']}")
            print(f"receipt      {out['receiptCid']}")
            print(f"mandate      {out['mandateCid']}")
            print("\nSettled: the receiver holds the funds. If this had been "
                  "an offer, it\nwould have been refused before submission.")
    except LabError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
