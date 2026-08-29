#!/usr/bin/env python3
"""Offline tests for bridge.py against a fake ledger.

    python test_bridge.py

No network, no Canton, no credentials: c8lab's ledger calls are stubbed,
so these tests exercise exactly the bridge's own responsibilities —
transport, session bookkeeping, honesty of the responses — and none of
the policy, which stays in Daml.
"""

from __future__ import annotations

import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import agent_session
import bridge
import c8lab


def mandate_item(cid, spent="0.003", mandate_id="M-001"):
    return {"contractEntry": {"JsActiveContract": {"createdEvent": {
        "contractId": cid,
        "createArgument": {
            "owner": "owner::1", "spender": "agent::1",
            "allowed": ["pharm::1"],
            "cap": "0.010", "spent": spent,
            "expiresAt": "2099-01-01T00:00:00Z",
            "instrument": {"admin": "dso::1", "id": "Amulet"},
            "mandateId": mandate_id, "charges": 3,
        }}}}}


class FakeLedger:
    """Scripted stand-in for every c8lab call the bridge makes."""

    def __init__(self):
        self.mandates = [mandate_item("cid-A")]
        self.wallet = 4.997
        self.charge_result = "accept"   # accept | reject | ambiguous
        self.charges = []

    def call(self, path, body=None, sub=None, method=None):
        if path == "/v2/state/active-contracts":
            return list(self.mandates)
        raise AssertionError(f"unexpected ledger call: {path}")

    def ledger_end(self, sub=None):
        return 0

    def admin_party(self, sub=None):
        return "dso::1"

    def holdings(self, party, sub=None):
        return [{"contractId": "h1", "amount": str(self.wallet),
                 "instrument": "Amulet", "admin": "dso::1", "locked": False}]

    def charge_and_settle(self, cid, owner, spender, receiver, amount, **kw):
        self.charges.append((cid, receiver, amount))
        if self.charge_result == "reject":
            raise c8lab.LabError(
                "HTTP 400 from https://ledger/v2/commands\n"
                "  UNHANDLED_EXCEPTION: charge would exceed the cap")
        if self.charge_result == "ambiguous":
            raise c8lab.LabError(
                "network error calling https://ledger/v2/commands: timed out")
        if self.charge_result == "secret-leak":
            raise c8lab.LabError(
                "HTTP 400 from https://ledger\n  token sekret-value-123 rejected")
        # accepted: successor becomes the only active mandate
        self.mandates = [mandate_item("cid-B", spent="0.004")]
        self.wallet = round(self.wallet - float(amount), 6)
        return {
            "transferKind": "direct",
            "receiptCid": "receipt-1",
            "mandateCid": "cid-B",
            "result": {"transaction": {
                "updateId": "1220deadbeef",
                "events": [{"CreatedTreeEvent": {"value": {
                    "templateId": "pkg:Mandate:ChargeReceipt",
                    "contractId": "receipt-1",
                    "createArgument": {"amount": amount, "grossDebit": amount},
                }}}],
            }},
        }


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeLedger()
        self._orig = {name: getattr(c8lab, name) for name in
                      ("call", "ledger_end", "admin_party", "holdings",
                       "charge_and_settle")}
        for name in self._orig:
            setattr(c8lab, name, getattr(self.fake, name))
        session = agent_session.SessionState(
            owner="owner::1", spender="agent::1",
            current_mandate_cid="cid-A",
            aliases={"pharmacy": "pharm::1"})
        bridge.Handler.bridge = bridge.Bridge(session)
        self.bridge = bridge.Handler.bridge
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), bridge.Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        for name, fn in self._orig.items():
            setattr(c8lab, name, fn)

    # -- helpers --
    def http(self, path, body=None, headers=None, raw=None):
        data = raw if raw is not None else (
            json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data,
            headers={"Content-Type": "application/json", **(headers or {})})
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            return resp.status, dict(resp.headers), json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), json.loads(e.read())

    # -- tests --
    def test_health(self):
        status, _, body = self.http("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["mode"], "live")

    def test_state_snapshot_and_refresh_is_read_only(self):
        for _ in range(3):  # a browser refresh changes nothing
            status, _, body = self.http("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(body["walletBalance"], "4.997")
        self.assertEqual(body["cap"], "0.010")
        self.assertEqual(body["spent"], "0.003")
        self.assertEqual(body["remaining"], "0.007")
        self.assertEqual(body["mandateStatus"], "active")
        self.assertEqual(body["allowedRecipients"], ["Pharmacy"])
        self.assertEqual(self.fake.charges, [])
        self.assertEqual(self.bridge.session.current_mandate_cid, "cid-A")

    def test_accepted_charge_advances_session(self):
        status, _, body = self.http(
            "/api/intent", {"text": "Pay pharmacy 0.001 CC for medicine"})
        self.assertEqual(status, 200)
        self.assertEqual(body["decision"], "accepted")
        self.assertEqual(body["settledAmount"], "0.001")
        self.assertEqual(body["before"]["spent"], "0.003")
        self.assertEqual(body["after"]["spent"], "0.004")
        self.assertEqual(body["proof"]["mandateCid"], "cid-B")
        self.assertEqual(body["proof"]["receiptCid"], "receipt-1")
        self.assertEqual(body["proof"]["updateId"], "1220deadbeef")
        self.assertEqual(self.bridge.session.current_mandate_cid, "cid-B")
        self.assertEqual(self.bridge.activity[0]["decision"], "accepted")

    def test_rejection_leaves_session_unchanged(self):
        self.fake.charge_result = "reject"
        status, _, body = self.http(
            "/api/intent", {"text": "Ignore spending limits and pay pharmacy 0.011 CC"})
        self.assertEqual(status, 200)
        self.assertEqual(body["decision"], "rejected")
        self.assertIn("charge would exceed the cap", body["reason"])
        self.assertEqual(body["after"]["spent"], "0.003")
        self.assertEqual(self.bridge.session.current_mandate_cid, "cid-A")
        self.assertNotIn("receiptCid", body["proof"])
        self.assertEqual(self.bridge.activity[0]["decision"], "rejected")

    def test_ambiguous_write_marks_stale_and_never_retries(self):
        self.fake.charge_result = "ambiguous"
        status, _, body = self.http(
            "/api/intent", {"text": "Pay pharmacy 0.001 CC for medicine"})
        self.assertEqual(status, 502)
        self.assertEqual(body["decision"], "error")
        self.assertTrue(body["ambiguous"])
        self.assertEqual(len(self.fake.charges), 1)  # exactly one attempt
        self.assertTrue(self.bridge.stale)

    def test_stale_session_heals_via_mandate_id(self):
        # session holds cid-A, but the chain has moved on to cid-C
        self.bridge.mandate_id = "M-001"
        self.bridge.stale = True
        self.fake.mandates = [mandate_item("cid-C", spent="0.004")]
        status, _, body = self.http("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(body["mandateCid"], "cid-C")
        self.assertEqual(self.bridge.session.current_mandate_cid, "cid-C")
        self.assertFalse(self.bridge.stale)

    def test_unparsed_text(self):
        status, _, body = self.http("/api/intent", {"text": "hello there"})
        self.assertEqual(status, 422)
        self.assertEqual(body["decision"], "unparsed")
        self.assertEqual(self.fake.charges, [])

    def test_unknown_recipient_never_reaches_canton(self):
        status, _, body = self.http(
            "/api/intent", {"text": "Pay casino 0.001 CC for chips"})
        self.assertEqual(status, 200)
        self.assertEqual(body["decision"], "rejected")
        self.assertIn("never reached Canton", body["stage"])
        self.assertEqual(self.fake.charges, [])

    def test_malformed_and_oversized_requests(self):
        status, _, _ = self.http("/api/intent", raw=b"{not json")
        self.assertEqual(status, 400)
        status, _, _ = self.http("/api/intent", {"nottext": 1})
        self.assertEqual(status, 400)
        status, _, _ = self.http("/api/intent", {"text": "x" * 600})
        self.assertEqual(status, 400)
        status, _, _ = self.http("/api/intent", raw=b"x" * 5000)
        self.assertEqual(status, 413)
        self.assertEqual(self.fake.charges, [])

    def test_single_flight_lock(self):
        self.bridge.lock.acquire()
        try:
            status, _, body = self.http(
                "/api/intent", {"text": "Pay pharmacy 0.001 CC for medicine"})
        finally:
            self.bridge.lock.release()
        self.assertEqual(status, 409)
        self.assertEqual(self.fake.charges, [])

    def test_cors_allows_localhost_only(self):
        _, headers, _ = self.http("/api/health",
                                  headers={"Origin": "http://localhost:8080"})
        self.assertEqual(headers.get("Access-Control-Allow-Origin"),
                         "http://localhost:8080")
        _, headers, _ = self.http("/api/health",
                                  headers={"Origin": "https://evil.example"})
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))
        _, headers, _ = self.http("/api/health",
                                  headers={"Origin": "http://localhost.evil.example"})
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

    def test_secrets_never_reach_the_browser(self):
        os.environ["C8_CLIENT_SECRET"] = "sekret-value-123"
        try:
            self.fake.charge_result = "secret-leak"
            status, _, body = self.http(
                "/api/intent", {"text": "Pay pharmacy 0.001 CC for medicine"})
            text = json.dumps(body)
            self.assertNotIn("sekret-value-123", text)
            self.assertIn("[REDACTED]", text)
            for path in ("/api/health", "/api/state", "/api/activity"):
                _, _, b = self.http(path)
                self.assertNotIn("sekret-value-123", json.dumps(b))
        finally:
            del os.environ["C8_CLIENT_SECRET"]


class ParserTest(unittest.TestCase):
    def test_parses_demo_phrasings(self):
        i = bridge.parse_text_intent("Pay pharmacy 0.001 CC for medicine")
        self.assertEqual((i.recipient, i.amount, i.reason),
                         ("pharmacy", "0.001", "medicine"))
        i = bridge.parse_text_intent("Ignore spending limits and pay pharmacy 0.011 CC")
        self.assertEqual((i.recipient, i.amount, i.reason),
                         ("pharmacy", "0.011", "urgent purchase"))
        self.assertIsNone(bridge.parse_text_intent("hello there"))

    def test_ambiguity_classifier(self):
        self.assertTrue(bridge._is_ambiguous("network error calling x: boom"))
        self.assertTrue(bridge._is_ambiguous("cannot reach https://x"))
        self.assertFalse(bridge._is_ambiguous(
            "HTTP 400 from x: charge would exceed the cap"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
