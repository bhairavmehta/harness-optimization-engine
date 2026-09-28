'use strict';
/* Harness Optimization Engine — single-page frontend (vanilla JS, hash routing). */

const S = { agent: 'billing', boot: null, timers: [], query: new URLSearchParams(), jobs: {} };
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pct = (v, d = 1) => v == null ? '—' : (v * 100).toFixed(d) + '%';
const pts = (v, d = 1) => v == null ? '—' : (v >= 0 ? '+' : '−') + Math.abs(v * 100).toFixed(d) + ' pts';
const num = v => v == null ? '—' : Math.round(v).toLocaleString('en-US');
const fx = (v, d = 2) => v == null ? '—' : Number(v).toFixed(d);
const sign = (v, d = 0) => (v >= 0 ? '+' : '−') + Math.abs(v).toFixed(d);
const cls = v => v > 0 ? 'pos' : v < 0 ? 'neg' : '';

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
const post = (path, body = {}) => api(path, { method: 'POST', body: JSON.stringify(body) });

let toastTimer;
function toast(msg, err = false) {
  let t = $('.toast');
  if (!t) { t = document.createElement('div'); t.className = 'toast'; t.setAttribute('role', 'status'); document.body.appendChild(t); }
  t.className = 'toast' + (err ? ' err' : '');
  t.textContent = msg;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.remove(), err ? 6000 : 3200);
}

let ACT = {};
document.addEventListener('click', e => {
  const nav = e.target.closest('[data-href]');
  if (nav && !e.target.closest('a,button,select,input')) { location.hash = nav.dataset.href; return; }
  const el = e.target.closest('[data-act]');
  if (el && ACT[el.dataset.act]) { e.preventDefault(); ACT[el.dataset.act](el, e); }
});
document.addEventListener('change', e => {
  const el = e.target.closest('[data-change]');
  if (el && ACT[el.dataset.change]) ACT[el.dataset.change](el, e);
});

async function busy(btn, fn) {
  if (!btn) return fn();
  const html = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span> ${esc(btn.dataset.busy || 'Working…')}`;
  try { return await fn(); } catch (e) { toast(e.message, true); }
  finally { if (btn.isConnected) { btn.disabled = false; btn.innerHTML = html; } }
}

const page = html => { $('#main').innerHTML = html; };
function crumbs(items) {
  $('#crumbs').innerHTML = items.map(([l, h]) => h ? `<a href="${h}">${esc(l)}</a>` : `<span>${esc(l)}</span>`).join(' <span class="faint">/</span> ');
}
function head(title, sub = '', actions = '') {
  return `<div class="page-head"><div><h1>${title}</h1>${sub ? `<div class="sub">${sub}</div>` : ''}</div><div class="actions">${actions}</div></div>`;
}
const kpis = items => `<div class="kpis">${items.map(k => `<div class="kpi"><div class="v">${k.v}</div><div class="l">${esc(k.l)}</div>${k.d ? `<div class="d muted">${k.d}</div>` : ''}</div>`).join('')}</div>`;

const SEV = { Critical: 'critical', High: 'high', Medium: 'medium', Low: '' };
const sevBadge = s => `<span class="badge ${SEV[s] ?? ''}">${esc(s)}</span>`;
const GOOD = ['Live', 'Fixed', 'Approved', 'Passed', 'Healthy', 'Validated', 'Active', 'done'];
const WARN = ['Waiting', 'Awaiting approval', 'Fix in approval', 'Rolling out', 'Changes requested', 'Drifting', 'Pending', 'running', 'Fix validated'];
const BAD = ['Rejected', 'Rolled back', 'Below threshold', 'failed', 'cancelled'];
const status = s => `<span class="badge ${GOOD.includes(s) ? 'good' : WARN.includes(s) ? 'warn' : BAD.includes(s) ? 'bad' : 'info'}">${esc(s)}</span>`;
const empty = (msg, action = '') => `<div class="empty">${msg}${action ? `<div style="margin-top:12px">${action}</div>` : ''}</div>`;

function observeOnly(a) {
  return `<div class="panel">${empty(`${esc(a.name)} is connected as <b>${esc(a.integration.toLowerCase())}</b>. This demo simulates traces for the billing and outage agents only. Pick one of them from the agent menu, or test a proven pattern against this agent from the <a href="#/patterns">pattern library</a>.`)}</div>`;
}

/* ------------------------------------------------------------------ charts (inline SVG) */
function lineChart({ series, labels = [], height = 220, yFmt = v => pct(v, 0), yMin, yMax, markers = [] }) {
  const W = 720, H = height, L = 46, R = 12, T = 12, B = 28;
  const all = series.flatMap(s => s.values.filter(v => v != null));
  let lo = yMin ?? Math.min(...all), hi = yMax ?? Math.max(...all);
  if (!(hi > lo)) { hi = lo + 1; }
  const pad = (hi - lo) * 0.08; if (yMin == null) lo -= pad; if (yMax == null) hi += pad;
  const n = Math.max(...series.map(s => s.values.length));
  const x = i => L + (n <= 1 ? 0 : i * (W - L - R) / (n - 1));
  const y = v => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
  let g = '';
  for (let k = 0; k <= 4; k++) {
    const v = lo + (hi - lo) * k / 4;
    g += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="#EFEEF4"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${esc(yFmt(v))}</text>`;
  }
  const step = Math.ceil(n / 8);
  labels.forEach((l, i) => { if (i % step === 0 || i === n - 1) g += `<text x="${x(i)}" y="${H - 8}" text-anchor="${i === n - 1 && n > 1 ? 'end' : i === 0 ? 'start' : 'middle'}">${esc(l)}</text>`; });
  markers.forEach(m => {
    g += `<line x1="${x(m.i)}" x2="${x(m.i)}" y1="${T}" y2="${H - B}" stroke="#5A2A78" stroke-dasharray="4 4"/>` +
      `<text x="${x(m.i) + 5}" y="${T + 11}" style="fill:#5A2A78">${esc(m.label)}</text>`;
  });
  series.forEach(s => {
    const pts_ = s.values.map((v, i) => v == null ? null : [x(i), y(v)]).filter(Boolean);
    if (!pts_.length) return;
    g += `<polyline fill="none" stroke="${s.color}" stroke-width="${s.width || 2.2}" ${s.dash ? `stroke-dasharray="${s.dash}"` : ''} stroke-linejoin="round" points="${pts_.map(p => p.join(',')).join(' ')}"/>`;
    if (s.dots) pts_.forEach(p => { g += `<circle cx="${p[0]}" cy="${p[1]}" r="3.2" fill="#fff" stroke="${s.color}" stroke-width="2"/>`; });
  });
  const legend = series.length > 1 ? `<div class="legend">${series.map(s => `<span><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join('')}</div>` : '';
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img">${g}</svg>${legend}`;
}

function scatter({ points, xFmt = v => num(v), yFmt = v => pct(v, 0), xLabel = '', yLabel = '' }) {
  const W = 560, H = 280, L = 52, R = 20, T = 16, B = 40;
  const xs = points.map(p => p.x), ys = points.map(p => p.y);
  let [x0, x1] = [Math.min(...xs), Math.max(...xs)], [y0, y1] = [Math.min(...ys), Math.max(...ys)];
  const px = (x1 - x0 || x0 * 0.1 || 1) * 0.15, py = (y1 - y0 || 0.05) * 0.2;
  x0 -= px; x1 += px; y0 -= py; y1 += py;
  const X = v => L + (W - L - R) * (v - x0) / (x1 - x0), Y = v => T + (H - T - B) * (1 - (v - y0) / (y1 - y0));
  let g = '';
  for (let k = 0; k <= 3; k++) {
    const vy = y0 + (y1 - y0) * k / 3, vx = x0 + (x1 - x0) * k / 3;
    g += `<line x1="${L}" x2="${W - R}" y1="${Y(vy)}" y2="${Y(vy)}" stroke="#EFEEF4"/><text x="${L - 6}" y="${Y(vy) + 4}" text-anchor="end">${esc(yFmt(vy))}</text>`;
    g += `<text x="${X(vx)}" y="${H - 22}" text-anchor="middle">${esc(xFmt(vx))}</text>`;
  }
  g += `<text x="${(L + W - R) / 2}" y="${H - 4}" text-anchor="middle">${esc(xLabel)}</text>`;
  g += `<text x="12" y="${T + (H - T - B) / 2}" transform="rotate(-90 12 ${T + (H - T - B) / 2})" text-anchor="middle">${esc(yLabel)}</text>`;
  points.forEach(p => {
    g += `<circle cx="${X(p.x)}" cy="${Y(p.y)}" r="${p.r || 7}" fill="${p.color}" fill-opacity=".9" stroke="#fff" stroke-width="2"/>` +
      `<text x="${X(p.x) + 11}" y="${Y(p.y) + 4}" style="fill:#1A1233;font-weight:500">${esc(p.label)}</text>`;
  });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img">${g}</svg>`;
}

function spark(values, color = '#0070AD', w = 96, h = 26, thr = null) {
  if (!values || values.length < 2) return '';
  const lo = Math.min(...values, thr ?? 1), hi = Math.max(...values, thr ?? 0);
  const x = i => 2 + i * (w - 4) / (values.length - 1), y = v => 2 + (h - 4) * (1 - (v - lo) / ((hi - lo) || 1));
  const t = thr != null ? `<line x1="0" x2="${w}" y1="${y(thr)}" y2="${y(thr)}" stroke="#FF304C" stroke-dasharray="2 2" stroke-width="1"/>` : '';
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${t}<polyline fill="none" stroke="${color}" stroke-width="1.8" points="${values.map((v, i) => `${x(i)},${y(v)}`).join(' ')}"/></svg>`;
}
const hbar = (label, v, max, red) => `<div class="hbar"><div><div class="small">${esc(label)}</div><div class="bar ${red ? 'red' : ''}"><span style="width:${Math.max(2, 100 * v / (max || 1))}%"></span></div></div><div class="num small">${num(v)}</div></div>`;

/* ------------------------------------------------------------------ before / after replay */
const ROLE = { customer: 'Customer', agent: 'Agent' };
function msgHTML(m, extra = '') {
  if (m.role === 'tool') {
    const args = Object.entries(m.args || {}).map(([k, v]) => `${k}=${v}`).join(', ');
    return `<div class="tool ${/BLOCKED/.test(m.text) ? 'blocked' : ''}">⚙ <b>${esc(m.name)}</b>(${esc(args)}) → ${esc(m.text)}</div>`;
  }
  if (m.role === 'system') return `<div class="sysmsg ${/session ended/.test(m.text) ? 'end' : ''}">${esc(m.text)}</div>`;
  return `<div class="msg ${m.role} ${extra}"><span class="who">${ROLE[m.role]}</span>${esc(m.text)}</div>`;
}

function outcomeHTML(side) {
  const e = side.eval, res = e.resolution, o = e.outcome;
  return `<div class="outcome">
    <div class="verdict"><span class="dot ${side.gold ? 'good' : 'bad'}"></span>${side.gold ? 'Resolved' : 'Not resolved'} <span class="muted small" style="font-weight:400">(human audit)</span></div>
    <div><span class="k">Resolution judge</span><br>${res.pass ? '<span class="pos">Pass</span>' : '<span class="neg">Fail</span>'} · ${fx(res.score)}</div>
    <div><span class="k">Repeat contact</span><br>${o.repeat_contact ? `<span class="neg">Yes, ${o.repeat_hours} h later</span>` : 'None in 72 h'}</div>
    <div><span class="k">Policy</span><br>${e.policy.pass ? 'Pass' : `<span class="neg">${esc(e.policy.detail)}</span>`}</div>
    <div><span class="k">Tool sequence</span><br>${e.tool_sequence.anomaly ? `<span class="neg">${esc(e.tool_sequence.detail)}</span>` : 'Expected order'}</div>
    <div><span class="k">Tokens</span><br>${num(side.tokens)}</div>
    <div><span class="k">Latency</span><br>${fx(side.latency, 1)} s</div>
    <div style="grid-column:1/-1" class="muted small">Judge rationale: ${esc(res.rationale)}</div>
  </div>`;
}

function forkText(r) {
  const ch = [];
  r.before.decisions.forEach((d, i) => {
    const a = r.after.decisions[i];
    if (a && a.d === d.d && a.a !== d.a) ch.push(`${r.decision_labels[d.d]}: <b>${esc(r.action_labels[d.a])}</b> → <b>${esc(r.action_labels[a.a])}</b>`);
  });
  if (ch.length) return ch.slice(0, 2).join(' · ');
  const gates = r.after.harness.gates.filter(g => !r.before.harness.gates.includes(g));
  if (gates.length) return `Gate fires: <b>${esc(S.boot.library.gates[gates[0]].text)}</b>`;
  return 'The harness change takes effect here';
}

function renderReplay(r) {
  const d = r.divergence;
  const B = r.before, A = r.after;
  if (d < 0) {
    return `<details class="shared" open><summary><span>Identical under both harnesses · ${B.messages.length} messages</span><span>${esc(r.scenario.label)}</span></summary>
      <div class="msgs">${B.messages.map(m => msgHTML(m)).join('')}</div></details>
      <div class="fork none"><span>No divergence: this change does not alter this conversation</span></div>
      <div class="lanes"><div class="lane before">${laneHead('Before', B)}${outcomeHTML(B)}</div><div class="lane after">${laneHead('After', A)}${outcomeHTML(A)}</div></div>`;
  }
  const prefix = B.messages.slice(0, d), older = prefix.slice(0, -2), tail = prefix.slice(-2);
  const shared = prefix.length ? `<div class="shared"><div class="shared-head"><span>Same in both versions · ${prefix.length} message${prefix.length === 1 ? '' : 's'}</span><span>${esc(r.scenario.label)} · seed ${r.scen_seed}</span></div>
      ${older.length ? `<details><summary>Show ${older.length} earlier message${older.length === 1 ? '' : 's'}</summary><div class="msgs">${older.map(m => msgHTML(m)).join('')}</div></details>` : ''}
      <div class="msgs">${tail.map(m => msgHTML(m)).join('')}</div></div>` : '';
  return `${shared}
    <div class="fork"><span>${forkText(r)}</span></div>
    <div class="lanes">
      <div class="lane before">${laneHead('Before', B)}<div class="msgs">${B.messages.slice(d).map(m => msgHTML(m, 'new')).join('')}</div>${outcomeHTML(B)}</div>
      <div class="lane after">${laneHead('After', A)}<div class="msgs">${A.messages.slice(d).map(m => msgHTML(m, 'new')).join('')}
        ${A.truncated ? '<div class="sysmsg">Prefix replay: stops after the first changed turn</div>' : ''}</div>${outcomeHTML(A)}</div>
    </div>
    <details class="decisions"><summary class="muted small" style="cursor:pointer;margin-top:12px">Decision probabilities at each step</summary>
      <table><tr><th>Decision</th><th>Before</th><th>After</th></tr>
      ${B.decisions.map((x, i) => { const y = A.decisions[i]; return `<tr><td>${esc(r.decision_labels[x.d])}</td><td>${esc(r.action_labels[x.a])} <span class="faint">p=${fx(x.p[x.a])}</span></td><td>${y ? `${esc(r.action_labels[y.a])} <span class="faint">p=${fx(y.p[y.a])}</span>` : '—'}</td></tr>`; }).join('')}
      </table></details>`;
}
const laneHead = (label, side) => `<div class="lane-head"><span class="who">${label}</span><span class="small muted">${esc(side.harness.name)}</span></div>`;

/* A replay widget: example picker, mode, simulator-error, and the split conversation. */
function replayWidget(id, opts) {
  const R = { ...opts, mode: 'simulator', sim: 0 };
  S[`replay_${id}`] = R;
  const traceCtl = opts.traceId ? `<div class="grow"><label class="field">Trace<span class="mono" style="color:var(--ink);padding:7px 0">${esc(opts.traceId)}</span></label></div>`
    : `<div class="grow"><label class="field">Example conversation<select id="${id}-ex" data-change="${id}-pick"><option>Loading examples…</option></select></label></div>
       <button class="btn sm" data-act="${id}-random">Random scenario</button>`;
  const html = `<div class="replay" id="${id}">
    <div class="replay-bar">${traceCtl}
      <label class="field">Replay mode<div class="seg" role="group"><button class="on" data-act="${id}-mode" data-mode="simulator">Full simulator</button><button data-act="${id}-mode" data-mode="prefix">Prefix only</button></div></label>
      <label class="field">Simulated-customer error <span id="${id}-simv">0%</span><input type="range" min="0" max="0.4" step="0.05" value="0" data-change="${id}-sim"></label>
    </div>
    <div class="replay-body" id="${id}-body"><div class="loading">Replaying…</div></div></div>`;

  const run = async (extra = {}) => {
    const body = { base_id: R.base, cand_id: R.cand, mode: R.mode, sim_error: R.sim, ...extra };
    if (R.traceId) body.trace_id = R.traceId;
    else if (R.current?.trace_id) body.trace_id = R.current.trace_id;
    else if (R.current?.scen_seed) { body.scen_seed = R.current.scen_seed; body.samp_seed = R.current.scen_seed; }
    const el = $(`#${id}-body`); if (!el) return;
    el.style.opacity = .5;
    try { const r = await post('/api/replay', body); el.innerHTML = renderReplay(r); } catch (e) { el.innerHTML = `<div class="alert bad">${esc(e.message)}</div>`; }
    el.style.opacity = 1;
  };
  ACT[`${id}-mode`] = el => { R.mode = el.dataset.mode; $$(`#${id} .seg button`).forEach(b => b.classList.toggle('on', b === el)); run(); };
  ACT[`${id}-sim`] = el => { R.sim = +el.value; $(`#${id}-simv`).textContent = pct(R.sim, 0); run(); };
  ACT[`${id}-pick`] = el => { if (el.value === '') return; R.current = R.examples[+el.value]; run(); };
  ACT[`${id}-random`] = () => { R.current = { scen_seed: 40000 + Math.floor(Math.random() * 20000) }; const s = $(`#${id}-ex`); if (s) s.value = ''; run(); };
  const init = async () => {
    if (!R.traceId) {
      R.examples = await api(`/api/replay-examples?base_id=${encodeURIComponent(R.base)}&cand_id=${encodeURIComponent(R.cand)}${R.theme ? `&theme=${encodeURIComponent(R.theme)}` : ''}`);
      const sel = $(`#${id}-ex`); if (!sel) return;
      sel.innerHTML = R.examples.length ? R.examples.map((x, i) => `<option value="${i}">${esc(x.trace_id)} · ${esc(x.label)} · “${esc(x.snippet.slice(0, 48))}”${x.fixed ? ' · fixed' : x.regressed ? ' · regressed' : ''}</option>`).join('')
        : '<option value="">No production trace changes under this candidate — try a random scenario</option>';
      R.current = R.examples[0] || { scen_seed: 40001 };
    }
    run();
  };
  return { html, init };
}

/* ================================================================== views */
async function vOverview() {
  crumbs([['Overview']]);
  const d = await api(`/api/overview/${S.agent}`);
  if (!d.kpis.traces) { page(head('Overview', esc(d.agent.name)) + observeOnly(d.agent)); return; }
  const k = d.kpis;
  const markers = d.releases.map(r => ({ i: r.day, label: `${r.version} released` }));
  const maxSig = Math.max(...d.signals.map(s => s.value));
  page(`${head('Overview', `${esc(d.agent.name)} · ${esc(d.production.version)} in production · last 14 days of traces`,
    `<button class="btn primary" data-act="analyze" data-busy="Analyzing…">Run analysis</button>`)}
    ${kpis([{ v: num(k.traces), l: 'Traces analyzed' }, { v: num(k.flagged), l: 'Flagged sessions', d: `${pct(k.flag_rate)} of traces` },
      { v: k.themes, l: 'Failure themes', d: `${k.critical} critical` }, { v: k.waiting, l: 'Waiting for approval', d: '<a href="#/approvals">Review queue</a>' }])}
    <div class="grid-main"><div>
      <div class="panel"><div class="panel-head"><h2>Flagged-session rate</h2><span class="muted small">Share of each day's sessions flagged by any signal</span></div>
        ${lineChart({ series: [{ name: 'Flagged', color: '#0070AD', values: d.daily.map(x => x.rate), dots: true }], labels: d.daily.map(x => x.date), markers, yMin: 0 })}</div>
      <div class="panel"><div class="panel-head"><h2>Failure themes</h2><a href="#/themes">All themes</a></div>${themeTable(d.themes)}</div>
    </div><div>
      <div class="panel"><h2>Detection signals</h2>${d.signals.map(s => hbar(s.label, s.value, maxSig)).join('')}</div>
      <div class="panel"><h2>Production harness</h2>
        <div class="kv"><span class="k">Version</span><span>${esc(d.production.version)}</span><span class="k">Integration</span><span>${esc(d.agent.integration)}</span>
        <span class="k">Gates</span><span>${d.production.gates.length ? d.production.gates.map(g => esc(S.boot.library.gates[g].text)).join('<br>') : 'None'}</span></div>
        <ul class="small" style="padding-left:18px;margin:12px 0 0">${d.production.lines.map(l => `<li>${esc(S.boot.library.lines[l].text)}${S.boot.library.lines[l].frozen ? ' <span class="lock">frozen</span>' : ''}</li>`).join('')}</ul></div>
    </div></div>`);
  ACT.analyze = btn => busy(btn, async () => { await post(`/api/analysis/${S.agent}`); toast('Analysis complete: themes re-clustered'); route(); });
}

function themeTable(ts) {
  if (!ts.length) return empty('No failure themes yet. Run analysis to cluster flagged traces.');
  return `<div class="table-wrap"><table><tr><th>Theme</th><th>Severity</th><th class="num">Traces</th><th class="num">Trend 7d</th><th class="num">Repeat contact</th><th>Status</th></tr>
    ${ts.map(t => `<tr class="click" data-href="#/themes/${t.id}"><td>${esc(t.name)}<div class="small muted">${esc(t.layer)} · first seen ${esc(t.first_seen)}</div></td>
      <td>${sevBadge(t.sev)}</td><td class="num">${num(t.traces)}</td><td class="num ${t.trend > 0 ? 'neg' : 'pos'}">${sign(t.trend * 100)}%</td>
      <td class="num">${pct(t.repeat_rate, 0)}</td><td>${status(t.status)}</td></tr>`).join('')}</table></div>`;
}

async function vThemes() {
  crumbs([['Failure themes']]);
  const ts = await api(`/api/themes/${S.agent}`);
  page(`${head('Failure themes', 'Flagged traces clustered by shared failure signature. Each theme links to evidence, a root-cause hypothesis and a fix bundle.')}
    <div class="panel">${themeTable(ts)}</div>`);
}

async function vTheme(tid) {
  const t = await api(`/api/theme/${tid}`);
  crumbs([['Failure themes', '#/themes'], [t.name]]);
  const rc = t.root_cause;
  const acts = t.bundle_id ? `<a class="btn primary" href="#/fixes/${t.bundle_id}/F-1">Open fix bundle</a>`
    : `<button class="btn primary" data-act="gen" data-busy="Proposing fixes…">Generate fix bundle</button>`;
  page(`${head(`${esc(t.name)} ${sevBadge(t.sev)}`, `${esc(t.desc)}`, `${acts}<a class="btn" href="#/regression?theme=${t.id}">Convert to regression tests</a>`)}
    ${kpis([{ v: num(t.traces), l: 'Traces in theme', d: `${pct(t.share, 0)} of flagged sessions` }, { v: pct(t.repeat_rate, 0), l: 'Repeat contact', d: `vs ${pct(t.repeat_base, 0)} agent baseline` },
      { v: fx(t.csat, 1), l: 'Average CSAT' }, { v: esc(t.first_seen), l: 'First seen', d: `${sign(t.trend * 100)}% week over week` }])}
    <div class="grid-main"><div>
      <div class="panel"><h2>Root-cause hypothesis</h2><p>${esc(rc.text)}</p>
        <div class="kv" style="margin-top:10px"><span class="k">Confidence</span><span><div class="bar" style="width:180px;display:inline-block;vertical-align:middle"><span style="width:${rc.confidence * 100}%"></span></div> ${fx(rc.confidence)}</span>
        <span class="k">Suspected layer</span><span>${esc(t.layer)}</span>
        ${rc.change ? `<span class="k">Correlated change</span><span><span class="mono">${esc(rc.change.from)} → ${esc(rc.change.to)}</span></span>` : ''}</div></div>
      <div class="panel"><h2>Daily occurrences</h2>${lineChart({ series: [{ name: 'Traces', color: '#FF304C', values: t.daily }], labels: t.daily.map((_, i) => `d${i}`), yFmt: v => num(v), yMin: 0, height: 170 })}</div>
      <div class="panel"><div class="panel-head"><h2>Evidence</h2><a href="#/traces?theme=${t.id}">All ${num(t.evidence_total)} traces</a></div>${traceTable(t.evidence)}</div>
    </div><div>
      <div class="panel"><h2>Sub-clusters</h2>${t.subclusters.map(s => `<div class="hbar"><div><div class="small">${esc(s.label)}</div><div class="bar"><span style="width:${s.share * 100}%"></span></div></div><div class="num small">${pct(s.share, 0)}</div></div>`).join('')}</div>
      <div class="panel"><h2>Fix bundle</h2>${t.bundle ? t.bundle.fixes.map(f => `<div class="approver"><div><a href="#/fixes/${t.bundle_id}/${f.id}">${f.id} · ${esc(f.title)}</a><div class="small muted">${esc(f.layer)} · ${esc(f.risk)} risk</div></div>${status(f.status)}</div>`).join('')
        : empty('No fixes proposed yet.', '<button class="btn sm" data-act="gen" data-busy="Proposing…">Generate fix bundle</button>')}</div>
      <div class="panel"><h2>Regression tests</h2><p class="muted">About ${t.suggested_tests} deduplicated tests can be generated from this theme's evidence.</p><a class="btn sm" href="#/regression?theme=${t.id}">Convert to tests</a></div>
    </div></div>`);
  ACT.gen = btn => busy(btn, async () => { const b = await post(`/api/theme/${tid}/bundle`, { n: 600 }); toast(`${b.fixes.length} fixes proposed and validated`); location.hash = `#/fixes/${b.id}/F-1`; });
}

function traceTable(items) {
  if (!items.length) return empty('No traces match.');
  return `<div class="table-wrap"><table><tr><th>Trace</th><th>Scenario</th><th>Customer</th><th>Judge</th><th>Outcome</th><th>Version</th><th>When</th></tr>
    ${items.map(t => `<tr class="click" data-href="#/traces/${t.id}"><td class="mono">${t.id}</td><td>${esc(t.label)}</td><td class="muted">“${esc(t.snippet.slice(0, 44))}”</td>
      <td>${t.judged_pass ? '<span class="pos">Pass</span>' : '<span class="neg">Fail</span>'} <span class="faint">${fx(t.judged_score)}</span></td>
      <td>${t.repeat ? '<span class="neg">Repeat contact</span>' : `CSAT ${t.csat}`}</td><td class="mono">${esc(t.version)}</td><td class="nowrap">${t.date} ${t.time}</td></tr>`).join('')}</table></div>`;
}

/* ------------------------------------------------------------------ fix bundles */
async function vFixes() {
  crumbs([['Fix bundles']]);
  const bs = await api(`/api/bundles?agent=${S.agent}`);
  page(`${head('Fix bundles', 'Each bundle groups candidate harness changes for one failure theme, validated offline against production traffic.')}
    ${bs.length ? bs.map(b => `<div class="panel"><div class="panel-head"><div><h2>${esc(b.theme_name)}</h2><div class="small muted">${b.id} · proposed from ${num(b.proposed_from)} failure traces · ${esc(b.created)}</div></div>
      ${b.combined ? `<div class="small">Best combination (${b.combined.fix_ids.join(' + ')}): <b class="${cls(b.combined.lift.diff)}">${pts(b.combined.lift.diff)}</b> resolution</div>` : ''}</div>
      <table><tr><th>Fix</th><th>Layer</th><th>Risk</th><th class="num">Resolution lift</th><th class="num">95% CI</th><th>Status</th></tr>
      ${b.fixes.map(f => { const v = f.validation, l = v && v.lift; return `<tr class="click" data-href="#/fixes/${b.id}/${f.id}"><td><b>${f.id}</b> ${esc(f.title)}</td><td>${esc(f.layer)}</td><td>${esc(f.risk)}</td>
        <td class="num ${l ? cls(l.diff) : ''}">${l ? pts(l.diff) : v && v.only_evaluator ? `κ ${fx(v.kappa_before)} → ${fx(v.kappa_after)}` : '—'}</td><td class="num muted">${l ? `${pts(l.lo)} to ${pts(l.hi)}` : ''}</td><td>${status(f.status)}</td></tr>`; }).join('')}</table></div>`).join('')
      : `<div class="panel">${empty('No fix bundles for this agent yet.', '<a class="btn" href="#/themes">Open a failure theme</a>')}</div>`}`);
}

const DELIVERY = {
  '1p_repo': [['pr', 'Open pull request'], ['registry', 'Publish to prompt registry'], ['overlay', 'Gateway overlay']],
  '1p_norepo': [['registry', 'Publish to prompt registry'], ['overlay', 'Gateway overlay']],
  '3p_config': [['config_api', 'Push via runtime config API'], ['vendor', 'Vendor change request'], ['overlay', 'Gateway overlay']],
  '3p_observe': [['vendor', 'Vendor change request'], ['overlay', 'Gateway overlay']],
};

function diffRows(rows) {
  return `<div class="diff">${rows.map(r => `<div class="diff-row ${r.mark === '+' ? 'add' : r.mark === '-' ? 'del' : r.mark === '~' ? 'chg' : r.frozen ? 'frozen' : ''}">
    <span class="m">${r.mark === '=' ? '' : r.mark === ' ' ? '' : r.mark}</span><span>${esc(r.text)}${r.before_text && r.mark === '~' ? `<div class="faint small">was: ${esc(r.before_text)}</div>` : ''}</span>
    ${r.frozen ? '<span class="lock">frozen</span>' : r.layer ? `<span class="faint small">${esc(r.layer)}</span>` : '<span></span>'}</div>`).join('')}</div>`;
}

function validationHTML(v) {
  if (!v) return empty('Not validated yet. Replay it against held-out production scenarios.');
  if (v.only_evaluator) return `<p>This fix changes how sessions are <b>scored</b>, not what the agent says, so conversations are unchanged. It is validated by judge–human agreement on the calibration set.</p>
    <div class="kv"><span class="k">Cohen's κ before</span><span>${fx(v.kappa_before)}</span><span class="k">Cohen's κ after</span><span class="${cls(v.kappa_after - v.kappa_before)}">${fx(v.kappa_after)}</span></div>`;
  const row = (l, k, f, better = 1) => { const d = v.cand[k] - v.base[k]; return `<tr><td>${l}</td><td class="num">${f(v.base[k])}</td><td class="num">${f(v.cand[k])}</td><td class="num ${cls(d * better)}">${k === 'tokens' ? sign(100 * d / v.base[k]) + '%' : k === 'p95' ? sign(d, 1) + ' s' : pts(d)}</td></tr>`; };
  return `<table><tr><th>Metric</th><th class="num">Before</th><th class="num">After</th><th class="num">Change</th></tr>
    ${row('Resolution (judge)', 'resolution', pct)}${row('Resolved (human audit)', 'gold', pct)}${row('Repeat contact 72h', 'repeat', pct, -1)}
    ${row('Policy violations', 'violations', v => pct(v, 2), -1)}${row('Tokens per task', 'tokens', num, -1)}${row('P95 latency', 'p95', v => fx(v, 1) + ' s', -1)}</table>
    <p class="small" style="margin-top:10px">Paired bootstrap on ${num(v.n)} held-out scenarios: resolution <b class="${cls(v.lift.diff)}">${pts(v.lift.diff)}</b> (95% CI ${pts(v.lift.lo)} to ${pts(v.lift.hi)})${v.sim_error ? ` · simulator error ${pct(v.sim_error, 0)}` : ''}.</p>
    <div class="chips">${v.regression ? `<span class="badge ${v.regression.gate ? 'good' : 'bad'}">Regression ${v.regression.passed}/${v.regression.total} pass</span>` : ''}
    <span class="badge ${v.frozen_untouched ? 'good' : 'bad'}">Frozen lines ${v.frozen_untouched ? 'untouched' : 'modified'}</span>
    <span class="badge ${v.kappa >= 0.7 ? 'good' : 'warn'}">Judge κ ${fx(v.kappa)}</span></div>`;
}

async function vFix(bid, fid) {
  const f = await api(`/api/fix/${bid}/${fid}`);
  crumbs([['Fix bundles', '#/fixes'], [f.theme.name, `#/themes/${f.theme.id}`], [f.id]]);
  const prev = f.index > 1 ? `#/fixes/${bid}/F-${f.index - 1}` : null, next = f.index < f.count ? `#/fixes/${bid}/F-${f.index + 1}` : null;
  const onlyEval = f.edits.every(e => e.op.includes('criterion'));
  const rw = onlyEval ? null : replayWidget('rp', { base: f.base.id, cand: f.cand.id, theme: f.theme.id });
  const methods = DELIVERY[f.agent.level] || DELIVERY['3p_observe'];
  const cfgChanged = f.config_rows.filter(r => r.mark !== ' ');
  page(`${head(`${f.id} · ${esc(f.title)}`, `${status(f.status)} <span class="badge purple">${esc(f.layer)}</span> <span class="badge">${esc(f.risk)} risk</span> · fix ${f.index} of ${f.count} for <a href="#/themes/${f.theme.id}">${esc(f.theme.name)}</a>`,
    `${prev ? `<a class="btn sm" href="${prev}">Previous fix</a>` : ''}${next ? `<a class="btn sm" href="${next}">Next fix</a>` : ''}`)}
    <div class="grid-main"><div>
      <div class="panel"><div class="panel-head"><h2>Before and after</h2><span class="small muted">${esc(f.base.version)} → ${esc(f.cand.version)} · same customer, same random draws</span></div>
        ${rw ? rw.html : `<div class="alert info">Evaluator-only change: conversations are identical. See the calibration result below.</div>`}</div>
      <div class="panel"><h2>What changes</h2>${diffRows(f.prompt_rows)}
        ${cfgChanged.length ? `<h3 style="margin:16px 0 8px">Configuration</h3>${diffRows(cfgChanged)}` : ''}</div>
      <div class="panel"><div class="panel-head"><h2>Offline validation</h2>
        <div class="actions"><select id="vn">${[300, 600, 1200, 2400].map(n => `<option ${n === 600 ? 'selected' : ''}>${n}</option>`).join('')}</select>
        <select id="vs" title="Simulated-customer error rate">${[0, 0.05, 0.1, 0.2].map(x => `<option value="${x}">${x ? pct(x, 0) + ' sim error' : 'No sim error'}</option>`).join('')}</select>
        <button class="btn sm primary" data-act="validate" data-busy="Replaying…">Run validation</button></div></div>
        <div id="val">${validationHTML(f.validation)}</div></div>
    </div><div>
      <div class="panel"><h2>Delivery</h2><p class="small muted">${esc(f.agent.name)} · ${esc(f.agent.integration)}</p>
        <div class="stack">${methods.map(([m, l]) => `<button class="btn" style="width:100%;justify-content:center" data-act="deliver" data-m="${m}">${l}</button>`).join('')}</div>
        <div id="deliv" style="margin-top:12px"></div></div>
      <div class="panel"><h2>Rollout plan</h2><ol class="small" style="padding-left:18px;margin:0">
        <li>Shadow traffic, 48 hours</li><li>Canary 5% → 25% → 50%</li><li>Full rollout</li></ol>
        <p class="small muted" style="margin-top:8px">Auto-rollback if resolution drops more than 1 pt or policy violations rise.</p></div>
      <div class="panel"><h2>Approval</h2>${f.approval ? `<p>In approval as <a href="#/approvals/${f.approval}">${f.approval}</a>.</p>`
        : `<p class="small muted">Routes by change type: ${esc(f.layer)} changes follow the approval policy.</p><button class="btn primary" data-act="toappr" data-busy="Routing…">Send to approvals</button>`}</div>
    </div></div>`);
  if (rw) rw.init();
  ACT.validate = btn => busy(btn, async () => { const r = await post(`/api/fix/${bid}/${fid}/validate`, { n: +$('#vn').value, sim_error: +$('#vs').value }); $('#val').innerHTML = validationHTML(r.validation); toast('Validation complete'); });
  ACT.deliver = el => busy(el, async () => {
    const r = await post(`/api/fix/${bid}/${fid}/deliver`, { method: el.dataset.m });
    const body = r.patch ? `<div class="small"><b>${esc(r.title)}</b><br><span class="mono">${esc(r.target)} · ${esc(r.branch)}</span></div><pre class="code" style="margin-top:8px">${diffColor(r.patch)}</pre>`
      : `<pre class="code">${esc(JSON.stringify(r.spec || r.payload || r.request || r.overlay, null, 2))}</pre>`;
    $('#deliv').innerHTML = `<div class="small" style="margin-bottom:6px"><b>${esc(r.method)}</b> artifact generated · logged to audit</div>${body}`;
  });
  ACT.toappr = btn => busy(btn, async () => { const a = await post(`/api/fix/${bid}/${fid}/approve-request`); toast(`${a.id} routed to ${a.approvers.map(x => x.role).join(', ')}`); refreshBoot(); location.hash = `#/approvals/${a.id}`; });
}
const diffColor = t => esc(t).split('\n').map(l => l.startsWith('+++') || l.startsWith('---') || l.startsWith('@@') ? `<span class="hdr">${l}</span>` : l.startsWith('+') ? `<span class="add">${l}</span>` : l.startsWith('-') ? `<span class="del">${l}</span>` : l).join('\n');

/* ------------------------------------------------------------------ approvals */
async function vApprovals() {
  crumbs([['Approvals']]);
  const d = await api('/api/approvals');
  const items = d.items.slice().sort((a, b) => (a.status === 'Waiting' ? 0 : 1) - (b.status === 'Waiting' ? 0 : 1));
  page(`${head('Approvals', 'Changes route to approvers by change type. Nothing ships without the required sign-offs and a passing regression gate.')}
    ${kpis([{ v: d.waiting, l: 'Waiting for a decision' }, { v: d.median_days != null ? `${d.median_days} d` : '—', l: 'Median time to decision' },
      { v: d.rolled_back_30d, l: 'Rolled back, last 30 days' }, { v: items.filter(a => a.status === 'Live').length, l: 'Live changes' }])}
    <div class="panel"><table><tr><th>Request</th><th>Change</th><th>Agent</th><th>Type</th><th>Risk</th><th>Waiting on</th><th class="num">Age</th><th>Status</th></tr>
    ${items.map(a => `<tr class="click" data-href="#/approvals/${a.id}"><td class="mono">${a.id}</td><td>${esc(a.title)}</td><td class="small">${esc(a.agent_name)}</td><td class="small">${esc(a.change_type)}</td>
      <td>${esc(a.risk)}</td><td>${esc(a.waiting_on || '—')}</td><td class="num">${a.age_days} d</td><td>${status(a.status)}</td></tr>`).join('')}</table></div>
    <div class="panel"><h2>Approval policy</h2><table><tr><th>Change type</th><th>Approvers</th><th>Rollout</th></tr>
      ${d.policy.map(p => `<tr><td>${esc(p.type)}</td><td>${p.approvers.map(esc).join(', ')}</td><td>${esc(p.rollout)}</td></tr>`).join('')}</table></div>`);
}

async function vApproval(cid) {
  const a = await api(`/api/approval/${cid}`);
  crumbs([['Approvals', '#/approvals'], [a.id]]);
  const pending = a.approvers.filter(x => x.status === 'Pending');
  const rw = replayWidget('rpa', { base: a.base_id, cand: a.harness_id });
  const ro = a.rollout;
  page(`${head(`${a.id} · ${esc(a.title)}`, `${status(a.status)} · ${esc(a.agent_name)} · ${esc(a.change_type)} · ${esc(a.risk)} risk`)}
    <div class="grid-main"><div>
      ${ro ? `<div class="panel"><div class="panel-head"><h2>Rollout</h2>${['Approved', 'Rolling out'].includes(a.status) ? '<button class="btn primary" data-act="advance" data-busy="Running stage…">Advance to next stage</button>' : ''}</div>
        <div class="stages">${ro.stages.map(s => `<div class="stage ${s.status.split(' ')[0]}"><b>${esc(s.name)}</b><div>${status(s.status)}</div>
          ${s.metrics ? `<div class="n">n=${s.metrics.n} · resolution <span class="${cls(s.metrics.delta)}">${pts(s.metrics.delta)}</span><br>violations ${pct(s.metrics.viol_cand, 2)}</div>` : ''}</div>`).join('')}</div></div>` : ''}
      <div class="panel"><div class="panel-head"><h2>What reviewers see: before and after</h2></div>${rw.html}</div>
      <div class="panel"><h2>Change</h2><ul style="padding-left:18px;margin:0">${a.edit_labels.map(l => `<li>${esc(l)}</li>`).join('') || '<li class="muted">No harness edits recorded</li>'}</ul>
        <div class="chips" style="margin-top:12px">${(a.layers || []).map(l => `<span class="badge purple">${esc(l)}</span>`).join('')}</div></div>
    </div><div>
      <div class="panel"><h2>Approvers</h2>${a.approvers.map(x => `<div class="approver"><div>${esc(x.role)}<div class="small muted">${x.by ? `${esc(x.by)} · ${esc(x.at)}` : 'Not yet reviewed'}</div></div>${status(x.status)}</div>`).join('')}
        ${pending.length && a.status === 'Waiting' ? `<div style="margin-top:14px" class="stack"><label class="field">Acting as<select id="role">${pending.map(x => `<option>${esc(x.role)}</option>`).join('')}</select></label>
          <textarea id="cmt" placeholder="Comment (optional)"></textarea>
          <div class="actions"><button class="btn primary" data-act="dec" data-d="approve">Approve</button><button class="btn" data-act="dec" data-d="changes">Request changes</button><button class="btn danger" data-act="dec" data-d="reject">Reject</button></div></div>` : ''}</div>
      <div class="panel"><h2>Automated checks</h2><div class="kv">
        <span class="k">Regression</span><span>${esc(a.checks.regression || '—')}</span><span class="k">Frozen lines</span><span>${esc(a.checks.frozen || '—')}</span>
        <span class="k">Judge health</span><span>${esc(a.checks.judge || '—')}</span><span class="k">Rollout</span><span>${esc(a.rollout_plan)}</span></div></div>
      ${a.comments.length ? `<div class="panel"><h2>Comments</h2>${a.comments.map(c => `<p><b>${esc(c.by)}</b> <span class="faint small">${esc(c.at)}</span><br>${esc(c.text)}</p>`).join('')}</div>` : ''}
    </div></div>`);
  rw.init();
  ACT.dec = el => busy(el, async () => { await post(`/api/approval/${cid}/decide`, { role: $('#role').value, decision: el.dataset.d, comment: $('#cmt').value }); toast('Decision recorded'); refreshBoot(); route(); });
  ACT.advance = btn => busy(btn, async () => { const r = await post(`/api/approval/${cid}/advance`); toast(r.status === 'Rolled back' ? 'Auto-rollback: guardrail metric breached' : r.status === 'Live' ? 'Promoted to production' : 'Stage passed'); route(); });
}

/* ------------------------------------------------------------------ experiments */
async function vExperiments() {
  crumbs([['Experiments']]);
  const [ex, cands] = await Promise.all([api(`/api/experiments?agent=${S.agent}`), api(`/api/candidates/${S.agent}`)]);
  const prodId = (cands.find(c => c.production) || {}).id;
  page(`${head('Experiments', 'Candidates compared on the same held-out scenarios with the same evaluators: paired bootstrap confidence intervals, Holm correction across candidates.')}
    <div class="panel"><table><tr><th>Experiment</th><th>Name</th><th class="num">Candidates</th><th class="num">Scenarios</th><th class="num">Seeds</th><th>Recommended</th><th>Run</th></tr>
      ${ex.length ? ex.slice().reverse().map(e => `<tr class="click" data-href="#/experiments/${e.id}"><td class="mono">${e.id}</td><td>${esc(e.name)}</td><td class="num">${e.candidates.length}</td><td class="num">${num(e.n)}</td>
        <td class="num">${e.seeds}</td><td class="mono small">${esc(e.recommended || '—')}</td><td class="small">${esc(e.created)}</td></tr>`).join('') : `<tr><td colspan="7">${empty('No experiments yet.')}</td></tr>`}</table></div>
    ${cands.length ? `<div class="panel"><h2>New experiment</h2><p class="small muted">The first selected harness is the baseline. Candidates found by the optimizer or RL trainer appear here automatically.</p>
      <div class="table-wrap"><table><tr><th></th><th>Harness</th><th>Changes vs production</th></tr>
      ${cands.map(c => `<tr><td><input type="checkbox" class="cand" value="${esc(c.id)}" ${c.id === prodId ? 'checked' : ''}></td><td>${esc(c.name)} ${c.production ? '<span class="badge good">production</span>' : ''} ${c.has_adapter ? '<span class="badge purple">adapter</span>' : ''}<div class="small mono faint">${esc(c.id)}</div></td>
        <td class="small">${c.edits_vs_prod.map(esc).join('<br>') || '—'}</td></tr>`).join('')}</table></div>
      <div class="form-grid" style="margin-top:14px"><label class="field">Held-out scenarios<select id="xn">${[400, 800, 1200, 2400].map(n => `<option ${n === 1200 ? 'selected' : ''}>${n}</option>`).join('')}</select></label>
        <label class="field">Sampling seeds<select id="xs">${[1, 2, 3, 5].map(n => `<option ${n === 3 ? 'selected' : ''}>${n}</option>`).join('')}</select></label>
        <label class="field">Simulated-customer error<select id="xe">${[0, 0.05, 0.1, 0.2].map(x => `<option value="${x}">${pct(x, 0)}</option>`).join('')}</select></label>
        <label class="field">Name<input type="text" id="xname" placeholder="Experiment name"></label></div>
      <button class="btn primary" data-act="runexp" data-busy="Running experiment…">Run experiment</button></div>` : ''}`);
  ACT.runexp = btn => busy(btn, async () => {
    const ids = $$('.cand:checked').map(c => c.value);
    const ordered = [prodId, ...ids.filter(i => i !== prodId)].filter(i => ids.includes(i));
    if (ordered.length < 2) throw new Error('Pick a baseline and at least one candidate.');
    const e = await post('/api/experiments', { agent: S.agent, candidates: ordered, n: +$('#xn').value, seeds: +$('#xs').value, sim_error: +$('#xe').value, name: $('#xname').value || undefined });
    location.hash = `#/experiments/${e.id}`;
  });
}

const COLORS = ['#8D88A0', '#0070AD', '#12ABDB', '#5A2A78', '#FF304C', '#178A55', '#C98500'];
async function vExperiment(eid) {
  const e = await api(`/api/experiment/${eid}`);
  crumbs([['Experiments', '#/experiments'], [e.id]]);
  const base = e.results[0];
  const rec = e.results.find(r => r.id === e.recommended);
  const rw = replayWidget('rpx', { base: base.id, cand: (rec || e.results[1]).id, theme: e.theme_id });
  page(`${head(`${e.id} · ${esc(e.name)}`, `${num(e.n)} held-out scenarios × ${e.seeds} seed${e.seeds > 1 ? 's' : ''} · baseline ${esc(base.name)}${e.sim_error ? ` · simulator error ${pct(e.sim_error, 0)}` : ''}${e.optimizer ? ` · optimizer explored ${e.optimizer.explored} candidates, ${pct(e.optimizer.budget_used, 0)} of budget` : ''}`)}
    ${rec ? `<div class="alert info"><div><b>Recommended: ${esc(rec.name)}.</b> Best reward among significant, policy-safe, harness-only candidates. Weight changes go through the separate model-risk path.</div>
      <button class="btn primary sm" data-act="promote" data-c="${esc(rec.id)}" data-busy="Routing…">Send to approvals</button></div>` : ''}
    <div class="panel table-wrap"><table><tr><th>Candidate</th><th class="num">Resolution (judge)</th><th class="num">Lift, 95% CI</th><th class="num">Holm p</th><th class="num">Human audit</th><th class="num">Violations</th><th class="num">Tokens</th><th class="num">P95</th><th class="num">Reward</th><th></th></tr>
      ${e.results.map((r, i) => { const m = r.metrics; return `<tr class="${r.id === e.recommended ? 'hl' : ''}"><td><span class="dot" style="background:${COLORS[i % 7]}"></span>${esc(r.name)}<div class="small faint">${esc(r.note || '')}${e.seeds > 1 ? ` · per-seed ${m.seed_res.map(x => pct(x)).join(', ')}` : ''}</div></td>
        <td class="num">${pct(m.resolution)}</td><td class="num">${r.lift ? `<span class="${cls(r.lift.diff)}">${pts(r.lift.diff)}</span><div class="small faint">${pts(r.lift.lo)} to ${pts(r.lift.hi)}</div>` : '<span class="faint">baseline</span>'}</td>
        <td class="num">${r.lift ? `${fx(r.lift.p_holm, 3)} ${r.significant ? '<span class="badge good">sig.</span>' : ''}` : ''}</td>
        <td class="num">${pct(m.gold)}${r.audit ? `<div class="small faint">${r.audit.confirmed}/${r.audit.sampled} judged-resolved confirmed</div>` : `<div class="small faint">${e.base_audit.confirmed}/${e.base_audit.sampled} confirmed</div>`}</td>
        <td class="num">${pct(m.violations, 2)}</td><td class="num">${num(m.tokens)}</td><td class="num">${fx(m.p95, 1)} s</td><td class="num">${fx(m.reward, 3)}</td>
        <td>${i ? `<button class="btn sm ghost" data-act="cmp" data-c="${esc(r.id)}">Compare</button>` : ''}</td></tr>`; }).join('')}</table></div>
    <div class="grid-2">
      <div class="panel"><h2>Quality against cost</h2>${scatter({ points: e.results.map((r, i) => ({ x: r.metrics.tokens, y: r.metrics.resolution, label: r.name.split(':')[0], color: COLORS[i % 7] })), xLabel: 'Tokens per task', yLabel: 'Resolution (judge)' })}</div>
      <div class="panel"><h2>Reward-hacking check</h2><p class="small muted">Judge lift should match the human-audited lift. A gap, or a jump in detailed closing summaries (which the judge over-rewards), means the candidate is optimizing the judge rather than the outcome.</p>
        <table><tr><th>Candidate</th><th class="num">Judge lift</th><th class="num">Audit lift</th><th class="num">Detailed summaries</th></tr>
        ${e.results.map(r => { const gap = r.lift ? r.lift.diff - r.gold_lift.diff : 0; const hack = r.metrics.detailed - base.metrics.detailed > 0.15 || gap > 0.03;
          return `<tr><td>${esc(r.name.split(':')[0])}</td><td class="num">${r.lift ? pts(r.lift.diff) : '—'}</td><td class="num">${r.gold_lift ? pts(r.gold_lift.diff) : '—'}</td><td class="num">${pct(r.metrics.detailed, 0)} ${hack ? '<span class="badge bad">check</span>' : ''}</td></tr>`; }).join('')}</table></div>
    </div>
    <div class="panel"><div class="panel-head"><h2>Before and after</h2><select id="cmpsel" data-change="cmpsel">${e.results.slice(1).map(r => `<option value="${esc(r.id)}" ${r.id === (rec || e.results[1]).id ? 'selected' : ''}>${esc(r.name)}</option>`).join('')}</select></div><div id="rpx-wrap">${rw.html}</div></div>`);
  rw.init();
  const swap = id => { const w = replayWidget('rpx', { base: base.id, cand: id, theme: e.theme_id }); $('#rpx-wrap').innerHTML = w.html; w.init(); $('#cmpsel').value = id; };
  ACT.cmpsel = el => swap(el.value);
  ACT.cmp = el => { swap(el.dataset.c); $('#rpx-wrap').scrollIntoView({ behavior: 'smooth' }); };
  ACT.promote = btn => busy(btn, async () => { const a = await post(`/api/experiment/${eid}/promote`, { candidate: btn.dataset.c }); refreshBoot(); location.hash = `#/approvals/${a.id}`; });
}

/* ------------------------------------------------------------------ optimizer & RL */
async function vOptimizer() {
  crumbs([['Optimizer & RL']]);
  const a = S.boot.agents.find(x => x.id === S.agent);
  if (!a.kind) { page(head('Optimizer & RL') + observeOnly(a)); return; }
  const cands = await api(`/api/candidates/${S.agent}`);
  const tab = S.query.get('tab') || 'search';
  const opts = cands.map(c => `<option value="${esc(c.id)}" ${c.production ? 'selected' : ''}>${esc(c.name)}${c.production ? ' (production)' : ''}</option>`).join('');
  const rlOK = a.level === '1p_repo';
  const f = (id, label, v, extra = '') => `<label class="field">${label}<input type="number" id="${id}" value="${v}" ${extra}></label>`;
  page(`${head('Optimizer & RL', 'Two ways to improve the agent from AI feedback: search over the harness (prompt, tools, gates), or fine-tune an adapter on the policy with reinforcement learning.')}
    <div class="tabs"><button class="${tab === 'search' ? 'on' : ''}" data-act="tab" data-t="search">Harness search</button><button class="${tab === 'rl' ? 'on' : ''}" data-act="tab" data-t="rl">RL fine-tune</button></div>
    <div class="grid-main"><div>
    ${tab === 'search' ? `<div class="panel"><h2>Reflective harness search</h2>
      <p class="small muted">GEPA-style loop: reflect on failing minibatch traces → propose one edit → minibatch filter → full evaluation → Pareto pool by scenario → occasional merge. Winner is chosen on a fresh split with Holm correction, then confirmed once on a third split. Frozen policy lines are never edited.</p>
      <div class="form-grid"><label class="field">Start from<select id="o_base">${opts}</select></label>
        ${f('o_budget', 'Rollout budget', 6000, 'step="1000" min="1000"')}${f('o_mb', 'Minibatch size', 40, 'min="10"')}${f('o_nopt', 'Optimization split', 200)}${f('o_nsel', 'Selection split', 300)}${f('o_nconf', 'Confirmation split', 600)}
        ${f('o_wres', 'Weight: resolution', 1.0, 'step="0.1"')}${f('o_wtok', 'Weight: tokens', 0.15, 'step="0.05"')}${f('o_wlat', 'Weight: latency', 0.05, 'step="0.05"')}${f('o_wemp', 'Weight: empathy', 0.0, 'step="0.1"')}
        ${f('o_eps', 'Exploration rate', 0.2, 'step="0.05" min="0" max="1"')}${f('o_topk', 'Finalists', 3, 'min="1" max="6"')}${f('o_seed', 'Seed', 1)}
        <label class="field">Simulated-customer error<select id="o_sim">${[0, 0.05, 0.1, 0.2].map(x => `<option value="${x}">${pct(x, 0)}</option>`).join('')}</select></label>
        <label class="field">Policy violations<select id="o_mode"><option value="constraint">Hard constraint</option><option value="penalty">Penalty in reward</option></select></label></div>
      <div class="actions" style="margin-bottom:14px"><label class="check"><input type="checkbox" id="o_merge" checked> Merge frontier candidates</label>
        <label class="check"><input type="checkbox" id="o_llm" ${S.boot.llm ? '' : 'disabled'}> LLM reflective proposer ${S.boot.llm ? '' : '<span class="faint small">(set ANTHROPIC_API_KEY)</span>'}</label></div>
      <button class="btn primary" data-act="runopt" data-busy="Starting…">Run optimizer</button></div>`
    : `<div class="panel"><h2>RL fine-tune on AI feedback</h2>
      ${rlOK ? '' : '<div class="alert warn">Weight changes need a first-party agent with repo access. Switch to the billing agent to run RL.</div>'}
      <p class="small muted">Trains an adapter on the agent's decision logits (the simulator's stand-in for a LoRA adapter) with a KL penalty to the reference policy. The AI judge has a verbosity bias, so watch the gap between judged and human-audited resolution.</p>
      <div class="form-grid"><label class="field">Reference harness<select id="r_base">${opts}</select></label>
        <label class="field">Algorithm<select id="r_algo"><option value="grpo">GRPO (group-relative)</option><option value="reinforce">REINFORCE + baseline</option><option value="dpo">DPO from AI preferences</option></select></label>
        <label class="field">Reward source<select id="r_src"><option value="judge">AI judge (RLAIF)</option><option value="verifiable">Verifiable end-state</option><option value="gold">Human labels (oracle)</option></select></label>
        ${f('r_iters', 'Iterations', 30, 'min="1" max="200"')}${f('r_batch', 'Prompts per iteration', 12)}${f('r_group', 'Group size (GRPO)', 4)}
        ${f('r_lr', 'Learning rate', 0.5, 'step="0.1"')}${f('r_kl', 'KL coefficient', 0.05, 'step="0.01"')}${f('r_beta', 'DPO β', 0.5, 'step="0.1"')}
        ${f('r_wtok', 'Weight: tokens', 0.05, 'step="0.05"')}${f('r_pb', 'Judge position bias', 0.08, 'step="0.02"')}${f('r_seed', 'Seed', 1)}
        <label class="field">Policy violations<select id="r_mode"><option value="constraint">Hard constraint</option><option value="penalty">Penalty in reward</option></select></label></div>
      <div class="actions" style="margin-bottom:14px"><label class="check"><input type="checkbox" id="r_swap" checked> Swap positions in pairwise judging (DPO)</label></div>
      <button class="btn primary" data-act="runrl" data-busy="Starting…" ${rlOK ? '' : 'disabled'}>Start training</button></div>`}
      <div id="jobview"></div>
    </div><div>
      <div class="panel"><h2>Recent runs</h2><div id="joblist" class="small muted">Loading…</div></div>
    </div></div>`);
  const v = id => +$(`#${id}`).value;
  ACT.tab = el => { location.hash = `#/optimizer?tab=${el.dataset.t}`; };
  ACT.runopt = btn => busy(btn, async () => {
    const j = await post('/api/optimizer/run', { agent: S.agent, base_id: $('#o_base').value, budget: v('o_budget'), minibatch: v('o_mb'), n_opt: v('o_nopt'), n_sel: v('o_nsel'), n_conf: v('o_nconf'),
      weights: { resolution: v('o_wres'), tokens: v('o_wtok'), latency: v('o_wlat'), empathy: v('o_wemp') }, epsilon: v('o_eps'), top_k: v('o_topk'), seed: v('o_seed'),
      sim_error: v('o_sim'), policy_mode: $('#o_mode').value, merge: $('#o_merge').checked, use_llm: $('#o_llm').checked });
    watchJob(j.id);
  });
  ACT.runrl = btn => busy(btn, async () => {
    const j = await post('/api/rl/run', { agent: S.agent, base_id: $('#r_base').value, algorithm: $('#r_algo').value, reward_source: $('#r_src').value, iterations: v('r_iters'),
      batch: v('r_batch'), group: v('r_group'), lr: v('r_lr'), kl_coef: v('r_kl'), beta: v('r_beta'), weights: { tokens: v('r_wtok') }, position_bias: v('r_pb'),
      swap_positions: $('#r_swap').checked, policy_mode: $('#r_mode').value, seed: v('r_seed') });
    watchJob(j.id);
  });
  ACT.openjob = el => watchJob(el.dataset.j);
  ACT.canceljob = el => post(`/api/jobs/${el.dataset.j}/cancel`).then(() => toast('Cancelling…'));
  ACT.jobexp = btn => busy(btn, async () => {
    const e = await post('/api/experiments', { agent: S.agent, candidates: [btn.dataset.base, btn.dataset.cand], n: 1200, seeds: 2, name: `Run ${btn.dataset.job}: ${btn.dataset.cand}` });
    location.hash = `#/experiments/${e.id}`;
  });
  ACT.jobcmp = el => { const w = replayWidget('rpj', { base: el.dataset.base, cand: el.dataset.cand }); $('#jobreplay').innerHTML = w.html; w.init(); $('#jobreplay').scrollIntoView({ behavior: 'smooth' }); };
  const list = async () => {
    const js = await api('/api/jobs');
    const el = $('#joblist'); if (!el) return;
    el.innerHTML = js.length ? js.map(j => `<div class="approver"><div><a href="#" data-act="openjob" data-j="${j.id}">${j.id}</a> · ${j.kind === 'rl' ? `RL ${esc((j.params.algorithm || 'grpo').toUpperCase())}` : 'Harness search'}<div class="faint">${j.params.agent} · ${j.elapsed}s</div></div>${status(j.status)}</div>`).join('') : 'No runs yet in this session.';
  };
  list(); S.timers.push(setInterval(list, 3000));
  const last = S.jobs[`${S.agent}:${tab}`]; if (last) watchJob(last);
}

function watchJob(id) {
  const tick = async () => {
    let j; try { j = await api(`/api/jobs/${id}`); } catch (e) { return; }
    S.jobs[`${j.params.agent}:${j.kind === 'rl' ? 'rl' : 'search'}`] = id;
    const el = $('#jobview'); if (!el) return;
    const keepReplay = $('#jobreplay')?.innerHTML || '';
    el.innerHTML = renderJob(j) + `<div id="jobreplay">${keepReplay}</div>`;
    if (j.status !== 'running') clearInterval(S.jobTimer);
  };
  clearInterval(S.jobTimer);
  tick(); S.jobTimer = setInterval(tick, 1000);
}

function renderJob(j) {
  const head_ = `<div class="panel-head"><h2>${j.id} · ${j.kind === 'rl' ? 'RL fine-tune' : 'Harness search'}</h2><div class="actions">${status(j.status)}${j.status === 'running' ? `<button class="btn sm" data-act="canceljob" data-j="${j.id}">Cancel</button>` : ''}</div></div>
    <div class="progress"><span style="width:${j.progress * 100}%"></span></div><div class="small muted" style="margin:6px 0 12px">${pct(j.progress, 0)} · ${j.elapsed}s${j.error ? ` · <span class="neg">${esc(j.error)}</span>` : ''}</div>`;
  const log = `<div class="log" aria-live="polite">${j.logs.slice(-60).map(l => `<div><span class="t">${fx(l.t, 1)}s</span>${esc(l.msg)}</div>`).join('')}</div>`;
  return `<div class="panel">${head_}${j.kind === 'rl' ? rlBody(j) : optBody(j)}<h3 style="margin:16px 0 8px">Log</h3>${log}</div>`;
}

function optBody(j) {
  const snap = j.result || j.snapshot;
  if (!snap) return '';
  const pool = snap.pool.slice().sort((a, b) => b.reward - a.reward);
  let out = `<div class="kv" style="margin-bottom:12px"><span class="k">Rollouts used</span><span>${num(snap.used)} of ${num(snap.budget)}</span><span class="k">Candidates explored</span><span>${snap.explored} (${snap.rejected.length} rejected at minibatch)</span></div>
    <div class="table-wrap"><table><tr><th>Candidate</th><th>Parent</th><th>Edits from production</th><th class="num">Reward</th><th class="num">Judge</th><th class="num">Human audit</th><th class="num">Tokens</th><th>Frontier</th></tr>
    ${pool.slice(0, 12).map(c => `<tr><td class="mono">${c.id}</td><td class="mono faint">${c.parent || '—'}</td><td class="small">${c.edits.map(esc).join('<br>') || 'Seed'}${c.detailed > 0.4 ? ' <span class="badge bad">verbose</span>' : ''}</td>
      <td class="num">${fx(c.reward, 3)}</td><td class="num">${pct(c.resolution)}</td><td class="num">${pct(c.gold)}</td><td class="num">${num(c.tokens)}</td><td>${c.frontier ? '<span class="badge good">Pareto</span>' : ''}</td></tr>`).join('')}</table></div>`;
  if (j.result) {
    const r = j.result;
    if (r.selection.length) out += `<h3 style="margin:16px 0 8px">Selection on a fresh split</h3><table><tr><th>Finalist</th><th class="num">Reward</th><th class="num">Lift</th><th class="num">p</th><th class="num">Holm p</th></tr>
      ${r.selection.map(s => `<tr class="${r.best && s.id === r.best.id ? 'hl' : ''}"><td class="mono">${s.id}</td><td class="num">${fx(s.reward, 3)}</td><td class="num ${cls(s.lift)}">${sign(s.lift, 3)}</td><td class="num">${fx(s.p, 3)}</td><td class="num">${fx(s.p_holm, 3)}</td></tr>`).join('')}</table>`;
    if (r.best && r.confirmation) {
      const c = r.confirmation, gap = c.resolution.diff - c.gold.diff;
      out += `<div class="alert ${gap > 0.02 ? 'warn' : 'info'}" style="margin-top:14px"><div><b>${esc(r.best.name)}</b> confirmed on ${num(c.n)} new scenarios: judge ${pts(c.resolution.diff)} (${pts(c.resolution.lo)} to ${pts(c.resolution.hi)}), human audit ${pts(c.gold.diff)}, tokens ${sign(100 * (c.cand.tokens - c.base.tokens) / c.base.tokens)}%.
        ${gap > 0.02 ? ' The judge lift exceeds the audited lift — inspect for reward hacking.' : ''}</div></div>
        <div class="actions"><button class="btn primary" data-act="jobexp" data-job="${j.id}" data-base="${esc(j.params.base_id)}" data-cand="${esc(r.best.id)}" data-busy="Running experiment…">Run as experiment</button>
        <button class="btn" data-act="jobcmp" data-base="${esc(j.params.base_id)}" data-cand="${esc(r.best.id)}">Compare conversations</button></div>`;
    }
  }
  return out;
}

function rlBody(j) {
  const snap = j.result || j.snapshot;
  if (!snap) return '';
  const cv = snap.curve, held = snap.held;
  const heldAt = it => held.find(h => h.it === it);
  const labels = cv.map(p => p.it);
  let out = `<h3 style="margin-bottom:6px">Training signal vs held-out outcome</h3>${lineChart({
    series: [{ name: 'Train reward', color: '#0070AD', values: cv.map(p => p.reward) },
      { name: 'Held-out judge resolution', color: '#12ABDB', values: labels.map(i => heldAt(i)?.resolution ?? null), dots: true },
      { name: 'Held-out human audit', color: '#FF304C', values: labels.map(i => heldAt(i)?.gold ?? null), dots: true, dash: '5 4' }],
    labels, yFmt: v => fx(v, 2), height: 230 })}
    <div class="grid-2" style="margin-top:10px"><div><h3 style="margin-bottom:6px">KL to reference</h3>${lineChart({ series: [{ name: 'KL', color: '#5A2A78', values: cv.map(p => p.kl) }], labels, yFmt: v => fx(v, 3), yMin: 0, height: 150 })}</div>
    <div><h3 style="margin-bottom:6px">Detailed closing summaries</h3>${lineChart({ series: [{ name: 'Detailed', color: '#C98500', values: cv.map(p => p.detailed) }], labels, yMin: 0, height: 150 })}</div></div>`;
  if (j.result) {
    const r = j.result;
    if (r.warning) out += `<div class="alert warn" style="margin-top:12px">${esc(r.warning)}</div>`;
    out += `<h3 style="margin:16px 0 8px">Policy before and after training</h3><div class="table-wrap"><table><tr><th>Decision</th><th>Action</th><th class="num">Before</th><th class="num">After</th></tr>
      ${r.policy.map(d => d.actions.map((a, i) => `<tr>${i === 0 ? `<td rowspan="${d.actions.length}">${esc(d.label)}</td>` : ''}<td>${esc(a.label)}</td><td class="num">${pct(a.before)}</td><td class="num ${cls(a.after - a.before)}">${pct(a.after)}</td></tr>`).join('')).join('')}</table></div>
      <div class="actions" style="margin-top:14px"><span class="small">Registered as <b>${esc(r.candidate.name)}</b></span>
        <button class="btn primary" data-act="jobexp" data-job="${j.id}" data-base="${esc(j.params.base_id)}" data-cand="${esc(r.candidate.id)}" data-busy="Running experiment…">Run as experiment</button>
        <button class="btn" data-act="jobcmp" data-base="${esc(j.params.base_id)}" data-cand="${esc(r.candidate.id)}">Compare conversations</button></div>`;
  }
  return out;
}

/* ------------------------------------------------------------------ regression suites */
async function vRegression() {
  crumbs([['Regression suites']]);
  const a = S.boot.agents.find(x => x.id === S.agent);
  if (!a.kind) { page(head('Regression suites') + observeOnly(a)); return; }
  const [suites, themes, cands] = await Promise.all([api(`/api/suites?agent=${S.agent}`), api(`/api/themes/${S.agent}`), api(`/api/candidates/${S.agent}`)]);
  const su = await api(`/api/suite/${suites[0].id}`);
  const pre = S.query.get('theme');
  S.suiteRun = S.suiteRun && S.suiteRun.suite === su.id ? S.suiteRun : null;
  const res = S.suiteRun ? Object.fromEntries(S.suiteRun.results.map(r => [r.id, r.pass])) : {};
  page(`${head('Regression suites', 'Failure traces become permanent tests. Every harness change is replayed against the suite before it can ship.')}
    <div class="grid-main"><div>
      <div class="panel"><div class="panel-head"><div><h2 class="mono">${esc(su.name)}</h2><div class="small muted">${su.tests.length} tests · ${su.tests.filter(t => t.holdout).length} held out · ${esc(su.runs_in)}</div></div>
        <div class="actions"><select id="runh">${cands.map(c => `<option value="${esc(c.id)}" ${c.production ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}</select>
        <label class="check small"><input type="checkbox" id="runho"> Include holdout</label><button class="btn primary sm" data-act="runsuite" data-busy="Replaying suite…">Run suite</button></div></div>
        ${S.suiteRun ? `<div class="alert ${S.suiteRun.gate_ok ? 'info' : 'bad'}"><div><b>${S.suiteRun.gate_ok ? 'Gate passes' : 'Gate blocks release'}</b> for ${esc(S.suiteRun.name)}: ${S.suiteRun.passed}/${S.suiteRun.total} pass (${pct(S.suiteRun.rate)}), policy tests ${S.suiteRun.policy_ok ? 'all pass' : 'failing'}.</div></div>` : ''}
        <div class="table-wrap" style="max-height:560px;overflow:auto"><table><tr><th>Test</th><th>Scenario</th><th>Expected behaviour</th><th>Check</th><th>Flags</th><th>Result</th></tr>
        ${su.tests.slice().reverse().map(t => `<tr><td class="mono">${t.id}</td><td>${esc(t.scenario)}<div class="small faint">seed ${t.seed}</div></td><td>${esc(t.expected)}</td><td class="small">${esc(t.check)}</td>
          <td>${t.holdout ? '<span class="badge">holdout</span>' : ''}${t.synthetic ? '<span class="badge purple">synthetic</span>' : ''}${t.status === 'Draft' ? status('Draft') : ''}</td>
          <td>${t.id in res ? (res[t.id] ? '<span class="pos">Pass</span>' : '<span class="neg">Fail</span>') : '<span class="faint">—</span>'}</td></tr>`).join('')}</table></div></div>
    </div><div>
      <div class="panel"><h2>Release gate</h2>
        <label class="field">Minimum pass rate<input type="number" id="gmin" value="${su.gate.min_pass * 100}" min="50" max="100" step="1"></label>
        <label class="check" style="margin:10px 0"><input type="checkbox" id="gpol" ${su.gate.policy_all ? 'checked' : ''}> Every policy test must pass</label>
        <p class="small muted">Changing the gate requires AI Governance sign-off and is written to the audit log.</p>
        <button class="btn sm" data-act="gate">Save gate</button></div>
      <div class="panel" id="convert"><h2>Convert a theme to tests</h2>
        <label class="field">Failure theme<select id="cth">${themes.map(t => `<option value="${t.id}" ${t.id === pre ? 'selected' : ''}>${esc(t.name)} (${t.traces})</option>`).join('')}</select></label>
        <div class="form-grid" style="margin-top:10px"><label class="field">Maximum tests<input type="number" id="cmax" value="64" min="5" max="200"></label>
        <label class="field">Holdout share<input type="number" id="cho" value="20" min="0" max="50"></label></div>
        <label class="check"><input type="checkbox" id="csyn" checked> Add synthetic variations (20%)</label>
        <label class="check" style="margin:6px 0 12px"><input type="checkbox" id="cred" checked> Redact customer PII</label>
        <button class="btn primary sm" data-act="preview" data-busy="Deduplicating…">Preview tests</button>
        <div id="cprev" style="margin-top:12px"></div></div>
    </div></div>`);
  if (pre) $('#convert').scrollIntoView();
  ACT.runsuite = btn => busy(btn, async () => { S.suiteRun = { ...(await post(`/api/suite/${su.id}/run`, { harness_id: $('#runh').value, include_holdout: $('#runho').checked })), name: $('#runh').selectedOptions[0].textContent }; route(); });
  ACT.gate = () => post(`/api/suite/${su.id}/gate`, { min_pass: +$('#gmin').value / 100, policy_all: $('#gpol').checked }).then(() => toast('Gate saved · AI Governance sign-off requested'));
  const conv = commit => post(`/api/theme/${$('#cth').value}/convert`, { max_tests: +$('#cmax').value, holdout: +$('#cho').value / 100, synthetic: $('#csyn').checked, redact: $('#cred').checked, commit });
  ACT.preview = btn => busy(btn, async () => {
    const r = await conv(false);
    $('#cprev').innerHTML = `<p class="small">${r.evidence} evidence traces → <b>${r.tests.length} tests</b> (${r.tests.filter(t => t.synthetic).length} synthetic, ${r.tests.filter(t => t.holdout).length} holdout). They fail on production by construction and should pass once the fix ships.</p>
      <div style="max-height:220px;overflow:auto"><table>${r.tests.slice(0, 40).map(t => `<tr><td class="mono small">${t.id}</td><td class="small">${esc(t.expected)}</td></tr>`).join('')}</table></div>
      <button class="btn primary sm" style="margin-top:10px" data-act="commit" data-busy="Creating…">Create ${r.tests.length} tests</button>`;
  });
  ACT.commit = btn => busy(btn, async () => { const r = await conv(true); toast(`${r.tests.length} tests added to ${r.suite}`); S.suiteRun = null; route(); });
}

/* ------------------------------------------------------------------ evidence explorer */
async function vTraces() {
  crumbs([['Evidence explorer']]);
  const a = S.boot.agents.find(x => x.id === S.agent);
  if (!a.kind) { page(head('Evidence explorer') + observeOnly(a)); return; }
  const th = S.query.get('theme') || '', flt = S.query.get('filter') || 'flagged', off = +(S.query.get('offset') || 0);
  const [themes, d] = await Promise.all([api(`/api/themes/${S.agent}`), api(`/api/traces/${S.agent}?limit=50&offset=${off}${th ? `&theme=${th}` : ''}${flt !== 'all' ? `&filter=${flt}` : ''}`)]);
  const q = (k, v) => { const p = new URLSearchParams(S.query); p.set(k, v); if (k !== 'offset') p.delete('offset'); return `#/traces?${p}`; };
  page(`${head('Evidence explorer', 'Every production trace with its evaluator verdicts, outcome signals and span timeline.')}
    <div class="panel"><div class="actions" style="margin-bottom:12px">
      <select data-change="fth"><option value="">All themes</option>${themes.map(t => `<option value="${t.id}" ${t.id === th ? 'selected' : ''}>${esc(t.name)}</option>`).join('')}</select>
      <div class="seg">${[['flagged', 'Flagged'], ['judge_fail', 'Judge fail'], ['repeat', 'Repeat contact'], ['unlabeled', 'Unlabeled'], ['all', 'All']].map(([k, l]) => `<button class="${k === flt ? 'on' : ''}" data-act="flt" data-f="${k}">${l}</button>`).join('')}</div>
      <span class="muted small">${num(d.total)} traces</span></div>
      ${traceTable(d.items)}
      <div class="actions" style="margin-top:12px;justify-content:flex-end">${off > 0 ? `<a class="btn sm" href="${q('offset', Math.max(0, off - 50))}">Newer</a>` : ''}${off + 50 < d.total ? `<a class="btn sm" href="${q('offset', off + 50)}">Older</a>` : ''}</div></div>`);
  ACT.fth = el => { location.hash = q('theme', el.value); };
  ACT.flt = el => { location.hash = q('filter', el.dataset.f); };
}

async function vTrace(tid) {
  const t = await api(`/api/trace/${tid}`);
  crumbs([['Evidence explorer', '#/traces'], [tid]]);
  const cands = await api(`/api/candidates/${t.agent}`);
  const ev = t.evaluators, res = ev.resolution;
  const total = Math.max(...t.spans.map(s => s.start + s.dur));
  const alt = cands.filter(c => c.id !== t.harness);
  page(`${head(`<span class="mono">${tid}</span>`, `${esc(t.label)} · ${esc(t.version)} · ${t.date} ${t.time}${t.theme_name ? ` · <a href="#/themes/${t.theme_id}">${esc(t.theme_name)}</a>` : ''}`,
    `<button class="btn sm" data-act="tosuite">Add to regression suite</button>`)}
    <div class="grid-main"><div>
      <div class="panel"><h2>Conversation</h2><div class="msgs" style="max-width:640px">${t.messages.map(m => msgHTML(m)).join('')}</div></div>
      <div class="panel"><h2>Span timeline</h2><div class="timeline">${t.spans.map(s => `<div class="span-row"><span class="mono small">${esc(s.name)}</span><div class="track"><span class="${s.kind}" style="left:${100 * s.start / total}%;width:${Math.max(0.8, 100 * s.dur / total)}%"></span></div><span class="num small">${fx(s.dur)} s</span></div>`).join('')}</div>
        <p class="small muted" style="margin-top:8px">${fx(t.latency, 1)} s agent time · ${num(t.tokens)} tokens</p></div>
      <div class="panel"><div class="panel-head"><h2>Replay with another harness</h2><select id="altsel" data-change="alt">${alt.map(c => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('')}</select></div><div id="trp"></div></div>
    </div><div>
      <div class="panel"><h2>Evaluators</h2>
        <div class="approver"><div>Resolution judge<div class="small muted">${esc(res.rationale)}</div></div>${res.pass ? '<span class="badge good">Pass</span>' : '<span class="badge bad">Fail</span>'}</div>
        ${Object.entries(res.criteria).map(([k, v]) => `<div class="small" style="padding:3px 0 3px 12px"><span class="dot ${v ? 'good' : 'bad'}"></span>${esc(S.boot.library.criteria[k])}</div>`).join('')}
        <div class="approver"><div>Policy adherence<div class="small muted">${esc(ev.policy.detail)}</div></div>${ev.policy.pass ? '<span class="badge good">Pass</span>' : '<span class="badge bad">Fail</span>'}</div>
        <div class="approver"><div>Tool-sequence check<div class="small muted">${esc(ev.tool_sequence.detail)}</div></div>${ev.tool_sequence.anomaly ? '<span class="badge bad">Anomaly</span>' : '<span class="badge good">OK</span>'}</div>
        <div class="approver"><div>Empathy and tone</div>${ev.empathy.pass ? '<span class="badge good">Pass</span>' : '<span class="badge bad">Fail</span>'}</div>
        <div class="approver"><div>Repeat contact 72h</div>${ev.outcome.repeat_contact ? `<span class="badge bad">${ev.outcome.repeat_hours} h</span>` : '<span class="badge good">None</span>'}</div>
        <div class="approver"><div>CSAT</div><span>${ev.outcome.csat}</span></div></div>
      <div class="panel"><h2>Human label</h2><p class="small muted">Labels feed the judge calibration set.</p>
        ${t.human ? `<p>Labeled: <b>${esc(t.human)}</b></p>` : ''}
        <div class="actions">${['Confirmed failure', 'Not a failure', 'Unsure'].map(v => `<button class="btn sm" data-act="label" data-v="${v}">${v}</button>`).join('')}</div></div>
      <div class="panel"><h2>Agent decisions</h2><table>${t.decisions.map(d => `<tr><td class="small">${esc(S.boot.decisions[d.d])}</td><td class="small">${esc(S.boot.actions[d.a])}</td><td class="num small faint">p=${fx(d.p[d.a])}</td></tr>`).join('')}</table></div>
    </div></div>`);
  const load = id => { if (!id) { $('#trp').innerHTML = empty('No other harness for this agent yet.'); return; } const w = replayWidget('rpt', { base: t.harness, cand: id, traceId: tid }); $('#trp').innerHTML = w.html; w.init(); };
  load(alt.length ? (alt.find(c => c.id.endsWith('-B')) || alt[alt.length - 1]).id : null);
  if ($('#altsel') && alt.length) $('#altsel').value = (alt.find(c => c.id.endsWith('-B')) || alt[alt.length - 1]).id;
  ACT.alt = el => load(el.value);
  ACT.label = el => post(`/api/trace/${tid}/label`, { verdict: el.dataset.v }).then(() => { toast('Label saved to calibration set'); route(); });
  ACT.tosuite = el => busy(el, async () => { const r = await post(`/api/trace/${tid}/to-suite`); toast(`Added as ${r.id}`); });
}

/* ------------------------------------------------------------------ evaluator health */
async function vEvaluators() {
  crumbs([['Evaluator health']]);
  const a = S.boot.agents.find(x => x.id === S.agent);
  if (!a.kind) { page(head('Evaluator health') + observeOnly(a)); return; }
  const d = await api(`/api/evaluators/${S.agent}`);
  const bad = d.items.filter(e => e.status !== 'Healthy');
  page(`${head('Evaluator health', `Judges are checked against human labels every week. Below κ ${fx(d.threshold)} a judge stops being used as an optimization reward until it is recalibrated.`)}
    ${bad.map(e => `<div class="alert ${e.status === 'Drifting' ? 'warn' : 'bad'}"><div><b>${esc(e.name)}</b> is ${e.status === 'Drifting' ? 'drifting' : 'below threshold'} (κ ${fx(e.kappa)}). ${e.role === 'Optimization paused' ? 'Optimization against it is paused.' : ''}
      ${e.id === 'resolution' && S.agent === 'outage' ? 'This judge cannot see whether a stated ETA was correct, so it over-passes ETA sessions; the tool-sequence check covers that gap.' : ''}</div>
      <button class="btn sm" data-act="recal" data-e="${e.id}" data-busy="Recalibrating…">Recalibrate</button></div>`).join('')}
    <div class="panel"><table><tr><th>Evaluator</th><th>Type</th><th class="num">Cohen's κ vs humans</th><th>Last 7 weeks</th><th>Status</th><th>Used as</th><th></th></tr>
      ${d.items.map(e => `<tr><td>${esc(e.name)}${e.criteria ? `<div class="small faint">${e.criteria.length} rubric criteria</div>` : ''}</td><td>${esc(e.type)}</td><td class="num">${e.kappa == null ? '<span class="faint">n/a</span>' : fx(e.kappa)}</td>
        <td>${spark(e.history, e.status === 'Healthy' ? '#0070AD' : '#FF304C', 110, 26, d.threshold)}</td><td>${status(e.status)}</td><td>${esc(e.role)}</td>
        <td>${e.kappa != null ? `<button class="btn sm ghost" data-act="recal" data-e="${e.id}" data-busy="…">Recalibrate</button>` : ''}</td></tr>`).join('')}</table></div>
    <div class="grid-2">
      <div class="panel"><h2>Calibration set</h2><div class="kv"><span class="k">Human-labeled sessions</span><span>${num(d.calibration.size)}</span>
        <span class="k">Added weekly</span><span>${d.calibration.weekly}</span><span class="k">Reserved as holdout</span><span>${pct(d.calibration.reserved, 0)}</span></div>
        <p class="small muted" style="margin-top:10px">Judges never see holdout labels. Recalibration updates rubric thresholds and few-shot examples, then re-measures κ on the holdout.</p></div>
      <div class="panel"><div class="panel-head"><h2>Labeling queue</h2><span class="small muted">${num(d.queue_total)} sessions near the judge's decision boundary</span></div>
        <table>${d.queue.slice(0, 10).map(t => `<tr><td class="mono small"><a href="#/traces/${t.id}">${t.id}</a></td><td class="small">${esc(t.label)}</td><td class="num small">${fx(t.judged_score)}</td>
          <td class="nowrap">${['Confirmed failure', 'Not a failure'].map(v => `<button class="btn sm ghost" data-act="qlabel" data-t="${t.id}" data-v="${v}">${v === 'Confirmed failure' ? 'Failure' : 'Fine'}</button>`).join('')}</td></tr>`).join('')}</table></div>
    </div>`);
  ACT.recal = btn => busy(btn, async () => { await post(`/api/evaluators/${S.agent}/${btn.dataset.e}/recalibrate`); toast('Recalibrated and re-measured on the holdout'); route(); });
  ACT.qlabel = el => post(`/api/trace/${el.dataset.t}/label`, { verdict: el.dataset.v }).then(() => { el.closest('tr').remove(); toast('Label saved'); });
}

/* ------------------------------------------------------------------ patterns */
async function vPatterns() {
  crumbs([['Pattern library']]);
  const d = await api('/api/patterns');
  const agents = S.boot.agents;
  page(`${head('Pattern library', 'Fixes proven on one agent, packaged so other agents with the same failure signature can test them.')}
    ${kpis([{ v: d.stats.proven, l: 'Proven patterns' }, { v: d.stats.agents_using, l: 'Agents using a pattern' }, { v: d.stats.registered, l: 'Registered agents' }, { v: d.stats.open_matches, l: 'Untested matches' }])}
    ${d.items.map(p => `<div class="panel"><div class="panel-head"><div><h2>${esc(p.name)}</h2><div class="small muted">${p.id} · ${esc(p.layer)} · proven on ${esc(p.proven_on_name)}${p.lift ? ` · ${esc(p.lift)}` : ''}${p.note ? ` · ${esc(p.note)}` : ''}</div></div></div>
      ${p.edit_labels.length ? `<ul class="small" style="margin:0 0 12px;padding-left:18px">${p.edit_labels.map(l => `<li>${esc(l)}</li>`).join('')}</ul>` : '<p class="small muted">Context and memory change: not representable in the simulated harness.</p>'}
      <table><tr><th>Candidate agent</th><th>Integration</th><th>Result</th><th></th></tr>
      ${agents.filter(a => a.id !== p.proven_on).map(a => { const r = p.tests[a.id]; const match = p.matches.includes(a.id);
        return `<tr><td>${esc(a.name)} ${match ? '<span class="badge info">same signature</span>' : ''}</td><td class="small">${esc(a.integration)}</td>
          <td class="small">${r ? (r.status === 'tested' ? `<span class="${cls(r.lift)}">${pts(r.lift)}</span> resolution (${pts(r.lo)} to ${pts(r.hi)})` : `<span class="muted">${esc(r.message)}</span>`) : '<span class="faint">Not tested</span>'}</td>
          <td><button class="btn sm" data-act="ptest" data-p="${p.id}" data-a="${a.id}" data-busy="Testing…">Test</button></td></tr>`; }).join('')}</table></div>`).join('')}`);
  ACT.ptest = btn => busy(btn, async () => { const r = await post(`/api/pattern/${btn.dataset.p}/test`, { target: btn.dataset.a }); toast(r.message); route(); });
}

/* ------------------------------------------------------------------ agents */
async function vAgents() {
  crumbs([['Agents & connections']]);
  const d = await api('/api/agents');
  page(`${head('Agents & connections', 'What the engine can do depends on how each agent is connected. Third-party agents get recommendations and vendor change requests; first-party agents can get pull requests and weight updates.')}
    <div class="panel"><table><tr><th>Agent</th><th>Type</th><th>Integration</th><th>Owner</th><th class="num">Traffic</th><th>Production</th><th class="num">Traces</th></tr>
      ${d.items.map(a => `<tr><td>${esc(a.name)}${a.repo ? `<div class="small mono faint">${esc(a.repo)}</div>` : ''}${a.vendor ? `<div class="small faint">Vendor ${esc(a.vendor)}</div>` : ''}</td><td>${esc(a.type)}</td><td>${esc(a.integration)}</td><td>${esc(a.owner)}</td>
        <td class="num">${esc(a.traffic)}</td><td class="mono">${esc(a.production || '—')}</td><td class="num">${num(a.traces)}</td></tr>`).join('')}</table></div>
    <div class="grid-main"><div class="panel"><h2>Capability by integration level</h2><div class="table-wrap"><table><tr><th>Capability</th>${d.levels.map(l => `<th>${esc(l[1])}</th>`).join('')}</tr>
      ${d.capabilities.map(c => `<tr><td>${esc(c.name)}</td>${c.values.map(v => `<td>${v === 'Yes' ? '<span class="badge good">Yes</span>' : v === 'No' ? '<span class="badge">No</span>' : '<span class="badge warn">Partial</span>'}</td>`).join('')}</tr>`).join('')}</table></div></div>
    <div class="panel"><h2>Register an agent</h2><div class="stack">
      <label class="field">Name<input type="text" id="an" placeholder="e.g. Fios Install Scheduler"></label>
      <label class="field">Type<select id="at"><option>First-party</option><option>Third-party</option></select></label>
      <label class="field">Integration<select id="al">${d.levels.map(l => `<option value="${l[0]}">${esc(l[1])}</option>`).join('')}</select></label>
      <label class="field">Owner<input type="text" id="ao"></label><label class="field">Weekly traffic<input type="text" id="atr" placeholder="e.g. 40K / wk"></label>
      <button class="btn primary" data-act="reg">Register agent</button></div></div></div>`);
  ACT.reg = btn => busy(btn, async () => { if (!$('#an').value) throw new Error('Give the agent a name.'); await post('/api/agents', { name: $('#an').value, type: $('#at').value, level: $('#al').value, owner: $('#ao').value, traffic: $('#atr').value }); await refreshBoot(); toast('Agent registered'); route(); });
}

/* ------------------------------------------------------------------ audit */
async function vAudit() {
  crumbs([['Audit log']]);
  const actor = S.query.get('actor') || '', q = S.query.get('q') || '';
  const d = await api(`/api/audit?${actor ? `actor=${encodeURIComponent(actor)}&` : ''}${q ? `q=${encodeURIComponent(q)}` : ''}`);
  page(`${head('Audit log', 'Append-only and hash-chained: every entry carries the SHA-256 of the one before it, so any edit breaks the chain.',
    `<button class="btn" data-act="verify" data-busy="Verifying…">Verify chain</button><a class="btn" href="/api/audit/export">Export JSONL</a>`)}
    <div id="vres"></div>
    <div class="panel"><div class="actions" style="margin-bottom:12px"><select data-change="actor"><option value="">All actors</option>${d.actors.map(a => `<option ${a === actor ? 'selected' : ''}>${esc(a)}</option>`).join('')}</select>
      <input type="text" id="aq" placeholder="Search events, objects, details" value="${esc(q)}" style="min-width:280px"><button class="btn sm" data-act="search">Search</button>
      ${q || actor ? '<a class="btn sm ghost" href="#/audit">Clear</a>' : ''}<span class="small muted">${d.items.length} entries</span></div>
      <div class="table-wrap"><table><tr><th>Time</th><th>Actor</th><th>Event</th><th>Object</th><th>Detail</th><th>Hash</th></tr>
      ${d.items.map(r => `<tr><td class="nowrap small">${esc(r.time)}</td><td>${esc(r.actor)}</td><td>${esc(r.event)}</td><td><a class="mono small" href="#/audit?q=${encodeURIComponent(r.obj)}">${esc(r.obj)}</a></td>
        <td class="small">${esc(r.detail)}</td><td class="mono small faint" title="prev ${esc(r.prev)}">${r.hash.slice(0, 10)}…</td></tr>`).join('')}</table></div></div>`);
  ACT.actor = el => { location.hash = `#/audit?actor=${encodeURIComponent(el.value)}`; };
  ACT.search = () => { location.hash = `#/audit?q=${encodeURIComponent($('#aq').value)}`; };
  ACT.verify = btn => busy(btn, async () => { const r = await api('/api/audit/verify'); $('#vres').innerHTML = `<div class="alert ${r.ok ? 'info' : 'bad'}">${r.ok ? `Chain intact: ${r.entries} entries, head <span class="mono">${r.head.slice(0, 16)}…</span>` : `Chain broken at entry ${r.broken_at}`}</div>`; });
}

/* ================================================================== shell */
const NAV = [['overview', 'Overview'], ['themes', 'Failure themes'], ['fixes', 'Fix bundles'], ['approvals', 'Approvals'], ['experiments', 'Experiments'],
  ['optimizer', 'Optimizer & RL'], ['sep'], ['regression', 'Regression suites'], ['traces', 'Evidence explorer'], ['evaluators', 'Evaluator health'],
  ['patterns', 'Pattern library'], ['agents', 'Agents & connections'], ['audit', 'Audit log']];
const ROUTES = [[/^overview$/, vOverview], [/^themes$/, vThemes], [/^themes\/(.+)$/, vTheme], [/^fixes$/, vFixes], [/^fixes\/([^/]+)\/([^/]+)$/, vFix],
  [/^approvals$/, vApprovals], [/^approvals\/(.+)$/, vApproval], [/^experiments$/, vExperiments], [/^experiments\/(.+)$/, vExperiment],
  [/^optimizer$/, vOptimizer], [/^regression$/, vRegression], [/^traces$/, vTraces], [/^traces\/(.+)$/, vTrace], [/^evaluators$/, vEvaluators],
  [/^patterns$/, vPatterns], [/^agents$/, vAgents], [/^audit$/, vAudit]];

function renderNav(section) {
  $('#nav').innerHTML = NAV.map(([k, l]) => k === 'sep' ? '<li class="sep" role="separator"></li>'
    : `<li><a href="#/${k}" class="${k === section ? 'active' : ''}" ${k === section ? 'aria-current="page"' : ''}><span>${l}</span>${k === 'approvals' && S.boot?.waiting ? `<span class="count">${S.boot.waiting}</span>` : ''}</a></li>`).join('');
}

async function route() {
  S.timers.forEach(clearInterval); S.timers = []; clearInterval(S.jobTimer); ACT = {};
  const h = location.hash.replace(/^#\/?/, '') || 'overview';
  const [path, qs] = h.split('?');
  S.query = new URLSearchParams(qs || '');
  renderNav(path.split('/')[0]);
  page('<div class="loading">Loading…</div>');
  for (const [re, fn] of ROUTES) {
    const m = path.match(re);
    if (m) {
      try { await fn(...m.slice(1).map(decodeURIComponent)); }
      catch (e) { page(`<div class="alert bad"><div>${esc(e.message)}</div><a class="btn sm" href="#/overview">Go to overview</a></div>`); }
      $('#main').focus({ preventScroll: true });
      return;
    }
  }
  location.hash = '#/overview';
}

async function refreshBoot() {
  S.boot = await api('/api/bootstrap');
  const sel = $('#agent');
  sel.innerHTML = S.boot.agents.map(a => `<option value="${a.id}" ${a.id === S.agent ? 'selected' : ''}>${esc(a.name)}</option>`).join('');
  $('#llm-state').textContent = S.boot.llm ? 'LLM proposer: connected' : 'LLM proposer: off (simulation only)';
  renderNav((location.hash.replace(/^#\/?/, '').split(/[/?]/)[0]) || 'overview');
}

async function boot() {
  for (let i = 0; i < 30; i++) { try { await refreshBoot(); break; } catch (e) { await new Promise(r => setTimeout(r, 500)); } }
  $('#agent').addEventListener('change', e => {
    S.agent = e.target.value;
    const section = (location.hash.replace(/^#\/?/, '').split(/[/?]/)[0]) || 'overview';
    const target = `#/${NAV.some(n => n[0] === section) ? section : 'overview'}`;
    if (location.hash !== target) location.hash = target; else route();
  });
  $('#reset').addEventListener('click', async e => {
    if (!confirm('Re-seed all demo data? Runs, approvals and labels from this session will be lost.')) return;
    e.target.disabled = true; e.target.textContent = 'Resetting…';
    await post('/api/reset'); S.jobs = {}; S.suiteRun = null; await refreshBoot();
    e.target.disabled = false; e.target.textContent = 'Reset demo data'; toast('Demo data re-seeded'); route();
  });
  window.addEventListener('hashchange', route);
  route();
}
boot();
