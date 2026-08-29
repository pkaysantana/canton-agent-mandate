// Integration seam. The UI talks only to this interface; swap
// FixtureDataSource for a live adapter over the Python runtime later
// without touching the rendering code.
//
// Contract:
//   getAuthorityState() -> Promise<{
//     walletBalance, cap, spent, remaining : string   // decimal CC
//     mandateStatus : "active" | "revoked" | "expired"
//     allowedRecipients : string[]
//   }>
//   submitIntent(text) -> Promise<{
//     intent: { recipient, amount, reason },
//     decision: "accepted" | "rejected",
//     settledAmount?: string,        // when accepted
//     reason?: string,               // when rejected
//     proof: { mandateCid, updateId, receiptCid?, damlError? }
//   }>
//
// A live implementation would POST the text to the agent runtime
// (agent_session.py) and return Canton's actual outcome verbatim.

import { parseIntent, evaluate, applySettlement, fmtCC, toMils } from "./mandate.js";

const FIXTURE_STATE = {
  walletBalance: "4.997",
  cap: "0.010",
  spent: "0.003",
  remaining: "0.007",
  mandateStatus: "active",
  allowedRecipients: ["Pharmacy"],
};

const FIXTURE_ACTIVITY = [
  { decision: "accepted", amount: "0.001", recipient: "Pharmacy" },
  { decision: "accepted", amount: "0.001", recipient: "Pharmacy" },
  { decision: "accepted", amount: "0.001", recipient: "Pharmacy" },
  { decision: "rejected", amount: "0.008", recipient: "Pharmacy", reason: "exceeded mandate" },
];

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
  constructor() {
    this.state = { ...FIXTURE_STATE };
    this.activity = FIXTURE_ACTIVITY.map((a) => ({ ...a }));
    this.seq = 0;
  }

  async getAuthorityState() {
    return { ...this.state };
  }

  async getActivity() {
    return this.activity.map((a) => ({ ...a }));
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
      this.activity.unshift({ decision: "accepted", amount: fmtCC(toMils(intent.amount)), recipient: recipientDisplay });
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
    });
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
