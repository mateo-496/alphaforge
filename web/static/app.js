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

  // ---- Sliders: live value label + filled track ----
  function paint(sl) {
    const r = $("input[type=range]", sl), out = $(".slider-val", sl);
    const labels = sl.dataset.labels ? JSON.parse(sl.dataset.labels) : null, unit = sl.dataset.unit;
    const v = +r.value, lo = +r.min, hi = +r.max;
    out.textContent = labels ? labels[v] : unit === "year" ? (v >= hi ? `${v}+ years` : `${v} year${v > 1 ? "s" : ""}`)
                    : unit === "%" ? (v === 0 ? "None" : `${v}%`) : v;
    r.style.setProperty("--fill", `${((v - lo) / (hi - lo)) * 100}%`);
  }
  $$(".slider").forEach(sl => { paint(sl); $("input", sl).addEventListener("input", () => paint(sl)); });

  // ---- Tag boxes: searchable multi-select with optional write-in ----
  const boxes = {};
  $$(".tagbox").forEach(box => {
    const name = box.dataset.name, free = box.dataset.free === "1";
    const opts = JSON.parse($(".tag-options", box).textContent);
    const byV = Object.fromEntries(opts.map(o => [o.v, o]));
    const input = $(".tag-input", box), menu = $(".tag-menu", box), chips = $(".chips", box);
    let active = -1, shown = [];
    const values = () => $$("input[type=hidden]", chips).map(i => i.value);

    function add(v, label) {
      if (!v || values().includes(v)) return;
      const chip = document.createElement("span");
      chip.className = "chip";
      const o = byV[v];
      chip.innerHTML = `${o && o.g ? `<i>${o.g}</i>` : ""}<span></span><button type="button" aria-label="Remove">×</button><input type="hidden">`;
      chip.querySelector("span").textContent = label || (o ? o.l : v.replace(/^text:/, ""));
      const hid = chip.querySelector("input"); hid.name = name; hid.value = v;
      chip.querySelector("button").addEventListener("click", () => { chip.remove(); input.focus(); });
      chips.appendChild(chip);
    }
    function render() {
      const q = input.value.trim().toLowerCase(), have = new Set(values());
      const holdings = name === "protected_holdings" ? new Set($$("input[name=ticker]", form).map(i => resolve(i.value)).filter(Boolean)) : null;
      shown = opts.filter(o => (!holdings || holdings.has(o.v)) && !have.has(o.v) && (!q || o.l.toLowerCase().includes(q) || (o.g || "").toLowerCase().startsWith(q))).slice(0, 60);
      let html = "", g = null;
      shown.forEach((o, i) => {
        if (o.g && o.g !== g) { g = o.g; html += `<li class="tag-group" aria-hidden="true">${g}</li>`; }
        const on = i === active || (active < 0 && q && i === 0);   // Enter picks the first match
        html += `<li role="option" data-i="${i}" class="${on ? "on" : ""}">${o.l.replace(/[<>&]/g, "")}</li>`;
      });
      if (free && q && !opts.some(o => o.l.toLowerCase() === q))
        html += `<li role="option" data-i="free" class="free ${active === shown.length || (active < 0 && !shown.length) ? "on" : ""}">Add “${input.value.trim().replace(/[<>&]/g, "")}”</li>`;
      menu.innerHTML = html || '<li class="tag-empty">No match</li>';
      menu.hidden = false; input.setAttribute("aria-expanded", "true");
    }
    function pick(i) {
      if (i === "free" || i === shown.length) {
        const t = input.value.trim();
        if (free && t) add(name === "exclusions" ? `text:${t}` : t);
      } else if (shown[i]) add(shown[i].v);
      input.value = ""; active = -1;
      menu.hidden = true; input.setAttribute("aria-expanded", "false");   // reopen on typing / arrow / click
    }
    input.addEventListener("focus", render);
    input.addEventListener("input", () => { active = -1; render(); });
    input.addEventListener("keydown", e => {
      const n = shown.length + (free && input.value.trim() ? 1 : 0);
      if (e.key === "ArrowDown") { e.preventDefault(); if (menu.hidden) { active = -1; render(); return; } active = Math.min(n - 1, active + 1); render(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(0, active - 1); render(); }
      else if (e.key === "Enter") {   // highlighted item; otherwise the first match; otherwise the typed text
        e.preventDefault();
        if (!input.value.trim() && active < 0) return;
        pick(active >= 0 ? (active === shown.length ? "free" : active) : (shown.length ? 0 : "free"));
      }
      else if (e.key === "Backspace" && !input.value) { const last = chips.lastElementChild; if (last) last.remove(); }
      else if (e.key === "Escape") { menu.hidden = true; }
    });
    menu.addEventListener("mousedown", e => {
      const li = e.target.closest("li[data-i]");
      if (li) { e.preventDefault(); pick(li.dataset.i === "free" ? "free" : +li.dataset.i); }
    });
    input.addEventListener("blur", () => setTimeout(() => { menu.hidden = true; input.setAttribute("aria-expanded", "false"); }, 120));
    box.addEventListener("click", e => {
      if (e.target.closest(".tag-field") && e.target.tagName !== "BUTTON") { input.focus(); if (menu.hidden) render(); }
    });
    boxes[name] = { set(vals) { chips.innerHTML = ""; (vals || []).forEach(v => add(v)); } };
  });

  // ---- Persona presets and sample profiles ----
  const setRange = (name, v) => {
    const r = form.querySelector(`input[type=range][name="${name}"]`);
    if (r) { r.value = v; paint(r.closest(".slider")); }
  };
  const DEFAULTS = { age: "", horizon_years: 10, risk_level: 3, objective_level: 3, experience: "intermediate",
    esg_importance: "none", crypto_max: 0, max_single_weight: 0.25, exclusions: [], avoid_countries: [],
    protected_holdings: [], max_turnover: 1, replacement_types: [], interests: [], notes: "", base_currency: null };

  function fill(p) {
    p = { ...DEFAULTS, ...p };
    form.querySelector("input[name=age]").value = p.age ?? "";
    setRange("horizon_years", Math.min(30, p.horizon_years));
    setRange("risk_level", p.risk_level);
    setRange("objective_level", p.objective_level);
    setRange("experience", { beginner: 1, intermediate: 2, advanced: 3 }[p.experience] || 2);
    setRange("esg", { none: 0, some: 1, high: 2 }[p.esg_importance] || 0);
    setRange("crypto_max", Math.round(p.crypto_max * 100));
    setRange("max_single_weight", Math.round(p.max_single_weight * 100 / 5) * 5);
    setRange("max_turnover", Math.round(p.max_turnover * 100 / 5) * 5);
    boxes.protected_holdings && boxes.protected_holdings.set(p.protected_holdings);
    $$("input[name=replacement_types]", form).forEach(input => { input.checked = (p.replacement_types || []).includes(input.value); });
    boxes.exclusions && boxes.exclusions.set(p.exclusions);
    boxes.avoid_countries && boxes.avoid_countries.set(p.avoid_countries);
    boxes.interests && boxes.interests.set(p.interests);
    form.querySelector("textarea[name=notes]").value = p.notes || "";
    if (p.base_currency) form.querySelector("select[name=base_currency]").value = p.base_currency;
  }

  $$("input[name=persona]", form).forEach(r => r.addEventListener("change", () => {
    fill((PERSONAS[r.value] || {}).profile || DEFAULTS);
  }));
  $$("[data-sample]").forEach(b => b.addEventListener("click", () => {
    const s = SAMPLES[b.dataset.sample];
    if (!s) return;
    $$("input[name=persona]", form).forEach(x => (x.checked = x.value === ""));
    fill(s.profile);
    $$("[data-sample]").forEach(x => x.classList.toggle("on", x === b));
  }));
})();
