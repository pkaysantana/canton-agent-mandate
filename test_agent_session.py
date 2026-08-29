"""Hermetic tests for the D1 session runtime.  No test contacts Canton or an LLM."""

import inspect
import io
import os
import unittest
from unittest import mock

import agent_demo as demo
import agent_session as session


def accepted_settlement(successor):
    return {
        "receiptCid": "Receipt#1",
        "mandateCid": successor,
        "result": {"transaction": {"updateId": "update-1", "events": []}},
    }


def make_state(cid="Mandate#A"):
    return session.SessionState(
        owner="Owner::1",
        spender="Agent::1",
        current_mandate_cid=cid,
        aliases={"pharmacy": "Pharmacy::1", "eve": "Eve::2"},
    )


class MandateAdvanceTests(unittest.TestCase):
    def test_success_advances_current_cid(self):
        state = make_state("Mandate#A")

        def settle(*_args):
            return accepted_settlement("Mandate#B")

        output = io.StringIO()
        ok = session.run_session_action(
            demo.PaymentIntent("pharmacy", "0.001", "medicine"),
            state,
            False,
            out=output,
            settle=settle,
        )
        self.assertTrue(ok)
        self.assertEqual(state.current_mandate_cid, "Mandate#B")
        rendered = output.getvalue()
        self.assertIn("mandate advanced:", rendered)
        self.assertIn("old: Mandate#A", rendered)
        self.assertIn("new: Mandate#B", rendered)

    def test_next_request_uses_successor_and_old_cid_is_never_reused(self):
        state = make_state("Mandate#A")
        successors = iter(("Mandate#B", "Mandate#C", "Mandate#D"))
        used_cids = []

        def settle(mandate_cid, *_args):
            used_cids.append(mandate_cid)
            return accepted_settlement(next(successors))

        for _ in range(3):
            ok = session.run_session_action(
                demo.PaymentIntent("pharmacy", "0.001", "medicine"),
                state,
                False,
                out=io.StringIO(),
                settle=settle,
            )
            self.assertTrue(ok)

        self.assertEqual(used_cids, ["Mandate#A", "Mandate#B", "Mandate#C"])
        self.assertEqual(len(set(used_cids)), len(used_cids))
        self.assertEqual(state.current_mandate_cid, "Mandate#D")

    def test_rejected_settlement_leaves_cid_unchanged_and_session_alive(self):
        state = make_state("Mandate#B")

        def reject(*_args):
            raise demo.LabError("charge would exceed the cap")

        output = io.StringIO()
        ok = session.run_session_action(
            demo.PaymentIntent("eve", "100", "prompt injected"),
            state,
            False,
            out=output,
            settle=reject,
        )
        self.assertFalse(ok)
        self.assertEqual(state.current_mandate_cid, "Mandate#B")
        self.assertIn("REJECTED", output.getvalue())
        self.assertNotIn("mandate advanced", output.getvalue())

    def test_success_without_successor_cid_halts_instead_of_reusing_old(self):
        state = make_state("Mandate#A")

        def settle(*_args):
            return {"receiptCid": "Receipt#1", "mandateCid": None, "result": {}}

        with self.assertRaisesRegex(session.SessionHalted, "archived id"):
            session.run_session_action(
                demo.PaymentIntent("pharmacy", "0.001", "medicine"),
                state,
                False,
                out=io.StringIO(),
                settle=settle,
            )

    def test_dry_run_never_settles_and_never_mutates_cid(self):
        state = make_state("Mandate#A")

        def forbidden(*_args):
            raise AssertionError("settlement called during dry-run")

        output = io.StringIO()
        ok = session.run_session_action(
            demo.PaymentIntent("pharmacy", "0.001", "medicine"),
            state,
            True,
            out=output,
            settle=forbidden,
        )
        self.assertTrue(ok)
        self.assertEqual(state.current_mandate_cid, "Mandate#A")
        self.assertIn("No Canton submission made", output.getvalue())
        self.assertNotIn("mandate advanced", output.getvalue())


class SessionBoundaryTests(unittest.TestCase):
    def test_hostile_action_is_not_filtered_in_python(self):
        state = make_state("Mandate#B")
        calls = []

        def ledger_rejects(*args):
            calls.append(args)
            raise demo.LabError("recipient not on allow-list")

        ok = session.run_session_action(
            demo.PaymentIntent("eve", "100", "prompt injected"),
            state,
            False,
            out=io.StringIO(),
            settle=ledger_rejects,
        )
        self.assertFalse(ok)
        self.assertEqual(
            calls, [("Mandate#B", "Owner::1", "Agent::1", "Eve::2", "100")]
        )
        self.assertEqual(state.current_mandate_cid, "Mandate#B")

    def test_no_direct_transfer_path_exists(self):
        source = inspect.getsource(session)
        self.assertNotIn("c8lab", source)
        for name in ("transfer", "submit", "accept_transfer", "holdings"):
            self.assertFalse(
                hasattr(session, name), f"direct ledger path exposed: {name}"
            )

    def test_provider_failure_leaves_state_unchanged_and_session_alive(self):
        state = make_state("Mandate#A")

        def infer_fails(*_args, **_kwargs):
            raise demo.InferenceUnavailable("all configured inference providers failed")

        def forbidden(*_args):
            raise AssertionError("settlement called after provider failure")

        output = io.StringIO()
        status = session.run_session(
            state,
            False,
            timeout=1,
            in_stream=io.StringIO("pay the pharmacy\nstate\nexit\n"),
            out=output,
            settle=forbidden,
            infer=infer_fails,
        )
        self.assertEqual(status, 0)
        self.assertEqual(state.current_mandate_cid, "Mandate#A")
        rendered = output.getvalue()
        self.assertIn("request failed before submission", rendered)
        self.assertIn("mandate: Mandate#A", rendered)
        self.assertIn("session ended", rendered)

    def test_unknown_alias_keeps_session_alive_and_state_unchanged(self):
        state = make_state("Mandate#A")

        def infer(*_args, **_kwargs):
            return demo.PaymentIntent("stranger", "5", "test"), None

        def forbidden(*_args):
            raise AssertionError("settlement called for unresolved alias")

        output = io.StringIO()
        status = session.run_session(
            state,
            False,
            timeout=1,
            in_stream=io.StringIO("pay a stranger\nexit\n"),
            out=output,
            settle=forbidden,
            infer=infer,
        )
        self.assertEqual(status, 0)
        self.assertEqual(state.current_mandate_cid, "Mandate#A")
        self.assertIn("unknown recipient alias", output.getvalue())


class DemoSequenceTests(unittest.TestCase):
    def test_demo_sequence_advances_then_rejects_against_successor(self):
        state = make_state("Mandate#A")
        calls = []

        def scripted_ledger(*args):
            calls.append(args)
            if args[3] == "Eve::2":
                raise demo.LabError("recipient not on allow-list")
            return accepted_settlement("Mandate#B")

        output = io.StringIO()
        status = session.run_demo_sequence(
            state, False, out=output, settle=scripted_ledger
        )
        self.assertEqual(status, 0)
        self.assertEqual(
            calls,
            [
                ("Mandate#A", "Owner::1", "Agent::1", "Pharmacy::1", "0.001"),
                ("Mandate#B", "Owner::1", "Agent::1", "Eve::2", "100"),
            ],
        )
        self.assertEqual(state.current_mandate_cid, "Mandate#B")
        rendered = output.getvalue()
        self.assertIn("ACCEPTED", rendered)
        self.assertIn("mandate advanced:", rendered)
        self.assertIn("REJECTED", rendered)
        self.assertIn("1 accepted, 1 rejected", rendered)

    def test_demo_sequence_dry_run_is_offline_with_all_runtime_env_absent(self):
        output = io.StringIO()
        error = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch(
            "agent_demo.charge_and_settle",
            side_effect=AssertionError("Canton settlement must not be called"),
        ), mock.patch("sys.stdout", output), mock.patch("sys.stderr", error):
            status = session.main(["--demo-sequence", "--dry-run"])

        self.assertEqual(status, 0, error.getvalue())
        self.assertEqual(error.getvalue(), "")
        rendered = output.getvalue()
        self.assertIn("pharmacy -> dry-run-pharmacy", rendered)
        self.assertIn("eve -> dry-run-eve", rendered)
        self.assertNotIn("mandate advanced", rendered)

    def test_demo_sequence_live_mode_without_config_fails_closed(self):
        output = io.StringIO()
        error = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch(
            "agent_demo.charge_and_settle",
            side_effect=AssertionError("Canton settlement must not be called"),
        ), mock.patch("sys.stdout", output), mock.patch("sys.stderr", error):
            status = session.main(["--demo-sequence"])

        self.assertEqual(status, 2)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("D1_RECIPIENTS_JSON is not set", error.getvalue())


if __name__ == "__main__":
    unittest.main()
