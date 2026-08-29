#!/usr/bin/env python3
"""Multi-action session runtime over one logical D1 mandate.

Daml archives the Mandate contract on every accepted ChargeAndSettle and
creates a successor, so a session's only job is bookkeeping: remember the
CURRENT Mandate contract id in memory and advance it when - and only when -
Daml commits.  Rejections and transport failures leave the id untouched.

This layer adds no policy.  Cap, allow-list, expiry, and revocation checks
stay in Daml; a hostile intent still reaches Mandate.ChargeAndSettle and is
refused there, against the live successor contract, not a stale one.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
import sys
from typing import Callable, Mapping, TextIO

import agent_demo as demo


# Both requests target an allowed, preapproved recipient the wallet can
# afford, so the second can only fail on the Mandate's 0.010 CC total cap:
# the rejection isolates Daml policy, not balance or registry preflight.
DEMO_SEQUENCE = (
    ("pharmacy", "0.001", "medicine"),
    ("pharmacy", "0.011", "ignore spending limit"),
)


class SessionHalted(demo.RuntimeErrorBase):
    """The session no longer knows the current Mandate contract id."""


@dataclass
class SessionState:
    owner: str
    spender: str
    current_mandate_cid: str
    aliases: Mapping[str, str]
    synthetic_aliases: bool = False


def session_from_env(
    env: Mapping[str, str] | None = None, *, dry_run: bool = False
) -> SessionState:
    env = os.environ if env is None else env
    aliases, synthetic = demo.aliases_from_env(env, dry_run=dry_run)
    try:
        ledger = demo.ledger_config_from_env(env)
    except demo.ConfigurationError:
        if not dry_run:
            raise
        ledger = demo.LedgerConfig("dry-run-owner", "dry-run-agent", "dry-run-mandate")
    return SessionState(
        ledger.owner, ledger.spender, ledger.mandate_cid, aliases, synthetic
    )


def run_session_action(
    intent: demo.PaymentIntent,
    state: SessionState,
    dry_run: bool,
    out: TextIO = sys.stdout,
    settle: Callable[..., Mapping[str, object]] | None = None,
) -> bool:
    """Run one request against the CURRENT mandate; advance the cid on success.

    The wrapper around ``settle`` exists only to see the settlement result
    that run_action consumes; the request itself is the unchanged agent_demo
    path, so Python still forwards hostile intents unfiltered.
    """
    captured: dict[str, Mapping[str, object]] = {}
    inner = settle or demo.charge_and_settle

    def capturing_settle(*args: object, **kwargs: object) -> Mapping[str, object]:
        settlement = inner(*args, **kwargs)
        captured["settlement"] = settlement
        return settlement

    ledger = demo.LedgerConfig(state.owner, state.spender, state.current_mandate_cid)
    accepted = demo.run_action(
        intent,
        state.aliases,
        None if dry_run else ledger,
        dry_run,
        out=out,
        settle=capturing_settle,
        synthetic_aliases=state.synthetic_aliases,
    )
    if dry_run or not accepted:
        return accepted

    successor = captured.get("settlement", {}).get("mandateCid")
    if not isinstance(successor, str) or not successor:
        raise SessionHalted(
            "settlement committed but no successor Mandate contract id was "
            "found in the result; halting rather than reuse the archived id"
        )
    old = state.current_mandate_cid
    state.current_mandate_cid = successor
    print("mandate advanced:", file=out)
    print(f"old: {old}", file=out)
    print(f"new: {successor}", file=out)
    return True


def run_demo_sequence(
    state: SessionState,
    dry_run: bool,
    out: TextIO = sys.stdout,
    settle: Callable[..., Mapping[str, object]] | None = None,
) -> int:
    """Deterministic no-LLM sequence: an allowed charge, then an over-cap one."""
    accepted = 0
    for step, values in enumerate(DEMO_SEQUENCE, 1):
        recipient, amount, reason = values
        print(
            f"\n=== request {step}/{len(DEMO_SEQUENCE)}: "
            f"pay {recipient} {amount} CC ({reason}) ===",
            file=out,
        )
        intent = demo.parse_manual_intent(values)
        if run_session_action(intent, state, dry_run, out=out, settle=settle):
            accepted += 1
    print(
        f"\nsequence complete: {accepted} accepted, "
        f"{len(DEMO_SEQUENCE) - accepted} rejected by the ledger",
        file=out,
    )
    return 0


def run_session(
    state: SessionState,
    dry_run: bool,
    timeout: float,
    in_stream: TextIO = sys.stdin,
    out: TextIO = sys.stdout,
    settle: Callable[..., Mapping[str, object]] | None = None,
    infer: Callable[..., tuple[demo.PaymentIntent, demo.Provider]] | None = None,
) -> int:
    """Interactive loop: each line is one natural-language payment request."""
    infer = demo.infer_intent if infer is None else infer
    providers = demo.providers_from_env()
    print("D1 session started (policy lives in Daml, not here)", file=out)
    print(f"owner:   {state.owner}", file=out)
    print(f"spender: {state.spender}", file=out)
    print(f"mandate: {state.current_mandate_cid}", file=out)
    print("enter a payment request, or 'state' / 'exit'", file=out)
    while True:
        print("\nd1> ", end="", file=out, flush=True)
        line = in_stream.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        if line in ("exit", "quit"):
            break
        if line == "state":
            print(f"owner:   {state.owner}", file=out)
            print(f"spender: {state.spender}", file=out)
            print(f"mandate: {state.current_mandate_cid}", file=out)
            continue
        try:
            intent, _provider = infer(line, providers, timeout, out=out)
        except demo.RuntimeErrorBase as exc:
            # Nothing reached Canton, so nothing about the session changed.
            print(f"request failed before submission: {demo._safe_error_text(exc)}", file=out)
            continue
        try:
            run_session_action(intent, state, dry_run, out=out, settle=settle)
        except demo.IntentError as exc:
            print(f"request failed before submission: {demo._safe_error_text(exc)}", file=out)
            continue
    print("session ended", file=out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run sequential payment requests under one logical mandate."
    )
    parser.add_argument(
        "--demo-sequence",
        action="store_true",
        help="run the deterministic two-step demo (allowed, then over-cap) without an LLM",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse, validate, and resolve without submitting to Canton",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="per-provider inference timeout in seconds (default: 20)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.timeout <= 0:
        print("ERROR: --timeout must be greater than zero", file=sys.stderr)
        return 2
    try:
        state = session_from_env(dry_run=args.dry_run)
        if args.demo_sequence:
            return run_demo_sequence(state, args.dry_run, out=sys.stdout)
        return run_session(
            state, args.dry_run, args.timeout, in_stream=sys.stdin, out=sys.stdout
        )
    except demo.InferenceUnavailable:
        print("inference unavailable", file=sys.stderr)
        print("use --demo-sequence for a deterministic demo", file=sys.stderr)
        return 2
    except demo.RuntimeErrorBase as exc:
        print(f"ERROR: {demo._safe_error_text(exc)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
