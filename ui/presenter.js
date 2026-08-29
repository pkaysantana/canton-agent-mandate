// Pure view-model layer: turns data-source results into exactly what the
// screen shows. No DOM. Tested directly, so state leakage between the
// settled and rejected views is a test failure, not a visual bug.

// The network badge is derived ONLY from the connection state, and
// "CANTON DEVNET · LIVE" appears for exactly one state: "live" — which
// app.js sets only after LiveDataSource's /api/health confirmed a real
// runtime AND /api/state loaded. Every other state, including a healthy
// fixture replay, must never read as live.
export const CONNECTION_STATES = ["replay", "connecting", "live", "degraded", "disconnected"];

export function badgeForConnection(conn) {
  switch (conn) {
    case "live":
      return { text: "CANTON DEVNET · LIVE", live: true, conn };
    case "connecting":
      return { text: "CONNECTING TO BRIDGE…", live: false, conn };
    case "degraded":
      return { text: "CANTON DEVNET · DEGRADED", live: false, conn };
    case "disconnected":
      return { text: "BRIDGE UNREACHABLE", live: false, conn };
    default: // replay, and any unknown value fails safe to the demo badge
      return { text: "DEMO · VERIFIED ON DEVNET", live: false, conn: "replay" };
  }
}

// Back-compat helper: a data source's mode maps to its resting
// connection state ("live" mode still starts at "connecting" in the app;
// this is only the fixture/replay path and unknown-mode fail-safe).
export function badgeForMode(mode) {
  return badgeForConnection(mode === "live" ? "live" : "replay");
}

const CAP_REASON = "charge would exceed the cap";

const cap1 = (s) => s.charAt(0).toUpperCase() + s.slice(1);

// View for the decision panel. Every field the panel renders comes from
// here; fields irrelevant to the outcome are absent/false, never stale.
export function decisionView(result) {
  const accepted = result.decision === "accepted";

  const checks = result.checks.map((c) => ({
    ok: c.ok,
    label: c.invertLabel && c.ok ? "Within remaining delegated authority" : c.label,
  }));

  const proofRows = [
    ["Mandate CID", result.proof.mandateCid],
    ["Update ID", result.proof.updateId],
  ];
  if (result.proof.receiptCid) proofRows.push(["Receipt CID", result.proof.receiptCid]);
  if (result.proof.damlError) proofRows.push(["Daml rejection", result.proof.damlError, "err"]);

  const view = {
    state: accepted ? "accepted" : "rejected",
    recipient: cap1(result.intent.recipient),
    amount: result.intent.amount,
    reason: result.intent.reason,
    badge: accepted ? "SETTLED" : "REJECTED",
    sub: accepted ? `${result.settledAmount} CC settled` : "0 CC moved",
    note: accepted ? "Mandate advanced" : `“${result.reason}”`,
    // The wallet-vs-authority comparison exists ONLY for the cap rejection.
    afford: null,
    checks,
    openChecks: !accepted,
    proofRows,
  };

  if (!accepted && result.reason === CAP_REASON) {
    view.afford = {
      wallet: result.before.walletBalance,
      remaining: result.before.remaining,
    };
  }

  return view;
}
