"""PVE2Dash frontend — served at /admin/pve2dash."""


def build_page() -> str:
    return """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PVE2 Dash — Cluster Dashboard</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#f5f5f5; padding:20px; }
  .container { max-width:1400px; margin:0 auto; }
  .header { display:flex; align-items:center; justify-content:space-between; margin-bottom:24px; flex-wrap:wrap; gap:12px; }
  .header h1 { font-size:1.5em; color:#333; display:flex; align-items:center; gap:10px; }
  .header-right { display:flex; align-items:center; gap:16px; flex-wrap:wrap; }
  .status-dot { width:10px; height:10px; border-radius:50%; display:inline-block; }
  .status-dot.online { background:#10b981; box-shadow:0 0 6px rgba(16,185,129,0.4); }
  .status-dot.offline { background:#dc2626; }
  .summary-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:16px; margin-bottom:24px; }
  .card { background:white; border-radius:10px; padding:20px; box-shadow:0 1px 3px rgba(0,0,0,0.1); }
  .card .label { color:#666; font-size:0.8em; text-transform:uppercase; font-weight:600; letter-spacing:0.03em; }
  .card .value { font-size:1.8em; font-weight:700; color:#333; margin-top:2px; }
  .card .sub { color:#999; font-size:0.85em; margin-top:4px; }
  .section-title { font-size:1.1em; color:#555; margin:24px 0 12px; display:flex; align-items:center; gap:8px; }
  .filters { display:flex; gap:8px; margin-bottom:12px; flex-wrap:wrap; }
  .filters select,.filters input { padding:8px 12px; border:1px solid #ddd; border-radius:6px; font-size:0.9em; }
  .filters button { padding:8px 16px; background:#667eea; color:white; border:none; border-radius:6px; cursor:pointer; font-weight:600; }
  .filters button:hover { background:#764ba2; }
  .node-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:16px; margin-bottom:24px; }
  .node-card { background:white; border-radius:10px; padding:20px; box-shadow:0 1px 3px rgba(0,0,0,0.1); }
  .node-card .node-name { font-weight:600; margin-bottom:12px; font-size:1.05em; }
  .node-card .stat-row { display:flex; justify-content:space-between; font-size:0.85em; color:#666; margin-bottom:4px; }
  .bar-track { height:6px; background:#eee; border-radius:3px; overflow:hidden; margin:2px 0 8px; }
  .bar-fill { height:100%; border-radius:3px; transition:width 0.5s ease; }
  .machine-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:12px; }
  .machine-card { background:white; border-radius:10px; padding:16px; box-shadow:0 1px 3px rgba(0,0,0,0.1); cursor:pointer; transition:box-shadow 0.2s,transform 0.15s; border:2px solid transparent; }
  .machine-card:hover { box-shadow:0 4px 12px rgba(0,0,0,0.12); transform:translateY(-1px); }
  .machine-card.selected { border-color:#667eea; }
  .machine-card .top-row { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:8px; }
  .machine-card .name { font-weight:600; font-size:0.95em; color:#333; }
  .machine-card .name .id-sub { font-weight:400; color:#999; font-size:0.85em; }
  .machine-card .info-row { display:flex; gap:8px; font-size:0.85em; color:#666; margin-bottom:6px; flex-wrap:wrap; }
  .machine-card .mem-row { margin-top:8px; }
  .badge { padding:2px 8px; border-radius:10px; font-size:0.78em; font-weight:600; display:inline-block; }
  .badge.running { background:#d1fae5; color:#059669; }
  .badge.stopped { background:#fee2e2; color:#dc2626; }
  .badge.vm { background:#e0e7ff; color:#3730a3; }
  .badge.lxc { background:#fef3c7; color:#d97706; }
  .tag-pill { display:inline-block; background:#e0e7ff; color:#3730a3; padding:1px 6px; border-radius:4px; font-size:0.8em; margin:1px; }
  .ip-pill { display:inline-block; background:#f3f4f6; color:#555; padding:1px 6px; border-radius:4px; font-size:0.8em; margin:1px; font-family:monospace; }
  .detail-panel { background:white; border-radius:10px; padding:24px; box-shadow:0 2px 12px rgba(0,0,0,0.1); margin-top:16px; display:none; }
  .detail-panel.visible { display:block; }
  .detail-panel.inline { grid-column: 1 / -1; margin-top: 4px; }
  .detail-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; flex-wrap:wrap; gap:12px; }
  .detail-header h2 { font-size:1.15em; }
  .detail-info { display:flex; gap:16px; flex-wrap:wrap; margin-bottom:16px; font-size:0.9em; color:#666; }
  .detail-info span { background:#f9fafb; padding:6px 12px; border-radius:6px; }
  canvas { width:100% !important; height:200px !important; border-radius:4px; }
  .chart-legend { display:flex; gap:16px; margin-bottom:8px; font-size:0.85em; color:#666; }
  .chart-legend-item { display:flex; align-items:center; gap:6px; }
  .chart-legend-swatch { width:14px; height:3px; border-radius:2px; display:inline-block; }
  .chart-timeframe { display:flex; gap:6px; margin-bottom:12px; }
  .chart-timeframe button { padding:4px 12px; border:1px solid #ddd; border-radius:6px; background:white; cursor:pointer; font-size:0.85em; color:#666; }
  .chart-timeframe button.active { background:#667eea; color:white; border-color:#667eea; }
  .loading { text-align:center; color:#999; padding:40px; }
  .empty-state { text-align:center; color:#999; padding:30px; }
  .spinner { display:inline-block; width:16px; height:16px; border:2px solid #e5e7eb; border-top-color:#667eea; border-radius:50%; animation:spin 0.6s linear infinite; vertical-align:middle; margin-right:6px; }
  @keyframes spin { to { transform:rotate(360deg); } }
  .sync-timer { font-variant-numeric:tabular-nums; }
  @media(max-width:600px) { .summary-grid { grid-template-columns:1fr 1fr; } .machine-grid { grid-template-columns:1fr; } }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <a href="/admin/hub" style="text-decoration:none;color:#667eea;font-weight:600;font-size:0.9em;white-space:nowrap;">&#8592; Hub</a>
    <h1>PVE2 Dash <span style="font-size:0.6em;color:#999;font-weight:400;">Cluster Dashboard</span></h1>
    <div class="header-right">
      <span><span class="status-dot online" id="conn-dot"></span> <span id="conn-label">Connected</span></span>
      <span style="color:#999;font-size:0.85em;">Updated: <span class="sync-timer" id="update-label">—</span></span>
    </div>
  </div>

  <details class="info-note" style="background:#f0f4ff;border:1px solid #c7d2fe;border-radius:8px;padding:10px 16px;margin:0 0 20px 0;font-size:0.88em;">
<summary style="cursor:pointer;font-weight:600;color:#4338ca;user-select:none;">&#8505;&#65039; How this dashboard works</summary>
<div style="margin-top:10px;color:#444;line-height:1.6;"><p><strong>How it works:</strong> a read-only view over the PVE2 Core cache plus live RRD statistics from Proxmox. The summary cards and machine bars come from the cache; the history charts come from Proxmox RRD data (hour/day/week/month/year).</p><p><strong>Why RRD:</strong> Proxmox stores rolling averages, not raw samples — the charts show trends over time. Pick a longer timeframe to see the shape of a machine&#39;s week, not just its current spike.</p></div>
</details>

<div class="summary-grid" id="summary"></div>

  <div class="section-title">Nodes</div>
  <div class="node-grid" id="node-grid"><div class="loading">Loading...</div></div>

  <div class="section-title">Machines <span id="machine-count" style="color:#999;font-weight:400;font-size:0.85em;"></span></div>
  <div class="filters">
    <select id="filter-status"><option value="">All status</option><option value="running">Running</option><option value="stopped">Stopped</option></select>
    <select id="filter-type"><option value="">All types</option><option value="vm">VM</option><option value="lxc">LXC</option></select>
    <select id="filter-node"><option value="">All nodes</option></select>
    <button onclick="loadMachines()">Apply</button>
  </div>
  <div class="machine-grid" id="machine-grid"><div class="loading">Loading...</div></div>

  <div class="detail-panel" id="detail-panel">
    <div class="detail-header">
      <h2 id="detail-title"></h2>
      <div>
        <span class="chart-timeframe" id="detail-timeframes">
          <button onclick="loadDetail('hour')">1h</button>
          <button class="active" onclick="loadDetail('day')">24h</button>
          <button onclick="loadDetail('week')">7d</button>
          <button onclick="loadDetail('month')">30d</button>
          <button onclick="loadDetail('year')">1y</button>
        </span>
        <button onclick="closeDetail()" style="margin-left:8px;padding:6px 12px;border:1px solid #ddd;border-radius:6px;cursor:pointer;background:white;font-size:0.85em;">✕</button>
      </div>
    </div>
    <div class="detail-info" id="detail-info"></div>
    <div class="chart-legend">
      <span class="chart-legend-item"><span class="chart-legend-swatch" style="background:#667eea;"></span> CPU %</span>
      <span class="chart-legend-item"><span class="chart-legend-swatch" style="background:#10b981;"></span> Memory %</span>
      <span class="chart-legend-item"><span class="chart-legend-swatch" style="background:#f59e0b;"></span> Disk %</span>
      <span class="chart-legend-item"><span class="chart-legend-swatch" style="background:#8b5cf6;"></span> Net In</span>
      <span class="chart-legend-item"><span class="chart-legend-swatch" style="background:#ec4899;"></span> Net Out</span>
    </div>
    <canvas id="detail-chart"></canvas>
  </div>
</div>

<script>
const CORE = '/api/plugins/pve2core';
const DASH = '/api/plugins/pve2dash';

let allMachines = [];
let selectedId = null;
let selectedNode = null;
let selectedType = 'qemu';
let currentTimeframe = 'day';

async function api(base, path, opts) {
  const r = await fetch(base + path, opts || {});
  if (!r.ok) throw new Error(r.statusText);
  return r.json();
}

function escapeHtml(s) { return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function relTime(d) {
  if (!d) return '—';
  const diff = (Date.now() - new Date(d).getTime()) / 1000;
  if (diff < 5) return 'just now';
  if (diff < 60) return Math.floor(diff) + 's ago';
  if (diff < 3600) return Math.floor(diff/60) + 'm ago';
  if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
  return Math.floor(diff/86400) + 'd ago';
}

async function loadSummary() {
  try {
    const [h, s, c] = await Promise.all([
      api(CORE, '/health'),
      api(CORE, '/cache/stats'),
      api(CORE, '/cluster').catch(()=>({}))
    ]);
    const online = h.proxmox_connected;
    document.getElementById('conn-label').textContent = online ? 'Connected' : 'Disconnected';
    document.getElementById('conn-dot').className = 'status-dot ' + (online ? 'online' : 'offline');
    document.getElementById('update-label').textContent = relTime(h.last_sync);
    document.getElementById('summary').innerHTML =
      '<div class="card"><div class="label">Cluster</div><div class="value" style="color:' + (online?'#059669':'#dc2626') + '">' + (online ? 'Online' : 'Offline') + '</div><div class="sub">' + (c.quorum_status||'—') + '</div></div>' +
      '<div class="card"><div class="label">Nodes</div><div class="value">' + (c.quorum_status||'').split('/')[0] || '?' + '</div><div class="sub">in cluster</div></div>' +
      '<div class="card"><div class="label">VMs</div><div class="value" style="color:#3730a3">' + (s.by_type?.vm||0) + '</div><div class="sub">' + (s.by_status?.running||0) + ' running</div></div>' +
      '<div class="card"><div class="label">LXCs</div><div class="value" style="color:#d97706">' + (s.by_type?.lxc||0) + '</div><div class="sub">containers</div></div>';
  } catch(e) { document.getElementById('summary').innerHTML = '<div class="card"><div class="value" style="color:#dc2626;">Offline</div><div class="sub">Cannot reach PVE2Core</div></div>'; }
}

async function loadNodes() {
  try {
    const machines = await api(CORE, '/machines');
    const nodes = {};
    machines.forEach(m => {
      if (!nodes[m.node]) nodes[m.node] = {vms:0, lxcs:0, mem_used:0, mem_max:0, cpu:0, name:m.node};
      if (m.type==='vm') nodes[m.node].vms++;
      else nodes[m.node].lxcs++;
      nodes[m.node].mem_used += m.used_mem_mb;
      nodes[m.node].mem_max += m.memory_mb;
      nodes[m.node].cpu = Math.max(nodes[m.node].cpu, m.cores);
    });
    const grid = document.getElementById('node-grid');
    const nodeSel = document.getElementById('filter-node');
    const keys = Object.keys(nodes);
    if (keys.length===0) { grid.innerHTML = '<div class="empty-state">No nodes — run PVE2Core sync first</div>'; return; }
    nodeSel.innerHTML = '<option value="">All nodes</option>' + keys.map(n => '<option value="' + n + '">' + n + '</option>').join('');
    grid.innerHTML = keys.map(n => {
      const nd = nodes[n];
      const memPct = nd.mem_max > 0 ? Math.round((nd.mem_used/nd.mem_max)*100) : 0;
      const memColor = memPct > 80 ? '#dc2626' : memPct > 60 ? '#d97706' : '#10b981';
      return '<div class="node-card">' +
        '<div class="node-name">' + n + '</div>' +
        '<div class="stat-row"><span>VMs</span><span><strong>' + nd.vms + '</strong></span></div>' +
        '<div class="stat-row"><span>LXCs</span><span><strong>' + nd.lxcs + '</strong></span></div>' +
        '<div class="stat-row"><span>Memory</span><span><strong>' + (nd.mem_used/1024).toFixed(0) + '/' + (nd.mem_max/1024).toFixed(0) + ' GB</strong></span></div>' +
        '<div class="bar-track"><div class="bar-fill" style="width:' + memPct + '%;background:' + memColor + ';"></div></div>' +
      '</div>';
    }).join('');
  } catch(e) { document.getElementById('node-grid').innerHTML = '<div class="empty-state" style="color:#dc2626;">Error loading nodes</div>'; }
}

async function loadMachines() {
  let path = '/machines';
  const params = [];
  const st = document.getElementById('filter-status').value;
  const tp = document.getElementById('filter-type').value;
  const nd = document.getElementById('filter-node').value;
  if (st) params.push('status=' + st);
  if (tp) params.push('type=' + tp);
  if (nd) params.push('node=' + nd);
  if (params.length) path += '?' + params.join('&');
  try {
    allMachines = await api(CORE, path);
    const grid = document.getElementById('machine-grid');
    document.getElementById('machine-count').textContent = '(' + allMachines.length + ')';
    // Preserve the detail panel: it lives inside the grid after a selection,
    // and a naive innerHTML wipe would destroy it (breaking further clicks).
    const panel = document.getElementById('detail-panel');
    const panelWasVisible = panel && panel.classList.contains('visible');
    if (panel && panel.parentElement === grid) panel.remove();
    if (!allMachines.length) { grid.innerHTML = '<div class="empty-state">No machines found</div>'; if (panelWasVisible) closeDetail(); return; }
    grid.innerHTML = allMachines.map(m => {
      const memPct = m.memory_mb > 0 ? Math.round((m.used_mem_mb/m.memory_mb)*100) : 0;
      const memColor = memPct > 80 ? '#dc2626' : memPct > 60 ? '#d97706' : '#10b981';
      const selected = selectedId === m.id ? ' selected' : '';
      return '<div class="machine-card' + selected + '" onclick="selectMachine(\\'' + m.id + '\\',\\'' + m.node + '\\',\\'' + m.type + '\\',this)">' +
        '<div class="top-row">' +
          '<div class="name">' + escapeHtml(m.name||'(' + m.id + ')') + ' <span class="id-sub">#' + m.id + '</span></div>' +
          '<div><span class="badge ' + m.type + '">' + m.type.toUpperCase() + '</span> <span class="badge ' + m.status + '">' + m.status + '</span></div>' +
        '</div>' +
        '<div class="info-row">' + m.node +
          (m.ip_addresses && m.ip_addresses.length ? ' · ' + m.ip_addresses.map(i => '<span class="ip-pill">' + i + '</span>').join('') : '') +
        '</div>' +
        '<div class="info-row">' + (m.tags||[]).map(t => '<span class="tag-pill">' + escapeHtml(t) + '</span>').join('') + '</div>' +
        '<div class="mem-row"><div style="font-size:0.8em;color:#999;margin-bottom:2px;">RAM: ' + (m.used_mem_mb/1024).toFixed(1) + ' / ' + (m.memory_mb/1024).toFixed(0) + ' GB</div>' +
        '<div class="bar-track"><div class="bar-fill" style="width:' + memPct + '%;background:' + memColor + ';"></div></div></div>' +
      '</div>';
    }).join('');
    // Re-attach the panel under the selected card if it survived the filter
    if (panelWasVisible && panel) {
      const card = allMachines.find(m => m.id === selectedId);
      const cardEl = card ? grid.querySelector('.machine-card.selected') : null;
      if (cardEl) { cardEl.classList.add('selected'); cardEl.insertAdjacentElement('afterend', panel); }
      else closeDetail();
    }
  } catch(e) { document.getElementById('machine-grid').innerHTML = '<div class="empty-state" style="color:#dc2626;">Error loading machines</div>'; }
}

async function selectMachine(id, node, type, el) {
  const panel = document.getElementById('detail-panel');
  if (!panel) return;
  // Clicking the selected machine again closes the panel
  if (selectedId === id && panel.classList.contains('visible')) { closeDetail(); return; }
  selectedId = id; selectedNode = node; selectedType = type === 'lxc' ? 'lxc' : 'qemu';
  document.querySelectorAll('.machine-card').forEach(c => c.classList.remove('selected'));
  el.classList.add('selected');
  // Place the graph directly under the clicked machine card
  panel.classList.remove('inline');
  el.insertAdjacentElement('afterend', panel);
  panel.classList.add('visible', 'inline');
  loadDetail(currentTimeframe);
  setTimeout(() => panel.scrollIntoView({behavior:'smooth', block:'nearest'}), 80);
}

function closeDetail() {
  document.getElementById('detail-panel').classList.remove('visible');
  selectedId = null;
  document.querySelectorAll('.machine-card').forEach(c => c.classList.remove('selected'));
}

let chartState = null;

function formatBytes(b) {
  if (b == null || isNaN(b)) return '—';
  const u = ['B','KB','MB','GB','TB']; let i = 0, v = b;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return v.toFixed(i ? 1 : 0) + ' ' + u[i];
}

function drawChart(hoverIdx) {
  if (!chartState) return;
  const {samples, cpu, mem, disk, labels, pad, cw, ch, stepX, w, h} = chartState;
  const canvas = document.getElementById('detail-chart');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, w, h);

  ctx.strokeStyle='#e5e7eb'; ctx.lineWidth=1;
  for(let i=0;i<=100;i+=20) { const y=pad.top+ch-(i/100)*ch; ctx.beginPath(); ctx.moveTo(pad.left,y); ctx.lineTo(w-pad.right,y); ctx.stroke(); ctx.fillStyle='#ccc'; ctx.font='9px sans-serif'; ctx.textAlign='right'; ctx.fillText(i+'%',pad.left-4,y+3); }

  function drawLine(data,color) { ctx.beginPath(); ctx.strokeStyle=color; ctx.lineWidth=2; data.forEach((v,i) => { const x=pad.left+i*stepX, y=pad.top+ch-(v/100)*ch; i===0?ctx.moveTo(x,y):ctx.lineTo(x,y); }); ctx.stroke(); }
  drawLine(cpu,'#667eea'); drawLine(mem,'#10b981'); drawLine(disk,'#f59e0b');

  ctx.fillStyle='#999'; ctx.font='10px sans-serif'; ctx.textAlign='center';
  const maxLabels = Math.min(8, samples.length);
  for(let i=0;i<maxLabels;i++) { const idx=Math.floor(i*samples.length/maxLabels); ctx.fillText(labels[idx],pad.left+idx*stepX,195); }

  if (hoverIdx != null && samples[hoverIdx]) {
    const x = pad.left + hoverIdx * stepX;
    ctx.strokeStyle='#94a3b8'; ctx.setLineDash([4,3]);
    ctx.beginPath(); ctx.moveTo(x,pad.top); ctx.lineTo(x,pad.top+ch); ctx.stroke(); ctx.setLineDash([]);
    [[cpu,'#667eea'],[mem,'#10b981'],[disk,'#f59e0b']].forEach(([arr,color]) => {
      ctx.fillStyle=color; ctx.beginPath(); ctx.arc(x, pad.top+ch-(arr[hoverIdx]/100)*ch, 4, 0, Math.PI*2); ctx.fill();
      ctx.strokeStyle='white'; ctx.lineWidth=1.5; ctx.stroke();
    });
    const s = samples[hoverIdx];
    const lines = [labels[hoverIdx], 'CPU ' + cpu[hoverIdx] + '%', 'Mem ' + mem[hoverIdx] + '%', 'Disk ' + disk[hoverIdx] + '%',
                   'Net \u2193 ' + formatBytes(s.netin) + '  \u2191 ' + formatBytes(s.netout)];
    ctx.font = '11px sans-serif';
    const tw = Math.max.apply(null, lines.map(l => ctx.measureText(l).width)) + 16;
    const th = lines.length * 15 + 10;
    let tx = x + 12; if (tx + tw > w - pad.right) tx = x - tw - 12;
    const ty = pad.top + 6;
    ctx.fillStyle = 'rgba(255,255,255,0.97)'; ctx.strokeStyle = '#c7d2fe'; ctx.lineWidth = 1;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(tx, ty, tw, th, 6); else ctx.rect(tx, ty, tw, th);
    ctx.fill(); ctx.stroke();
    lines.forEach((l, i) => {
      ctx.fillStyle = i === 0 ? '#333' : (['#667eea','#10b981','#f59e0b'][i-1] || '#555');
      ctx.textAlign = 'left'; ctx.fillText(l, tx + 8, ty + 18 + i * 15);
    });
  }
}

async function loadDetail(timeframe) {
  if (!selectedId || !selectedNode) return;
  currentTimeframe = timeframe || 'day';
  document.querySelectorAll('#detail-timeframes button').forEach(b => b.classList.remove('active'));
  const tfLabels = {hour:'1h', day:'24h', week:'7d', month:'30d', year:'1y'};
  document.querySelectorAll('#detail-timeframes button').forEach(b => {
    if (b.textContent === tfLabels[currentTimeframe]) b.classList.add('active');
  });
  try {
    const data = await api(DASH, '/history/' + selectedId + '?node=' + selectedNode + '&entity_type=' + selectedType + '&timeframe=' + currentTimeframe);
    const samples = data.samples || [];
    const m = allMachines.find(x => x.id === selectedId);
    document.getElementById('detail-title').innerHTML = (m ? escapeHtml(m.name) : '#' + selectedId) + ' <span style="font-weight:400;color:#999;font-size:0.85em;">#' + selectedId + ' on ' + selectedNode + '</span>';
    document.getElementById('detail-info').innerHTML =
      '<span>Type: ' + (selectedType==='qemu'?'VM':'LXC') + '</span>' +
      (m ? '<span>Status: <strong>' + m.status + '</strong></span>' : '') +
      (m ? '<span>Cores: ' + m.cores + '</span>' : '') +
      '<span>Samples: ' + samples.length + '</span>';

    const canvas = document.getElementById('detail-chart');
    const w = canvas.parentElement.clientWidth;
    canvas.width = w; canvas.height = 200;
    const pad = {top:16,bottom:36,left:40,right:16};
    const cw = w - pad.left - pad.right, ch = 200 - pad.top - pad.bottom;

    if (samples.length===0) {
      chartState = null;
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0,0,w,200);
      ctx.fillStyle='#999'; ctx.font='14px sans-serif'; ctx.fillText('No RRD data available',pad.left,110);
      return;
    }

    const labels = samples.map(s => { const d=new Date(s.timestamp*1000); return d.toLocaleDateString()+' '+d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}); });
    chartState = {
      samples, labels, pad, cw, ch, stepX: cw / Math.max(samples.length-1,0.1), w, h: 200,
      cpu:  samples.map(s => Math.min(100, Math.round(s.cpu*100))),
      mem:  samples.map(s => Math.min(100, Math.round(((s.mem_used||0)/(s.mem_max||1))*100))),
      disk: samples.map(s => Math.min(100, Math.round(((s.disk_used||0)/(s.disk_max||1))*100))),
    };
    drawChart(null);
  } catch(e) { document.getElementById('detail-title').textContent = 'Error loading detail for #' + selectedId; }
}

const _chartCv = document.getElementById('detail-chart');
_chartCv.addEventListener('mousemove', e => {
  if (!chartState) return;
  const rect = _chartCv.getBoundingClientRect();
  const idx = Math.round((e.clientX - rect.left - chartState.pad.left) / chartState.stepX);
  drawChart(idx >= 0 && idx < chartState.samples.length ? idx : null);
});
_chartCv.addEventListener('mouseleave', () => drawChart(null));

document.getElementById('filter-type').addEventListener('change', loadMachines);
document.getElementById('filter-status').addEventListener('change', loadMachines);
document.getElementById('filter-node').addEventListener('change', loadMachines);

loadSummary(); loadNodes(); loadMachines();
setInterval(() => { loadSummary(); loadNodes(); }, 15000);
</script>
</body>
</html>"""
