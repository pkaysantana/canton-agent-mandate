#!/usr/bin/env python3
"""Minimal AI intent -> alias resolution -> Daml settlement runtime.

The model is only a parser.  It receives no tools and makes no authorization
decisions.  The sole value-moving function reachable from this application is
the existing c8lab.charge_and_settle() path; Daml remains the policy authority.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import os
import sys
from typing import Callable, Mapping, TextIO
import urllib.error
import urllib.request

from c8lab import LabError, charge_and_settle


INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "recipient": {"type": "string"},
        "amount": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["recipient", "amount", "reason"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are a payment-intent parser.

Extract the payment the user is asking the agent to make.
Do not decide whether the payment is allowed.
Do not modify requested values to comply with policy.
Return only the requested structured schema."""

RULE = "-" * 33
DRY_RUN_ALIASES = {
    "pharmacy": "dry-run-pharmacy",
    "eve": "dry-run-eve",
}
SECRET_ENV_NAMES = (
    "LLM_API_KEY",
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
    "NVIDIA_API_KEY",
    "C8_CLIENT_SECRET",
    "C8_ACCESS_TOKEN",
)


class RuntimeErrorBase(Exception):
    """Expected operator-facing failure (shown without a traceback)."""


class ConfigurationError(RuntimeErrorBase):
    pass


class IntentError(RuntimeErrorBase):
    pass


class ProviderError(RuntimeErrorBase):
    pass


class InferenceUnavailable(RuntimeErrorBase):
    pass


@dataclass(frozen=True)
class PaymentIntent:
    recipient: str
    amount: str
    reason: str


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    model: str
    api_key: str


@dataclass(frozen=True)
class LedgerConfig:
    owner: str
    spender: str
    mandate_cid: str


def _required_env(env: Mapping[str, str], names: tuple[str, ...]) -> list[str]:
    return [name for name in names if not env.get(name, "").strip()]


def providers_from_env(env: Mapping[str, str] = os.environ) -> list[Provider]:
    """Return explicitly configured then free-tier-oriented providers.

    OpenAI and Anthropic keys are intentionally not recognized.  A generic
    endpoint is used only when all three LLM_* values are explicitly set.
    """
    providers: list[Provider] = []
    generic = ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL")
    if any(env.get(name) for name in generic):
        missing = _required_env(env, generic)
        if missing:
            raise ConfigurationError(
                "incomplete generic LLM configuration; missing "
                + ", ".join(missing)
            )
        providers.append(
            Provider(
                env.get("LLM_PROVIDER_NAME", "Configured LLM"),
                env["LLM_BASE_URL"],
                env["LLM_MODEL"],
                env["LLM_API_KEY"],
            )
        )

    if env.get("GROQ_API_KEY"):
        providers.append(
            Provider(
                "Groq",
                "https://api.groq.com/openai/v1",
                "openai/gpt-oss-120b",
                env["GROQ_API_KEY"],
            )
        )
    if env.get("GEMINI_API_KEY"):
        providers.append(
            Provider(
                "Gemini",
                "https://generativelanguage.googleapis.com/v1beta/openai/",
                "gemini-3.7-flash",
                env["GEMINI_API_KEY"],
            )
        )
    if env.get("OPENROUTER_API_KEY"):
        providers.extend(
            (
                Provider(
                    "OpenRouter GLM free",
                    "https://openrouter.ai/api/v1",
                    "z-ai/glm-5.2:free",
                    env["OPENROUTER_API_KEY"],
                ),
                Provider(
                    "OpenRouter free router",
                    "https://openrouter.ai/api/v1",
                    "openrouter/free",
                    env["OPENROUTER_API_KEY"],
                ),
            )
        )

    # Avoid sending the same request twice when explicit configuration is an
    # alias of a provider-specific configuration.
    unique: list[Provider] = []
    seen: set[tuple[str, str, str]] = set()
    for provider in providers:
        identity = (
            provider.base_url.rstrip("/"),
            provider.model,
            provider.api_key,
        )
        if identity not in seen:
            seen.add(identity)
            unique.append(provider)
    return unique


def _validate_intent_object(value: object) -> PaymentIntent:
    if not isinstance(value, dict):
        raise IntentError("payment intent must be a JSON object")
    expected = set(INTENT_SCHEMA["required"])
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if extra:
            details.append("unexpected: " + ", ".join(extra))
        raise IntentError("payment intent fields invalid (" + "; ".join(details) + ")")
    if any(not isinstance(value[name], str) for name in expected):
        raise IntentError("recipient, amount, and reason must all be strings")
    if not value["recipient"].strip():
        raise IntentError("recipient alias must not be empty")
    try:
        amount = Decimal(value["amount"])
    except InvalidOperation:
        raise IntentError("amount is not a valid decimal string") from None
    if not amount.is_finite():
        raise IntentError("amount must be a finite decimal string")
    return PaymentIntent(value["recipient"], value["amount"], value["reason"])


def parse_intent_json(raw: str) -> PaymentIntent:
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        raise IntentError("payment intent is not valid JSON") from None
    return _validate_intent_object(value)


def request_intent(provider: Provider, instruction: str, timeout: float) -> PaymentIntent:
    """Call one OpenAI-compatible chat endpoint with strict JSON Schema."""
    body = {
        "model": provider.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": instruction},
        ],
        "temperature": 0,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "payment_intent",
                "strict": True,
                "schema": INTENT_SCHEMA,
            },
        },
    }
    request = urllib.request.Request(
        provider.base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + provider.api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
        content = payload["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ProviderError("provider returned non-text structured output")
        return parse_intent_json(content)
    except urllib.error.HTTPError as exc:
        # Do not echo response bodies: some gateways reflect request metadata.
        raise ProviderError(f"HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ProviderError("network unavailable") from None
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, IntentError):
        raise ProviderError("malformed or schema-invalid response") from None


def infer_intent(
    instruction: str,
    providers: list[Provider],
    timeout: float,
    out: TextIO = sys.stdout,
    requester: Callable[[Provider, str, float], PaymentIntent] = request_intent,
) -> tuple[PaymentIntent, Provider]:
    if not providers:
        raise InferenceUnavailable("no inference provider is configured")
    for index, provider in enumerate(providers):
        try:
            return requester(provider, instruction, timeout), provider
        except ProviderError:
            if index + 1 < len(providers):
                print(
                    f"{provider.name} unavailable -> "
                    f"{providers[index + 1].name} fallback",
                    file=out,
                )
    raise InferenceUnavailable("all configured inference providers failed")


def aliases_from_env(
    env: Mapping[str, str] = os.environ, *, dry_run: bool = False
) -> tuple[dict[str, str], bool]:
    raw = env.get("D1_RECIPIENTS_JSON", "")
    if not raw:
        if dry_run:
            return dict(DRY_RUN_ALIASES), True
        raise ConfigurationError("D1_RECIPIENTS_JSON is not set")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise ConfigurationError("D1_RECIPIENTS_JSON is not valid JSON") from None
    if not isinstance(value, dict) or not value:
        raise ConfigurationError("D1_RECIPIENTS_JSON must be a non-empty JSON object")
    aliases: dict[str, str] = {}
    for alias, party in value.items():
        if not isinstance(alias, str) or not alias.strip():
            raise ConfigurationError("recipient aliases must be non-empty strings")
        if not isinstance(party, str) or not party.strip():
            raise ConfigurationError(f"party for alias {alias!r} must be a non-empty string")
        normalized = alias.casefold()
        if normalized in aliases:
            raise ConfigurationError(f"duplicate case-insensitive alias: {alias}")
        aliases[normalized] = party
    return aliases, False


def ledger_config_from_env(env: Mapping[str, str] = os.environ) -> LedgerConfig:
    names = ("D1_OWNER", "D1_SPENDER", "D1_MANDATE_CID")
    missing = _required_env(env, names)
    if missing:
        raise ConfigurationError("missing live ledger configuration: " + ", ".join(missing))
    return LedgerConfig(env["D1_OWNER"], env["D1_SPENDER"], env["D1_MANDATE_CID"])


def resolve_recipient(intent: PaymentIntent, aliases: Mapping[str, str]) -> str:
    try:
        return aliases[intent.recipient.casefold()]
    except KeyError:
        raise IntentError(f"unknown recipient alias: {intent.recipient}") from None


def _created_value(result: Mapping[str, object], suffix: str) -> Mapping[str, object]:
    transaction = result.get("transaction", {})
    if not isinstance(transaction, dict):
        return {}
    for event in transaction.get("events", []):
        if not isinstance(event, dict):
            continue
        created = event.get("CreatedTreeEvent", {})
        if isinstance(created, dict):
            created = created.get("value", created)
        if not created:
            created = event.get("CreatedEvent", {})
        if not isinstance(created, dict):
            continue
        if str(created.get("templateId", "")).endswith(":" + suffix):
            arguments = created.get("createArgument", created.get("createArguments", {}))
            return arguments if isinstance(arguments, dict) else {}
    return {}


def _transaction_id(settlement: Mapping[str, object]) -> str:
    result = settlement.get("result", {})
    if not isinstance(result, dict):
        return "not returned"
    transaction = result.get("transaction", {})
    if not isinstance(transaction, dict):
        return "not returned"
    for name in ("updateId", "transactionId", "offset", "commandId"):
        if transaction.get(name):
            return str(transaction[name])
    return "not returned"


def _safe_error_text(error: BaseException, env: Mapping[str, str] = os.environ) -> str:
    text = str(error).strip() or error.__class__.__name__
    for name in SECRET_ENV_NAMES:
        secret = env.get(name)
        if secret:
            text = text.replace(secret, "[REDACTED]")
    lines = [line.strip() for line in text.splitlines() if line.strip()][:6]
    compact = " | ".join(line[:300] for line in lines)
    return compact[:900] + ("…" if len(compact) > 900 else "")


def _show_action(intent: PaymentIntent, party: str, out: TextIO) -> None:
    print(RULE, file=out)
    print("AI PROPOSED ACTION", file=out)
    print(RULE, file=out)
    print(f"recipient: {intent.recipient}", file=out)
    print(f"amount:    {intent.amount} CC", file=out)
    print(f"reason:    {intent.reason}", file=out)
    print("\nResolved party:", file=out)
    print(f"{intent.recipient} -> {party}", file=out)


def run_action(
    intent: PaymentIntent,
    aliases: Mapping[str, str],
    ledger: LedgerConfig | None,
    dry_run: bool,
    out: TextIO = sys.stdout,
    settle: Callable[..., Mapping[str, object]] | None = None,
    synthetic_aliases: bool = False,
) -> bool:
    """Resolve and either display or invoke the one bounded financial tool."""
    if synthetic_aliases and not dry_run:
        raise ConfigurationError("synthetic recipient aliases are dry-run only")
    party = resolve_recipient(intent, aliases)
    _show_action(intent, party, out)
    if synthetic_aliases:
        print("(synthetic dry-run alias; not a Canton Party ID)", file=out)
    print(f"\n{RULE}", file=out)
    print("LEDGER RESULT", file=out)
    print(RULE, file=out)
    if dry_run:
        print("DRY RUN", file=out)
        print("\nNo Canton submission made.", file=out)
        return True
    if ledger is None:
        raise ConfigurationError("live ledger configuration was not loaded")

    try:
        # This is deliberately the only value-moving call in the runtime.
        # Amount, recipient, expiry, allow-list, and cap policy stay in Daml.
        settlement = (settle or charge_and_settle)(
            ledger.mandate_cid,
            ledger.owner,
            ledger.spender,
            party,
            intent.amount,
        )
    except LabError as exc:
        print("REJECTED", file=out)
        print("\nDaml/Canton did not commit the proposed action.", file=out)
        print(f"reason: {_safe_error_text(exc)}", file=out)
        print("\nNo value moved.", file=out)
        return False

    receipt = _created_value(settlement.get("result", {}), "Mandate:ChargeReceipt")
    print("ACCEPTED", file=out)
    print(f"\namount settled: {receipt.get('amount', intent.amount)} CC", file=out)
    print(f"gross debit: {receipt.get('grossDebit', 'not returned')} CC", file=out)
    print(f"fee: {receipt.get('fee', 'not returned')} CC", file=out)
    print(f"receipt: {settlement.get('receiptCid', 'not returned')}", file=out)
    print(f"successor mandate: {settlement.get('mandateCid', 'not returned')}", file=out)
    print(f"transaction/update id: {_transaction_id(settlement)}", file=out)
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parse a payment intent, then let the Daml mandate decide it."
    )
    parser.add_argument("instruction", nargs="?", help="natural-language payment request")
    parser.add_argument(
        "--manual-json",
        metavar="JSON",
        help="deterministic payment intent; bypasses inference only",
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
    if bool(args.instruction) == bool(args.manual_json):
        print("ERROR: provide exactly one instruction or --manual-json", file=sys.stderr)
        return 2
    if args.timeout <= 0:
        print("ERROR: --timeout must be greater than zero", file=sys.stderr)
        return 2
    try:
        aliases, synthetic_aliases = aliases_from_env(dry_run=args.dry_run)
        if args.manual_json:
            intent = parse_intent_json(args.manual_json)
        else:
            intent, _provider = infer_intent(
                args.instruction, providers_from_env(), args.timeout, out=sys.stdout
            )
        ledger = None if args.dry_run else ledger_config_from_env()
        return (
            0
            if run_action(
                intent,
                aliases,
                ledger,
                args.dry_run,
                out=sys.stdout,
                synthetic_aliases=synthetic_aliases,
            )
            else 1
        )
    except InferenceUnavailable:
        print("inference unavailable", file=sys.stderr)
        print("use --manual-json for deterministic demo", file=sys.stderr)
        return 2
    except RuntimeErrorBase as exc:
        print(f"ERROR: {_safe_error_text(exc)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
