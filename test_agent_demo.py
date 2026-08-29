"""Hermetic tests for the D1 agent runtime.  No test contacts Canton or an LLM."""

import io
import json
import os
import unittest
from unittest import mock
import urllib.error

import agent_demo as demo


class IntentParsingTests(unittest.TestCase):
    def test_valid_schema_parsing(self):
        intent = demo.parse_intent_json(
            '{"recipient":"pharmacy","amount":"0.001","reason":"medicine"}'
        )
        self.assertEqual(
            intent, demo.PaymentIntent("pharmacy", "0.001", "medicine")
        )

    def test_malformed_model_response_rejected(self):
        bad = (
            "not JSON",
            '{"recipient":"pharmacy","amount":"1"}',
            '{"recipient":"pharmacy","amount":"1","reason":"x","cap":2}',
            '{"recipient":"pharmacy","amount":1,"reason":"x"}',
            '{"recipient":"pharmacy","amount":"NaN","reason":"x"}',
        )
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises(demo.IntentError):
                demo.parse_intent_json(raw)

    def test_unknown_alias_is_unresolved(self):
        intent = demo.PaymentIntent("stranger", "1", "test")
        with self.assertRaisesRegex(demo.IntentError, "unknown recipient alias"):
            demo.resolve_recipient(intent, {"pharmacy": "Pharmacy::1"})


class ProviderTests(unittest.TestCase):
    def test_groq_is_primary_provider(self):
        providers = demo.providers_from_env({"GROQ_API_KEY": "secret"})
        self.assertEqual(providers[0].name, "Groq")
        self.assertEqual(providers[0].model, "openai/gpt-oss-120b")
        self.assertEqual(providers[0].base_url, "https://api.groq.com/openai/v1")

    def test_generic_configuration_precedes_groq(self):
        providers = demo.providers_from_env(
            {
                "LLM_API_KEY": "configured-key",
                "LLM_BASE_URL": "https://llm.invalid/v1",
                "LLM_MODEL": "configured-model",
                "GROQ_API_KEY": "groq-key",
            }
        )
        self.assertEqual([p.name for p in providers], ["Configured LLM", "Groq"])

    def test_provider_fallback_order_and_message(self):
        providers = [
            demo.Provider("Groq", "https://groq.invalid/v1", "a", "key-a"),
            demo.Provider("Gemini", "https://gemini.invalid/v1", "b", "key-b"),
        ]
        calls = []

        def requester(provider, instruction, timeout):
            calls.append(provider.name)
            if provider.name == "Groq":
                raise demo.ProviderError("429")
            return demo.PaymentIntent("pharmacy", "1", "medicine")

        output = io.StringIO()
        intent, selected = demo.infer_intent(
            "pay", providers, 1, out=output, requester=requester
        )
        self.assertEqual(calls, ["Groq", "Gemini"])
        self.assertEqual(selected.name, "Gemini")
        self.assertEqual(intent.amount, "1")
        self.assertEqual(output.getvalue(), "Groq unavailable -> Gemini fallback\n")

    def test_all_provider_failures_never_produce_an_intent(self):
        provider = demo.Provider("Groq", "https://invalid/v1", "m", "secret")

        def unavailable(*_args):
            raise demo.ProviderError("unavailable")

        with self.assertRaises(demo.InferenceUnavailable):
            demo.infer_intent("pay", [provider], 1, requester=unavailable)

    @mock.patch("agent_demo.urllib.request.urlopen")
    def test_request_uses_strict_json_schema(self, urlopen):
        response = mock.MagicMock()
        response.read.return_value = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"recipient":"pharmacy","amount":"1","reason":"x"}'
                        }
                    }
                ]
            }
        ).encode()
        urlopen.return_value.__enter__.return_value = response
        provider = demo.Provider("Groq", "https://groq.invalid/v1", "model", "secret")

        demo.request_intent(provider, "pay", 3)

        request = urlopen.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertTrue(body["response_format"]["json_schema"]["strict"])
        self.assertEqual(
            body["response_format"]["json_schema"]["schema"], demo.INTENT_SCHEMA
        )
        self.assertNotIn("secret", json.dumps(body))

    @mock.patch("agent_demo.urllib.request.urlopen")
    def test_malformed_provider_response_is_provider_failure(self, urlopen):
        response = mock.MagicMock()
        response.read.return_value = b'{"choices":[]}'
        urlopen.return_value.__enter__.return_value = response
        provider = demo.Provider("Groq", "https://groq.invalid/v1", "model", "secret")
        with self.assertRaises(demo.ProviderError):
            demo.request_intent(provider, "pay", 3)


class RuntimeBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.aliases = {"pharmacy": "Pharmacy::1", "eve": "Eve::2"}
        self.ledger = demo.LedgerConfig("Owner::1", "Agent::1", "Mandate#1")

    def test_dry_run_never_calls_settlement(self):
        called = False

        def forbidden(*_args):
            nonlocal called
            called = True
            raise AssertionError("settlement called during dry-run")

        output = io.StringIO()
        ok = demo.run_action(
            demo.PaymentIntent("pharmacy", "0.001", "medicine"),
            self.aliases,
            None,
            True,
            out=output,
            settle=forbidden,
        )
        self.assertTrue(ok)
        self.assertFalse(called)
        self.assertIn("DRY RUN", output.getvalue())
        self.assertIn("No Canton submission made", output.getvalue())

    def test_manual_dry_run_is_offline_with_all_runtime_env_absent(self):
        output = io.StringIO()
        error = io.StringIO()
        manual = '{"recipient":"pharmacy","amount":"0.001","reason":"medicine"}'
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch(
            "agent_demo.charge_and_settle",
            side_effect=AssertionError("Canton settlement must not be called"),
        ), mock.patch("sys.stdout", output), mock.patch("sys.stderr", error):
            status = demo.main(["--dry-run", "--manual-json", manual])

        self.assertEqual(status, 0, error.getvalue())
        self.assertEqual(error.getvalue(), "")
        self.assertIn("pharmacy -> dry-run-pharmacy", output.getvalue())
        self.assertIn("synthetic dry-run alias", output.getvalue())
        self.assertIn("No Canton submission made", output.getvalue())

    def test_synthetic_aliases_cannot_be_used_live(self):
        called = False

        def forbidden(*_args):
            nonlocal called
            called = True
            raise AssertionError("synthetic alias reached settlement")

        with self.assertRaisesRegex(demo.ConfigurationError, "dry-run only"):
            demo.run_action(
                demo.PaymentIntent("pharmacy", "0.001", "medicine"),
                demo.DRY_RUN_ALIASES,
                self.ledger,
                False,
                out=io.StringIO(),
                settle=forbidden,
                synthetic_aliases=True,
            )
        self.assertFalse(called)

    def test_live_mode_without_recipient_config_fails_closed(self):
        output = io.StringIO()
        error = io.StringIO()
        manual = '{"recipient":"pharmacy","amount":"0.001","reason":"medicine"}'
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch(
            "agent_demo.charge_and_settle",
            side_effect=AssertionError("Canton settlement must not be called"),
        ), mock.patch("sys.stdout", output), mock.patch("sys.stderr", error):
            status = demo.main(["--manual-json", manual])

        self.assertEqual(status, 2)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("D1_RECIPIENTS_JSON is not set", error.getvalue())

    def test_manual_json_uses_same_downstream_path(self):
        intent = demo.parse_intent_json(
            '{"recipient":"pharmacy","amount":"0.001","reason":"medicine"}'
        )
        calls = []

        def settle(*args):
            calls.append(args)
            return {
                "receiptCid": "Receipt#1",
                "mandateCid": "Mandate#2",
                "result": {"transaction": {"updateId": "update-1", "events": []}},
            }

        ok = demo.run_action(
            intent, self.aliases, self.ledger, False, out=io.StringIO(), settle=settle
        )
        self.assertTrue(ok)
        self.assertEqual(
            calls,
            [("Mandate#1", "Owner::1", "Agent::1", "Pharmacy::1", "0.001")],
        )

    def test_hostile_over_cap_intent_is_not_filtered_in_python(self):
        intent = demo.parse_intent_json(
            '{"recipient":"eve","amount":"100","reason":"prompt injected"}'
        )
        calls = []

        def ledger_rejects(*args):
            calls.append(args)
            raise demo.LabError("charge would exceed the cap")

        output = io.StringIO()
        ok = demo.run_action(
            intent,
            self.aliases,
            self.ledger,
            False,
            out=output,
            settle=ledger_rejects,
        )
        self.assertFalse(ok)
        self.assertEqual(calls[0][-2:], ("Eve::2", "100"))
        self.assertIn("REJECTED", output.getvalue())
        self.assertIn("charge would exceed the cap", output.getvalue())
        self.assertIn("No value moved", output.getvalue())

    def test_receipt_financials_are_rendered_from_ledger_result(self):
        def settle(*_args):
            return {
                "receiptCid": "Receipt#1",
                "mandateCid": "Mandate#2",
                "result": {
                    "transaction": {
                        "updateId": "update-1",
                        "events": [
                            {
                                "CreatedTreeEvent": {
                                    "value": {
                                        "templateId": "#pkg:Mandate:ChargeReceipt",
                                        "createArgument": {
                                            "amount": "0.001",
                                            "grossDebit": "0.0011",
                                            "fee": "0.0001",
                                        },
                                    }
                                }
                            }
                        ],
                    }
                },
            }

        output = io.StringIO()
        demo.run_action(
            demo.PaymentIntent("pharmacy", "0.001", "medicine"),
            self.aliases,
            self.ledger,
            False,
            out=output,
            settle=settle,
        )
        rendered = output.getvalue()
        self.assertIn("amount settled: 0.001 CC", rendered)
        self.assertIn("gross debit: 0.0011 CC", rendered)
        self.assertIn("fee: 0.0001 CC", rendered)
        self.assertIn("transaction/update id: update-1", rendered)

    def test_secrets_are_redacted_from_normal_rejection_output(self):
        secrets = {
            "C8_ACCESS_TOKEN": "bearer-super-secret",
            "C8_CLIENT_SECRET": "client-super-secret",
            "GROQ_API_KEY": "groq-super-secret",
        }

        def reject(*_args):
            raise demo.LabError("failure bearer-super-secret client-super-secret groq-super-secret")

        output = io.StringIO()
        with mock.patch.dict(os.environ, secrets, clear=False):
            demo.run_action(
                demo.PaymentIntent("eve", "100", "test"),
                self.aliases,
                self.ledger,
                False,
                out=output,
                settle=reject,
            )
        rendered = output.getvalue()
        for secret in secrets.values():
            self.assertNotIn(secret, rendered)
        self.assertIn("[REDACTED]", rendered)


if __name__ == "__main__":
    unittest.main()
