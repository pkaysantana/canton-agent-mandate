#!/usr/bin/env python3
"""Thin loopback HTTP bridge: the authority console's live transport.

    Browser (ui/?mode=live)
        |  localhost HTTP, JSON
    this bridge
        |  agent_session.SessionState (owns the CURRENT successor Mandate cid)
        |  c8lab.charge_and_settle    (the only value-moving call)
    Mandate.ChargeAndSettle -> Canton Token Standard

This layer is transport glue ONLY. It deliberately implements none of:
spending cap, recipient allow-list, expiry, revocation. Those live in the
Daml Mandate and are checked by the ledger on every charge. The bridge's
whole job is: parse text into an intent, forward it, report what Canton
decided, and keep the session's successor contract id straight.

Security posture:
  - binds 127.0.0.1 unless --host says otherwise;
  - CORS echoes only http://localhost[:port] / http://127.0.0.1[:port];
  - request bodies are bounded (4 KiB);
  - no environment values are ever serialised into a response, and all
    error text passes through agent_demo._safe_error_text (secret
    redaction) before leaving the process;
  - an ambiguous write (network failure while a submission may have
    committed) is NEVER retried: the session is marked stale and the next
    /api/state re-resolves the current Mandate by its stable mandateId.

Run:
    python bridge.py            # needs the usual C8_* / D1_* environment
    python bridge.py --port 8917
"""

from __future__ import annotations

import argparse
import io
import json
import re
import threading
import datetime
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import c8lab
import agent_demo as demo
import agent_session

MAX_BODY_BYTES = 4096
MAX_TEXT_CHARS = 500
ACTIVITY_LIMIT = 5
ALLOWED_ORIGIN = re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d+)?$")

# Messages whose presence in a LabError means the failure happened on the
# wire, not as a ledger decision: the submission MAY have committed.
_AMBIGUOUS_MARKERS = ("cannot reach", "network error calling", "timed out")


class BridgeError(Exception):
    def __init__(self, status: int, payload: dict):
        self.status = status
        self.payload = payload


@dataclass
class Bridge:
    session: agent_session.SessionState
    lock: threading.Lock = field(default_factory=threading.Lock)
    activity: list = field(default_factory=list)
    mandate_id: str | None = None   # stable across the archive/recreate chain
    stale: bool = False             # an ambiguous write happened; re-resolve
    last_ledger_contact: str | None = None

    # ── read-only ledger views ────────────────────────────────────────

    def _active_mandates(self) -> list[dict]:
        body = {
            "filter": {"filtersByParty": {self.session.owner: {"cumulative": [
                {"identifierFilter": {"TemplateFilter": {"value": {
                    "templateId": c8lab.MANDATE,
                    "includeCreatedEventBlob": False}}}}]}}},
            "verbose": False,
            "activeAtOffset": c8lab.ledger_end(),
        }
        out = []
        for item in c8lab.call("/v2/state/active-contracts", body):
            ev = (item.get("contractEntry", {})
                      .get("JsActiveContract", {})
                      .get("createdEvent", {}))
            args = ev.get("createArgument", ev.get("createArguments", {}))
            if ev.get("contractId") and isinstance(args, dict):
                out.append({"contractId": ev["contractId"], "args": args})
        return out

    def resolve_mandate(self) -> dict:
        """Find the CURRENT Mandate; heal a stale session via mandateId.

        Read-only with respect to the ledger: a browser refresh may call
        this any number of times without changing anything on Canton.
        """
        mandates = self._active_mandates()
        self.last_ledger_contact = _now_iso()
        for m in mandates:
            if m["contractId"] == self.session.current_mandate_cid:
                self.mandate_id = m["args"].get("mandateId") or self.mandate_id
                self.stale = False
                return m
        # The cid we hold is not active: either a charge committed that we
        # never heard about (ambiguous write) or the owner rotated state.
        # The mandateId survives the archive/recreate chain, so use it.
        if self.mandate_id:
            chain = [m for m in mandates
                     if m["args"].get("mandateId") == self.mandate_id]
            if len(chain) == 1:
                self.session.current_mandate_cid = chain[0]["contractId"]
                self.stale = False
                return chain[0]
        if len(mandates) == 1:
            m = mandates[0]
            self.session.current_mandate_cid = m["contractId"]
            self.mandate_id = m["args"].get("mandateId") or self.mandate_id
            self.stale = False
            return m
        raise BridgeError(409, {
            "error": "session mandate not found among active contracts",
            "stale": True,
            "activeMandates": len(mandates),
        })

    def snapshot(self) -> dict:
        """Authority state for the UI. Descriptive only — not enforcement."""
        m = self.resolve_mandate()
        args = m["args"]
        admin = c8lab.admin_party()
        spendable = [h for h in c8lab.holdings(self.session.owner)
                     if not h["locked"] and h["admin"] == admin
                     and h["instrument"] == args.get("instrument", {}).get("id", "Amulet")]
        wallet = sum(float(h["amount"]) for h in spendable)
        cap = float(args.get("cap", 0))
        spent = float(args.get("spent", 0))
        expires = str(args.get("expiresAt", ""))
        expired = False
        try:
            expired = _parse_time(expires) <= datetime.datetime.now(datetime.timezone.utc)
        except ValueError:
            pass
        alias_of = {v: k for k, v in self.session.aliases.items()}
        allowed = [alias_of.get(p, _short_party(p)).title()
                   for p in args.get("allowed", [])]
        return {
            "walletBalance": _fmt(wallet),
            "cap": _fmt(cap),
            "spent": _fmt(spent),
            "remaining": _fmt(cap - spent),
            "mandateStatus": "expired" if expired else "active",
            "allowedRecipients": allowed,
            "expiresAt": expires,
            "mandateCid": m["contractId"],
        }

    # ── the one write path ────────────────────────────────────────────

    def submit_intent(self, text: str) -> dict:
        intent = parse_text_intent(text)
        if intent is None:
            raise BridgeError(422, {"decision": "unparsed",
                                    "error": "could not parse a payment intent"})
        try:
            party = demo.resolve_recipient(intent, self.session.aliases)
        except demo.IntentError as exc:
            # Alias resolution is an address book, not policy: the request
            # never reached Canton, and the response says so.
            return {
                "intent": _intent_json(intent),
                "decision": "rejected",
                "reason": demo._safe_error_text(exc),
                "stage": "bridge:alias-resolution (never reached Canton)",
                "before": self.snapshot(),
                "after": self.snapshot(),
                "proof": {"mandateCid": self.session.current_mandate_cid},
            }

        before = self.snapshot()
        cid = self.session.current_mandate_cid
        try:
            settlement = c8lab.charge_and_settle(
                cid, self.session.owner, self.session.spender,
                party, intent.amount)
        except c8lab.LabError as exc:
            text_err = demo._safe_error_text(exc)
            if _is_ambiguous(str(exc)):
                # The submission may or may not have committed. Do not
                # retry; force re-resolution before the next write.
                self.stale = True
                raise BridgeError(502, {
                    "decision": "error",
                    "ambiguous": True,
                    "reason": text_err,
                    "note": ("outcome unknown: the request was not retried; "
                             "session marked stale and will re-resolve the "
                             "current Mandate before the next charge"),
                })
            after = self.snapshot()  # authoritative: verifies nothing moved
            entry = {"decision": "rejected", "amount": intent.amount,
                     "recipient": intent.recipient.title(),
                     "reason": _short_reason(text_err), "at": _now_hhmm()}
            self._record(entry)
            return {
                "intent": _intent_json(intent),
                "decision": "rejected",
                "reason": _short_reason(text_err),
                "reasonDetail": text_err,
                "before": before,
                "after": after,
                "proof": {"mandateCid": cid, "damlError": text_err},
            }

        successor = settlement.get("mandateCid")
        if not isinstance(successor, str) or not successor:
            self.stale = True
            raise BridgeError(502, {
                "decision": "error",
                "ambiguous": True,
                "reason": ("settlement committed but no successor Mandate id "
                           "was returned; session marked stale"),
            })
        self.session.current_mandate_cid = successor
        receipt = demo._created_value(settlement.get("result", {}),
                                      "Mandate:ChargeReceipt")
        after = self.snapshot()
        entry = {"decision": "accepted", "amount": intent.amount,
                 "recipient": intent.recipient.title(), "at": _now_hhmm()}
        self._record(entry)
        return {
            "intent": _intent_json(intent),
            "decision": "accepted",
            "settledAmount": str(receipt.get("amount", intent.amount)),
            "grossDebit": str(receipt.get("grossDebit", "")),
            "before": before,
            "after": after,
            "proof": {
                "mandateCid": successor,
                "receiptCid": settlement.get("receiptCid"),
                "updateId": demo._transaction_id(settlement),
            },
        }

    def _record(self, entry: dict) -> None:
        self.activity.insert(0, entry)
        del self.activity[ACTIVITY_LIMIT:]


# ── helpers ───────────────────────────────────────────────────────────

def parse_text_intent(text: str) -> demo.PaymentIntent | None:
    """Deterministic mirror of the UI's parser (ui/mandate.js). The bridge
    does not judge the request; it only extracts recipient/amount/reason."""
    t = str(text).strip()
    amount = None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:cc|canton\s+coin)\b", t, re.I)
    if not m:
        m = re.search(r"(\d+\.\d+)", t)
    if m:
        amount = m.group(1)
    rm = re.search(r"pay(?:ment)?(?:\s+to)?\s+([a-z][\w-]*)", t, re.I)
    recipient = rm.group(1) if rm else ("pharmacy" if re.search(r"pharmacy", t, re.I) else None)
    reason_m = re.search(r"\bfor\s+(.+?)\s*$", t, re.I)
    reason = reason_m.group(1).rstrip(".?!") if reason_m else (
        "urgent purchase" if re.search(r"ignore|limit|override", t, re.I) else "payment")
    if not amount or not recipient:
        return None
    try:
        return demo.parse_manual_intent((recipient.lower(), amount, reason.lower()))
    except demo.IntentError:
        return None


def _is_ambiguous(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in _AMBIGUOUS_MARKERS)


def _short_reason(text: str) -> str:
    m = re.search(r"charge would exceed the cap|mandate has expired|"
                  r"recipient not (?:on the )?allow", text, re.I)
    return m.group(0).lower() if m else text[:120]


def _intent_json(intent: demo.PaymentIntent) -> dict:
    return {"recipient": intent.recipient, "amount": intent.amount,
            "reason": intent.reason}


def _fmt(value: float) -> str:
    """At least 3 decimals (matches the console's CC display), at most 6."""
    s = f"{value:.6f}"
    while s.endswith("0") and len(s.split(".")[1]) > 3:
        s = s[:-1]
    return s


def _short_party(party: str) -> str:
    return party.split("::")[0]


def _parse_time(value: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _now_hhmm() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M UTC")


# ── HTTP layer ────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    bridge: Bridge | None = None
    server_version = "AgentMandateBridge/1"

    # -- plumbing --
    def _cors(self) -> dict:
        origin = self.headers.get("Origin", "")
        if origin and ALLOWED_ORIGIN.match(origin):
            return {"Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type",
                    "Vary": "Origin"}
        return {}

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in self._cors().items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # redact-by-construction: no bodies
        print(f"[bridge] {self.address_string()} {fmt % args}")

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise BridgeError(413, {"error": "request body too large"})
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            raise BridgeError(400, {"error": "body must be JSON"})
        if not isinstance(data, dict):
            raise BridgeError(400, {"error": "body must be a JSON object"})
        return data

    # -- routes --
    def do_OPTIONS(self):
        self.send_response(204)
        for k, v in self._cors().items():
            self.send_header(k, v)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        try:
            if self.path == "/api/health":
                b = self.bridge
                self._send(200, {
                    "ok": True,
                    "mode": "live",
                    "runtime": "agent_session",
                    "stale": b.stale,
                    "lastLedgerContact": b.last_ledger_contact,
                })
            elif self.path == "/api/state":
                self._send(200, self.bridge.snapshot())
            elif self.path == "/api/activity":
                self._send(200, self.bridge.activity[:ACTIVITY_LIMIT])
            else:
                self._send(404, {"error": "not found"})
        except BridgeError as exc:
            self._send(exc.status, exc.payload)
        except c8lab.LabError as exc:
            self._send(502, {"error": demo._safe_error_text(exc)})
        except Exception as exc:  # never leak a traceback to the browser
            self._send(500, {"error": demo._safe_error_text(exc)})

    def do_POST(self):
        if self.path != "/api/intent":
            self._send(404, {"error": "not found"})
            return
        if not self.bridge.lock.acquire(blocking=False):
            self._send(409, {"error": "another request is in flight"})
            return
        try:
            data = self._read_body()
            text = data.get("text")
            if not isinstance(text, str) or not text.strip():
                raise BridgeError(400, {"error": "field 'text' (string) is required"})
            if len(text) > MAX_TEXT_CHARS:
                raise BridgeError(400, {"error": "text too long"})
            self._send(200, self.bridge.submit_intent(text))
        except BridgeError as exc:
            self._send(exc.status, exc.payload)
        except c8lab.LabError as exc:
            self._send(502, {"error": demo._safe_error_text(exc)})
        except Exception as exc:
            self._send(500, {"error": demo._safe_error_text(exc)})
        finally:
            self.bridge.lock.release()


def serve(host: str, port: int) -> None:
    session = agent_session.session_from_env()
    Handler.bridge = Bridge(session)
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"agent-mandate bridge on http://{host}:{port}")
    print(f"owner:   {session.owner}")
    print(f"spender: {session.spender}")
    print(f"mandate: {session.current_mandate_cid}")
    print("policy lives in Daml, not here")
    server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address (default loopback only)")
    parser.add_argument("--port", type=int, default=8917)
    args = parser.parse_args(argv)
    try:
        serve(args.host, args.port)
    except demo.RuntimeErrorBase as exc:
        print(f"ERROR: {demo._safe_error_text(exc)}")
        return 2
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
