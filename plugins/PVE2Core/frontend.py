"""PVE2Core frontend — served at /admin/pve2core."""


def build_page(configured: bool = False) -> str:
    if not configured:
        return _setup_page()
    return _dashboard_page()


def _setup_page() -> str:
    return """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PVE2 Core — Setup</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#f0f2f5; display:flex; align-items:center; justify-content:center; min-height:100vh; }
  .setup-box { background:white; border-radius:12px; padding:40px; width:420px; box-shadow:0 4px 24px rgba(0,0,0,0.1); }
  .setup-box h1 { font-size:1.4em; color:#333; margin-bottom:24px; text-align:center; }
  .field { margin-bottom:16px; }
  .field label { display:block; font-size:0.85em; color:#666; margin-bottom:4px; font-weight:600; }
  .field input { width:100%; padding:10px 12px; border:1px solid #ddd; border-radius:6px; font-size:0.95em; outline:none; transition:border-color 0.2s; }
  .field input:focus { border-color:#667eea; box-shadow:0 0 0 3px rgba(102,126,234,0.15); }
  .btn { width:100%; padding:12px; background:#667eea; color:white; border:none; border-radius:6px; font-size:1em; font-weight:600; cursor:pointer; transition:background 0.2s; }
  .btn:hover { background:#764ba2; }
  .btn:disabled { opacity:0.6; cursor:not-allowed; }
  .error { color:#dc2626; font-size:0.85em; margin-top:8px; display:none; padding:8px 12px; background:#fee2e2; border-radius:6px; }
  .info { color:#666; font-size:0.85em; text-align:center; margin-top:16px; }
  .spinner { display:inline-block; width:16px; height:16px; border:2px solid rgba(255,255,255,0.3); border-top-color:white; border-radius:50%; animation:spin 0.6s linear infinite; vertical-align:middle; margin-right:6px; }
  @keyframes spin { to { transform:rotate(360deg); } }
</style>
</head>
<body>
<div class="setup-box">
  <a href="/admin/hub" style="display:block;text-align:right;text-decoration:none;color:#667eea;font-weight:600;font-size:0.85em;margin-bottom:8px;">&#8592; Hub</a>
  <h1>PVE2 Core — Setup</h1>
  <details style="background:#eef2ff;border:1px solid #c7d2fe;border-radius:8px;padding:10px 14px;margin:0 0 18px 0;font-size:0.85em;text-align:left;">
<summary style="cursor:pointer;font-weight:600;color:#4338ca;">&#8505;&#65039; What this does</summary>
<div style="margin-top:8px;color:#444;line-height:1.55;">Stores your Proxmox connection (URL + API token) in the database and mirrors it to the global settings all other plugins use. The token needs at least <em>read</em> privileges (PVEAuditor); add <em>VM.PowerMgmt</em> if you plan to let the Power scheduler start/stop machines.</div>
</details>
  
  <p style="color:#666;font-size:0.9em;text-align:center;margin-bottom:20px;">Connect to your Proxmox cluster</p>
  <div class="field">
    <label>Proxmox URL</label>
    <input id="url" type="text" placeholder="https://your-proxmox:8006" value="">
  </div>
  <div class="field">
    <label>Token ID</label>
    <input id="token" type="text" placeholder="user@pve!tokenid">
  </div>
  <div class="field">
    <label>Secret</label>
    <input id="secret" type="password" placeholder="••••••••">
  </div>
  <div class="field" style="display:flex;align-items:center;gap:8px;">
    <input id="insecure" type="checkbox" checked style="width:auto;">
    <label for="insecure" style="margin:0;font-size:0.85em;color:#666;">Skip SSL verification (self-signed cert)</label>
  </div>
  <button class="btn" id="connect-btn" onclick="connect()">Connect & Save</button>
  <div class="error" id="error-msg"></div>
  <div class="info" id="status-msg"></div>
</div>
<script>
async function connect() {
  const btn = document.getElementById('connect-btn');
  const err = document.getElementById('error-msg');
  const status = document.getElementById('status-msg');
  btn.disabled = true; err.style.display='none'; btn.innerHTML = '<span class="spinner"></span> Connecting...';
  try {
    const r = await fetch('/api/plugins/pve2core/setup', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        proxmox_url: document.getElementById('url').value,
        proxmox_token: document.getElementById('token').value,
        proxmox_secret: document.getElementById('secret').value,
        proxmox_insecure: document.getElementById('insecure').checked,
      })
    });
    const data = await r.json();
    if (data.connected) {
      status.textContent = 'Connected! (' + data.nodes + ' nodes found) Reloading...';
      setTimeout(() => location.reload(), 1000);
    } else {
      err.textContent = data.error || 'Connection failed';
      err.style.display = 'block';
      btn.disabled = false; btn.innerHTML = 'Connect & Save';
      status.textContent = '';
    }
  } catch(e) {
    err.textContent = 'Network error: ' + e.message;
    err.style.display = 'block';
    btn.disabled = false; btn.innerHTML = 'Connect & Save';
    status.textContent = '';
  }
}
</script>
</body>
</html>"""


def _dashboard_page() -> str:
    return """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PVE2 Core — Dashboard</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#f5f5f5; padding:20px; }
  .container { max-width:1400px; margin:0 auto; }
  .header { display:flex; align-items:center; justify-content:space-between; margin-bottom:24px; flex-wrap:wrap; gap:12px; }
  .header h1 { font-size:1.5em; color:#333; display:flex; align-items:center; gap:10px; }
  .header-right { display:flex; align-items:center; gap:16px; flex-wrap:wrap; }
  .status-dot { width:10px; height:10px; border-radius:50%; display:inline-block; transition:background 0.3s; }
  .status-dot.online { background:#10b981; box-shadow:0 0 6px rgba(16,185,129,0.4); }
  .status-dot.offline { background:#dc2626; }
  .summary-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:16px; margin-bottom:24px; }
  .card { background:white; border-radius:10px; padding:20px; box-shadow:0 1px 3px rgba(0,0,0,0.1); }
  .card .label { color:#666; font-size:0.8em; text-transform:uppercase; font-weight:600; letter-spacing:0.03em; }
  .card .value { font-size:1.8em; font-weight:700; color:#333; margin-top:2px; }
  .card .sub { color:#999; font-size:0.85em; margin-top:4px; }
  .filters { display:flex; gap:8px; margin-bottom:12px; flex-wrap:wrap; align-items:center; }
  .filters select,.filters input { padding:8px 12px; border:1px solid #ddd; border-radius:6px; font-size:0.9em; }
  .filters button { padding:8px 16px; background:#667eea; color:white; border:none; border-radius:6px; cursor:pointer; font-weight:600; }
  .filters button:hover { background:#764ba2; }
  .filters button:disabled { opacity:0.5; cursor:not-allowed; }
  table { width:100%; border-collapse:collapse; background:white; border-radius:10px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.1); }
  th,td { padding:10px 14px; text-align:left; border-bottom:1px solid #eee; font-size:0.9em; }
  th { background:#f9fafb; font-weight:600; color:#555; font-size:0.8em; text-transform:uppercase; letter-spacing:0.03em; }
  tr:hover { background:#f9fafb; }
  .badge { padding:2px 8px; border-radius:10px; font-size:0.8em; font-weight:600; display:inline-block; }
  .badge.running { background:#d1fae5; color:#059669; }
  .badge.stopped { background:#fee2e2; color:#dc2626; }
  .badge.vm { background:#e0e7ff; color:#3730a3; }
  .badge.lxc { background:#fef3c7; color:#d97706; }
  .badge.online { background:#d1fae5; color:#059669; }
  .badge.offline { background:#fee2e2; color:#dc2626; }
  .actions button { padding:4px 10px; border:none; border-radius:4px; cursor:pointer; font-size:0.8em; margin-right:4px; color:white; transition:opacity 0.15s; }
  .actions button:disabled { opacity:0.4; cursor:not-allowed; }
  .actions button:hover:not(:disabled) { opacity:0.8; }
  .btn-start { background:#10b981; }
  .btn-stop { background:#dc2626; }
  .btn-reboot { background:#d97706; }
  .section-title { font-size:1.1em; color:#555; margin-bottom:12px; display:flex; align-items:center; gap:8px; }
  .bar-track { height:6px; background:#eee; border-radius:3px; overflow:hidden; display:inline-block; }
  .bar-fill { height:100%; border-radius:3px; transition:width 0.4s ease; }
  .tab-bar { display:flex; gap:4px; margin-bottom:16px; }
  .tab-bar button { padding:8px 20px; border:1px solid #ddd; border-radius:8px 8px 0 0; background:#f9fafb; cursor:pointer; font-size:0.9em; font-weight:500; color:#666; border-bottom:2px solid transparent; }
  .tab-bar button.active { background:white; color:#333; border-bottom-color:#667eea; }
  .tab-content { display:none; }
  .tab-content.active { display:block; }
  .toast { position:fixed; bottom:24px; right:24px; padding:12px 20px; border-radius:8px; color:white; font-weight:500; font-size:0.9em; box-shadow:0 4px 12px rgba(0,0,0,0.15); z-index:1000; opacity:0; transform:translateY(10px); transition:all 0.3s ease; pointer-events:none; max-width:400px; }
  .toast.show { opacity:1; transform:translateY(0); }
  .toast.success { background:#059669; }
  .toast.error { background:#dc2626; }
  .toast.info { background:#3730a3; }
  .toast .task-id { font-size:0.85em; opacity:0.8; display:block; margin-top:4px; font-family:monospace; }
  .loading { text-align:center; color:#999; padding:40px; }
  .empty-state { text-align:center; color:#999; padding:30px; }
  .spinner { display:inline-block; width:16px; height:16px; border:2px solid rgba(255,255,255,0.3); border-top-color:white; border-radius:50%; animation:spin 0.6s linear infinite; vertical-align:middle; margin-right:6px; }
  @keyframes spin { to { transform:rotate(360deg); } }
  .sync-timer { font-variant-numeric:tabular-nums; }
  .tag-pill { display:inline-block; background:#e0e7ff; color:#3730a3; padding:1px 6px; border-radius:4px; font-size:0.8em; margin:1px; }
  .ip-pill { display:inline-block; background:#f3f4f6; color:#555; padding:1px 6px; border-radius:4px; font-size:0.8em; margin:1px; font-family:monospace; }
  @media(max-width:600px) { .summary-grid { grid-template-columns:1fr 1fr; } .header-right { width:100%; } }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>PVE2 Core
    <a href="/admin/hub" style="text-decoration:none;color:#667eea;font-weight:600;font-size:0.9em;white-space:nowrap;">&#8592; Hub</a>
    <h1>PVE2 Core <span style="font-size:0.6em;color:#999;font-weight:400;">Dashboard</span></h1>
    <div class="header-right">
      <span><span class="status-dot online" id="conn-dot"></span> <span id="conn-label">Connected</span></span>
      <span style="color:#999;font-size:0.85em;">Sync: <span class="sync-timer" id="sync-label">—</span></span>
      <span id="cluster-info" style="color:#999;font-size:0.85em;"></span>
      <button id="sync-btn" onclick="runSync()" style="padding:8px 16px;background:#667eea;color:white;border:none;border-radius:6px;cursor:pointer;font-weight:600;display:flex;align-items:center;gap:6px;">↻ Sync Now</button>
    </div>
  </div>

  <div class="tab-bar">
    <button class="active" onclick="switchTab('machines',this)">Machines</button>
    <button onclick="switchTab('storage',this)">Storage</button>
  </div>

  <div id="tab-machines" class="tab-content active">
    <details class="info-note" style="background:#f0f4ff;border:1px solid #c7d2fe;border-radius:8px;padding:10px 16px;margin:0 0 20px 0;font-size:0.88em;">
<summary style="cursor:pointer;font-weight:600;color:#4338ca;user-select:none;">&#8505;&#65039; How the core works &amp; why</summary>
<div style="margin-top:10px;color:#444;line-height:1.6;"><p><strong>How it works:</strong> &#8679; Sync Now polls the Proxmox API — nodes (with NICs and PCI devices), all VMs and LXCs (running <em>and</em> stopped) and, for running machines, their IP addresses via the QEMU guest agent — and stores everything in an in-memory cache.</p><p><strong>Why a cache:</strong> every other plugin (Dash, Audit, DNS, Proxy, Power, Wiki, Notify) reads machines from this cache instead of each hammering the Proxmox API. One sync feeds all of them.</p><p><strong>Why stopped machines appear:</strong> the Power scheduler must see them to start them on schedule; DNS/Proxy/Wiki can still manage their records and pages.</p><p><strong>After a restart</strong> the cache repopulates automatically, so dependent plugins keep working.</p></div>
</details>

<div class="summary-grid" id="summary"></div>

    <div class="section-title">Machines <span id="machine-count" style="color:#999;font-weight:400;font-size:0.85em;"></span></div>
    <div class="filters">
      <select id="filter-status"><option value="">All status</option><option value="running">Running</option><option value="stopped">Stopped</option></select>
      <select id="filter-type"><option value="">All types</option><option value="vm">VM</option><option value="lxc">LXC</option></select>
      <select id="filter-node"><option value="">All nodes</option></select>
      <button onclick="loadMachines()">Apply</button>
    </div>
    <table><thead><tr><th>ID</th><th>Name</th><th>Type</th><th>Node</th><th>Status</th><th>Memory</th><th>IP</th><th>Tags</th><th>Actions</th></tr></thead>
    <tbody id="machine-rows"><tr><td colspan="9" class="loading">Loading...</td></tr></tbody></table>
  </div>

  <div id="tab-storage" class="tab-content">
    <div class="section-title">Storage <span id="storage-count" style="color:#999;font-weight:400;font-size:0.85em;"></span></div>
    <table><thead><tr><th>Name</th><th>Node</th><th>Type</th><th>Size</th><th>Content</th></tr></thead>
    <tbody id="storage-rows"><tr><td colspan="5" class="loading">Loading...</td></tr></tbody></table>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const BASE = '/api/plugins/pve2core';
let lastSyncTime = null;
let syncTimer = null;

async function api(path, opts) {
  const r = await fetch(BASE + path, opts || {});
  if (!r.ok) { const e = await r.json().catch(()=>({})); throw new Error(e.detail || e.error || r.statusText); }
  return r.json();
}

function toast(msg, type, taskId) {
  const el = document.getElementById('toast');
  el.innerHTML = msg + (taskId ? '<span class="task-id">' + escapeHtml(taskId) + '</span>' : '');
  el.className = 'toast ' + (type||'info') + ' show';
  setTimeout(() => el.classList.remove('show'), 4000);
}

function escapeHtml(s) { return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function switchTab(name, btn) {
  document.querySelectorAll('.tab-bar button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  if (name === 'storage' && !document.getElementById('storage-rows').dataset.loaded) loadStorage();
}

function relTime(d) {
  if (!d) return '—';
  const diff = (Date.now() - new Date(d).getTime()) / 1000;
  if (diff < 5) return 'just now';
  if (diff < 60) return Math.floor(diff) + 's ago';
  if (diff < 3600) return Math.floor(diff/60) + 'm ago';
  if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
  return Math.floor(diff/86400) + 'd ago';
}

function startSyncTimer() {
  if (syncTimer) clearInterval(syncTimer);
  syncTimer = setInterval(() => {
    document.getElementById('sync-label').textContent = relTime(lastSyncTime);
  }, 1000);
}

async function loadSummary() {
  try {
    const h = await api('/health');
    lastSyncTime = h.last_sync;
    document.getElementById('conn-label').textContent = h.proxmox_connected ? 'Connected' : 'Disconnected';
    document.getElementById('conn-dot').className = 'status-dot ' + (h.proxmox_connected ? 'online' : 'offline');
    document.getElementById('sync-label').textContent = relTime(h.last_sync);
    if (h.last_sync) startSyncTimer();
  } catch(e) {}
  try {
    const s = await api('/cache/stats');
    document.getElementById('summary').innerHTML =
      '<div class="card"><div class="label">Cached</div><div class="value" style="color:#3730a3">' + (s.total||0) + '</div><div class="sub">machines total</div></div>' +
      '<div class="card"><div class="label">VMs</div><div class="value" style="color:#059669">' + (s.by_type?.vm||0) + '</div><div class="sub">' + (s.by_status?.running||0) + ' running</div></div>' +
      '<div class="card"><div class="label">LXCs</div><div class="value" style="color:#d97706">' + (s.by_type?.lxc||0) + '</div><div class="sub">containers</div></div>' +
      '<div class="card"><div class="label">Cluster</div><div class="value" style="font-size:1.1em;display:flex;align-items:center;gap:6px;">' + (h.proxmox_connected ? '<span style="color:#10b981;">●</span> Online' : '<span style="color:#dc2626;">●</span> Offline') + '</div><div class="sub" id="cluster-sub"></div></div>';
  } catch(e) {}
  try {
    const c = await api('/cluster');
    if (c.cluster_name) document.getElementById('cluster-info').textContent = c.quorum_status + (c.ceph_health ? ' · ' + c.ceph_health : '');
    const sub = document.getElementById('cluster-sub');
    if (c.quorum_status) sub.textContent = 'Quorum: ' + c.quorum_status;
  } catch(e) {}
}

async function loadNodes() {
  try {
    const machines = await api('/machines');
    const nodes = {};
    machines.forEach(m => {
      if (!nodes[m.node]) nodes[m.node] = {vms:0, lxcs:0, mem_max:0, mem_used:0};
      if (m.type==='vm') nodes[m.node].vms++;
      else nodes[m.node].lxcs++;
      nodes[m.node].mem_max = Math.max(nodes[m.node].mem_max, m.memory_mb);
      nodes[m.node].mem_used += m.used_mem_mb;
    });
    const nodeSel = document.getElementById('filter-node');
    const keys = Object.keys(nodes);
    nodeSel.innerHTML = '<option value="">All nodes</option>' + keys.map(n => '<option value="' + n + '">' + n + '</option>').join('');
  } catch(e) {}
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
    const data = await api(path);
    const tbody = document.getElementById('machine-rows');
    document.getElementById('machine-count').textContent = '(' + data.length + ')';
    if (!data.length) { tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No machines found</td></tr>'; return; }
    tbody.innerHTML = data.map(m => {
      const memPct = m.memory_mb > 0 ? Math.round((m.used_mem_mb/m.memory_mb)*100) : 0;
      const memColor = memPct > 80 ? '#dc2626' : memPct > 60 ? '#d97706' : '#10b981';
      return '<tr>' +
        '<td>' + m.id + '</td>' +
        '<td><strong>' + escapeHtml(m.name||'—') + '</strong></td>' +
        '<td><span class="badge ' + m.type + '">' + m.type.toUpperCase() + '</span></td>' +
        '<td>' + m.node + '</td>' +
        '<td><span class="badge ' + m.status + '">' + m.status + '</span></td>' +
        '<td><div style="display:flex;align-items:center;gap:6px;"><div class="bar-track" style="width:60px;"><div class="bar-fill" style="width:' + memPct + '%;background:' + memColor + ';"></div></div>' + (m.used_mem_mb/1024).toFixed(1) + '/' + (m.memory_mb/1024).toFixed(0) + ' GB</div></td>' +
        '<td>' + (m.ip_addresses||[]).map(i => '<span class="ip-pill">' + i + '</span>').join('') || '<span style="color:#ccc;">—</span>' + '</td>' +
        '<td>' + (m.tags||[]).map(t => '<span class="tag-pill">' + escapeHtml(t) + '</span>').join('') || '<span style="color:#ccc;">—</span>' + '</td>' +
        '<td class="actions">' + (m.status==='running'
          ? '<button class="btn-stop" onclick="machineAction(\\'' + m.id + '\\',\\'stop\\',this)">⏹ Stop</button><button class="btn-reboot" onclick="machineAction(\\'' + m.id + '\\',\\'reboot\\',this)">⟳ Reboot</button>'
          : '<button class="btn-start" onclick="machineAction(\\'' + m.id + '\\',\\'start\\',this)">▶ Start</button>') + '</td>' +
      '</tr>';
    }).join('');
  } catch(e) { document.getElementById('machine-rows').innerHTML = '<tr><td colspan="9" style="color:#dc2626;">Error loading machines</td></tr>'; }
}

async function machineAction(id, action, btn) {
  if (!confirm(action + ' machine ' + id + '?')) return;
  btn.disabled = true; btn.innerHTML = '...';
  try {
    const data = await api('/machines/' + id + '/action/' + action, {method:'POST'});
    if (data.task_id) {
      toast('✓ ' + action + ' accepted', 'success', data.task_id);
      setTimeout(() => { loadMachines(); loadSummary(); }, 2000);
    } else { toast('Action failed', 'error'); btn.disabled = false; btn.innerHTML = action; }
  } catch(e) { toast('Error: ' + e.message, 'error'); btn.disabled = false; btn.innerHTML = action; }
}

async function loadStorage() {
  document.getElementById('storage-rows').dataset.loaded = '1';
  try {
    const data = await api('/storage');
    const tbody = document.getElementById('storage-rows');
    document.getElementById('storage-count').textContent = '(' + data.length + ')';
    if (!data.length) { tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No storage found</td></tr>'; return; }
    tbody.innerHTML = data.map(s => '<tr>' +
      '<td><strong>' + escapeHtml(s.name) + '</strong></td>' +
      '<td>' + s.node + '</td>' +
      '<td><span class="badge" style="background:#f3f4f6;color:#555;">' + s.type + '</span></td>' +
      '<td>' + s.total_gb + ' GB</td>' +
      '<td style="font-size:0.85em;color:#666;">' + escapeHtml(s.content||'') + '</td>' +
    '</tr>').join('');
  } catch(e) { document.getElementById('storage-rows').innerHTML = '<tr><td colspan="5" style="color:#dc2626;">Error loading storage</td></tr>'; }
}

async function runSync() {
  const btn = document.getElementById('sync-btn');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Syncing...';
  try {
    const data = await api('/sync', {method:'POST'});
    if (data.status === 'success') {
      toast('✓ Sync complete: ' + data.total + ' machines (' + data.vms + ' VMs, ' + data.lxcs + ' LXCs)', 'success');
      lastSyncTime = new Date().toISOString();
      document.getElementById('sync-label').textContent = 'just now';
      startSyncTimer();
      loadSummary(); loadNodes(); loadMachines();
    } else { toast('Sync error: ' + (data.error||'unknown'), 'error'); }
  } catch(e) { toast('Sync failed: ' + e.message, 'error'); }
  btn.disabled = false; btn.innerHTML = '↻ Sync Now';
}

document.getElementById('filter-type').addEventListener('change', loadMachines);
document.getElementById('filter-status').addEventListener('change', loadMachines);
document.getElementById('filter-node').addEventListener('change', loadMachines);

loadSummary(); loadNodes(); loadMachines();
setInterval(loadSummary, 10000);
</script>
</body>
</html>"""
