// Integration seam. The UI talks only to this interface; swap
// FixtureDataSource for LiveDataSource later without touching the
// rendering code.
//
// Contract:
//   mode : "fixture" | "live"
//     "fixture" — deterministic local replay of behaviour that was
//     verified against DevNet. The UI MUST NOT present this as live.
//     "live"    — real Canton DevNet via a localhost API. Only a real
//     adapter may ever report this; the UI shows the LIVE badge solely
//     for this value.
//   getAuthorityState() -> Promise<{
//     walletBalance, cap, spent, remaining : string   // decimal CC
//     mandateStatus : "active" | "revoked" | "expired"
//     allowedRecipients : string[]
//   }>
//   getActivity() -> Promise<entry[]>   // newest first, at most 5
//   submitIntent(text) -> Promise<{
//     intent: { recipient, amount, reason },
//     decision: "accepted" | "rejected",
//     settledAmount?: string,        // when accepted
//     reason?: string,               // when rejected
//     before, after,                 // authority snapshots
//     checks,                        // ordered Daml check results
//     proof: { mandateCid, updateId, receiptCid?, damlError? }
//   }>
//   reset() -> Promise<void>          // fixture only: restore the take

import { parseIntent, evaluate, applySettlement, fmtCC, toMils } from "./mandate.js";

const ACTIVITY_LIMIT = 5;

const FIXTURE_STATE = {
  walletBalance: "4.997",
  cap: "0.010",
  spent: "0.003",
  remaining: "0.007",
  mandateStatus: "active",
  allowedRecipients: ["Pharmacy"],
};

// Newest first.
const FIXTURE_ACTIVITY = [
  { decision: "accepted", amount: "0.001", recipient: "Pharmacy", at: "15:47 UTC" },
  { decision: "accepted", amount: "0.001", recipient: "Pharmacy", at: "15:44 UTC" },
  { decision: "accepted", amount: "0.001", recipient: "Pharmacy", at: "15:41 UTC" },
  { decision: "rejected", amount: "0.008", recipient: "Pharmacy", reason: "exceeded mandate", at: "15:38 UTC" },
];

function nowUtc() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getUTCHours())}:${p(d.getUTCMinutes())} UTC`;
}

// Deterministic fixture identifiers — shaped like Canton ids, obviously synthetic.
function fixtureProof(seq, accepted) {
  const hex = (n) => n.toString(16).padStart(8, "0");
  return {
    mandateCid: `00d1${hex(0xa9e11e + seq)}…${hex(0x5eed + seq)}`,
    updateId: `1220${hex(0xc471f4 + seq)}…${hex(0xd1 + seq)}`,
    ...(accepted
      ? { receiptCid: `00fe${hex(0xbeef00 + seq)}…${hex(0xcafe + seq)}` }
      : {
          damlError:
            "UNHANDLED_EXCEPTION / Daml.Exception.AssertionFailed: " +
            "charge would exceed the cap (Mandate.ChargeAndSettle)",
        }),
  };
}

export class FixtureDataSource {
  // NOT live. Replays behaviour verified against DevNet, locally.
  mode = "fixture";

  constructor() {
    this.reset();
  }

  async reset() {
    this.state = { ...FIXTURE_STATE };
    this.activity = FIXTURE_ACTIVITY.map((a) => ({ ...a }));
    this.seq = 0;
  }

  async getAuthorityState() {
    return { ...this.state };
  }

  async getActivity() {
    return this.activity.slice(0, ACTIVITY_LIMIT).map((a) => ({ ...a }));
  }

  async submitIntent(text) {
    const intent = parseIntent(text);
    if (!intent) {
      return { intent: null, decision: "unparsed" };
    }
    this.seq += 1;
    const verdict = evaluate(this.state, intent);
    const proof = fixtureProof(this.seq, verdict.accepted);
    const recipientDisplay =
      this.state.allowedRecipients.find(
        (r) => r.toLowerCase() === intent.recipient.toLowerCase(),
      ) ?? intent.recipient;

    if (verdict.accepted) {
      const before = { ...this.state };
      this.state = applySettlement(this.state, intent.amount);
      this.activity.unshift({
        decision: "accepted",
        amount: fmtCC(toMils(intent.amount)),
        recipient: recipientDisplay,
        at: nowUtc(),
      });
      this.activity.length = Math.min(this.activity.length, ACTIVITY_LIMIT);
      return {
        intent,
        decision: "accepted",
        settledAmount: fmtCC(toMils(intent.amount)),
        before,
        after: { ...this.state },
        checks: verdict.checks,
        proof,
      };
    }

    this.activity.unshift({
      decision: "rejected",
      amount: fmtCC(toMils(intent.amount)),
      recipient: recipientDisplay,
      reason: verdict.reason === "charge would exceed the cap" ? "exceeded mandate" : verdict.reason,
      at: nowUtc(),
    });
    this.activity.length = Math.min(this.activity.length, ACTIVITY_LIMIT);
    return {
      intent,
      decision: "rejected",
      reason: verdict.reason,
      before: { ...this.state },
      after: { ...this.state },
      checks: verdict.checks,
      proof,
    };
  }
}

// Skeleton for the real adapter. Target architecture:
//
//   browser -> localhost API -> agent_session.py -> charge_and_settle -> Canton
//
// The browser NEVER holds C8 client secrets or bearer tokens; the
// localhost API owns credentials and the browser sees only outcomes.
// Only this class may report mode "live".
export class LiveDataSource {
  mode = "live";

  constructor(baseUrl = "http://localhost:8917") {
    this.baseUrl = baseUrl;
  }

  async getAuthorityState() {
    throw new Error("LiveDataSource not implemented: GET /authority");
  }

  async getActivity() {
    throw new Error("LiveDataSource not implemented: GET /activity");
  }

  async submitIntent(_text) {
    throw new Error("LiveDataSource not implemented: POST /intent");
  }

  async reset() {
    throw new Error("LiveDataSource has no reset: the ledger is real");
  }
}
