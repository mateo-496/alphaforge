// Scenario map: D3 world map, countries coloured by the intensity of the selected scenarios.
window.initScenarioMap = async function (runId) {
  const svgEl = document.getElementById("map");
  if (!svgEl || svgEl.dataset.ready) return;
  svgEl.dataset.ready = "1";

  // ISO 3166 alpha-3 -> numeric (ids used by world-atlas). Extend when scenarios add countries.
  const NUM = { USA: "840", CAN: "124", MEX: "484", CHN: "156", TWN: "158", JPN: "392", KOR: "410", PRK: "408",
    IND: "356", PHL: "608", VNM: "704", SGP: "702", SAU: "682", ARE: "784", QAT: "634", IRN: "364", IRQ: "368",
    ISR: "376", RUS: "643", UKR: "804", POL: "616", FIN: "246", EST: "233", LVA: "428", LTU: "440", DEU: "276",
    GBR: "826", FRA: "250", NLD: "528", IRL: "372", BRA: "076", AUS: "036" };
  const ISO = Object.fromEntries(Object.entries(NUM).map(([a, n]) => [n, a]));

  const [data, world] = await Promise.all([
    fetch(`/runs/${runId}/scenarios.json`).then(r => r.json()),
    fetch("/static/vendor/countries-110m.json").then(r => r.json()),
  ]);
  const byId = Object.fromEntries(data.scenarios.map(s => [s.id, s]));
  const land = topojson.feature(world, world.objects.countries).features.filter(f => f.id !== "010");

  const W = svgEl.clientWidth || 1000;
  const projection = d3.geoEqualEarth().fitWidth(W - 2, { type: "Sphere" });
  const H = Math.ceil(d3.geoPath(projection).bounds({ type: "Sphere" })[1][1]) + 2;
  projection.translate([projection.translate()[0] + 1, projection.translate()[1] + 1]);
  const svg = d3.select(svgEl).attr("viewBox", `0 0 ${W} ${H}`);
  const path = d3.geoPath(projection);

  const css = getComputedStyle(document.documentElement);
  const BASE = "#e2ddd1", STROKE = css.getPropertyValue("--paper").trim() || "#f6f4ee";
  const ramp = d3.interpolateRgb("#efcfc4", "#7a1212");

  svg.append("path").attr("d", path({ type: "Sphere" })).attr("fill", "none").attr("stroke", "#d8d4c9");
  const countries = svg.append("g").selectAll("path").data(land).join("path")
    .attr("d", path).attr("fill", BASE).attr("stroke", STROKE).attr("stroke-width", 0.6)
    .attr("class", "country");

  let selected = new Set();
  const intensity = () => {
    const out = {};
    for (const id of selected) for (const [c, v] of Object.entries(byId[id].countries)) out[c] = Math.max(out[c] || 0, v);
    return out;
  };

  function render() {
    const I = intensity();
    countries.transition().duration(550).ease(d3.easeCubicOut)
      .attr("fill", d => { const v = I[ISO[d.id]]; return v ? ramp(v) : BASE; })
      .attr("stroke", d => (I[ISO[d.id]] ? "#5a0d0d" : STROKE))
      .attr("stroke-width", d => (I[ISO[d.id]] ? 0.8 : 0.6));
    impact(I);
  }

  function impact(I) {
    const box = document.getElementById("scen-impact");
    if (!selected.size) { box.innerHTML = '<span class="muted">No scenario selected.</span>'; return; }
    const per = Object.entries(data.assets).map(([t, a]) =>
      [t, a.weight * Object.entries(a.country_weights).reduce((s, [c, w]) => s + w * (I[c] || 0), 0)]);
    const total = per.reduce((s, [, v]) => s + v, 0);
    const top = per.filter(([, v]) => v > 0.005).sort((a, b) => b[1] - a[1]).slice(0, 4);
    const names = [...selected].map(id => byId[id].name).join(" + ");
    box.innerHTML = `<span class="imp-num mono">${(total * 100).toFixed(0)}%</span>
      <span>of the portfolio's revenue, weighted by intensity, sits in countries hit by <b>${names}</b>.
      ${top.length ? `Most exposed: ${top.map(([t, v]) => `<span class="mono">${t}</span> ${(v * 100).toFixed(1)}%`).join(", ")}.` : "No holding is materially exposed."}</span>`;
  }

  // Tooltip
  const tip = document.getElementById("map-tip");
  countries.on("mousemove", (ev, d) => {
    const iso = ISO[d.id], I = intensity(), name = (iso && data.names[iso]) || d.properties.name;
    const x = data.exposure[iso];
    const hits = [...selected].filter(id => byId[id].countries[iso]).map(id => byId[id].name);
    if (!x && !I[iso]) { tip.hidden = true; return; }
    tip.innerHTML = `<b>${name}</b>` +
      (x ? `<span>Portfolio revenue <span class="mono">${(x * 100).toFixed(1)}%</span></span>` : "") +
      (I[iso] ? `<span>Intensity <span class="mono">${(I[iso] * 100).toFixed(0)}</span> · ${hits.join(", ")}</span>` : "");
    const r = svgEl.getBoundingClientRect();
    tip.style.left = `${ev.clientX - r.left + 14}px`; tip.style.top = `${ev.clientY - r.top + 14}px`;
    tip.hidden = false;
  }).on("mouseleave", () => (tip.hidden = true));

  document.querySelectorAll("#scen-list input").forEach(cb => cb.addEventListener("change", () => {
    cb.checked ? selected.add(cb.value) : selected.delete(cb.value);
    render();
  }));

  // Open on the scenario that hits this portfolio hardest.
  const worst = [...data.scenarios].sort((a, b) => b.exposure - a.exposure)[0];
  const cb = worst && document.querySelector(`#scen-list input[value="${worst.id}"]`);
  if (cb) { cb.checked = true; selected.add(worst.id); }
  render();
};
