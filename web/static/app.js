// AlphaForge form behaviour: persona presets, holdings table, running total.
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const json = id => { const el = document.getElementById(id); return el ? JSON.parse(el.textContent) : {}; };
  const PERSONAS = json("persona-data");
  const SAMPLES = json("sample-data");
  const UNIVERSE = json("universe-data");
  const form = $("#request-form");
  if (!form) return;

  const ALIASES = { BTC: "BTC-USD", ETH: "ETH-USD", GOOG: "GOOGL", CNI: "CNR.TO" };
  const resolve = raw => {
    const t = raw.trim().toUpperCase();
    const st = c => c && UNIVERSE[c] && UNIVERSE[c].starter;
    return [t, ALIASES[t], t + ".TO"].find(st) || (UNIVERSE[t] ? t : null);
  };

  // ---- Holdings ----
  const mode = () => (form.querySelector("input[name=mode]:checked") || {}).value || "weight";

  function updateRow(tr) {
    const input = $("input[name=ticker]", tr), cell = $(".asset-name", tr);
    const t = resolve(input.value);
    cell.classList.toggle("bad", !!input.value.trim() && !t);
    cell.innerHTML = t ? `${UNIVERSE[t].name} <span class="muted">· ${UNIVERSE[t].currency}</span>`
                       : (input.value.trim() ? "Not in universe" : "");
  }

  function updateTotal() {
    const total = $("#total"); if (!total) return;
    const m = mode();
    const sum = $$("input[name=amount]").reduce((s, i) => s + (parseFloat(i.value.replace(",", ".")) || 0), 0);
    const head = $("#amount-head");
    if (head) head.textContent = { weight: "Weight %", quantity: "Units", value: "Value" }[m];
    if (m === "weight") {
      total.textContent = sum ? `${sum.toFixed(1)}%` : "";
      total.classList.toggle("off", sum > 0 && Math.abs(sum - 100) > 0.5);
      total.title = total.classList.contains("off") ? "Weights will be rescaled to 100%" : "";
    } else {
      total.textContent = m === "value" && sum ? sum.toLocaleString() : "";
      total.classList.remove("off");
    }
  }

  function addRow() {
    const body = $("#holding-rows");
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><input class="mono" name="ticker" list="tickers" autocomplete="off" spellcheck="false" aria-label="Ticker"></td>
      <td class="asset-name"></td>
      <td class="num"><input class="mono num" name="amount" inputmode="decimal" aria-label="Amount"></td>
      <td><button type="button" class="row-x" aria-label="Remove row">×</button></td>`;
    body.appendChild(tr);
    $("input", tr).focus();
  }

  document.addEventListener("click", e => {
    if (e.target.id === "add-row") addRow();
    if (e.target.classList.contains("row-x")) {
      const rows = $$("#holding-rows tr");
      if (rows.length > 1) e.target.closest("tr").remove();
      else $$("input", rows[0]).forEach(i => (i.value = "")), updateRow(rows[0]);
      updateTotal();
    }
  });
  document.addEventListener("input", e => {
    if (e.target.name === "ticker") updateRow(e.target.closest("tr"));
    if (["amount", "mode"].includes(e.target.name)) updateTotal();
  });
  document.addEventListener("change", e => { if (e.target.name === "mode") updateTotal(); });
  document.body.addEventListener("htmx:afterSwap", updateTotal);
  updateTotal();

  // ---- Persona presets ----
  const set = (name, value) => {
    const els = $$(`[name="${name}"]`, form);
    if (!els.length) return;
    const type = els[0].type;
    if (type === "radio") els.forEach(el => (el.checked = el.value === String(value)));
    else if (type === "checkbox" && els.length === 1 && typeof value === "boolean") els[0].checked = value;
    else if (type === "checkbox") els.forEach(el => (el.checked = (value || []).includes(el.value)));
    else els[0].value = value ?? "";
  };
  const DEFAULTS = { age: "", horizon_years: 10, risk_tolerance: "moderate", objective: "balanced",
    experience: "intermediate", esg_importance: "none", avoid_controversies: false, crypto_max: 0,
    max_single_weight: 0.25, excluded_sectors: [], excluded_tickers: [], avoid_countries: [],
    interests: [], notes: "" };

  function fill(p) {
    for (const [k, v] of Object.entries({ ...DEFAULTS, ...p })) {
      if (k === "crypto_max" || k === "max_single_weight") set(k, Math.round(v * 100));
      else if (k === "excluded_tickers") set(k, v.join(", "));
      else set(k, v);
    }
  }
  $$("input[name=persona]", form).forEach(r => r.addEventListener("change", () => {
    fill((PERSONAS[r.value] || {}).profile || DEFAULTS);
  }));
  // Sample portfolios come with their own investor profile: fill it as a custom investor.
  $$("[data-sample]").forEach(b => b.addEventListener("click", () => {
    const s = SAMPLES[b.dataset.sample];
    if (!s) return;
    set("persona", "");
    fill(s.profile);
    $$("[data-sample]").forEach(x => x.classList.toggle("on", x === b));
  }));
})();
