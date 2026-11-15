// Run page: poll the event log, animate progress, then load the report and the scenario map.
(() => {
  const root = document.getElementById("run");
  if (!root) return;
  const runId = root.dataset.run;
  const $ = id => document.getElementById(id);
  const PHASES = ["assets", "firms", "scenarios", "macro", "countries", "risk", "remediation"];
  let seq = 0, done = false;
  const counts = {};
  // Phases 02-04 run in parallel and share one "now" slot. Track what is in flight per phase so that,
  // when one phase finishes, the slot switches to what is still running instead of freezing on the
  // last event of the finished phase (e.g. the last scenario while the filings agent keeps reading).
  const inflight = {}, started = {};
  const LABELS = { assets: "Market data & filings", firms: "Company disclosures", market: "Market stress",
                   scenarios: "Scenarios", macro: "Macro & sources", countries: "Country risk", risk: "Portfolio risk", remediation: "Recommendations" };
  let pendingShown = null, needPending = false, shownItem = null;

  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function show(label, title, sub) {
    pendingShown = null; needPending = false; shownItem = null;
    $("now-label").textContent = label;
    const stage = $("now-stage");
    const old = stage.querySelector(".now-item:not(.out)");
    if (old) { old.classList.add("out"); setTimeout(() => old.remove(), 450); }
    const el = document.createElement("div");
    el.className = "now-item in";
    el.innerHTML = `<span class="now-title">${esc(title)}</span><span class="now-sub mono">${esc(sub || "")}</span>`;
    stage.appendChild(el);
    requestAnimationFrame(() => requestAnimationFrame(() => el.classList.remove("in")));
  }

  function showItem(phase, kind, id, label) {
    const n = (inflight[phase] || new Map()).size;
    show(phase === "firms" ? "Filings agent reading" : kind === "asset" ? "Prices and filings" : "Assessing country",
         label, id + (n > 1 ? ` · ${n} in progress` : ""));
    shownItem = { phase, id };
  }

  // Everything running at this moment, one chip each: assets, countries and the scenario step all run in parallel.
  const GROUP = { assets: "Filings", firms: "Disclosures", countries: "Country", scenarios: "Scenarios", market: "Market", macro: "Macro" };
  function renderLive() {
    const chips = [];
    for (const [phase, items] of Object.entries(inflight)) {
      if (phase === "scenarios" || !(items instanceof Map)) continue;
      for (const [id, label] of items) chips.push(`<li><b>${esc(GROUP[phase] || phase)}</b> ${esc(label)}</li>`);
    }
    for (const p of Object.keys(started)) {
      if (p === "scenarios" && document.querySelector(`.phases li[data-phase="scenarios"]`)?.dataset.state === "active")
        chips.push(`<li><b>${GROUP.scenarios}</b> weekly set</li>`);
    }
    const el = $("live");
    if (el) { el.innerHTML = chips.join(""); el.hidden = !chips.length; }
  }

  function log(id, label, detail) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="code">${esc(id)}</span><span>${esc(label)}</span><span class="muted mono">${esc(detail)}</span>`;
    $("log").prepend(li);
    [...$("log").children].slice(8).forEach(n => n.remove());
  }

  const ago = t => { const s = Math.round((Date.now() - t) / 1000); return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`; };

  function pendingSub(phase) {
    const items = [...(inflight[phase] || new Map()).values()];
    return (items.length ? `reading ${items.slice(0, 3).join(", ")}${items.length > 3 ? "…" : ""} · ` : "") + ago(started[phase]);
  }

  function showPending() {
    const still = PHASES.filter(p => document.querySelector(`.phases li[data-phase="${p}"]`)?.dataset.state === "active");
    if (!still.length) return;
    const p = still[0];
    show("Still running", LABELS[p], pendingSub(p));
    pendingShown = p;
  }

  setInterval(() => {   // keep the elapsed time moving so a long step never looks frozen
    if (done || !pendingShown) return;
    const sub = document.querySelector("#now-stage .now-item:not(.out) .now-sub");
    if (sub) sub.textContent = pendingSub(pendingShown);
  }, 1000);

  function phaseState(phase, state) {
    const li = document.querySelector(`.phases li[data-phase="${phase}"]`);
    if (li) li.dataset.state = state;
    const i = PHASES.indexOf(phase);
    const pct = state === "done" ? (i + 1) / PHASES.length : (i + 0.5) / PHASES.length;
    $("bar-fill").style.width = `${Math.max(parseFloat($("bar-fill").style.width) || 0, pct * 100)}%`;
  }

  // done/total per phase, by item id: some items only send a "done" event (cached firms, country rows),
  // so a done item also counts as seen.
  function count(phase, k, id) {
    const c = (counts[phase] ??= { seen: new Set(), done: new Set() });
    c.seen.add(id); if (k === 1) c.done.add(id);
    const el = document.querySelector(`.phases li[data-phase="${phase}"] .ph-count`);
    if (el) el.textContent = `${c.done.size}/${c.seen.size}`;
  }

  function handle(e) {
    if (e.kind === "phase") {
      phaseState(e.phase, e.status === "start" ? "active" : "done");
      if (e.status === "start") started[e.phase] = Date.now();
      else { delete inflight[e.phase]; needPending = true; }
      renderLive();
      if (e.status === "start" && e.phase === "risk") show("Computing", "Portfolio risk", "tools/risk_math");
      if (e.status === "start" && e.phase === "countries") show("Geopolitical agent", "Country risk", "GPR index · scenarios");
      if (e.status === "start" && e.phase === "scenarios") show("Checking", "Geopolitical scenarios", "weekly set");
      if (e.status === "start" && e.phase === "macro") show("Country risk agent", "Macro & official sources", "World Bank");
      if (e.status === "done" && e.detail) log("", e.label || e.phase, e.detail);
    } else if (e.kind === "asset" || e.kind === "country") {
      const phase = e.phase || (e.kind === "asset" ? "assets" : "countries");
      (inflight[phase] ??= new Map());
      if (e.status === "start") {
        inflight[phase].set(e.id, e.label);
        count(phase, 0, e.id);
        showItem(phase, e.kind, e.id, e.label);
      } else {
        inflight[phase].delete(e.id);
        // The panel showed this item: switch to one still in flight, so a finished company never stays on
        // screen as "loading" while it already appears as done in the list below.
        if (shownItem && shownItem.phase === phase && shownItem.id === e.id) {
          const next = [...inflight[phase].entries()][0];
          if (next) showItem(phase, e.kind, next[0], next[1]);
          else needPending = true;
        }
        count(phase, 1, e.id);
        log(e.id, e.label, e.detail);
      }
      renderLive();
    } else if (e.kind === "source") {
      let host = e.detail;
      try { host = new URL(e.detail).hostname.replace(/^www\./, ""); } catch (_) {}
      if (e.status === "start") show(e.phase === "market" ? "Fetching indicator" : "Reading source", e.label, host);
      else log("", e.label, e.detail);
    } else if (e.kind === "llm") {
      if (e.status === "start") show("Writing", e.label, e.detail);
      else log("", e.label, e.detail);
    } else if (e.kind === "scenario") {
      show("Scenario", e.label, e.detail);
      log(e.id, e.label, e.detail);
    } else if (e.kind === "note") {
      show("Scenarios", e.label, e.detail);
      if (e.status === "error") log("", e.label, e.detail);
    } else if (e.kind === "run" && e.status === "error") {
      $("run-error").hidden = false;
      $("run-error").textContent = `The run failed: ${e.detail}`;
    }
  }

  async function finish() {
    const html = await (await fetch(`/runs/${runId}/result`)).text();
    $("progress").classList.add("leaving");
    setTimeout(() => {
      $("progress").hidden = true;
      $("run-title").textContent = "Geopolitical risk report";
      $("result").innerHTML = html;
      $("result").classList.add("appear");
      window.initScenarioMap && window.initScenarioMap(runId);
    }, 500);
  }

  async function poll() {
    try {
      const r = await (await fetch(`/runs/${runId}/events?after=${seq}`)).json();
      for (const e of r.events) { handle(e); seq = e.seq; }
      if (needPending) showPending();
      if (r.status === "done" && !done) { done = true; return setTimeout(finish, 600); }
      if (r.status === "error") return;
    } catch (_) { /* network blip: retry */ }
    setTimeout(poll, 400);
  }

  if (root.dataset.status === "done") {
    window.addEventListener("load", () => window.initScenarioMap && window.initScenarioMap(runId));
  } else {
    poll();
  }
})();

// Collapsible sections and "show all" rows (delegated: works after partial reloads).
document.addEventListener("click", e => {
  const ref = e.target.closest("a.annex-ref");
  if (ref) {   // open the annexes and flash the entry; don't toggle the scenario checkbox
    e.preventDefault();
    const id = ref.getAttribute("href").slice(1), ann = document.getElementById("annexes"), li = document.getElementById(id);
    if (ann) { ann.classList.remove("collapsed"); ann.querySelector(".block-toggle")?.setAttribute("aria-expanded", "true"); }
    if (li) { li.scrollIntoView({ behavior: "smooth", block: "center" }); li.classList.remove("flash"); void li.offsetWidth; li.classList.add("flash"); }
    return;
  }
  const t = e.target.closest(".block-toggle");
  if (t) {
    const block = t.closest(".block");
    block.classList.toggle("collapsed");
    t.setAttribute("aria-expanded", String(!block.classList.contains("collapsed")));
    return;
  }
  const m = e.target.closest("[data-more]");
  if (m) {
    const box = m.parentElement;
    if (!m.dataset.label) m.dataset.label = m.firstChild.textContent;
    const open = box.classList.toggle("expanded");
    m.classList.toggle("open", open);
    m.firstChild.textContent = open ? "Show fewer" : m.dataset.label;
  }
});
