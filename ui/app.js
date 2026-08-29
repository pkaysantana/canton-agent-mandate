// Agent Mandate — demo screen wiring. All data flows through the
// DataSource seam (datasource.js); this file only renders.

import { FixtureDataSource } from "./datasource.js";
import { toMils, fmtCC } from "./mandate.js";

const source = new FixtureDataSource();

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ── Authority panel ─────────────────────────────────── */

function renderAuthority(state) {
  $("wallet").textContent = state.walletBalance;
  $("cap").textContent = state.cap;
  $("spent").textContent = state.spent;
  $("remaining").textContent = state.remaining;
  const cap = toMils(state.cap);
  const spent = toMils(state.spent);
  const pct = cap ? (spent / cap) * 100 : 0;
  $("authbar-fill").style.width = `${pct}%`;
  $("authbar").setAttribute("aria-valuenow", state.spent);
  $("authbar-label").textContent = `${state.spent} / ${state.cap} CC`;
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
  $("authbar-label").textContent = `${after.spent} / ${after.cap} CC`;
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

const cap1 = (s) => s.charAt(0).toUpperCase() + s.slice(1);

function renderDecision(result) {
  const panel = $("decision");
  panel.hidden = false;
  panel.classList.remove("accepted", "rejected");
  void panel.offsetWidth; // restart entry/stamp animations
  panel.classList.add(result.decision);

  $("p-recipient").textContent = cap1(result.intent.recipient);
  $("p-amount").textContent = fmtCC(toMils(result.intent.amount));
  $("p-reason").textContent = result.intent.reason;

  const afford = $("afford");
  if (result.decision === "rejected" && result.reason === "charge would exceed the cap") {
    $("afford-wallet").textContent = result.before.walletBalance;
    $("afford-remaining").textContent = result.before.remaining;
    afford.hidden = false;
  } else {
    afford.hidden = true;
  }

  if (result.decision === "accepted") {
    $("verdict-badge").textContent = "ACCEPTED";
    $("verdict-sub").textContent = `${result.settledAmount} CC settled`;
    $("verdict-note").textContent = "Mandate advanced";
  } else {
    $("verdict-badge").textContent = "REJECTED";
    $("verdict-sub").textContent = "0 CC moved";
    $("verdict-note").textContent = `“${result.reason}”`;
  }

  const checks = $("checks");
  checks.innerHTML = "";
  for (const c of result.checks) {
    const li = document.createElement("li");
    li.className = c.ok ? "ok" : "bad";
    const label = c.invertLabel && c.ok ? "Within remaining delegated authority" : c.label;
    li.innerHTML = `<span class="mark">${c.ok ? "✓" : "✕"}</span><b></b>`;
    li.querySelector("b").textContent = label;
    checks.appendChild(li);
  }
  $("checks-disclosure").open = result.decision === "rejected";
  $("proof-disclosure").open = false;

  const proof = $("proof");
  proof.innerHTML = "";
  const rows = [
    ["Mandate CID", result.proof.mandateCid],
    ["Update ID", result.proof.updateId],
  ];
  if (result.proof.receiptCid) rows.push(["Receipt CID", result.proof.receiptCid]);
  if (result.proof.damlError) rows.push(["Daml rejection", result.proof.damlError, "err"]);
  for (const [k, v, cls] of rows) {
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
    <span class="act-dot"></span>
    <span class="act-main">
      <span class="act-head">
        <span><span class="act-verb">${verb}</span>
        <span class="act-amount"></span></span>
      </span>
      <span class="act-sub"></span>
    </span>`;
  li.querySelector(".act-amount").textContent = ` ${entry.amount} CC → ${entry.recipient}`;
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

async function submit(text) {
  if (running || !text.trim()) return;
  running = true;
  $("send").disabled = true;
  $("decision").hidden = true;

  const pipelineDone = runPipeline();
  const result = await source.submitIntent(text);
  await pipelineDone;

  if (result.decision === "unparsed") {
    settlePipeline(false);
    resetPipeline();
    $("composer").placeholder = "Try: Pay pharmacy 0.001 CC for medicine";
    running = false;
    $("send").disabled = false;
    return;
  }

  settlePipeline(result.decision === "accepted");
  renderDecision(result);
  await renderActivity(true);

  if (result.decision === "accepted") {
    await sleep(350);
    animateAuthority(result.before, result.after);
  } else if (result.reason === "charge would exceed the cap") {
    flashOvershoot(result.before, toMils(result.intent.amount));
  }

  running = false;
  $("send").disabled = false;
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

document.querySelector(".revoke").addEventListener("click", () => {
  // Non-functional in the demo: owner-side control, shown for completeness.
});

source.getAuthorityState().then(renderAuthority);
renderActivity(false);
