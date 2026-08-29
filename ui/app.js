// Agent Mandate — demo screen wiring. Data comes only from the
// DataSource seam (datasource.js); what to show comes only from the
// presenter (presenter.js); this file renders.

import { FixtureDataSource, LiveDataSource } from "./datasource.js";
import { badgeForConnection, decisionView } from "./presenter.js";
import { toMils, fmtCC } from "./mandate.js";

// ?mode=live selects the real bridge; anything else is the honest replay.
const MODE = new URLSearchParams(location.search).get("mode") === "live"
  ? "live" : "replay";
const source = MODE === "live" ? new LiveDataSource() : new FixtureDataSource();

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ── Connection state: the ONLY source of the badge ──────
   "live" is set in exactly one place, after /api/health AND /api/state
   both succeeded against the real bridge. */

let conn = MODE === "live" ? "connecting" : "replay";

function setConn(next, note) {
  conn = next;
  const badge = badgeForConnection(conn);
  $("net-badge").dataset.mode = badge.conn;
  $("net-badge-text").textContent = badge.text;
  const el = $("live-note");
  if (note) {
    el.textContent = note;
    el.hidden = false;
  } else {
    el.hidden = true;
  }
}

/* ── Authority panel ─────────────────────────────────── */

function renderAuthority(state) {
  $("wallet").textContent = state.walletBalance;
  $("cap").textContent = state.cap;
  $("spent").textContent = state.spent;
  $("remaining").textContent = state.remaining;
  const cap = toMils(state.cap);
  const pct = cap ? (toMils(state.spent) / cap) * 100 : 0;
  $("authbar-fill").style.width = `${pct}%`;
  $("authbar").setAttribute("aria-valuenow", state.spent);
}

// Tween a numeric field from -> to over ~700ms, then flash it.
function animateValue(el, from, to, cls) {
  const f = toMils(from);
  const t = toMils(to);
  if (f === t) return;
  const start = performance.now();
  const dur = 700;
  function frame(now) {
    const k = Math.min(1, (now - start) / dur);
    const eased = 1 - Math.pow(1 - k, 3);
    el.textContent = fmtCC(Math.round(f + (t - f) * eased));
    if (k < 1) requestAnimationFrame(frame);
    else {
      el.textContent = fmtCC(t);
      el.classList.remove("tick", "tick-down");
      void el.offsetWidth;
      el.classList.add(cls);
    }
  }
  requestAnimationFrame(frame);
}

function animateAuthority(before, after) {
  animateValue($("spent"), before.spent, after.spent, "tick");
  animateValue($("remaining"), before.remaining, after.remaining, "tick-down");
  animateValue($("wallet"), before.walletBalance, after.walletBalance, "tick-down");
  const cap = toMils(after.cap);
  $("authbar-fill").style.width = `${(toMils(after.spent) / cap) * 100}%`;
  $("authbar").setAttribute("aria-valuenow", after.spent);
}

// Briefly show how far an over-cap request would overshoot the bar.
async function flashOvershoot(state, amountMils) {
  const cap = toMils(state.cap);
  const spent = toMils(state.spent);
  const ghost = $("authbar-ghost");
  ghost.style.width = `${Math.min(100, ((spent + amountMils) / cap) * 100)}%`;
  await sleep(1600);
  ghost.style.width = "0";
}

/* ── Pipeline ────────────────────────────────────────── */

const stages = [...document.querySelectorAll(".stage")];
const links = [...document.querySelectorAll(".stage-link")];

function resetPipeline() {
  stages.forEach((s) => s.classList.remove("active", "done", "verdict-ok", "verdict-bad"));
  links.forEach((l) => l.classList.remove("active"));
}

async function runPipeline() {
  resetPipeline();
  for (let i = 0; i < 3; i++) {
    stages[i].classList.add("active");
    await sleep(i === 0 ? 350 : 550);
    stages[i].classList.remove("active");
    stages[i].classList.add("done");
    links[i].classList.add("active");
    await sleep(180);
  }
  stages[3].classList.add("active");
  await sleep(600);
}

function settlePipeline(accepted) {
  stages[3].classList.remove("active");
  stages[3].classList.add(accepted ? "verdict-ok" : "verdict-bad");
}

/* ── Decision panel ──────────────────────────────────── */

function renderDecision(view) {
  const panel = $("decision");
  panel.hidden = false;
  panel.classList.remove("accepted", "rejected");
  void panel.offsetWidth; // restart entry/stamp animations
  panel.classList.add(view.state);

  $("p-recipient").textContent = view.recipient;
  $("p-amount").textContent = fmtCC(toMils(view.amount));
  $("p-reason").textContent = view.reason;

  const afford = $("afford");
  if (view.afford) {
    $("afford-wallet").textContent = view.afford.wallet;
    $("afford-remaining").textContent = view.afford.remaining;
    afford.hidden = false;
  } else {
    afford.hidden = true;
  }

  $("verdict-badge").textContent = view.badge;
  $("verdict-sub").textContent = view.sub;
  $("verdict-note").textContent = view.note;

  const checks = $("checks");
  checks.innerHTML = "";
  for (const c of view.checks) {
    const li = document.createElement("li");
    li.className = c.ok ? "ok" : "bad";
    li.innerHTML = `<span class="mark" aria-hidden="true">${c.ok ? "✓" : "✕"}</span><b></b>`;
    li.querySelector("b").textContent = `${c.label}${c.ok ? "" : " — failed"}`;
    checks.appendChild(li);
  }
  $("checks-disclosure").open = view.openChecks;
  $("proof-disclosure").open = false;

  const proof = $("proof");
  proof.innerHTML = "";
  for (const [k, v, cls] of view.proofRows) {
    const div = document.createElement("div");
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = k;
    dd.textContent = v;
    if (cls) dd.className = cls;
    div.append(dt, dd);
    proof.appendChild(div);
  }
}

/* ── Activity ────────────────────────────────────────── */

function activityRow(entry, isNew) {
  const li = document.createElement("li");
  li.className = entry.decision + (isNew ? " new" : "");
  const verb = entry.decision === "accepted" ? "Settled" : "Rejected";
  li.innerHTML = `
    <span class="act-dot" aria-hidden="true"></span>
    <span class="act-main">
      <span class="act-head">
        <span><span class="act-verb">${verb}</span>
        <span class="act-amount"></span></span>
        <span class="act-time"></span>
      </span>
      <span class="act-sub"></span>
    </span>`;
  li.querySelector(".act-amount").textContent = ` ${entry.amount} CC → ${entry.recipient}`;
  li.querySelector(".act-time").textContent = entry.at ?? "";
  li.querySelector(".act-sub").textContent = entry.reason ? `· ${entry.reason}` : "";
  return li;
}

async function renderActivity(newest) {
  const list = $("activity");
  const entries = await source.getActivity();
  list.innerHTML = "";
  entries.forEach((e, i) => list.appendChild(activityRow(e, newest && i === 0)));
}

/* ── Submit flow ─────────────────────────────────────── */

let running = false;

function setBusy(busy) {
  running = busy;
  $("send").disabled = busy;
  document.querySelector(".center").setAttribute("aria-busy", String(busy));
}

async function submit(text) {
  if (running || !text.trim()) return;
  setBusy(true);
  $("decision").hidden = true;

  const pipelineDone = runPipeline();
  let result;
  try {
    result = await source.submitIntent(text);
  } catch (err) {
    await pipelineDone;
    resetPipeline();
    // Transport failure: nothing to render as a ledger decision.
    setConn(err.kind === "timeout" ? "degraded" : "disconnected",
      err.kind === "timeout"
        ? "The bridge did not answer in time. The request was not retried — check the bridge, then refresh."
        : "Cannot reach the local bridge. Start bridge.py, or reload with ?mode=replay.");
    setBusy(false);
    return;
  }
  await pipelineDone;

  if (result.decision === "unparsed") {
    resetPipeline();
    $("composer").placeholder = "Try: Pay pharmacy 0.001 CC for medicine";
    setBusy(false);
    return;
  }

  if (result.decision === "error") {
    resetPipeline();
    setConn("degraded", result.ambiguous
      ? "Outcome unknown: the charge may or may not have committed. It was NOT retried; the session will re-resolve the current Mandate. Refreshing state…"
      : `Bridge error: ${result.reason}`);
    if (MODE === "live") refreshLive(false);
    setBusy(false);
    return;
  }

  if (MODE === "live") setConn("live");

  const view = decisionView(result);
  settlePipeline(view.state === "accepted");
  renderDecision(view);
  await renderActivity(true);

  if (view.state === "accepted") {
    await sleep(350);
    animateAuthority(result.before, result.after);
  } else if (view.afford) {
    flashOvershoot(result.before, toMils(result.intent.amount));
  }

  setBusy(false);
}

/* ── Reset (fixture only) ────────────────────────────── */

async function resetDemo() {
  if (running) return;
  await source.reset();
  resetPipeline();
  $("decision").hidden = true;
  $("composer").value = "";
  $("authbar-ghost").style.width = "0";
  renderAuthority(await source.getAuthorityState());
  await renderActivity(false);
}

/* ── Wire up ─────────────────────────────────────────── */

$("composer-form").addEventListener("submit", (e) => {
  e.preventDefault();
  submit($("composer").value);
});

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    const text = chip.dataset.fill;
    $("composer").value = text;
    submit(text);
  });
});

$("reset").addEventListener("click", resetDemo);

/* ── Init ────────────────────────────────────────────── */

// Refresh live state; read-only on the ledger, safe on browser refresh.
async function refreshLive(includeHealth) {
  try {
    if (includeHealth) {
      const health = await source.health();
      if (!health.ok) throw Object.assign(new Error("bridge unhealthy"), { kind: "http" });
    }
    renderAuthority(await source.getAuthorityState());
    await renderActivity(false);
    setConn("live");
  } catch (err) {
    setConn(err.kind === "unreachable" ? "disconnected" : "degraded",
      err.kind === "unreachable"
        ? "Cannot reach the local bridge. Start bridge.py, or reload with ?mode=replay."
        : `Bridge reachable but state unavailable: ${err.message}`);
  }
}

setConn(conn);
if (MODE === "live") {
  $("reset").hidden = true; // the ledger is real; there is nothing to reset
  refreshLive(true);
} else {
  source.getAuthorityState().then(renderAuthority);
  renderActivity(false);
}
