// Scenario map: D3 world map, countries coloured by the intensity of the selected scenarios.
window.initScenarioMap = async function (runId, preloaded) {
  const svgEl = document.getElementById("map");
  if (!svgEl || svgEl.dataset.ready) return;
  svgEl.dataset.ready = "1";


  const [data, world] = await Promise.all([
    preloaded ? Promise.resolve(preloaded) : fetch(`/runs/${runId}/scenarios.json`).then(r => r.json()),
    fetch("/static/vendor/countries-110m.json").then(r => r.json()),
  ]);
  // ISO 3166 alpha-3 <-> numeric (world-atlas ids), full table from the server.
  const ISO = Object.fromEntries(Object.entries(data.num).map(([a, n]) => [n, a]));
  const byId = Object.fromEntries(data.scenarios.map(s => [s.key, s]));
  const land = topojson.feature(world, world.objects.countries).features.filter(f => f.id !== "010");

  const W = svgEl.clientWidth || 1000;
  const projection = d3.geoEqualEarth().fitWidth(W - 2, { type: "Sphere" });
  const H = Math.ceil(d3.geoPath(projection).bounds({ type: "Sphere" })[1][1]) + 2;
  projection.translate([projection.translate()[0] + 1, projection.translate()[1] + 1]);
  const svg = d3.select(svgEl).attr("viewBox", `0 0 ${W} ${H}`);
  const path = d3.geoPath(projection);

  const css = getComputedStyle(document.documentElement);
  const tok = n => css.getPropertyValue(n).trim();   // colours come from style.css :root only
  const BASE = tok("--map-land"), STROKE = tok("--surface"), EDGE = tok("--border"), INK = tok("--ink-2");
  // One colour per scenario (palette in style.css, --sc-1..12, in the order of the scenario list); the shade is the intensity.
  const PAL = Array.from({ length: 12 }, (_, i) => tok(`--sc-${i + 1}`));
  const color = Object.fromEntries(data.scenarios.map((s, i) => [s.key, PAL[i % PAL.length]]));
  const TINT = "#F4F6FA";
  document.querySelectorAll(".scen-list input").forEach(cb =>
    cb.closest(".scen-item").style.setProperty("--sc", color[cb.value] || ""));

  svg.append("path").attr("d", path({ type: "Sphere" })).attr("fill", "none").attr("stroke", EDGE);
  const countries = svg.append("g").selectAll("path").data(land).join("path")
    .attr("d", path).attr("fill", BASE).attr("stroke", STROKE).attr("stroke-width", 0.6)
    .attr("class", "country");

  // Highlight country: ink outline drawn on top, independent of scenario colours.
  const hlLayer = svg.append("g").attr("pointer-events", "none");
  function setHighlight(iso) {
    const f = land.filter(d => ISO[d.id] === iso);
    hlLayer.selectAll("path").data(f, d => d.id).join(
      enter => enter.append("path").attr("d", path).attr("fill", "none").attr("stroke", INK)
        .attr("stroke-width", 0).call(e => e.transition().duration(400).attr("stroke-width", 2)),
      update => update,
      exit => exit.remove());
  }
  setHighlight(data.highlight);

  let selected = new Set();
  const intensity = () => {
    const out = {};
    for (const id of selected) for (const [c, v] of Object.entries(byId[id].countries)) out[c] = Math.max(out[c] || 0, v);
    return out;
  };

  // For each country, the selected scenario that hits it hardest decides the colour.
  function strongest() {
    const out = {};
    for (const id of selected) for (const [c, v] of Object.entries(byId[id].countries))
      if (!out[c] || v > out[c].v) out[c] = { v, id };
    return out;
  }

  function render() {
    const I = intensity(), S = strongest(), at = d => S[ISO[d.id]];
    countries.transition().duration(550).ease(d3.easeCubicOut)
      .attr("fill", d => { const p = at(d); return p && p.v ? d3.interpolateRgb(TINT, color[p.id])(0.3 + 0.7 * p.v) : BASE; })
      .attr("stroke", d => { const p = at(d); return p && p.v ? d3.color(color[p.id]).darker(0.7).formatHex() : STROKE; })
      .attr("stroke-width", d => { const p = at(d); return p && p.v ? 0.8 : 0.6; });
    impact(I);
  }

  function impact(I) {
    const box = document.getElementById("scen-impact");
    if (!selected.size) { box.innerHTML = '<span class="muted">No scenario selected.</span>'; return; }
    const per = Object.entries(data.assets).map(([t, a]) =>
      [t, a.weight * Object.entries(a.country_weights).reduce((s, [c, w]) => s + ((I[c] || 0) >= 0.5 ? w : 0), 0)]);
    const total = per.reduce((s, [, v]) => s + v, 0);
    const top = per.filter(([, v]) => v > 0.005).sort((a, b) => b[1] - a[1]).slice(0, 4);
    const names = [...selected].map(id => `<span style="color:${color[id]}">${byId[id].name}</span>`).join(" + ");
    box.innerHTML = `<span class="imp-num mono">${(total * 100).toFixed(0)}%</span>
      <span>of the portfolio's revenue sits in countries directly involved in <b>${names}</b>.
      ${top.length ? `Most exposed: ${top.map(([t, v]) => `<span class="code">${t}</span> ${(v * 100).toFixed(1)}%`).join(", ")}.` : "No holding is materially exposed."}</span>`;
  }

  // Tooltip
  const tip = document.getElementById("map-tip");
  countries.on("mousemove", (ev, d) => {
    const iso = ISO[d.id], I = intensity(), name = (iso && data.names[iso]) || d.properties.name;
    const x = data.exposure[iso];
    const hits = [...selected].filter(id => byId[id].countries[iso]).map(id => `<span style="color:${color[id]}">${byId[id].name}</span>`);
    if (!x && !I[iso]) { tip.hidden = true; return; }
    tip.innerHTML = `<b>${name}</b>` +
      (x ? `<span>Portfolio revenue <span class="mono">${(x * 100).toFixed(1)}%</span></span>` : "") +
      (I[iso] ? `<span>Intensity <span class="mono">${(I[iso] * 100).toFixed(0)}</span> · ${hits.join(", ")}</span>` : "");
    const r = svgEl.getBoundingClientRect();
    tip.style.left = `${ev.clientX - r.left + 14}px`; tip.style.top = `${ev.clientY - r.top + 14}px`;
    tip.hidden = false;
  }).on("mouseleave", () => (tip.hidden = true));

  document.querySelectorAll(".scen-list input").forEach(cb => cb.addEventListener("change", () => {
    cb.checked ? selected.add(cb.value) : selected.delete(cb.value);
    render();
  }));

  bindControls(runId, setHighlight);

  // Open on the scenario that hits this portfolio hardest.
  // With a highlight country, open on its most dangerous scenario instead.
  const hlFirst = data.highlight && data.scenarios.find(s => s.scope === `country-${data.highlight}`);
  // Default: the worst scenario among the visible cards (not one hidden behind "Show all").
  const visible = new Set([...document.querySelectorAll(".scen-item:not(.more) input")].map(i => i.value));
  const worst = hlFirst || [...data.scenarios].filter(s => visible.has(s.key)).sort((a, b) => b.exposure - a.exposure)[0];
  const cb = worst && document.querySelector(`.scen-list input[value="${worst.key}"]`);
  if (cb) { cb.checked = true; selected.add(worst.key); }
  render();
};


// Regenerate / highlight-country controls under the map.
function bindControls(runId, setHighlight) {
  const box = document.querySelector(".scen-controls");
  if (!box) return;
  const btn = document.getElementById("regen-btn"), sel = document.getElementById("hl-country");
  const status = document.getElementById("regen-status"), section = document.getElementById("scenarios");
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const host = u => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (_) { return u || ""; } };

  async function start(force) {
    if (btn) btn.disabled = true;
    sel.disabled = true;
    section.classList.add("busy");
    status.innerHTML = '<span class="dot"></span> ' + (force ? "Regenerating scenarios" : "Loading scenarios");
    const body = new FormData();
    body.set("country", sel.value);
    if (force) body.set("force", "1");
    const r = await fetch(`/runs/${runId}/scenarios`, { method: "POST", body });
    const j = await r.json();
    if (!r.ok) return fail(j.error);
    poll(j.seq);
  }

  function fail(msg) {
    if (btn) btn.disabled = false;
    sel.disabled = false;
    section.classList.remove("busy");
    status.innerHTML = `<span class="err">Could not update the scenarios: ${esc(msg)}</span>`;
  }

  async function poll(seq) {
    let r;
    try { r = await (await fetch(`/runs/${runId}/events?after=${seq}`)).json(); }
    catch (_) { return setTimeout(() => poll(seq), 800); }
    for (const e of r.events) {
      seq = e.seq;
      if (e.kind === "source" && e.status === "start")
        status.innerHTML = `<span class="dot"></span> Reading <b>${esc(e.label)}</b> <span class="mono muted">${esc(host(e.detail))}</span>`;
      if (e.kind === "llm" && e.status === "start")
        status.innerHTML = `<span class="dot"></span> Writing scenarios <span class="mono muted">${esc(e.detail)}</span>`;
      if (e.kind === "regen" && e.status === "error") return fail(e.detail);
      if (e.kind === "regen" && e.status === "done") return reload();
    }
    setTimeout(() => poll(seq), 400);
  }

  async function reload() {
    const html = await (await fetch(`/runs/${runId}/scenarios-section`)).text();
    const tmp = document.createElement("div");
    tmp.innerHTML = html.trim();
    const fresh = tmp.firstElementChild;
    section.replaceWith(fresh);
    fresh.classList.add("appear");
    const ann = document.getElementById("annexes");   // letters may have changed: refresh the annexes too
    if (ann) {
      const t2 = document.createElement("div");
      t2.innerHTML = (await (await fetch(`/runs/${runId}/annexes`)).text()).trim();
      const nAnn = t2.firstElementChild;
      if (!ann.classList.contains("collapsed")) { nAnn.classList.remove("collapsed"); }
      ann.replaceWith(nAnn);
    }
    window.initScenarioMap(runId);
  }

  if (btn) btn.addEventListener("click", () => start(true));
  sel.addEventListener("change", () => { setHighlight(sel.value); start(false); });
}
