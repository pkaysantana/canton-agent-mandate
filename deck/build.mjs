// Agent Mandate — Cantor8 hackathon deck builder.
//   node build.mjs
// Emits Agent_Mandate_Cantor8_2026.pptx (16:9, 13.33 x 7.5 in).
// All figures are verified DevNet results; do not edit numbers here
// without re-verifying against the ledger evidence.

import PptxGenJS from "pptxgenjs";

const C = {
  bg: "0B0C0E",
  panel: "121418",
  line: "22262C",
  text: "ECEEF0",
  muted: "8D939C",
  faint: "5D636C",
  brass: "C8AB7A",
  brassDim: "8A7A58",
  yellow: "F3FF97",
  green: "3FC98F",
  red: "E5645F",
  redDim: "3A1D1C",
};

const FONT = "Segoe UI";
const MONO = "Consolas";

const pptx = new PptxGenJS();
pptx.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
pptx.author = "Agent Mandate";
pptx.title = "Agent Mandate — Financial authority for autonomous agents";

const W = 13.33;

function slideBase(pageLabel) {
  const s = pptx.addSlide();
  s.background = { color: C.bg };
  if (pageLabel) {
    s.addText("Agent Mandate", {
      x: 0.55, y: 7.08, w: 2.5, h: 0.3,
      fontFace: FONT, fontSize: 9, color: C.faint, charSpacing: 2,
    });
    s.addText(pageLabel, {
      x: W - 1.6, y: 7.08, w: 1.05, h: 0.3, align: "right",
      fontFace: FONT, fontSize: 9, color: C.faint,
    });
  }
  return s;
}

function chip(s, x, y, w, h, label, opts = {}) {
  s.addShape(pptx.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.05,
    fill: { color: opts.fill ?? C.panel },
    line: { color: opts.border ?? C.line, width: opts.borderWidth ?? 1 },
  });
  s.addText(label, {
    x, y, w, h, align: "center", valign: "middle",
    fontFace: FONT, fontSize: opts.fontSize ?? 12,
    bold: opts.bold ?? false,
    color: opts.color ?? C.text,
  });
}

function arrow(s, x, y, w = 0.34) {
  s.addText("→", {
    x, y, w, h: 0.4, align: "center", valign: "middle",
    fontFace: FONT, fontSize: 14, color: C.faint,
  });
}

function hairline(s, x, y, w, color = C.line) {
  s.addShape(pptx.ShapeType.line, { x, y, w, h: 0, line: { color, width: 0.75 } });
}

/* ════ SLIDE 1 — Title ═══════════════════════════════ */
{
  const s = slideBase();

  // brand mark: shield reduced to a bordered square with a check
  s.addShape(pptx.ShapeType.roundRect, {
    x: 0.9, y: 1.05, w: 0.52, h: 0.52, rectRadius: 0.07,
    fill: { color: C.panel }, line: { color: C.brassDim, width: 1.25 },
  });
  s.addText("✓", {
    x: 0.9, y: 1.05, w: 0.52, h: 0.52, align: "center", valign: "middle",
    fontFace: FONT, fontSize: 18, color: C.brass, bold: true,
  });

  s.addText("Agent Mandate", {
    x: 0.85, y: 1.75, w: 11, h: 1.1,
    fontFace: FONT, fontSize: 54, bold: true, color: C.text, charSpacing: 0.5,
  });
  s.addText("Financial authority for autonomous agents", {
    x: 0.9, y: 2.85, w: 11, h: 0.5,
    fontFace: FONT, fontSize: 20, color: C.brass,
  });

  s.addText(
    [
      { text: "The AI decides what it wants to do.\n", options: { color: C.text } },
      { text: "The ledger decides what it is ", options: { color: C.text } },
      { text: "allowed", options: { color: C.brass } },
      { text: " to do.", options: { color: C.text } },
    ],
    {
      x: 0.9, y: 3.75, w: 11.5, h: 1.35,
      fontFace: FONT, fontSize: 27, bold: true, lineSpacing: 40,
    },
  );

  // subtle motif
  const my = 5.55, ch = 0.46;
  chip(s, 0.9, my, 1.55, ch, "AI intent", { color: C.muted, fontSize: 11.5 });
  arrow(s, 2.47, my + 0.03);
  chip(s, 2.83, my, 1.85, ch, "Daml authority", { color: C.brass, border: C.brassDim, fontSize: 11.5 });
  arrow(s, 4.70, my + 0.03);
  chip(s, 5.06, my, 1.45, ch, "Canton", { color: C.yellow, fontSize: 11.5 });

  s.addText("Cantor8 London Hackathon · Build on Canton · 29 August 2026", {
    x: 0.9, y: 6.75, w: 8, h: 0.35,
    fontFace: FONT, fontSize: 11, color: C.muted,
  });
}

/* ════ SLIDE 2 — Bounded authority ═══════════════════ */
{
  const s = slideBase("2");

  s.addText(
    [
      { text: "AI agents don't just need wallets.\n", options: { color: C.text } },
      { text: "They need bounded authority.", options: { color: C.brass } },
    ],
    { x: 0.9, y: 0.55, w: 11.6, h: 1.3, fontFace: FONT, fontSize: 30, bold: true, lineSpacing: 42 },
  );

  const colY = 2.25;
  s.addText("THE AGENT MAY DECIDE", {
    x: 0.9, y: colY, w: 5.2, h: 0.4,
    fontFace: FONT, fontSize: 13, bold: true, color: C.muted, charSpacing: 3,
  });
  s.addText("THE AGENT MUST NOT DECIDE", {
    x: 7.2, y: colY, w: 5.2, h: 0.4,
    fontFace: FONT, fontSize: 13, bold: true, color: C.brass, charSpacing: 3,
  });
  hairline(s, 0.9, colY + 0.5, 5.2);
  hairline(s, 7.2, colY + 0.5, 5.2, C.brassDim);

  // center divider
  s.addShape(pptx.ShapeType.line, {
    x: 6.665, y: colY, w: 0, h: 3.3, line: { color: C.line, width: 0.75 },
  });

  const may = ["who it wants to pay", "how much it wants to send", "why it wants to pay", "when to initiate"];
  const mustNot = ["its own spending cap", "its own recipient permissions", "its own expiry", "its own revocation"];
  may.forEach((t, i) => {
    s.addText(t, {
      x: 0.9, y: colY + 0.75 + i * 0.68, w: 5.2, h: 0.5,
      fontFace: FONT, fontSize: 17, color: C.text,
    });
  });
  mustNot.forEach((t, i) => {
    s.addText(t, {
      x: 7.2, y: colY + 0.75 + i * 0.68, w: 5.2, h: 0.5,
      fontFace: FONT, fontSize: 17, color: C.text,
    });
  });

  hairline(s, 0.9, 6.35, 11.5);
  s.addText(
    [
      { text: "Probabilistic intent ", options: { color: C.text } },
      { text: "≠", options: { color: C.brass } },
      { text: " financial authority", options: { color: C.text } },
    ],
    { x: 0.9, y: 6.5, w: 11.5, h: 0.55, align: "center", fontFace: FONT, fontSize: 21, bold: true },
  );
}

/* ════ SLIDE 3 — Put the authority in Daml ═══════════ */
{
  const s = slideBase("3");

  s.addText("Put the authority in Daml", {
    x: 0.9, y: 0.55, w: 11.5, h: 0.7, fontFace: FONT, fontSize: 30, bold: true, color: C.text,
  });

  // horizontal architecture
  const fy = 1.85, fh = 0.62;
  const steps = [
    { t: "Natural-language\nrequest", w: 1.85, color: C.muted },
    { t: "AI intent", w: 1.35, color: C.muted },
    { t: "Agent runtime", w: 1.6, color: C.text },
    { t: "Daml Mandate", w: 2.0, color: C.brass, border: C.brass, borderWidth: 2, bold: true, big: true },
    { t: "Canton Token\nStandard", w: 1.8, color: C.yellow },
    { t: "Canton Coin", w: 1.5, color: C.yellow },
  ];
  let x = 0.72;
  let mandateCenter = 0;
  for (let i = 0; i < steps.length; i++) {
    const st = steps[i];
    const yOff = st.big ? -0.09 : 0;
    const hh = st.big ? fh + 0.18 : fh;
    chip(s, x, fy + yOff, st.w, hh, st.t, {
      color: st.color, border: st.border, borderWidth: st.borderWidth,
      bold: st.bold, fontSize: 11.5,
    });
    if (st.t === "Daml Mandate") mandateCenter = x + st.w / 2;
    x += st.w;
    if (i < steps.length - 1) { arrow(s, x, fy + 0.11, 0.3); x += 0.3; }
  }

  // control boundary under the Daml Mandate chip
  s.addShape(pptx.ShapeType.line, {
    x: mandateCenter, y: fy + 0.72, w: 0, h: 0.35, line: { color: C.brassDim, width: 1 },
  });
  const bx = mandateCenter - 1.6, by = 3.0;
  s.addShape(pptx.ShapeType.roundRect, {
    x: bx, y: by, w: 3.2, h: 1.72, rectRadius: 0.05,
    fill: { color: C.panel }, line: { color: C.brassDim, width: 1.25 },
  });
  s.addText("THE CONTROL BOUNDARY", {
    x: bx + 0.25, y: by + 0.14, w: 2.8, h: 0.3,
    fontFace: FONT, fontSize: 10, bold: true, color: C.brass, charSpacing: 2,
  });
  ["Recipient allowlist", "Cumulative cap", "Expiry", "Revocation"].forEach((t, i) => {
    s.addText([
      { text: "·  ", options: { color: C.brass, bold: true } },
      { text: t, options: { color: C.text } },
    ], {
      x: bx + 0.25, y: by + 0.48 + i * 0.3, w: 2.8, h: 0.3, fontFace: FONT, fontSize: 12.5,
    });
  });

  s.addText("Python deliberately does not enforce these policies.", {
    x: 0.9, y: 5.05, w: 6.6, h: 0.4,
    fontFace: FONT, fontSize: 14, italic: true, color: C.muted,
  });

  // successor state transition
  const ty = 5.95;
  chip(s, 8.05, ty, 1.6, 0.5, "Mandate A", { color: C.text, fontSize: 11.5 });
  s.addText("successful payment →", {
    x: 9.67, y: ty + 0.06, w: 1.62, h: 0.4, align: "center",
    fontFace: FONT, fontSize: 9.5, color: C.faint,
  });
  chip(s, 11.3, ty, 1.6, 0.5, "Mandate B", { color: C.brass, border: C.brassDim, fontSize: 11.5 });
  s.addText("successor automatically adopted", {
    x: 8.05, y: ty + 0.6, w: 4.85, h: 0.3, align: "center",
    fontFace: FONT, fontSize: 10.5, color: C.muted,
  });
}

/* ════ SLIDE 4 — HERO: rejection ═════════════════════ */
{
  const s = slideBase("4");

  s.addText(
    [
      { text: "The wallet could afford it. ", options: { color: C.text } },
      { text: "The agent wasn't authorised.", options: { color: C.red } },
    ],
    { x: 0.9, y: 0.5, w: 11.6, h: 0.7, fontFace: FONT, fontSize: 28, bold: true },
  );

  // three stat panels
  const py = 1.55, ph = 1.6, pw = 3.65;
  const panels = [
    { x: 0.9,  label: "FUNDS AVAILABLE",     value: "4.997 CC",  sub: "✓  sufficient",          subColor: C.muted, valueColor: C.text },
    { x: 4.84, label: "REQUESTED",           value: "0.008 CC",  sub: "to approved Pharmacy",   subColor: C.muted, valueColor: C.text },
    { x: 8.78, label: "DELEGATED AUTHORITY", value: "0.007 CC",  sub: "✕  insufficient",        subColor: C.red,   valueColor: C.brass, valueSuffix: " remaining" },
  ];
  for (const p of panels) {
    s.addShape(pptx.ShapeType.roundRect, {
      x: p.x, y: py, w: pw, h: ph, rectRadius: 0.05,
      fill: { color: C.panel }, line: { color: C.line, width: 1 },
    });
    s.addText(p.label, {
      x: p.x + 0.3, y: py + 0.18, w: pw - 0.6, h: 0.3,
      fontFace: FONT, fontSize: 11, bold: true, color: C.faint, charSpacing: 2,
    });
    s.addText(
      p.valueSuffix
        ? [{ text: p.value, options: { color: p.valueColor } },
           { text: p.valueSuffix, options: { color: C.muted, fontSize: 13, bold: false } }]
        : p.value,
      {
        x: p.x + 0.3, y: py + 0.5, w: pw - 0.6, h: 0.6,
        fontFace: FONT, fontSize: 30, bold: true, color: p.valueColor,
      },
    );
    s.addText(p.sub, {
      x: p.x + 0.3, y: py + 1.13, w: pw - 0.6, h: 0.32,
      fontFace: FONT, fontSize: 13, color: p.subColor,
    });
  }

  // verdict
  s.addShape(pptx.ShapeType.roundRect, {
    x: 5.09, y: 3.55, w: 3.15, h: 0.85, rectRadius: 0.05,
    fill: { color: C.redDim }, line: { color: C.red, width: 1.5 },
  });
  s.addText("REJECTED", {
    x: 5.09, y: 3.55, w: 3.15, h: 0.85, align: "center", valign: "middle",
    fontFace: FONT, fontSize: 30, bold: true, color: C.red, charSpacing: 4,
  });
  s.addText("“charge would exceed the cap”", {
    x: 3.9, y: 4.5, w: 5.53, h: 0.4, align: "center",
    fontFace: FONT, fontSize: 15, italic: true, color: C.red,
  });
  s.addText("0 CC moved", {
    x: 3.9, y: 4.9, w: 5.53, h: 0.45, align: "center",
    fontFace: FONT, fontSize: 19, bold: true, color: C.text,
  });

  // checks (left) + evidence (right)
  const cy = 5.55;
  const checks = [
    ["✓", "Recipient approved", C.muted],
    ["✓", "Wallet had sufficient funds", C.muted],
    ["✓", "Mandate active", C.muted],
    ["✕", "Exceeded delegated authority", C.red],
  ];
  checks.forEach(([m, t, mc], i) => {
    s.addText([
      { text: `${m}  `, options: { color: mc, bold: true } },
      { text: t, options: { color: m === "✕" ? C.red : C.text } },
    ], {
      x: 2.4, y: cy + i * 0.34, w: 4.4, h: 0.32, fontFace: FONT, fontSize: 13,
    });
  });
  s.addText("Enforced by  Mandate.ChargeAndSettle  ·  Daml", {
    x: 7.3, y: cy + 0.48, w: 4.6, h: 0.35,
    fontFace: MONO, fontSize: 12, color: C.muted,
  });

  hairline(s, 0.9, 7.0, 11.5);
  s.addText("Having the funds is not the same as having the authority to spend them.", {
    x: 0.9, y: 7.05, w: 11.5, h: 0.4, align: "center",
    fontFace: FONT, fontSize: 14.5, color: C.brass,
  });
}

/* ════ SLIDE 5 — Roadmap ═════════════════════════════ */
{
  const s = slideBase("5");

  s.addText("From AI wallets to machine authority infrastructure", {
    x: 0.9, y: 0.55, w: 11.6, h: 0.7, fontFace: FONT, fontSize: 28, bold: true, color: C.text,
  });

  const cols = [
    {
      x: 0.9, head: "PROVEN TODAY", headColor: C.text, rule: C.line,
      items: [
        "5 CC funded on DevNet",
        "3 real 0.001 CC settlements",
        "Atomic Canton Token Standard settlement",
        "Daml cap rejection",
        "Successor Mandate state",
      ],
    },
    {
      x: 5.06, head: "NEXT", headColor: C.brass, rule: C.brassDim,
      items: [
        "Procurement agents",
        "Treasury agents",
        "Recurring budgets",
        "Multi-party approvals",
        "Institutional audit + revocation",
      ],
    },
    {
      x: 9.22, head: "WHY CANTON", headColor: C.yellow, rule: C.yellow,
      items: [
        "Shared financial state",
        "Selective visibility",
        "Deterministic authority",
        "Atomic settlement",
      ],
    },
  ];

  const colY = 1.85, colW = 3.35;
  for (const c of cols) {
    s.addText(c.head, {
      x: c.x, y: colY, w: colW, h: 0.35,
      fontFace: FONT, fontSize: 13, bold: true, color: c.headColor, charSpacing: 3,
    });
    hairline(s, c.x, colY + 0.45, colW, c.rule);
    c.items.forEach((t, i) => {
      s.addText(t, {
        x: c.x, y: colY + 0.72 + i * 0.78, w: colW, h: 0.74,
        fontFace: FONT, fontSize: 14.5, color: C.text, valign: "top",
      });
    });
  }

  hairline(s, 0.9, 6.5, 11.5);
  s.addText(
    [
      { text: "AI intent. ", options: { color: C.muted } },
      { text: "Deterministic financial authority.", options: { color: C.brass, bold: true } },
    ],
    { x: 0.9, y: 6.62, w: 11.5, h: 0.5, align: "center", fontFace: FONT, fontSize: 19 },
  );
}

await pptx.writeFile({ fileName: "Agent_Mandate_Cantor8_2026.pptx" });
console.log("wrote Agent_Mandate_Cantor8_2026.pptx");
