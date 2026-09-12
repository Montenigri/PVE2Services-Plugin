"""PVE2Audit frontend — served at /admin/pve2audit."""


def build_page() -> str:
    return """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PVE2 Audit — Rightsizing</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#f5f5f5; padding:20px; }
  .container { max-width:1200px; margin:0 auto; }
  .header { display:flex; align-items:center; justify-content:space-between; margin-bottom:24px; flex-wrap:wrap; gap:12px; }
  .header h1 { font-size:1.5em; color:#333; }
  .badge { padding:4px 12px; border-radius:12px; font-size:0.85em; font-weight:600; display:inline-block; }
  .badge.critical { background:#fee2e2; color:#dc2626; }
  .badge.warning { background:#fef3c7; color:#d97706; }
  .badge.info { background:#e0e7ff; color:#3730a3; }
  .badge.applied { background:#d1fae5; color:#059669; }
  .badge.dismiss { background:#f3f4f6; color:#6b7280; }
  .summary-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:16px; margin-bottom:24px; }
  .card { background:white; border-radius:10px; padding:20px; box-shadow:0 1px 3px rgba(0,0,0,0.1); }
  .card .label { color:#666; font-size:0.8em; text-transform:uppercase; font-weight:600; }
  .card .value { font-size:1.8em; font-weight:700; color:#333; margin-top:2px; }
  .card .sub { color:#999; font-size:0.85em; margin-top:4px; }
  .filters { display:flex; gap:8px; margin-bottom:16px; flex-wrap:wrap; align-items:center; }
  .filters select,.filters input { padding:8px 12px; border:1px solid #ddd; border-radius:6px; font-size:0.9em; }
  .filters button { padding:8px 16px; background:#667eea; color:white; border:none; border-radius:6px; cursor:pointer; font-weight:600; }
  .filters button:hover { background:#764ba2; }
  .filters button:disabled { opacity:0.5; cursor:not-allowed; }
  table { width:100%; border-collapse:collapse; background:white; border-radius:10px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.1); }
  th,td { padding:12px 16px; text-align:left; border-bottom:1px solid #eee; }
  th { background:#f9fafb; font-weight:600; color:#555; font-size:0.8em; text-transform:uppercase; letter-spacing:0.03em; }
  tr:hover { background:#f9fafb; }
  .actions button { padding:4px 10px; border:none; border-radius:4px; cursor:pointer; font-size:0.8em; margin-right:4px; transition:opacity 0.15s; }
  .actions button:disabled { opacity:0.4; cursor:not-allowed; }
  .actions button:hover:not(:disabled) { opacity:0.8; }
  .btn-apply { background:#d1fae5; color:#059669; }
  .btn-dismiss { background:#fef3c7; color:#d97706; }
  .detail-panel { background:white; border-radius:10px; padding:24px; box-shadow:0 1px 3px rgba(0,0,0,0.1); margin-bottom:24px; display:none; }
  .detail-panel.visible { display:block; }
  canvas { width:100% !important; height:240px !important; margin-top:16px; border-radius:4px; }
  .loading { text-align:center; color:#999; padding:40px; }
  .empty-state { text-align:center; color:#999; padding:40px; }
  .node-bars { display:flex; gap:12px; flex-wrap:wrap; margin-bottom:24px; }
  .node-bar-card { background:white; border-radius:8px; padding:16px; flex:1; min-width:180px; box-shadow:0 1px 3px rgba(0,0,0,0.1); }
  .node-bar-card .node-name { font-weight:600; margin-bottom:8px; }
  .bar-track { height:8px; background:#eee; border-radius:4px; overflow:hidden; margin:4px 0; }
  .bar-fill { height:100%; border-radius:4px; transition:width 0.4s ease; }
  .toast { position:fixed; bottom:24px; right:24px; padding:12px 20px; border-radius:8px; color:white; font-weight:500; font-size:0.9em; box-shadow:0 4px 12px rgba(0,0,0,0.15); z-index:1000; opacity:0; transform:translateY(10px); transition:all 0.3s ease; pointer-events:none; }
  .toast.show { opacity:1; transform:translateY(0); }
  .toast.success { background:#059669; }
  .toast.error { background:#dc2626; }
  .toast.info { background:#3730a3; }
  .spinner { display:inline-block; width:16px; height:16px; border:2px solid rgba(255,255,255,0.3); border-top-color:white; border-radius:50%; animation:spin 0.6s linear infinite; vertical-align:middle; margin-right:6px; }
  @keyframes spin { to { transform:rotate(360deg); } }
  .legend { display:flex; gap:16px; margin-bottom:8px; font-size:0.85em; color:#666; }
  .legend-item { display:flex; align-items:center; gap:6px; }
  .legend-swatch { width:14px; height:3px; border-radius:2px; display:inline-block; }
  .chart-legend { display:flex; gap:16px; margin-bottom:8px; font-size:0.85em; color:#666; flex-wrap:wrap; }
  .chart-legend-item { display:flex; align-items:center; gap:6px; }
  .chart-legend-swatch { width:14px; height:3px; border-radius:2px; display:inline-block; }
  .timestamp-sub { color:#999; font-size:0.75em; margin-top:4px; }
  .entity-group { background:white; border-radius:10px; margin-bottom:12px; box-shadow:0 1px 3px rgba(0,0,0,0.1); overflow:hidden; }
  .entity-group summary { padding:14px 16px; cursor:pointer; display:flex; align-items:center; gap:12px; flex-wrap:wrap; list-style:none; }
  .entity-group summary::-webkit-details-marker { display:none; }
  .entity-group summary:hover { background:#f9fafb; }
  .entity-group[open] summary { border-bottom:1px solid #eee; background:#f9fafb; }
  .entity-group .entity-recs { padding:6px 16px 12px; }
  .entity-group .entity-recs table { box-shadow:none; border-radius:0; }
  .chev { margin-left:auto; color:#999; font-size:0.8em; transition:transform 0.2s; }
  .entity-group[open] .chev { transform:rotate(90deg); }
  .info-note { background:#f0f4ff; border:1px solid #c7d2fe; border-radius:8px; padding:10px 16px; margin:0 0 20px 0; font-size:0.88em; }
  .info-note summary { cursor:pointer; font-weight:600; color:#4338ca; user-select:none; }
  .info-note .note-body { margin-top:10px; color:#444; line-height:1.6; }
  .info-note .note-body p { margin-bottom:8px; }
  .info-note .note-body ul { margin:4px 0 8px 18px; }
  @media(max-width:600px) { .summary-grid { grid-template-columns:1fr 1fr; } }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <a href="/admin/hub" style="text-decoration:none;color:#667eea;font-weight:600;font-size:0.9em;white-space:nowrap;">&#8592; Hub</a>
    <h1>PVE2 Audit — Rightsizing</h1>
    <div style="display:flex;align-items:center;gap:12px;">
      <span id="sync-timestamp" style="color:#999;font-size:0.85em;"></span>
      <button id="sync-btn" class="badge info" onclick="runSync()" style="cursor:pointer;border:none;display:flex;align-items:center;gap:6px;">🔄 Run Collector</button>
    </div>
  </div>

  <details class="info-note">
    <summary>&#8505;&#65039; How rightsizing works &amp; why</summary>
    <div class="note-body">
      <p><strong>How it works:</strong> a background job samples every machine every 15-30 minutes into a 30-day history; the analyzer then compares the <strong>median</strong> of that history against thresholds to produce advice. Advice is never applied <em>automatically</em> — but clicking <strong>✓ Apply executes it for real</strong> on the machine via the Proxmox API (CPU/memory only; disk/idle advice is a manual checklist). Downsizes ask you to type CONFIRM first.</p>
      <p><strong>Why the median (and not the average or the last value):</strong> a bursty machine — idle all day, busy for ten minutes — has a low median but real peaks. The average would get dragged around by those bursts and the last value only says "right now". The median describes the typical load, so quiet periods don't hide behind one busy moment and busy moments don't condemn an otherwise idle machine.</p>
      <p><strong>Why bursts still block a downsize:</strong> the median alone would happily shrink a machine that spikes to 100% every hour. So a CPU reduction additionally requires that even the recorded <em>peaks</em> stayed below ~60% — if the machine ever burst near its limit in the window, the advice is withheld. Memory reductions are inherently burst-safe: they're sized on measured <em>peak</em> + 30% headroom, never on the median.</p>
      <p><strong>CPU — why one core at a time:</strong> Proxmox reports CPU as a fraction of <em>all assigned cores</em>, so "3% median" means the machine typically uses 3% of everything you gave it. CPU is burstable and guests rarely notice a single missing core, so we reduce conservatively and you re-measure after each step. p95 above 80% suggests adding cores instead.</p>
      <p><strong>Memory — why peak + 30%:</strong> memory is "sticky" — applications grow caches and rarely return it — so a reduction must fit the measured peak with headroom, rounded up to whole GB. RAM is usually what limits host density, which is why proving headroom pays off. Above 80% median we suggest peak + 1&nbsp;GB instead.</p>
      <p><strong>Disk — why critical:</strong> median usage above 80%. Disk exhaustion can corrupt databases and is the hardest resource to grow under pressure.</p>
      <p><strong>Idle:</strong> median CPU &lt; 2% and median memory &lt; 256&nbsp;MB — a stopped machine frees all its CPU and RAM instantly; only its disk stays allocated.</p>
      <p><strong>Trust the data:</strong> suggestions need <strong>7+ days</strong> of samples. Machines with less show an amber "only Xd of data" chip — treat those as preliminary and re-check after a week. Samples older than 30 days are pruned.</p>
    </div>
  </details>

  <div class="summary-grid" id="summary"></div>

  <h2 style="margin-bottom:12px;font-size:1.1em;color:#555;">Node Allocation</h2>
  <div class="node-bars" id="node-bars"></div>

  <h2 style="margin-bottom:4px;font-size:1.1em;color:#555;">Complete Audit</h2>
  <div style="color:#999;font-size:0.85em;margin-bottom:8px;">Every machine with its full advice list, a 30-day usage graph, and the reasoning behind each recommendation — expand a machine to see everything.</div>
  <div id="coverage-banner" style="display:none;background:#fef3c7;border:1px solid #fcd34d;border-radius:8px;padding:10px 14px;margin-bottom:12px;font-size:0.88em;color:#92400e;"></div>
  <div class="filters">
    <select id="filter-category"><option value="">All categories</option><option value="cpu">CPU</option><option value="memory">Memory</option><option value="disk">Disk</option><option value="idle">Idle</option><option value="node_balance">Node Balance</option><option value="drift">Drift</option></select>
    <select id="filter-severity"><option value="">All severities</option><option value="critical">Critical</option><option value="warning">Warning</option><option value="info">Info</option></select>
    <button onclick="loadRecs()">Apply</button>
  </div>

  <div id="rec-table"><div class="loading">Loading recommendations...</div></div>

  <div class="detail-panel" id="detail-panel">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
      <h3 id="detail-title" style="font-size:1.1em;"></h3>
      <button onclick="closeDetail()" style="padding:6px 12px;border:1px solid #ddd;border-radius:6px;cursor:pointer;background:white;font-size:0.85em;">✕ Close</button>
    </div>
    <div class="legend" id="detail-legend">
      <span class="legend-item"><span class="legend-swatch" style="background:#667eea;"></span> CPU %</span>
      <span class="legend-item"><span class="legend-swatch" style="background:#10b981;"></span> Memory %</span>
      <span class="legend-item"><span class="legend-swatch" style="background:#f59e0b;"></span> Disk %</span>
    </div>
    <canvas id="detail-chart"></canvas>
    <div id="detail-recs" style="margin-top:16px;"></div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const BASE = '/api/plugins/pve2audit';

// Expanded-dropdown state, preserved across the 30s auto-refresh
const openGroups = new Set();
const groupSamples = new Map();

async function api(path, opts) {
  const r = await fetch(BASE + path, opts || {});
  if (!r.ok) { const e = await r.json().catch(()=>({})); throw new Error(e.detail || e.error || r.statusText); }
  return r.json();
}

function toast(msg, type) {
  const el = document.getElementById('toast');
  el.textContent = msg; el.className = 'toast ' + (type||'info') + ' show';
  setTimeout(() => el.classList.remove('show'), 3500);
}

async function loadSummary() {
  try {
    const s = await api('/report/summary');
    const cat = s.by_category || {};
    document.getElementById('summary').innerHTML =
      `<div class="card"><div class="label">Total</div><div class="value">${s.total}</div><div class="sub">active recommendations</div></div>` +
      `<div class="card"><div class="label">Critical</div><div class="value" style="color:#dc2626">${s.by_severity?.critical||0}</div><div class="sub">needs immediate action</div></div>` +
      `<div class="card"><div class="label">Warning</div><div class="value" style="color:#d97706">${s.by_severity?.warning||0}</div><div class="sub">review suggested</div></div>` +
      `<div class="card"><div class="label">By Category</div><div class="value" style="font-size:1.1em;">${Object.entries(cat).filter(([,v])=>v>0).map(([k,v])=>k+':'+v).join(' · ')||'—'}</div><div class="sub">CPU · Mem · Disk · Idle</div></div>`;
  } catch(e) { document.getElementById('summary').innerHTML = '<div class="card"><div class="value" style="color:#dc2626;">Error loading summary</div></div>'; }
}

async function loadNodes() {
  try {
    const data = await api('/report/nodes');
    const bars = document.getElementById('node-bars');
    if (!data.nodes || data.nodes.length === 0) { bars.innerHTML = '<div class="card empty-state">No node data — run collector first</div>'; return; }
    bars.innerHTML = data.nodes.map(n => {
      const pct = Math.round((n.avg_mem_pct||0)*100);
      const color = pct > 80 ? '#dc2626' : pct > 60 ? '#d97706' : '#10b981';
      return '<div class="node-bar-card">' +
        '<div class="node-name">' + n.node + '</div>' +
        '<div style="font-size:0.85em;color:#666;">VMs: ' + n.total_vms + ' | LXCs: ' + n.total_lxcs + '</div>' +
        '<div style="font-size:0.85em;color:#666;margin-top:4px;">Memory</div>' +
        '<div class="bar-track"><div class="bar-fill" style="width:' + pct + '%;background:' + color + ';"></div></div>' +
        '<div style="font-size:0.85em;display:flex;justify-content:space-between;"><span>0%</span><span>' + pct + '%</span></div>' +
      '</div>';
    }).join('');
  } catch(e) { document.getElementById('node-bars').innerHTML = '<div class="card empty-state">Error loading nodes</div>'; }
}

function escHtml(s) { return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function drawUsageChart(canvas, samples, hoverIdx) {
  let st = canvas._chartState;
  if (samples) {
    const w = canvas.parentElement.clientWidth;
    canvas.width = w; canvas.height = 180;
    st = canvas._chartState = {
      samples,
      pad: {top:14,bottom:34,left:40,right:12},
      w, h: 180,
      labels: samples.map(s => { const d=new Date(s.timestamp); return d.toLocaleDateString()+' '+d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}); }),
      cpu:  samples.map(s => Math.min(100, Math.round((s.cpu_avg||0)*100))),
      mem:  samples.map(s => Math.min(100, Math.round(((s.mem_used||0)/(s.mem_max||1))*100))),
      disk: samples.map(s => Math.min(100, Math.round(((s.disk_used||0)/(s.disk_max||1))*100))),
    };
    st.cw = w - st.pad.left - st.pad.right;
    st.ch = st.h - st.pad.top - st.pad.bottom;
    st.stepX = st.cw / Math.max(samples.length-1, 0.1);
    if (!canvas._hoverWired) {
      canvas._hoverWired = true;
      canvas.addEventListener('mousemove', e => {
        const s = canvas._chartState; if (!s) return;
        const rect = canvas.getBoundingClientRect();
        const idx = Math.round((e.clientX - rect.left - s.pad.left) / s.stepX);
        drawUsageChart(canvas, null, idx >= 0 && idx < s.samples.length ? idx : null);
      });
      canvas.addEventListener('mouseleave', () => drawUsageChart(canvas, null, null));
    }
  }
  if (!st) return;
  const {pad, cw, ch, stepX, w} = st;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0,0,w,st.h);
  if (!st.samples || st.samples.length===0) { ctx.fillStyle='#999'; ctx.font='13px sans-serif'; ctx.fillText('No history yet — the collector runs every 15-30 min', pad.left, 100); return; }
  ctx.strokeStyle='#e5e7eb'; ctx.lineWidth=1;
  for(let i=0;i<=100;i+=25) { const y=pad.top+ch-(i/100)*ch; ctx.beginPath(); ctx.moveTo(pad.left,y); ctx.lineTo(w-pad.right,y); ctx.stroke(); ctx.fillStyle='#ccc'; ctx.font='9px sans-serif'; ctx.textAlign='right'; ctx.fillText(i+'%',pad.left-4,y+3); }
  function line(data,color) { ctx.beginPath(); ctx.strokeStyle=color; ctx.lineWidth=2; data.forEach((v,i) => { const x=pad.left+i*stepX, y=pad.top+ch-(v/100)*ch; i===0?ctx.moveTo(x,y):ctx.lineTo(x,y); }); ctx.stroke(); }
  line(st.cpu,'#667eea'); line(st.mem,'#10b981'); line(st.disk,'#f59e0b');
  ctx.fillStyle='#999'; ctx.font='10px sans-serif'; ctx.textAlign='center';
  const maxL = Math.min(6, st.samples.length);
  for(let i=0;i<maxL;i++) { const idx=Math.floor(i*st.samples.length/maxL); ctx.fillText(st.labels[idx],pad.left+idx*stepX,196); }
  if (hoverIdx != null && st.samples[hoverIdx]) {
    const x = pad.left + hoverIdx * stepX;
    ctx.strokeStyle='#94a3b8'; ctx.setLineDash([4,3]);
    ctx.beginPath(); ctx.moveTo(x,pad.top); ctx.lineTo(x,pad.top+ch); ctx.stroke(); ctx.setLineDash([]);
    [[st.cpu,'#667eea'],[st.mem,'#10b981'],[st.disk,'#f59e0b']].forEach(([arr,color]) => {
      ctx.fillStyle=color; ctx.beginPath(); ctx.arc(x, pad.top+ch-(arr[hoverIdx]/100)*ch, 4, 0, Math.PI*2); ctx.fill();
      ctx.strokeStyle='white'; ctx.lineWidth=1.5; ctx.stroke();
    });
    const s = st.samples[hoverIdx];
    const lines = [st.labels[hoverIdx], 'CPU ' + st.cpu[hoverIdx] + '%', 'Mem ' + st.mem[hoverIdx] + '%', 'Disk ' + st.disk[hoverIdx] + '%'];
    ctx.font = '11px sans-serif';
    const tw = Math.max.apply(null, lines.map(l => ctx.measureText(l).width)) + 16;
    const th = lines.length * 15 + 10;
    let tx = x + 12; if (tx + tw > w - pad.right) tx = x - tw - 12;
    const ty = pad.top + 6;
    ctx.fillStyle = 'rgba(255,255,255,0.97)'; ctx.strokeStyle = '#c7d2fe'; ctx.lineWidth = 1;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(tx, ty, tw, th, 6); else ctx.rect(tx, ty, tw, th);
    ctx.fill(); ctx.stroke();
    lines.forEach((l, i) => { ctx.fillStyle = i === 0 ? '#333' : (['#667eea','#10b981','#f59e0b'][i-1] || '#555'); ctx.textAlign = 'left'; ctx.fillText(l, tx + 8, ty + 18 + i * 15); });
  }
}

async function loadRecs() {
  const cat = document.getElementById('filter-category').value;
  const sev = document.getElementById('filter-severity').value;
  let path = '/recommendations?active_only=1';
  if (cat) path += '&category=' + cat;
  if (sev) path += '&severity=' + sev;
  try {
    const recs = await api(path);
    const el = document.getElementById('rec-table');
    if (recs.length === 0) { el.innerHTML = '<div class="card empty-state">No active recommendations — run the collector</div>'; return; }

    // Coverage: warn when history is shorter than the recommended 7 days
    const withDays = recs.filter(r => r.data_days != null);
    const lowDataEntities = new Set(withDays.filter(r => r.data_days < 7).map(r => r.entity_id));
    const bannerEl = document.getElementById('coverage-banner');
    if (withDays.length && lowDataEntities.size) {
      const minD = Math.min(...withDays.filter(r => lowDataEntities.has(r.entity_id)).map(r => r.data_days));
      bannerEl.style.display = 'block';
      bannerEl.innerHTML = '&#9888; <strong>Early data:</strong> ' + lowDataEntities.size + ' machine(s) have less than 7 days of samples' +
        (minD != null ? ' (as little as ' + minD + 'd)' : '') +
        '. Suggestions for them are preliminary — the collector adds a sample every 15-30 min; re-check after a full week.';
    } else if (!withDays.length) {
      bannerEl.style.display = 'block';
      bannerEl.innerHTML = '&#9888; <strong>No history yet:</strong> the collector just started — suggestions need 7+ days of samples to be reliable.';
    } else { bannerEl.style.display = 'none'; }

    // Complete audit: group every advice by machine so nothing is hidden.
    const groups = {};
    recs.forEach(r => {
      const g = groups[r.entity_id] = groups[r.entity_id] || {
        name: r.entity_name || r.entity_id, node: r.node || '', type: r.entity_type || '', recs: [],
        data_days: r.data_days, sample_count: r.sample_count
      };
      g.recs.push(r);
    });
    const sevRank = {critical:0, warning:1, info:2};
    const entries = Object.entries(groups).map(([eid, g]) => {
      const worst = g.recs.reduce((w, r) => ((sevRank[r.severity] ?? 3) < (sevRank[w] ?? 3) ? r.severity : w), 'info');
      return {eid, g, worst};
    }).sort((a, b) => (sevRank[a.worst] ?? 3) - (sevRank[b.worst] ?? 3) || a.g.name.localeCompare(b.g.name));

    el.innerHTML = entries.map(e => {
      const cats = [...new Set(e.g.recs.map(r => r.category))].join(', ');
      const safeId = e.eid.replace(/[^a-zA-Z0-9_-]/g, '_');
      const dd = e.g.data_days;
      const dataChip = dd == null
        ? '<span class="badge dismiss" title="No samples yet">no data</span>'
        : (dd < 7
            ? '<span class="badge warning" title="Less than 7 days of samples — treat advice as preliminary">&#9888; ' + dd + 'd of data</span>'
            : '<span class="badge applied" title="Days of sampled history">&#10003; ' + dd + 'd of data</span>');
      const rows = e.g.recs.map(r =>
        '<tr>' +
        '<td><strong>' + escHtml(r.category) + '</strong></td>' +
        '<td><span class="badge ' + r.severity + '">' + r.severity + '</span></td>' +
        '<td style="font-size:0.9em;">' + escHtml(r.current_value||'-') + '</td>' +
        '<td style="font-size:0.9em;">' + escHtml(r.suggested_value||'-') + '</td>' +
        '<td style="font-size:0.85em;color:#666;max-width:340px;">' + escHtml(r.rationale||'-') + '</td>' +
        '<td class="actions"><button class="btn-apply" onclick="updateRec(' + r.id + ',\\'applied\\',this)">✓ Apply</button><button class="btn-dismiss" onclick="updateRec(' + r.id + ',\\'dismiss\\',this)">✕ Dismiss</button></td>' +
        '</tr>').join('');
      return '<details class="entity-group" data-eid="' + escHtml(e.eid) + '">' +
        '<summary>' +
          '<span style="font-weight:600;">' + escHtml(e.g.name) + '</span>' +
          '<span class="timestamp-sub" style="margin-top:0;">' + escHtml(e.eid) + (e.g.node ? ' · ' + escHtml(e.g.node) : '') + '</span>' +
          '<span class="badge ' + e.worst + '">' + e.worst + '</span>' +
          '<span style="color:#666;font-size:0.85em;">' + e.g.recs.length + ' advice' + (e.g.recs.length > 1 ? 's' : '') + ' — ' + escHtml(cats) + '</span>' +
          dataChip +
          '<span class="chev">▶</span>' +
        '</summary>' +
        '<div class="entity-recs">' +
          '<div class="chart-legend"><span class="chart-legend-item"><span class="chart-legend-swatch" style="background:#667eea;"></span> CPU %</span>' +
          '<span class="chart-legend-item"><span class="chart-legend-swatch" style="background:#10b981;"></span> Memory %</span>' +
          '<span class="chart-legend-item"><span class="chart-legend-swatch" style="background:#f59e0b;"></span> Disk %</span>' +
          '<span style="color:#999;font-size:0.8em;">last 30 days · 15-30 min samples</span></div>' +
          '<canvas id="echart-' + safeId + '" height="180"></canvas>' +
          '<table style="margin-top:12px;"><thead><tr><th>Category</th><th>Severity</th><th>Current</th><th>Suggested</th><th>Why</th><th>Actions</th></tr></thead><tbody>' + rows + '</tbody></table>' +
          '<div style="padding:10px 4px 2px;"><a href="#" onclick="showDetail(\\'' + e.eid + '\\');return false;" style="color:#667eea;font-size:0.85em;text-decoration:none;">📈 Open full utilization panel</a></div>' +
        '</div>' +
      '</details>';
    }).join('');

    // Lazy-load the usage graph the first time a machine is expanded, and
    // restore open/expanded state across the 30s auto-refresh (otherwise the
    // refresh would collapse whatever the user had open).
    el.querySelectorAll('details.entity-group').forEach(d => {
      const eid = d.dataset.eid;
      if (openGroups.has(eid)) {
        d.open = true;
        if (groupSamples.has(eid)) {
          d.dataset.loaded = '1';
          const canvas = document.getElementById('echart-' + eid.replace(/[^a-zA-Z0-9_-]/g, '_'));
          if (canvas) drawUsageChart(canvas, groupSamples.get(eid));
        }
      }
      d.addEventListener('toggle', () => {
        if (d.open) openGroups.add(eid); else { openGroups.delete(eid); groupSamples.delete(eid); }
        if (!d.open || d.dataset.loaded) return;
        d.dataset.loaded = '1';
        const canvas = document.getElementById('echart-' + eid.replace(/[^a-zA-Z0-9_-]/g, '_'));
        if (!canvas) return;
        api('/history/' + encodeURIComponent(eid) + '?days=30')
          .then(data => { groupSamples.set(eid, data.samples || []); drawUsageChart(canvas, data.samples || []); })
          .catch(() => drawUsageChart(canvas, []));
      });
    });
  } catch(e) { document.getElementById('rec-table').innerHTML = '<div class="card empty-state" style="color:#dc2626;">Error loading recommendations</div>'; }
}

function isDownsize(rec) {
  const num = s => parseFloat((s||'').replace(/[^0-9.]/g, ''));
  if (!rec || rec.category === 'disk' || rec.category === 'idle') return false;
  if (rec.category === 'cpu') {
    const cur = num((rec.current_value||'').split('@')[0]);
    const sug = num(rec.suggested_value);
    return sug > 0 && cur > 0 && sug < cur;
  }
  if (rec.category === 'memory') {
    const cur = num((rec.current_value||'').split('@')[0]);   // "2.0 GB @ 89% avg"
    const sug = num(rec.suggested_value);                     // "3 GB"
    return sug > 0 && cur > 0 && sug < cur;
  }
  return false;
}

async function updateRec(id, action, btn) {
  btn.disabled = true;
  try {
    if (action === 'applied') {
      // Apply = execute the change on the machine via Proxmox.
      const rec = (await api('/recommendations?active_only=1')).find(r => r.id === id);
      if (!rec) throw new Error('Recommendation not found');
      if (rec.category === 'disk' || rec.category === 'idle') {
        const r = await api('/recommendations/' + id + '/apply', {method:'POST'});
        toast('ℹ️ ' + (r.message||'Handled as bookkeeping'), 'info');
        loadRecs(); loadSummary(); return;
      }
      const what = rec.category === 'cpu'
        ? 'set CPU to ' + rec.suggested_value
        : 'set memory to ' + rec.suggested_value;
      const name = rec.entity_name || rec.entity_id;
      if (isDownsize(rec)) {
        const answer = prompt(
          '⚠ DOWNSIZE ' + name + '\\n\\n' + what + '\\n\\n' +
          'Downsizing is the risky direction — verify the machine can live with it ' +
          '(the advice is median-based with burst protection, but you know the workload).\\n\\n' +
          'Type CONFIRM to execute:');
        if (answer !== 'CONFIRM') { btn.disabled = false; return; }
      } else {
        if (!confirm('Apply to ' + name + '?\\n\\n' + what + '\\n\\nRunning machines: applies live with hotplug, otherwise at next start.')) { btn.disabled = false; return; }
      }
      const r = await api('/recommendations/' + id + '/apply', {method:'POST'});
      if (r.status === 'ok') { toast('✓ ' + (r.message||'Applied'), 'success'); loadRecs(); loadSummary(); return; }
      if (r.status === 'manual') { toast('ℹ️ ' + r.message, 'info'); loadRecs(); return; }
      throw new Error(r.message || 'Apply failed');
    }
    await api('/recommendations/' + id + '?action=' + action, {method:'PATCH'});
    toast('✕ Dismissed', 'success');
    loadRecs(); loadSummary();
  } catch(e) { toast('Failed: ' + e.message, 'error'); btn.disabled = false; }
}

async function showDetail(entityId) {
  const panel = document.getElementById('detail-panel');
  panel.classList.add('visible');
  document.getElementById('detail-title').textContent = 'Entity: ' + entityId;
  try {
    const data = await api('/history/' + entityId + '?days=30');
    const canvas = document.getElementById('detail-chart');
    const samples = data.samples || [];
    drawUsageChart(canvas, samples);
    const recs = await api('/recommendations?entity_id=' + entityId + '&active_only=1');
    document.getElementById('detail-recs').innerHTML = recs.length
      ? recs.map(r => '<div style="padding:10px 12px;border-left:3px solid ' + (r.severity==='critical'?'#dc2626':r.severity==='warning'?'#d97706':'#3730a3') + ';margin-bottom:8px;background:#f9fafb;border-radius:0 6px 6px 0;"><strong>' + r.category + '</strong> <span class="badge ' + r.severity + '">' + r.severity + '</span><br><span style="font-size:0.9em;color:#666;">' + r.rationale + '</span></div>').join('')
      : '<div style="color:#999;padding:8px;">No active recommendations</div>';
  } catch(e) { document.getElementById('detail-title').textContent += ' (error loading data)'; }
}

function closeDetail() { document.getElementById('detail-panel').classList.remove('visible'); }

async function runSync() {
  const btn = document.getElementById('sync-btn');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Syncing...';
  try {
    const data = await fetch(BASE + '/sync?timeframe=hour',{method:'POST'}).then(r=>r.json());
    if (data.status === 'success') {
      const c = data.collector||{}, a = data.analyzer||{};
      toast('✓ Synced: ' + (c.collected||0) + ' samples, ' + (a.created||0) + ' recommendations', 'success');
      document.getElementById('sync-timestamp').textContent = 'Last sync: ' + new Date().toLocaleTimeString();
      loadSummary(); loadRecs(); loadNodes();
    } else { toast('Sync error: ' + (data.error||'unknown'), 'error'); }
  } catch(e) { toast('Sync failed: ' + e.message, 'error'); }
  btn.disabled = false; btn.innerHTML = '🔄 Run Collector';
}

document.getElementById('filter-category').addEventListener('change', loadRecs);
document.getElementById('filter-severity').addEventListener('change', loadRecs);

loadSummary(); loadNodes(); loadRecs();
setInterval(() => { loadSummary(); loadRecs(); }, 30000);
</script>
</body>
</html>"""
