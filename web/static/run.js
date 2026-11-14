// Run page: poll the event log, animate progress, then load the report and the scenario map.
(() => {
  const root = document.getElementById("run");
  if (!root) return;
  const runId = root.dataset.run;
  const $ = id => document.getElementById(id);
  const PHASES = ["assets", "countries", "risk", "report", "scenarios"];
  let seq = 0, done = false;
  const counts = { assets: [0, 0], countries: [0, 0] };

  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function show(label, title, sub) {
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

  function log(id, label, detail) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="mono">${esc(id)}</span><span>${esc(label)}</span><span class="muted mono">${esc(detail)}</span>`;
    $("log").prepend(li);
    [...$("log").children].slice(8).forEach(n => n.remove());
  }

  function phaseState(phase, state) {
    const li = document.querySelector(`.phases li[data-phase="${phase}"]`);
    if (li) li.dataset.state = state;
    const i = PHASES.indexOf(phase);
    const pct = state === "done" ? (i + 1) / PHASES.length : (i + 0.5) / PHASES.length;
    $("bar-fill").style.width = `${Math.max(parseFloat($("bar-fill").style.width) || 0, pct * 100)}%`;
  }

  function count(phase, k) {
    const c = counts[phase]; c[k]++;
    const el = document.querySelector(`.phases li[data-phase="${phase}"] .ph-count`);
    if (el) el.textContent = `${c[1]}/${c[0]}`;
  }

  function handle(e) {
    if (e.kind === "phase") {
      phaseState(e.phase, e.status === "start" ? "active" : "done");
      if (e.status === "start" && e.phase === "risk") show("Computing", "Portfolio risk", "tools/risk_math");
      if (e.status === "start" && e.phase === "report") show("Writing", "Report", "drivers · watchlist · what-ifs");
      if (e.status === "done" && e.detail) log("", e.label || e.phase, e.detail);
    } else if (e.kind === "asset" || e.kind === "country") {
      const phase = e.kind === "asset" ? "assets" : "countries";
      if (e.status === "start") {
        count(phase, 0);
        show(e.kind === "asset" ? "Reading filings" : "Assessing country", e.label, e.id);
      } else {
        count(phase, 1);
        log(e.id, e.label, e.detail);
      }
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
