/* ExperienceOS ledger demo — front-end behavior.
   Talks to the local API in server.py; renders the chat, the per-message
   inspector (receipts), and the living ledger with lifecycle animations. */

"use strict";

const $ = (id) => document.getElementById(id);

const els = {
  log: $("chat-log"),
  hero: $("hero"),
  composer: $("composer"),
  input: $("composer-input"),
  send: $("composer-send"),
  sessionChip: $("session-chip"),
  ledger: $("ledger"),
  ledgerCount: $("ledger-count"),
  ledgerEmpty: $("ledger-empty"),
  fab: $("ledger-fab"),
  fabCount: $("fab-count"),
  providerChip: $("provider-chip"),
  providerLabel: $("provider-label"),
  settings: $("settings"),
  engine: $("engine"),
  engineList: $("engine-list"),
  toast: $("toast"),
};

const state = {
  session: 1,
  pending: false,
  provider: null,
  ledgerIds: { active: new Set(), superseded: new Set(), forgotten: new Set() },
};

const sessionId = () => `session-${state.session}`;

/* ---------- helpers ---------- */

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function scrollLog() {
  els.log.scrollTop = els.log.scrollHeight;
}

let toastTimer;
function toast(message) {
  els.toast.textContent = message;
  els.toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { els.toast.hidden = true; }, 4200);
}

async function api(path, options) {
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

const shortDigest = (d) => (d ? `⌗${d.slice(0, 10)}` : "");

/* Minimal, safe markdown-lite for model replies: escape everything first,
   then allow bold, inline code, and bullet lines. */
function renderReply(container, text) {
  const escape = (s) =>
    s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const inline = (s) =>
    escape(s)
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  const blocks = text.split(/\n{2,}/);
  container.innerHTML = blocks
    .map((block) => {
      const lines = block.split("\n");
      if (lines.every((l) => /^\s*([-*•]|\d+[.)])\s+/.test(l) || !l.trim())) {
        const items = lines
          .filter((l) => l.trim())
          .map((l) => `<li>${inline(l.replace(/^\s*([-*•]|\d+[.)])\s+/, ""))}</li>`)
          .join("");
        return `<ul>${items}</ul>`;
      }
      return `<p>${lines.map((l) => inline(l.replace(/^#{1,4}\s+/, ""))).join("<br>")}</p>`;
    })
    .join("");
}

/* ---------- provider / state ---------- */

function renderProvider(s) {
  state.provider = s.provider;
  const live = s.provider === "qwen";
  els.providerChip.classList.toggle("live", live);
  els.providerLabel.textContent = live
    ? `${s.model} · Alibaba Cloud`
    : "offline deterministic";
  const qwenRadio = document.querySelector('input[name="provider"][value="qwen"]');
  const offlineRadio = document.querySelector('input[name="provider"][value="offline"]');
  (live ? qwenRadio : offlineRadio).checked = true;
  if (!s.qwen_configured) {
    $("row-qwen").classList.add("disabled");
    qwenRadio.disabled = true;
    $("qwen-sub").textContent = "not configured — add QWEN_API_KEY to .env";
  }
}

/* ---------- chat ---------- */

function addUserMessage(text) {
  const msg = el("div", "msg msg-user");
  msg.appendChild(el("div", "msg-body", text));
  els.log.appendChild(msg);
  scrollLog();
}

const PENDING_NOTES = [
  "consulting the ledger…",
  "retrieving experience…",
  "thinking with qwen-plus…",
  "composing a reply…",
];

function addPending() {
  const msg = el("div", "msg msg-assistant");
  const body = el("div", "msg-body");
  const dots = el("span", "pending-dots");
  for (let i = 0; i < 3; i++) dots.appendChild(el("i"));
  const note = el("span", "pending-note", PENDING_NOTES[0]);
  body.append(dots, note);
  msg.appendChild(body);
  els.log.appendChild(msg);
  scrollLog();
  let i = 0;
  const timer = setInterval(() => {
    i = (i + 1) % PENDING_NOTES.length;
    if (state.provider !== "qwen" && PENDING_NOTES[i].includes("qwen")) i++;
    note.textContent = PENDING_NOTES[i % PENDING_NOTES.length];
  }, 2600);
  return { msg, stop: () => clearInterval(timer) };
}

function inspectorSummary(turn) {
  const bits = [];
  if (turn.superseded.length) {
    const to = turn.created[0] ? ` → ${clip(turn.created[0].text, 26)}` : "";
    bits.push(`updated · ${clip(turn.superseded[0].text, 26)}${to}`);
  } else if (turn.forgotten.length) {
    bits.push(`forgot · ${clip(turn.forgotten[0].text, 34)}`);
  } else if (turn.created.length) {
    const kinds = [...new Set(turn.created.map((c) => c.kind))].join(", ");
    bits.push(`remembered · ${turn.created.length} ${kinds}`);
  }
  const receipt = turn.transition && turn.transition.receipt;
  if (receipt) bits.push(shortDigest(receipt));
  return bits.join("  ·  ");
}

const clip = (t, n) => (t && t.length > n ? t.slice(0, n - 1) + "…" : t || "");

function receiptCard(turn) {
  const t = turn.transition || {};
  const wrap = el("div", "receipt-wrap");
  const inner = el("div");
  const card = el("div", "receipt");
  card.appendChild(el("div", "receipt-title", "Transition receipt"));

  const rows = [];
  if (t.type) rows.push(["Transition", t.type.replace("_", " ")]);
  if (t.route) rows.push(["Route", t.route.replace("_", " ")]);
  if (t.verifier) rows.push(["Verifier", t.verifier]);
  if (t.authority_checked) rows.push(["Authority", t.authority_reason || "checked"]);
  if (t.receipt) rows.push(["Receipt", shortDigest(t.receipt)]);
  if (t.auth_reason) rows.push(["Authorization", t.auth_reason.replace("_", " ")]);
  if (t.replacement && t.replacement.applied) {
    rows.push([
      "Replacement",
      t.replacement.receipt_issued ? "applied · receipt issued" : "applied",
    ]);
  }
  if (t.effect === "verified_existing_actions") {
    rows.push(["Handled by", "planner (precedence)"]);
  }
  if (turn.forgotten.length && !t.type) rows.push(["Action", "forget"]);

  const dl = el("dl");
  for (const [k, v] of rows) {
    const row = el("div", "receipt-row");
    row.append(el("dt", null, k), el("dd", null, v));
    dl.appendChild(row);
  }
  card.appendChild(dl);

  const authorized = t.authorized === true || t.effect === "verified_existing_actions"
    || (!t.type && (turn.superseded.length || turn.forgotten.length || turn.created.length));
  if (authorized) {
    const seal = el("div", "seal");
    seal.innerHTML = `<b>${t.authorized ? "EXACT MATCH" : "APPLIED"}</b>${
      t.receipt ? shortDigest(t.receipt) : "ledger entry"}`;
    card.appendChild(seal);
  }

  inner.appendChild(card);
  wrap.appendChild(inner);
  return wrap;
}

function addAssistantMessage(reply, turn) {
  const msg = el("div", "msg msg-assistant");
  const body = el("div", "msg-body");
  renderReply(body, reply);
  msg.appendChild(body);

  const expandable = turn && (
    turn.superseded.length || turn.forgotten.length ||
    (turn.transition && turn.transition.receipt)
  );
  const summary = turn ? inspectorSummary(turn) : "";
  if (summary) {
    const line = el(expandable ? "button" : "span", "inspect-line");
    const chev = expandable
      ? `<svg class="chev" viewBox="0 0 12 12" aria-hidden="true">` +
        `<path d="M4 2.5 8 6l-4 3.5" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>`
      : "";
    line.innerHTML = `<span class="tick">✎</span><span></span>${chev}`;
    line.children[1].textContent = summary;
    if (expandable) {
      line.setAttribute("aria-expanded", "false");
      const wrap = receiptCard(turn);
      line.addEventListener("click", () => {
        const open = wrap.classList.toggle("open");
        line.setAttribute("aria-expanded", String(open));
        if (open) setTimeout(scrollLog, 320);
      });
      msg.append(line, wrap);
    } else {
      msg.appendChild(line);
    }
  }

  els.log.appendChild(msg);
  scrollLog();
  return msg;
}

/* ---------- the ledger ---------- */

function ledgerEntry(item, status, isNew) {
  const li = el("li", `entry ${status}`);
  if (isNew) {
    li.classList.add("inked");
    if (status === "superseded") li.classList.add("struck");
    if (status === "forgotten") li.classList.add("redacted");
  }
  li.appendChild(el("span", "entry-kind", item.kind || ""));
  li.appendChild(el("span", "entry-text", item.text));
  if (status === "superseded" && item.replaced_by) {
    const note = el("span", "entry-note");
    note.innerHTML = `↳ superseded by <span class="to"></span>`;
    note.querySelector(".to").textContent = clip(item.replaced_by, 42);
    li.appendChild(note);
  }
  if (status === "forgotten" && item.reason) {
    li.appendChild(el("span", "entry-note", `↳ ${item.reason}`));
  }
  return li;
}

function renderLedger(ledger) {
  const total =
    ledger.active.length + ledger.superseded.length + ledger.forgotten.length;
  els.ledgerCount.textContent = `${total} ${total === 1 ? "entry" : "entries"}`;
  els.fabCount.textContent = String(total);
  els.ledgerEmpty.hidden = total > 0;

  for (const status of ["active", "superseded", "forgotten"]) {
    const items = ledger[status];
    const section = $(`sec-${status}`);
    const list = $(`list-${status}`);
    section.hidden = items.length === 0;
    list.textContent = "";
    const prev = state.ledgerIds[status];
    for (const item of items) {
      list.appendChild(ledgerEntry(item, status, !prev.has(item.id)));
    }
    state.ledgerIds[status] = new Set(items.map((i) => i.id));
  }
}

/* ---------- send flow ---------- */

async function send(message) {
  if (state.pending || !message.trim()) return;
  state.pending = true;
  els.send.disabled = true;
  if (els.hero) els.hero.remove();
  els.hero = null;
  addUserMessage(message);
  const pending = addPending();
  try {
    const data = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: sessionId() }),
    });
    pending.stop();
    pending.msg.remove();
    addAssistantMessage(data.reply, data.turn);
    renderLedger(data.ledger);
  } catch (err) {
    pending.stop();
    pending.msg.remove();
    toast(`No reply (${err.message}). Check the model settings and try again.`);
  } finally {
    state.pending = false;
    els.send.disabled = false;
    els.input.focus();
  }
}

els.composer.addEventListener("submit", (e) => {
  e.preventDefault();
  const message = els.input.value;
  els.input.value = "";
  send(message);
});

document.querySelectorAll(".chip").forEach((chip) =>
  chip.addEventListener("click", () => {
    els.input.value = chip.dataset.fill;
    els.input.focus();
  })
);

/* ---------- sessions ---------- */

function newSession() {
  state.session += 1;
  els.sessionChip.textContent = `Session ${state.session}`;
  const divider = el("div", "session-divider", `Session ${state.session} · memory persists`);
  els.log.appendChild(divider);
  scrollLog();
  els.input.focus();
}
$("btn-new-session").addEventListener("click", newSession);
$("settings-new-session").addEventListener("click", () => {
  els.settings.close();
  newSession();
});

/* ---------- settings ---------- */

$("btn-settings").addEventListener("click", () => els.settings.showModal());
document.querySelectorAll("[data-close]").forEach((b) =>
  b.addEventListener("click", () => b.closest("dialog").close())
);

document.querySelectorAll('input[name="provider"]').forEach((radio) =>
  radio.addEventListener("change", async () => {
    try {
      const s = await api("/api/provider", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: radio.value }),
      });
      renderProvider(s);
      toast(
        radio.value === "qwen"
          ? "Now answering with qwen-plus on Alibaba Cloud."
          : "Now answering offline. Memory kept."
      );
    } catch (err) {
      toast(`Could not switch model (${err.message}).`);
    }
  })
);

const resetBtn = $("btn-reset");
let resetArmed = false;
resetBtn.addEventListener("click", async () => {
  if (!resetArmed) {
    resetArmed = true;
    resetBtn.textContent = "Erase everything — click to confirm";
    resetBtn.classList.add("confirm");
    setTimeout(() => {
      resetArmed = false;
      resetBtn.textContent = "Erase all remembered experience";
      resetBtn.classList.remove("confirm");
    }, 4000);
    return;
  }
  try {
    await api("/api/reset", { method: "POST" });
    location.reload();
  } catch (err) {
    toast(`Reset failed (${err.message}).`);
  }
});

/* ---------- engine room ---------- */

$("btn-engine").addEventListener("click", async () => {
  els.engine.showModal();
  try {
    const data = await api("/api/turns");
    renderEngine(data.turns);
  } catch {
    /* leave the empty note */
  }
});

function renderEngine(turns) {
  els.engineList.textContent = "";
  if (!turns.length) {
    els.engineList.appendChild(el("p", "sheet-note", "No turns yet."));
    return;
  }
  for (const turn of [...turns].reverse()) {
    const t = turn.transition || {};
    const card = el("div", "engine-turn");
    const head = el("div", "engine-turn-head");
    head.appendChild(el("span", null, `${turn.session_id} · “${clip(turn.message, 46)}”`));
    const label =
      t.effect === "action_replaced" ? "updated · governed replacement"
      : t.effect === "verified_existing_actions" ? "handled by planner"
      : t.effect === "applied" || t.effect === "action_added" ? "transition applied"
      : turn.forgotten.length ? "forgot"
      : turn.created.length ? "create only"
      : "no lifecycle change";
    head.appendChild(el("span", "fx", label));
    card.appendChild(head);

    const grid = el("dl", "engine-grid");
    const rows = [
      ["planner", turn.planner.map((p) => p.action).join(", ") || "—"],
      ["route", t.route ? t.route.replace("_", " ") : "—"],
      ["transition", t.type ? t.type.replace("_", " ") : "—"],
      ["verifier", t.verifier || "—"],
      ["authority", t.authority_checked ? t.authority_reason || "checked" : "—"],
      ["receipt", t.receipt ? shortDigest(t.receipt) : "—"],
      ["authorization", t.auth_reason ? t.auth_reason.replace("_", " ") : "—"],
      ["replacement", t.replacement && t.replacement.applied
        ? (t.replacement.receipt_issued ? "applied · receipt" : "applied") : "—"],
      ["context", turn.context.selected_count != null
        ? `${turn.context.selected_count} selected · ${turn.context.skipped_count} skipped · budget ${turn.context.budget}`
        : "—"],
      ["memory", [
        turn.created.length && `${turn.created.length} created`,
        turn.superseded.length && `${turn.superseded.length} superseded`,
        turn.forgotten.length && `${turn.forgotten.length} forgotten`,
      ].filter(Boolean).join(" · ") || "unchanged"],
    ];
    for (const [k, v] of rows) {
      const row = el("div");
      row.append(el("dt", null, k), el("dd", null, String(v)));
      grid.appendChild(row);
    }
    card.appendChild(grid);
    els.engineList.appendChild(card);
  }
}

/* ---------- mobile ledger ---------- */

const mobile = window.matchMedia("(max-width: 960px)");
function syncFab() {
  els.fab.hidden = !mobile.matches;
  if (!mobile.matches) els.ledger.classList.remove("open");
}
mobile.addEventListener("change", syncFab);
els.fab.addEventListener("click", () => els.ledger.classList.toggle("open"));
document.addEventListener("click", (e) => {
  if (
    mobile.matches &&
    els.ledger.classList.contains("open") &&
    !els.ledger.contains(e.target) &&
    e.target !== els.fab && !els.fab.contains(e.target)
  ) {
    els.ledger.classList.remove("open");
  }
});

/* ---------- init ---------- */

(async function init() {
  syncFab();
  try {
    const [s, ledger] = await Promise.all([api("/api/state"), api("/api/ledger")]);
    renderProvider(s);
    renderLedger(ledger);
  } catch {
    els.providerLabel.textContent = "backend unreachable";
    toast("The local server is not responding. Start it with: python web/server.py");
  }
  els.input.focus();
})();
