// Assay app. No build step, no framework: a data layer, a router, and views.
// The data layer has two implementations behind one interface: the live API, or
// window.ASSAY_DATA baked in by `assay site`, which replays recorded runs.

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const STATIC = window.ASSAY_DATA;

// ------------------------------------------------------------------ data layer
const live = {
  mode: "live",
  async bootstrap() { return (await fetch("/api/bootstrap")).json(); },
  async set(id) { const r = await fetch(`/api/sets/${encodeURIComponent(id)}`); return r.ok ? r.json() : null; },
  async startRun(id) {
    const r = await fetch(`/api/sets/${encodeURIComponent(id)}/runs`, { method: "POST" });
    const body = await r.json();
    if (!r.ok) throw new Error(body.error || "Couldn't start the run");
    return body.run_id;
  },
  events(runId, onEvent) {
    const es = new EventSource(`/api/runs/${runId}/events`);
    const kinds = ["run.started", "search.done", "backend.error", "candidate.found", "candidate.fetched", "verdict", "row.done", "run.finished", "run.saved"];
    kinds.forEach((k) => es.addEventListener(k, (m) => { const e = JSON.parse(m.data); onEvent(e); if (k === "run.saved") es.close(); }));
    es.onerror = () => { /* the browser retries; history is replayed on reconnect */ };
    return () => es.close();
  },
  exportUrl(id, fmt) { return `/api/sets/${encodeURIComponent(id)}/export.${fmt}`; },
};

const replay = {
  mode: "static",
  async bootstrap() { return { mode: "static", sets: STATIC.sets }; },
  async set(id) { return STATIC.details[id] || null; },
  async startRun(id) { return STATIC.details[id]?.run?.id; },
  events(runId, onEvent) {
    // Replay the recorded stream. Real timings are milliseconds; stretch them so people can watch.
    const evs = STATIC.events[runId] || [];
    let i = 0, cancelled = false;
    const step = () => {
      if (cancelled || i >= evs.length) return;
      const e = evs[i++];
      onEvent(e);
      const pace = { "run.started": 500, "search.done": 600, "candidate.found": 70, "candidate.fetched": 110, verdict: 55, "row.done": 90 };
      setTimeout(step, pace[e.kind] ?? 300);
    };
    step();
    return () => { cancelled = true; };
  },
  exportUrl() { return null; },
};
const api = STATIC ? replay : live;

// ------------------------------------------------------------------ hallmarks
const OCT = "M7 1h10l6 6v10l-6 6H7l-6-6V7z";
function hallmark(status) {
  if (status === "pass") return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${OCT}" fill="url(#gold-grad)"/><path d="${OCT}" fill="none" stroke="#5e4718" stroke-width=".8"/><path d="M7.2 12.4l3.1 3.1 6.6-7" fill="none" stroke="#171b1a" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  if (status === "fail") return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${OCT}" fill="#2c3332" stroke="#5f6866" stroke-width="1"/><path d="M8.3 8.3l7.4 7.4M15.7 8.3l-7.4 7.4" stroke="#c4664c" stroke-width="2" stroke-linecap="round"/></svg>`;
  if (status === "pending") return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${OCT}" fill="none" stroke="#4a5553" stroke-width="1"/></svg>`;
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${OCT}" fill="none" stroke="#7d8481" stroke-width="1.2" stroke-dasharray="2.2 2"/><path d="M10 9.6a2.1 2.1 0 1 1 3 1.9c-.7.3-1 .8-1 1.5v.4M12 16.3v.1" fill="none" stroke="#9aa19e" stroke-width="1.6" stroke-linecap="round"/></svg>`;
}
const STATUS_WORD = { pass: "Proven", fail: "Disproven", unclear: "Not proven" };
const STATUS_LINE = {
  pass: "A source states this, in so many words.",
  fail: "A source states the opposite.",
  unclear: "Nothing on the fetched pages settles it either way.",
};
const serial = (hash) => (hash || "").slice(0, 12).toUpperCase().replace(/(.{4})(?=.)/g, "$1-");
const host = (u) => { try { return new URL(u).host.replace(/^www\./, ""); } catch { return u; } };
const ago = (iso) => {
  if (!iso) return "";
  const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
  return d.toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });
};

// ------------------------------------------------------------------ state + router
const state = { sets: [], detail: null, setId: null, tab: "results", filter: "proven", running: null, menuOpen: false };

function route() {
  const [, kind, id, tab] = location.hash.split("/");
  if (kind === "sets" && id) {
    if (state.setId !== id) { state.setId = id; state.detail = null; state.filter = "proven"; }
    state.tab = tab || "results";
    load(id);
  } else {
    state.setId = null;
    renderRail();
    renderWelcome();
  }
}

async function load(id) {
  if (!state.detail || state.detail.spec.id !== id) state.detail = await api.set(id);
  renderRail();
  renderSet();
}

// ------------------------------------------------------------------ rail
function renderRail() {
  $("#sets").innerHTML = state.sets.map((s) => {
    const l = s.latest;
    const line = l ? `<em>${l.matches} proven</em> of ${l.candidates}${s.monitor_every ? `, watched ${s.monitor_every === "1d" ? "daily" : "every " + s.monitor_every}` : ""}` : "Not run yet";
    return `<a class="set-link ${s.id === state.setId ? "on" : ""}" href="#/sets/${esc(s.id)}"><b>${esc(s.name)}</b><small>${line}</small></a>`;
  }).join("");
  $("#mode-label").textContent = api.mode === "static" ? "Static demo, fictional data" : "Running locally";
}

// ------------------------------------------------------------------ welcome
function renderWelcome() {
  $("#main").innerHTML = `
    ${demoNote()}
    <section class="welcome">
      <h1>Lists you can prove.</h1>
      <p class="question">Describe the companies you're looking for. Assay searches, reads their sites, and checks every criterion.
      A check only passes when Assay can quote the sentence that proves it, so every row comes with its receipts.</p>
      <div class="sets-grid">${state.sets.map((s) => `
        <a class="set-card" href="#/sets/${esc(s.id)}"><h3>${esc(s.name)}</h3><p>${esc(s.description || "")}</p></a>`).join("")}
      </div>
    </section>`;
}

function demoNote() {
  if (api.mode !== "static") return "";
  return `<div class="demo-note"><img class="mark" src="static/logo.svg" alt="">
    <div>This is the live demo. The companies are fictional, captured from a small test web in August and October 2026.
    Press <b>Run assay</b> to watch the engine replay its October run. <a href="https://github.com/keshava3112/Assay" target="_blank" rel="noopener">Run it on your own criteria</a></div></div>`;
}

// ------------------------------------------------------------------ set view
function renderSet() {
  const d = state.detail;
  if (!d) { $("#main").innerHTML = `<div class="empty"><h3>That set doesn't exist</h3>Pick one from the list on the left.</div>`; return; }
  const spec = d.spec, run = d.run;
  const reqCount = spec.criteria.filter((c) => c.required).length;
  const watching = spec.monitor_every ? `<span class="watch"><i></i>Watched ${spec.monitor_every === "1d" ? "daily" : "every " + spec.monitor_every}</span>` : "";
  const changes = run ? run.changes.length : 0;
  $("#main").innerHTML = `
    ${demoNote()}
    <p class="kicker">${spec.entity === "company" ? "Company set" : esc(spec.entity) + " set"}, ${reqCount} required check${reqCount !== 1 ? "s" : ""}</p>
    <div class="head-row">
      <div><h1>${esc(spec.name)}</h1><p class="question">${esc(spec.description || spec.query)}</p></div>
      <div class="actions">
        ${watching}
        <div class="menu"><button class="btn" id="export-btn" aria-haspopup="true" aria-expanded="${state.menuOpen}">Export</button>${state.menuOpen ? exportMenu(spec) : ""}</div>
        <button class="btn gold" id="run-btn" ${state.running ? "disabled" : ""}>${state.running ? "Assaying…" : "Run assay"}</button>
      </div>
    </div>
    ${run ? `<div class="facts">
      <div class="fact"><b class="gold">${run.stats.matches}</b><span>proven on every check</span></div>
      <div class="fact"><b>${run.stats.candidates}</b><span>companies assayed</span></div>
      <div class="fact"><b>${run.stats.judge_calls}</b><span>checks, each with a source</span></div>
      <div class="fact"><b>${run.stats.pages_fetched + run.stats.pages_cached}</b><span>pages read</span></div>
      <div class="fact"><b>${changes}</b><span>change${changes !== 1 ? "s" : ""} since last run</span></div>
    </div>` : ""}
    <nav class="tabs" aria-label="Views">
      ${["results", "changes", "runs", "definition"].map((t) => `<a href="#/sets/${esc(spec.id)}/${t}" class="${state.tab === t ? "on" : ""}">${
        { results: "Results", changes: "Changes", runs: "Runs", definition: "Definition" }[t]}${t === "changes" && changes ? `<span class="count">${changes}</span>` : ""}</a>`).join("")}
    </nav>
    <section id="view"></section>`;
  $("#run-btn").onclick = startRun;
  $("#export-btn").onclick = (e) => { e.stopPropagation(); state.menuOpen = !state.menuOpen; renderSet(); };
  ({ results: renderResults, changes: renderChanges, runs: renderRuns, definition: renderDefinition }[state.tab] || renderResults)();
}

function exportMenu(spec) {
  const items = api.mode === "static"
    ? [["csv", "CSV", "Every cell with its quote and source"], ["json", "JSON", "The full run, receipts included"]]
    : [["csv", "CSV", "Every cell with its quote and source"], ["xlsx", "Excel", "Colour-coded, ready to share"], ["json", "JSON", "The full run, receipts included"]];
  return `<div class="menu-list" role="menu">${items.map(([f, l, s]) => `<a href="#" role="menuitem" data-export="${f}">${l}<small>${s}</small></a>`).join("")}</div>`;
}

document.addEventListener("click", (e) => {
  const a = e.target.closest("[data-export]");
  if (a) { e.preventDefault(); doExport(a.dataset.export); state.menuOpen = false; renderSet(); return; }
  if (state.menuOpen && !e.target.closest(".menu")) { state.menuOpen = false; renderSet(); }
});

function doExport(fmt) {
  const d = state.detail;
  const url = api.exportUrl(d.spec.id, fmt);
  if (url) { location.href = url; return; }
  // static demo: build it in the browser
  let blob;
  if (fmt === "json") blob = new Blob([JSON.stringify({ set: d.spec, run: d.run }, null, 1)], { type: "application/json" });
  else {
    const head = ["company", "website", "match", ...d.spec.criteria.flatMap((c) => [c.label, `${c.label} (quote)`, `${c.label} (source)`])];
    const rows = d.run.rows.map((r) => [r.name, r.homepage, isMatch(r) ? "yes" : "no", ...d.spec.criteria.flatMap((c) => {
      const v = r.verdicts[c.id], ev = v?.evidence?.[0];
      return [v?.status || "", ev?.quote || v?.rationale || "", ev?.url || ""];
    })]);
    const csv = [head, ...rows].map((r) => r.map((x) => `"${String(x).replace(/"/g, '""')}"`).join(",")).join("\n");
    blob = new Blob([csv], { type: "text/csv" });
  }
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${d.spec.id}.${fmt}`;
  link.click();
  toast(`Exported ${fmt.toUpperCase()}`);
}

const isMatch = (r) => state.detail.spec.criteria.filter((c) => c.required).every((c) => r.verdicts[c.id]?.status === "pass");
const score = (r) => { const req = state.detail.spec.criteria.filter((c) => c.required); return req.filter((c) => r.verdicts[c.id]?.status === "pass").length / Math.max(1, req.length); };

// ------------------------------------------------------------------ results
function renderResults() {
  const d = state.detail, spec = d.spec;
  const rows = state.running ? state.running.rows : (d.run?.rows || []);
  if (!rows.length && !state.running) {
    $("#view").innerHTML = `<div class="empty"><h3>Nothing assayed yet</h3>Run the assay to search, read and check every candidate against your criteria.</div>`;
    return;
  }
  const proven = rows.filter(isMatch), near = rows.filter((r) => !isMatch(r) && score(r) >= .66);
  const shown = state.running ? rows : state.filter === "proven" ? proven : state.filter === "near" ? near : rows;
  $("#view").innerHTML = `
    ${state.running ? liveBox() : `<div class="filters" role="group" aria-label="Filter">
      ${[["proven", `Proven (${proven.length})`], ["near", `Near misses (${near.length})`], ["all", `Everything assayed (${rows.length})`]]
        .map(([k, l]) => `<button data-filter="${k}" class="${state.filter === k ? "on" : ""}" aria-pressed="${state.filter === k}">${l}</button>`).join("")}
    </div>`}
    <div class="table-wrap"><table class="ledger">
      <thead><tr><th>Company</th>
        ${spec.criteria.map((c) => `<th class="crit" scope="col">${esc(c.label)}${c.required ? "" : "<small>optional</small>"}</th>`).join("")}
        ${spec.enrich.map((e) => `<th scope="col">${esc(e.label)}</th>`).join("")}
      </tr></thead>
      <tbody>${shown.map((r) => rowHtml(r, spec)).join("") || `<tr><td colspan="9" class="empty">No ${state.filter === "near" ? "near misses" : "proven companies"} in this run.</td></tr>`}</tbody>
    </table></div>
    <div class="legend">
      <span>${hallmark("pass")} Proven, with a quote</span><span>${hallmark("fail")} Disproven by a source</span>
      <span>${hallmark("unclear")} Not proven either way</span><span>Click any mark to see its certificate</span>
    </div>`;
  $("#view").querySelectorAll("[data-filter]").forEach((b) => (b.onclick = () => { state.filter = b.dataset.filter; renderResults(); }));
  $("#view").querySelectorAll("[data-cell]").forEach((b) => (b.onclick = () => openCert(b.dataset.row, b.dataset.cell)));
  $("#view").querySelectorAll("[data-field]").forEach((b) => (b.onclick = () => openField(b.dataset.row, b.dataset.field)));
}

function rowHtml(r, spec) {
  const m = !state.running || r.done ? isMatch(r) : false;
  const req = spec.criteria.filter((c) => c.required);
  return `<tr class="${m ? "match" : ""}" data-key="${esc(r.key)}">
    <td class="co"><b>${esc(r.name)}</b><a href="${esc(r.homepage)}" target="_blank" rel="noopener">${esc(host(r.homepage))}</a>
      ${m ? `<div class="strip" aria-label="Proven on every required check">${req.map(() => "<i class='p'></i>").join("")}</div>` : ""}</td>
    ${spec.criteria.map((c) => {
      const v = r.verdicts[c.id];
      const st = v ? v.status : "pending";
      const fresh = state.running && v && v._fresh ? " stamp" : "";
      return `<td class="crit"><button class="punch ${st === "pending" ? "pending" : ""}${fresh}" ${v ? `data-row="${esc(r.key)}" data-cell="${esc(c.id)}"` : "disabled"}
        aria-label="${esc(c.label)}: ${v ? STATUS_WORD[st] : "checking"}">${hallmark(st)}</button></td>`;
    }).join("")}
    ${spec.enrich.map((e) => {
      const f = r.fields?.[e.id];
      return f && f.value ? `<td class="field"><button data-row="${esc(r.key)}" data-field="${esc(e.id)}">${esc(f.value)}</button></td>` : `<td class="field none">${state.running ? "" : "Not stated"}</td>`;
    }).join("")}
  </tr>`;
}

// ------------------------------------------------------------------ certificate
function rowByKey(key) { return (state.running?.rows || state.detail.run?.rows || []).find((r) => r.key === key); }

function openCert(key, cid) {
  const r = rowByKey(key), c = state.detail.spec.criteria.find((x) => x.id === cid), v = r?.verdicts[cid];
  if (!v) return;
  const ev = v.evidence?.[0];
  showDrawer(`
    <div class="drawer-top"><span>Assay certificate</span><button class="close" data-close aria-label="Close">Close</button></div>
    <div class="cert"><div class="cert-in">
      <div class="cert-head">${hallmark(v.status)}<div><h2>${STATUS_WORD[v.status]}</h2><p>${STATUS_LINE[v.status]}</p></div></div>
      ${ev ? `<div class="serial" style="margin-top:14px">No. ${serial(ev.content_hash)}</div>` : ""}
      <dl>
        <dt>Company</dt><dd>${esc(r.name)}</dd>
        <dt>Tested for</dt><dd>${esc(c.question)}${c.within_months ? ` <span class="tag">within ${c.within_months} months</span>` : ""}</dd>
        ${ev ? `<dt>Source</dt><dd><a href="${esc(ev.url)}" target="_blank" rel="noopener">${esc(ev.url)}</a></dd>
        <dt>Captured</dt><dd>${ago(ev.fetched_at)}</dd>` : ""}
      </dl>
      ${ev ? `<div class="found"><div class="q">${esc(ev.quote)}</div>${contextHtml(ev)}</div>` : ""}
      <div class="verdict-note">${esc(v.rationale)}</div>
      ${v.gated ? `<div class="gated">The receipt gate downgraded this verdict: ${esc(v.gated)}</div>` : ""}
      ${ev ? `<div class="cert-foot">The quote was checked word for word against the page as captured, fingerprint <code>sha256 ${esc(ev.content_hash.slice(0, 16))}…</code></div>` : ""}
    </div></div>`);
}

function openField(key, fid) {
  const r = rowByKey(key), e = state.detail.spec.enrich.find((x) => x.id === fid), f = r?.fields?.[fid];
  if (!f) return;
  const ev = f.evidence?.[0];
  showDrawer(`
    <div class="drawer-top"><span>Assay certificate</span><button class="close" data-close aria-label="Close">Close</button></div>
    <div class="cert"><div class="cert-in">
      <div class="cert-head">${hallmark("pass")}<div><h2>${esc(f.value)}</h2><p>${esc(e.label)}, as stated by the source.</p></div></div>
      ${ev ? `<div class="serial" style="margin-top:14px">No. ${serial(ev.content_hash)}</div>
      <dl><dt>Company</dt><dd>${esc(r.name)}</dd><dt>Source</dt><dd><a href="${esc(ev.url)}" target="_blank" rel="noopener">${esc(ev.url)}</a></dd>
      <dt>Captured</dt><dd>${ago(ev.fetched_at)}</dd></dl>
      <div class="found"><div class="q">${esc(ev.quote)}</div>${contextHtml(ev)}</div>` : ""}
    </div></div>`);
}

function contextHtml(ev) {
  if (!ev.context || ev.context === ev.quote) return "";
  const ctx = esc(ev.context), q = esc(ev.quote);
  return `<div class="ctx">${ctx.includes(q) ? ctx.replace(q, `<mark>${q}</mark>`) : ctx}</div>`;
}

function showDrawer(html) {
  const d = $("#drawer");
  d.innerHTML = html;
  d.classList.add("open");
  d.setAttribute("aria-hidden", "false");
  $("#scrim").hidden = false;
  $("[data-close]", d).focus();
}
function closeDrawer() {
  $("#drawer").classList.remove("open");
  $("#drawer").setAttribute("aria-hidden", "true");
  $("#scrim").hidden = true;
}
document.addEventListener("click", (e) => { if (e.target.closest("[data-close]") || e.target.id === "scrim") closeDrawer(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

// ------------------------------------------------------------------ changes
const WORD = { pass: "proven", fail: "disproven", unclear: "not proven" };

function renderChanges() {
  const hist = (state.detail.history || []).filter((h) => h.changes.length);
  if (!hist.length) {
    $("#view").innerHTML = `<div class="empty"><h3>No changes yet</h3>Changes appear once a set has been assayed twice: a company that newly qualifies, one that stops, or a check whose answer moved, each with its new evidence.</div>`;
    return;
  }
  const spec = state.detail.spec;
  const labelOf = (id) => (spec.criteria.find((x) => x.id === id) || spec.enrich.find((x) => x.id === id) || {}).label || id;
  const line = (c) => c.kind === "field"
    ? `<b>${esc(labelOf(c.criterion_id))}</b> is now ${esc(c.after || "not stated")}${c.before ? `, was ${esc(c.before)}` : ""}`
    : `<b>${esc(labelOf(c.criterion_id))}</b> is now ${WORD[c.after]}, was ${WORD[c.before]}`;
  const groups = (changes) => {
    const by = new Map();
    changes.forEach((c) => { if (!by.has(c.key)) by.set(c.key, []); by.get(c.key).push(c); });
    return [...by.values()];
  };
  const card = (cs) => {
    const lead = cs.find((c) => c.kind === "new_match") || cs.find((c) => c.kind === "lost_match") || cs[0];
    const details = cs.filter((c) => c.kind === "verdict" || c.kind === "field");
    const ev = (lead.evidence?.[0] ? lead : cs.find((c) => c.evidence?.length))?.evidence?.[0];
    const icon = lead.kind === "new_match" ? hallmark("pass") : lead.kind === "lost_match" ? hallmark("fail")
      : hallmark(lead.after === "pass" ? "pass" : lead.after === "fail" ? "fail" : "unclear");
    const title = lead.kind === "new_match" ? `${esc(lead.name)} now qualifies`
      : lead.kind === "lost_match" ? `${esc(lead.name)} no longer qualifies` : esc(lead.name);
    return `<article class="change ${esc(lead.kind)}"><div class="change-icon">${icon}</div><div>
      <h4>${title}</h4>${details.length ? `<ul>${details.map((c) => `<li>${line(c)}</li>`).join("")}</ul>` : ""}
      ${ev ? `<blockquote>${esc(ev.quote)}</blockquote><div class="src">From <a href="${esc(ev.url)}" target="_blank" rel="noopener">${esc(ev.url)}</a></div>` : ""}
    </div></article>`;
  };
  $("#view").innerHTML = `<div class="timeline">${hist.map((h) => `
    <section><div class="when">Assayed ${ago(h.finished_at)}, compared with the run before</div>
      ${groups(h.changes).map(card).join("")}
    </section>`).join("")}</div>`;
}

// ------------------------------------------------------------------ runs + definition
function renderRuns() {
  const h = state.detail.history || [];
  $("#view").innerHTML = h.length ? `<div class="table-wrap"><table class="ledger runs"><thead><tr><th>Assayed</th><th>Proven</th><th>Companies</th><th>Pages read</th><th>Checks</th><th>Downgraded by the gate</th><th>Changes</th></tr></thead>
    <tbody>${h.map((r) => `<tr><td>${ago(r.finished_at)}</td><td>${r.stats.matches}</td><td>${r.stats.candidates}</td>
      <td>${r.stats.pages_fetched + r.stats.pages_cached}</td><td>${r.stats.judge_calls}</td><td>${r.stats.gated}</td><td>${r.changes.length}</td></tr>`).join("")}</tbody></table></div>`
    : `<div class="empty"><h3>No runs yet</h3>Run the assay to create the first one.</div>`;
}

function renderDefinition() {
  const s = state.detail.spec;
  $("#view").innerHTML = `<div class="def">
    <div class="def-item"><b>Search</b><p>${esc(s.query)}</p><code>backends: ${esc(s.backends.join(", "))}${state.detail.lead_sources.length ? `; publishers mined for leads: ${esc(state.detail.lead_sources.join(", "))}` : ""}</code></div>
    ${s.criteria.map((c) => `<div class="def-item"><b>${esc(c.label)}</b>${c.required ? "" : '<span class="tag">optional</span>'}${c.within_months ? `<span class="tag">within ${c.within_months} months</span>` : ""}
      <p>${esc(c.question)}</p>${c.signals.length ? `<code>proven by: ${esc(c.signals.join("  |  "))}</code><br>` : ""}${c.against.length ? `<code>disproven by: ${esc(c.against.join("  |  "))}</code>` : ""}</div>`).join("")}
    ${s.enrich.map((e) => `<div class="def-item"><b>${esc(e.label)}</b><p>${esc(e.question)}</p></div>`).join("")}
  </div>`;
}

// ------------------------------------------------------------------ running
function liveBox() {
  const r = state.running;
  const total = Math.max(1, r.candidates * state.detail.spec.criteria.length);
  const pct = r.finished ? 100 : Math.min(98, Math.round((r.verdicts / total) * 100));
  return `<div class="live" aria-live="polite"><div>
      <h3>${r.finished ? "Assay complete" : r.phase}</h3>
      <p>${r.candidates ? `${r.candidates} companies, ${r.verdicts} of ${total} checks done` : "Searching for candidates"}</p>
      <div class="bar"><i style="width:${pct}%"></i></div></div>
    <div class="log">${r.log.slice(-4).map((l) => `<div>${l}</div>`).join("")}</div></div>`;
}

async function startRun() {
  const d = state.detail;
  let runId;
  try { runId = await api.startRun(d.spec.id); } catch (e) { toast(e.message); return; }
  state.tab = "results";
  if (location.hash.split("/")[3] !== "results") history.replaceState(null, "", `#/sets/${d.spec.id}/results`);
  state.running = { runId, rows: [], byKey: {}, candidates: 0, verdicts: 0, phase: "Searching", log: [], finished: false };
  renderSet();
  api.events(runId, (e) => onEvent(e));
}

function onEvent(e) {
  const r = state.running;
  if (!r) return;
  const d = e.data;
  const name = (k) => r.byKey[k]?.name || k;
  switch (e.kind) {
    case "run.started": r.log.push(`Searching ${esc(d.backends.join(", "))} for <b>${esc(d.query)}</b>`); break;
    case "search.done": r.log.push(`${d.hits} results`); r.phase = "Reading company sites"; break;
    case "backend.error": r.log.push(`${esc(d.backend)} is unavailable: ${esc(d.error)}`); break;
    case "candidate.found": break;
    case "candidate.fetched": {
      const row = { key: d.key, name: d.name, homepage: `https://${d.key}`, verdicts: {}, fields: {} };
      r.byKey[d.key] = row; r.rows.push(row); r.candidates++;
      r.log.push(`Read ${d.pages} page${d.pages !== 1 ? "s" : ""} from <b>${esc(d.name)}</b>`);
      break;
    }
    case "verdict": {
      r.phase = "Checking every criterion";
      const row = r.byKey[d.key];
      if (row) {
        Object.values(row.verdicts).forEach((v) => delete v._fresh);
        row.verdicts[d.criterion] = { status: d.status, rationale: "", evidence: d.quote ? [{ quote: d.quote, url: "", content_hash: "", fetched_at: "" }] : [], _fresh: true };
      }
      r.verdicts++;
      if (d.status === "pass") r.log.push(`<b>${esc(name(d.key))}</b>: ${esc(labelOf(d.criterion))} proven`);
      break;
    }
    case "row.done": { const row = r.byKey[d.key]; if (row) row.done = true; break; }
    case "run.finished": r.phase = "Comparing with the last run"; r.log.push(`<b>${d.matches}</b> proven of ${d.candidates}`); break;
    case "run.saved": finish(d.changes); return;
  }
  if (state.tab === "results" && $("#view")) renderResults();
}

const labelOf = (cid) => state.detail.spec.criteria.find((c) => c.id === cid)?.label || cid;

async function finish(changes) {
  state.running.finished = true;
  renderResults();
  await new Promise((res) => setTimeout(res, 700));
  state.running = null;
  state.detail = await api.set(state.setId);
  state.sets = (await api.bootstrap()).sets;
  renderRail();
  renderSet();
  toast(changes ? `Assay complete: ${changes} change${changes !== 1 ? "s" : ""} since the last run` : "Assay complete: nothing changed");
}

// ------------------------------------------------------------------ toast + boot
let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 3200);
}

function defs() {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("width", "0"); s.setAttribute("height", "0"); s.style.position = "absolute";
  s.innerHTML = `<defs><linearGradient id="gold-grad" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f1d894"/><stop offset=".5" stop-color="#c9a24e"/><stop offset="1" stop-color="#8c6b2a"/></linearGradient></defs>`;
  document.body.prepend(s);
}

async function boot() {
  defs();
  state.sets = (await api.bootstrap()).sets;
  if (!location.hash && state.sets.length === 1) location.hash = `#/sets/${state.sets[0].id}`;
  window.addEventListener("hashchange", route);
  route();
}
boot();
