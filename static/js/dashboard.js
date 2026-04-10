'use strict';

/* ═══════════════════════════════════════════
   FoxEx Dashboard – Charts & Widget System
═══════════════════════════════════════════ */

const TYPE_LABELS = {
  router:'Router', switch_l2:'Switch L2', switch_l3:'Switch L3',
  firewall:'Firewall', server:'Server', desktop:'Desktop',
  laptop:'Laptop', access_point:'Access Point', nas:'NAS',
  printer:'Drucker', camera:'IP-Kamera', generic:'Generisch',
};

const WIDGETS = [
  { id: 'stat-cards',        label: 'Status-Kacheln' },
  { id: 'status-donut',      label: 'Status-Donut' },
  { id: 'latency-trend',     label: 'Latenz-Verlauf' },
  { id: 'device-latency',    label: 'Geräte-Latenz' },
  { id: 'packet-loss',       label: 'Paketverlust' },
  { id: 'syslog-summary',    label: 'Syslog Status' },
  { id: 'snmp-alerts',       label: 'SNMP-Meldungen' },
  { id: 'snmp-traps',        label: 'SNMP Traps' },
  { id: 'dns-monitor',       label: 'URL-Monitor' },
  { id: 'device-table',      label: 'Geräteliste' },
  { id: 'tcp-check',         label: 'TCP-Port Check',   defaultHidden: true },
  { id: 'http-check',        label: 'HTTP/HTTPS Check', defaultHidden: true },
  { id: 'ssh-check',         label: 'SSH Banner-Check', defaultHidden: true },
  { id: 'netflow',           label: 'NetFlow/sFlow',    defaultHidden: true },
];

// ── Chart instances ────────────────────────────────────────────
let donutChart = null, latencyChart = null, barChart = null, lossChart = null;

const CHART_COLORS = {
  yellow:  '#e06820',   // fox orange
  green:   '#28a745',
  red:     '#dc3545',
  blue:    '#4a9eff',
  gray:    '#6c7293',
  orange:  '#e06820',
};

const gridColor = 'rgba(255,255,255,0.07)';
const tickColor = '#6c7293';
const baseChartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: { legend: { labels: { color: tickColor } } },
};

// ── Init ──────────────────────────────────────────────────────
let _prefs = {};

async function _loadPrefsFromServer() {
  try {
    const r = await fetch('/api/user/dashboard-prefs');
    if (r.ok) {
      const data = await r.json();
      _prefs = data.prefs || {};
    }
  } catch { /* use defaults */ }
}

document.addEventListener('DOMContentLoaded', async () => {
  await _loadPrefsFromServer();
  applyWidgetOrder();
  applyWidgetVisibility();
  applyWidgetWidths();
  applyWidgetHeights();
  buildWidgetToggles();
  initResizeHandles();
  loadAll();
  setInterval(loadAll, 30000);
});

// ── Custom drag-resize handles ────────────────────────────────
function initResizeHandles() {
  document.querySelectorAll('.widget-resize-handle').forEach(handle => {
    const card   = handle.closest('.card');
    const body   = card?.querySelector('.resizable-body');
    const widget = handle.closest('.dash-widget');
    if (!body) return;

    handle.addEventListener('mousedown', (e) => {
      e.preventDefault();
      const startY = e.clientY;
      const startH = body.offsetHeight;
      handle.classList.add('dragging');

      const onMove = (ev) => {
        const newH = Math.max(60, startH + ev.clientY - startY);
        body.style.height = newH + 'px';
        [donutChart, latencyChart, barChart, lossChart].forEach(c => c?.resize());
      };
      const onUp = () => {
        handle.classList.remove('dragging');
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        if (widget) {
          const prefs = getPrefs();
          if (!prefs._heights) prefs._heights = {};
          prefs._heights[widget.dataset.widgetId] = body.offsetHeight;
          savePrefs(prefs);
        }
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  });
}

function applyWidgetHeights() {
  const prefs   = getPrefs();
  const heights = prefs._heights || {};
  Object.entries(heights).forEach(([id, h]) => {
    const w    = document.getElementById(`widget-${id}`);
    const body = w?.querySelector('.resizable-body');
    if (body && h) body.style.height = h + 'px';
  });
}

async function loadAll() {
  await loadSummary();
  loadLatencyTrend();
  loadPacketLossTrend();
  loadAlertCounts();
}

// ── Summary + table + donut + bar ─────────────────────────────
async function loadSummary() {
  try {
    const r    = await fetch('/api/dashboard/summary');
    const data = await r.json();

    document.getElementById('cnt-total').textContent   = data.total;
    document.getElementById('cnt-online').textContent  = data.online;
    document.getElementById('cnt-offline').textContent = data.offline;
    document.getElementById('cnt-unknown').textContent = data.unknown;
    document.getElementById('last-update').textContent =
      'Aktualisiert: ' + new Date().toLocaleTimeString('de-DE');

    renderDonut(data);
    renderDeviceBar(data.devices);
    renderTable(data.devices);
  } catch (e) { console.error(e); }
}

function renderDonut(data) {
  const ctx = document.getElementById('statusDonut').getContext('2d');
  const chartData = {
    labels: ['Online', 'Offline', 'Unbekannt'],
    datasets: [{
      data: [data.online, data.offline, data.unknown],
      backgroundColor: [CHART_COLORS.green, CHART_COLORS.red, CHART_COLORS.gray],
      borderWidth: 0,
    }],
  };
  if (donutChart) {
    donutChart.data = chartData;
    donutChart.update();
  } else {
    donutChart = new Chart(ctx, {
      type: 'doughnut',
      data: chartData,
      options: {
        ...baseChartOptions,
        cutout: '65%',
        plugins: {
          legend: { position: 'bottom', labels: { color: tickColor, padding: 12 } },
        },
      },
    });
  }
}

function renderDeviceBar(devices) {
  const labels = devices.map(d => d.name);
  const values = devices.map(d => d.latency_ms ?? 0);
  const colors = devices.map(d => {
    if (d.status === 'offline') return CHART_COLORS.red;
    if (d.status !== 'online') return CHART_COLORS.gray;
    // Color by worst ICMP alert severity if triggered
    if (d.icmp_alert_severity === 'critical') return CHART_COLORS.red;
    if (d.icmp_alert_severity === 'warning')  return '#e0c020';   // yellow
    if (d.icmp_alert_severity === 'info')     return CHART_COLORS.blue;
    return CHART_COLORS.green;
  });
  const ctx = document.getElementById('deviceLatencyBar').getContext('2d');
  const chartData = {
    labels,
    datasets: [{
      label: 'Latenz (ms)',
      data: values,
      backgroundColor: colors,
      borderRadius: 4,
    }],
  };
  if (barChart) {
    barChart.data = chartData;
    barChart.update();
  } else {
    barChart = new Chart(ctx, {
      type: 'bar',
      data: chartData,
      options: {
        ...baseChartOptions,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: tickColor }, grid: { color: gridColor } },
          y: { ticks: { color: tickColor }, grid: { color: gridColor }, beginAtZero: true },
        },
      },
    });
  }
}

// ── Trends (shared time range) ─────────────────────────────────
function loadTrends() {
  loadLatencyTrend();
  loadPacketLossTrend();
}

// ── Latency trend ──────────────────────────────────────────────
async function loadLatencyTrend() {
  const hours = document.getElementById('latency-hours')?.value ?? 24;
  try {
    const r    = await fetch(`/api/dashboard/latency-trend?hours=${hours}`);
    const data = await r.json();
    const labels = data.map(d => fmtTime(d.time));
    const values = data.map(d => d.avg_ms);
    const ctx    = document.getElementById('latencyTrend').getContext('2d');
    const chartData = {
      labels,
      datasets: [{
        label: 'Ø Latenz (ms)',
        data: values,
        borderColor: CHART_COLORS.yellow,
        backgroundColor: 'rgba(224,104,32,0.12)',
        tension: 0.4,
        fill: true,
        pointRadius: 3,
        pointBackgroundColor: CHART_COLORS.yellow,
      }],
    };
    if (latencyChart) {
      latencyChart.data = chartData;
      latencyChart.update();
    } else {
      latencyChart = new Chart(ctx, {
        type: 'line',
        data: chartData,
        options: {
          ...baseChartOptions,
          plugins: { legend: { display: false } },
          scales: {
            x: { ticks: { color: tickColor, maxTicksLimit: 8 }, grid: { color: gridColor } },
            y: { ticks: { color: tickColor }, grid: { color: gridColor }, beginAtZero: true },
          },
        },
      });
    }
  } catch (e) { console.error(e); }
}

// ── Packet loss trend ─────────────────────────────────────────
async function loadPacketLossTrend() {
  const hours = document.getElementById('packet-loss-hours')?.value ?? 24;
  try {
    const r    = await fetch(`/api/dashboard/packet-loss-trend?hours=${hours}`);
    const data = await r.json();
    const labels = data.map(d => fmtTime(d.time));
    const values = data.map(d => d.avg_loss);
    const ctx    = document.getElementById('packetLossChart').getContext('2d');
    const chartData = {
      labels,
      datasets: [{
        label: 'Ø Paketverlust (%)',
        data: values,
        borderColor: CHART_COLORS.red,
        backgroundColor: 'rgba(220,53,69,0.1)',
        tension: 0.4,
        fill: true,
        pointRadius: 3,
        pointBackgroundColor: CHART_COLORS.red,
      }],
    };
    if (lossChart) {
      lossChart.data = chartData;
      lossChart.update();
    } else {
      lossChart = new Chart(ctx, {
        type: 'line',
        data: chartData,
        options: {
          ...baseChartOptions,
          plugins: { legend: { display: false } },
          scales: {
            x: { ticks: { color: tickColor, maxTicksLimit: 8 }, grid: { color: gridColor } },
            y: { ticks: { color: tickColor }, grid: { color: gridColor }, beginAtZero: true, max: 100 },
          },
        },
      });
    }
  } catch (e) { console.error(e); }
}

// ── Device Table ──────────────────────────────────────────────
function renderTable(devices) {
  const tbody = document.getElementById('device-tbody');
  if (!devices.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-5">
      <i class="bi bi-hdd-network display-6 d-block mb-2"></i>
      Keine Geräte. <a href="/devices">Gerät hinzufügen</a>
    </td></tr>`;
    return;
  }
  tbody.innerHTML = devices.map(d => `
    <tr>
      <td><img src="${iconSrc(d)}" width="28" height="28" class="device-icon"
               onerror="this.src='/static/icons/generic.svg'"></td>
      <td><a href="/devices/${d.id}" class="text-decoration-none text-light fw-semibold">
        ${escHtml(d.name)}</a></td>
      <td><code class="text-muted">${d.ip_address}</code></td>
      <td><span class="text-muted small">${TYPE_LABELS[d.device_type] || d.device_type}</span></td>
      <td>${statusBadge(d.status)}</td>
      <td>${d.latency_ms != null
        ? `<span class="text-warning">${d.latency_ms.toFixed(1)} ms</span>`
        : '<span class="text-muted">–</span>'}</td>
      <td class="text-muted small">${fmtDate(d.last_seen)}</td>
      <td>
        <div class="btn-group btn-group-sm">
          <a href="/devices/${d.id}" class="btn btn-outline-secondary"><i class="bi bi-eye"></i></a>
          <button class="btn btn-outline-info" onclick="checkDevice(${d.id}, this)" title="Jetzt prüfen">
            <i class="bi bi-broadcast"></i>
          </button>
        </div>
      </td>
    </tr>
  `).join('');
}

async function checkDevice(id, btn) {
  btn.disabled = true;
  const orig = btn.innerHTML;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
  await fetch(`/api/check/device/${id}`, { method: 'POST' });
  setTimeout(async () => {
    await loadSummary();
    btn.disabled = false;
    btn.innerHTML = orig;
  }, 3000);
}

// ── Widget Customisation ──────────────────────────────────────
let editMode = false;
let _sortable = null;

function getPrefs() { return _prefs; }
function savePrefs(p) {
  _prefs = p;
  fetch('/api/user/dashboard-prefs', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prefs: p }),
  }).catch(() => {});
}

function applyWidgetVisibility() {
  const prefs = getPrefs();
  WIDGETS.forEach(w => {
    const el = document.getElementById(`widget-${w.id}`);
    if (el) {
      const hidden = prefs[w.id] === false || (prefs[w.id] === undefined && w.defaultHidden);
      el.style.display = hidden ? 'none' : '';
    }
  });
}

function isWidgetHidden(id) {
  const el = document.getElementById(`widget-${id}`);
  return !el || el.style.display === 'none';
}

function applyWidgetOrder() {
  const prefs = getPrefs();
  const order = prefs._order;
  if (!order || !order.length) return;
  const container = document.getElementById('widget-container');
  if (!container) return;
  order.forEach(id => {
    const el = document.getElementById(`widget-${id}`);
    if (el) container.appendChild(el);
  });
}

function buildWidgetToggles() {
  const prefs   = getPrefs();
  const container = document.getElementById('widget-toggles');
  if (!container) return;
  container.innerHTML = WIDGETS.map(w => {
    const visible = prefs[w.id] === undefined ? !w.defaultHidden : prefs[w.id] !== false;
    return `
      <div class="form-check form-check-inline">
        <input class="form-check-input" type="checkbox" id="tog-${w.id}"
               ${visible ? 'checked' : ''}
               onchange="toggleWidget('${w.id}', this.checked)">
        <label class="form-check-label small" for="tog-${w.id}">${w.label}</label>
      </div>
    `;
  }).join('');
}

const _WIDGET_LOADERS = {
  'syslog-summary': () => typeof loadSyslogSummary  === 'function' && loadSyslogSummary(),
  'snmp-alerts':    () => typeof loadSnmpAlertsDash === 'function' && loadSnmpAlertsDash(),
  'snmp-traps':     () => typeof loadTrapSummary    === 'function' && loadTrapSummary(),
  'dns-monitor':    () => typeof loadDnsMonitor     === 'function' && loadDnsMonitor(),
  'tcp-check':      () => typeof loadTcpCheck       === 'function' && loadTcpCheck(),
  'http-check':     () => typeof loadHttpCheck      === 'function' && loadHttpCheck(),
  'ssh-check':      () => typeof loadSshCheck       === 'function' && loadSshCheck(),
  'netflow':        () => typeof loadNetflow        === 'function' && loadNetflow(),
};

function toggleWidget(id, visible) {
  const el = document.getElementById(`widget-${id}`);
  if (el) el.style.display = visible ? '' : 'none';
  const prefs = getPrefs();
  prefs[id] = visible;
  savePrefs(prefs);
  if (visible && _WIDGET_LOADERS[id]) _WIDGET_LOADERS[id]();
}

function toggleEditMode() {
  editMode = !editMode;
  document.getElementById('edit-panel').style.display = editMode ? '' : 'none';
  const btn = document.getElementById('edit-toggle');
  const container = document.getElementById('widget-container');

  btn.innerHTML = editMode
    ? '<i class="bi bi-check-lg"></i> Fertig'
    : '<i class="bi bi-pencil-square"></i> Anpassen';
  btn.className = editMode
    ? 'btn btn-sm btn-warning'
    : 'btn btn-sm btn-outline-secondary';

  if (container) container.classList.toggle('edit-mode', editMode);

  if (editMode && typeof Sortable !== 'undefined') {
    _sortable = Sortable.create(container, {
      handle: '.widget-drag-handle',
      animation: 180,
      ghostClass: 'sortable-ghost',
      dragClass: 'sortable-drag',
      onEnd() {
        const order = [...container.children]
          .map(el => el.dataset.widgetId)
          .filter(Boolean);
        const prefs = getPrefs();
        prefs._order = order;
        savePrefs(prefs);
      },
    });
  } else if (_sortable) {
    _sortable.destroy();
    _sortable = null;
  }
}

function resetWidgets() {
  savePrefs({});
  const container = document.getElementById('widget-container');
  if (container) {
    const defaultOrder = WIDGETS.map(w => w.id);
    defaultOrder.forEach(id => {
      const el = document.getElementById(`widget-${id}`);
      if (el) container.appendChild(el);
    });
  }
  WIDGETS.forEach(w => {
    const el = document.getElementById(`widget-${w.id}`);
    if (el) {
      el.style.display = w.defaultHidden ? 'none' : '';
      applyWidthClass(el, DEFAULT_WIDTHS[w.id] || '1col');
    }
    const cb = document.getElementById(`tog-${w.id}`);
    if (cb) cb.checked = !w.defaultHidden;
  });
}

// ── Widget Width (3 states: full / 2col / 1col) ────────────────
const DEFAULT_WIDTHS = {
  'stat-cards': 'full', 'device-table': 'full',
  'status-donut': '2col', 'latency-trend': '2col',
  'device-latency': '2col', 'packet-loss': '2col',
  'syslog-summary': '2col', 'snmp-alerts': '2col',
  'snmp-traps': '2col', 'dns-monitor': '2col',
  'tcp-check': '2col', 'http-check': '2col',
  'ssh-check': '2col', 'netflow': '2col',
};

function getWidgetWidth(id) {
  const widths = getPrefs()._widths || {};
  return widths.hasOwnProperty(id) ? widths[id] : (DEFAULT_WIDTHS[id] || '1col');
}

function applyWidthClass(el, width) {
  el.classList.remove('widget-full', 'widget-2col');
  if (width === 'full') el.classList.add('widget-full');
  else if (width === '2col') el.classList.add('widget-2col');
}

function applyWidgetWidths() {
  // Migrate old boolean format to string format
  const prefs = getPrefs();
  if (prefs._widths) {
    let changed = false;
    Object.keys(prefs._widths).forEach(k => {
      if (typeof prefs._widths[k] === 'boolean') {
        prefs._widths[k] = prefs._widths[k] ? 'full' : '1col';
        changed = true;
      }
    });
    if (changed) savePrefs(prefs);
  }
  WIDGETS.forEach(w => {
    const el = document.getElementById(`widget-${w.id}`);
    if (el) applyWidthClass(el, getWidgetWidth(w.id));
  });
}

function toggleWidgetWidth(id) {
  const cycle = { 'full': '2col', '2col': '1col', '1col': 'full' };
  const next = cycle[getWidgetWidth(id)] || '2col';
  const el = document.getElementById(`widget-${id}`);
  if (el) applyWidthClass(el, next);
  const prefs = getPrefs();
  if (!prefs._widths) prefs._widths = {};
  prefs._widths[id] = next;
  savePrefs(prefs);
  setTimeout(() => {
    [donutChart, latencyChart, barChart, lossChart].forEach(c => c?.resize());
  }, 50);
}

// ── Helpers ───────────────────────────────────────────────────
function iconSrc(d) {
  if (d.icon_name?.startsWith('custom_')) return `/uploads/icons/${d.icon_name}`;
  return `/static/icons/${d.icon_name || d.device_type || 'generic'}.svg`;
}
function statusBadge(s) {
  const m = { online:['bg-success','Online'], offline:['bg-danger','Offline'], unknown:['bg-secondary','Unbekannt'] };
  const [cls,txt] = m[s] || m.unknown;
  return `<span class="badge ${cls}"><i class="bi bi-circle-fill" style="font-size:.45rem"></i> ${txt}</span>`;
}
function fmtDate(iso) {
  if (!iso) return '–';
  return new Date(iso).toLocaleString('de-DE', { dateStyle:'short', timeStyle:'short' });
}
function fmtTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleTimeString('de-DE', { hour:'2-digit', minute:'2-digit' });
}
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── DNS / URL Monitor Widget ───────────────────────────────────

async function loadDnsMonitor() {
  const body = document.getElementById('dns-monitor-body');
  if (!body) return;
  try {
    const r = await fetch('/api/url-monitors');
    if (!r.ok) return;
    const monitors = await r.json();
    if (!monitors.length) {
      body.innerHTML = `<div class="text-center text-muted small py-3">
        Keine URLs konfiguriert. <button class="btn btn-link btn-sm p-0" onclick="openDnsManage()">URL hinzufügen</button>
      </div>`;
      return;
    }
    body.innerHTML = `<table class="table table-dark table-sm mb-0" style="font-size:.78rem">
      <thead><tr><th>Name</th><th>URL</th><th>IP</th><th>Status</th><th class="text-muted">Zuletzt</th></tr></thead>
      <tbody>${monitors.map(m => {
        const online  = m.last_status === 'online';
        const unknown = m.last_status === 'unknown' || !m.last_status;
        const badge   = online
          ? '<span class="badge bg-success">Online</span>'
          : unknown
            ? '<span class="badge bg-secondary">Unbekannt</span>'
            : '<span class="badge bg-danger">Offline</span>';
        const ts = m.last_checked
          ? new Date(m.last_checked + 'Z').toLocaleString('de-DE', {dateStyle:'short',timeStyle:'short'})
          : '–';
        return `<tr>
          <td class="fw-semibold">${escHtml(m.name)}</td>
          <td class="text-muted text-truncate" style="max-width:140px" title="${escHtml(m.url)}">${escHtml(m.url)}</td>
          <td class="font-monospace text-muted" style="font-size:.72rem">${escHtml(m.last_ip || '–')}</td>
          <td>${badge}</td>
          <td class="text-muted" style="font-size:.7rem">${ts}</td>
        </tr>`;
      }).join('')}</tbody>
    </table>`;
  } catch(e) { console.error(e); }
}

// ── DNS Manage Modal ───────────────────────────────────────────

let _dnsMonitors = [];

async function openDnsManage() {
  const modal = new bootstrap.Modal(document.getElementById('dnsManageModal'));
  modal.show();
  await renderDnsManageList();
}

async function renderDnsManageList() {
  const body = document.getElementById('dns-manage-body');
  body.innerHTML = '<div class="text-center text-muted small py-3">Lade...</div>';
  const r = await fetch('/api/url-monitors');
  _dnsMonitors = await r.json();
  if (!_dnsMonitors.length) {
    body.innerHTML = '<p class="text-muted small text-center py-2">Noch keine URLs. Klicke "+ URL hinzufügen".</p>';
    return;
  }
  body.innerHTML = `<table class="table table-dark table-sm mb-0" style="font-size:.8rem">
    <thead><tr><th>Name</th><th>URL</th><th>Intervall</th><th>Aktiv</th><th></th></tr></thead>
    <tbody>${_dnsMonitors.map(m => `
      <tr id="dns-row-${m.id}">
        <td>${escHtml(m.name)}</td>
        <td class="text-muted text-truncate" style="max-width:160px">${escHtml(m.url)}</td>
        <td>${m.interval_s}s</td>
        <td>${m.enabled ? '<span class="badge bg-success">Ja</span>' : '<span class="badge bg-secondary">Nein</span>'}</td>
        <td class="text-end">
          <button class="btn btn-sm btn-outline-warning py-0 px-1 me-1" onclick="editDnsEntry(${m.id})" title="Bearbeiten"><i class="bi bi-pencil"></i></button>
          <button class="btn btn-sm btn-outline-danger py-0 px-1" onclick="deleteDnsEntry(${m.id})" title="Löschen"><i class="bi bi-trash"></i></button>
        </td>
      </tr>`).join('')}
    </tbody>
  </table>`;
}

function showAddDnsForm() {
  const body = document.getElementById('dns-manage-body');
  body.innerHTML = `
    <div class="p-2">
      <div class="mb-2"><label class="form-label small">Name</label>
        <input id="dns-new-name" type="text" class="form-control form-control-sm" placeholder="z.B. Firmenwebsite">
      </div>
      <div class="mb-2"><label class="form-label small">URL / Hostname</label>
        <input id="dns-new-url" type="text" class="form-control form-control-sm" placeholder="https://example.com oder server.local">
      </div>
      <div class="mb-3"><label class="form-label small">Intervall (Sekunden)</label>
        <input id="dns-new-interval" type="number" class="form-control form-control-sm" value="300" min="30">
      </div>
      <div class="d-flex gap-2">
        <button class="btn btn-sm btn-warning" onclick="saveDnsEntry()"><i class="bi bi-check-lg"></i> Speichern</button>
        <button class="btn btn-sm btn-secondary" onclick="renderDnsManageList()">Abbrechen</button>
      </div>
    </div>`;
}

function editDnsEntry(id) {
  const m = _dnsMonitors.find(x => x.id === id);
  if (!m) return;
  const body = document.getElementById('dns-manage-body');
  body.innerHTML = `
    <div class="p-2">
      <input type="hidden" id="dns-edit-id" value="${m.id}">
      <div class="mb-2"><label class="form-label small">Name</label>
        <input id="dns-new-name" type="text" class="form-control form-control-sm" value="${escHtml(m.name)}">
      </div>
      <div class="mb-2"><label class="form-label small">URL / Hostname</label>
        <input id="dns-new-url" type="text" class="form-control form-control-sm" value="${escHtml(m.url)}">
      </div>
      <div class="mb-2"><label class="form-label small">Intervall (Sekunden)</label>
        <input id="dns-new-interval" type="number" class="form-control form-control-sm" value="${m.interval_s}" min="30">
      </div>
      <div class="mb-3 form-check">
        <input type="checkbox" class="form-check-input" id="dns-new-enabled" ${m.enabled ? 'checked' : ''}>
        <label class="form-check-label small" for="dns-new-enabled">Aktiv</label>
      </div>
      <div class="d-flex gap-2">
        <button class="btn btn-sm btn-warning" onclick="saveDnsEntry(${m.id})"><i class="bi bi-check-lg"></i> Speichern</button>
        <button class="btn btn-sm btn-secondary" onclick="renderDnsManageList()">Abbrechen</button>
      </div>
    </div>`;
}

async function saveDnsEntry(editId) {
  const name     = document.getElementById('dns-new-name').value.trim();
  const url      = document.getElementById('dns-new-url').value.trim();
  const interval_s = parseInt(document.getElementById('dns-new-interval').value) || 300;
  const enabled  = document.getElementById('dns-new-enabled')?.checked ?? true;
  if (!name || !url) { alert('Name und URL erforderlich'); return; }
  if (editId) {
    await fetch(`/api/url-monitors/${editId}`, {
      method: 'PUT', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ name, url, interval_s, enabled }),
    });
  } else {
    await fetch('/api/url-monitors', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ name, url, interval_s }),
    });
  }
  await renderDnsManageList();
  loadDnsMonitor();
}

async function deleteDnsEntry(id) {
  if (!confirm('URL-Monitor wirklich löschen?')) return;
  await fetch(`/api/url-monitors/${id}`, { method: 'DELETE' });
  await renderDnsManageList();
  loadDnsMonitor();
}

// ── Widget Notification Modal ──────────────────────────────────

const NOTIF_WIDGET_META = {
  status:         { label: 'Gerät Status',           hasThreshold: false, thresholdUnit: '',    hasSeverity: false, hasTimer: true,  hasMessage: true,  excPlaceholder: 'IP-Adresse oder Hostname' },
  icmp_avg:       { label: 'Ø Latenz (alle Geräte)', hasThreshold: true,  thresholdUnit: 'ms',  hasSeverity: false, hasTimer: true,  hasMessage: false, excPlaceholder: 'IP-Adresse oder Hostname' },
  device_latency: { label: 'Latenz je Gerät',        hasThreshold: true,  thresholdUnit: 'ms',  hasSeverity: false, hasTimer: true,  hasMessage: false, excPlaceholder: 'IP-Adresse oder Hostname' },
  packet_loss:    { label: 'Ø Paketverlust',          hasThreshold: true,  thresholdUnit: '%',   hasSeverity: false, hasTimer: true,  hasMessage: false, excPlaceholder: 'IP-Adresse oder Hostname' },
  syslog:         { label: 'Syslog',                  hasThreshold: false, thresholdUnit: '',    hasSeverity: true,  hasTimer: false, hasMessage: false, excPlaceholder: 'IP-Adresse oder Hostname' },
  snmp:           { label: 'SNMP-Meldungen',          hasThreshold: false, thresholdUnit: '',    hasSeverity: true,  hasTimer: false, hasMessage: false, excPlaceholder: 'IP-Adresse oder Hostname' },
  dns:            { label: 'URL-Monitor (DNS)',        hasThreshold: false, thresholdUnit: '',    hasSeverity: false, hasTimer: true,  hasMessage: false, excPlaceholder: 'URL'                      },
  snmp_trap:      { label: 'SNMP Traps',               hasThreshold: false, thresholdUnit: '',    hasSeverity: false, hasTimer: false, hasMessage: false, excPlaceholder: 'IP-Adresse'               },
  tcp:            { label: 'TCP-Port Check',           hasThreshold: true,  thresholdUnit: 'ms',  hasSeverity: false, hasTimer: true,  hasMessage: false, excPlaceholder: 'IP-Adresse oder Hostname' },
  http_check:     { label: 'HTTP/HTTPS Check',         hasThreshold: true,  thresholdUnit: 'ms',  hasSeverity: false, hasTimer: true,  hasMessage: false, excPlaceholder: 'URL oder IP-Adresse'      },
  ssh:            { label: 'SSH Banner-Check',         hasThreshold: false, thresholdUnit: '',    hasSeverity: false, hasTimer: true,  hasMessage: false, excPlaceholder: 'IP-Adresse oder Hostname' },
  netflow:        { label: 'NetFlow/sFlow',            hasThreshold: false, thresholdUnit: '',    hasSeverity: false, hasTimer: false, hasMessage: false, excPlaceholder: 'IP-Adresse'               },
};

let _currentNotifType = null;
let _currentNotifRule = null;

async function openNotifModal(widgetType) {
  _currentNotifType = widgetType;
  const meta = NOTIF_WIDGET_META[widgetType] || { label: widgetType };
  document.getElementById('notif-modal-title').textContent = 'Benachrichtigungen – ' + meta.label;
  document.getElementById('notif-modal-msg').textContent = '';
  document.getElementById('notif-modal-body').innerHTML =
    '<div class="text-center text-muted small py-3"><span class="spinner-border spinner-border-sm"></span></div>';

  const modal = new bootstrap.Modal(document.getElementById('notifModal'));
  modal.show();

  const r = await fetch(`/api/notifications/rules/${widgetType}`);
  _currentNotifRule = r.ok ? await r.json() : null;
  renderNotifModalBody(_currentNotifRule, meta);
}

function renderNotifModalBody(rule, meta) {
  const enabled    = rule?.enabled ? true : false;
  const threshold  = rule?.threshold || '';
  const sevFilter  = rule?.severity_filter || '';
  const minDur     = rule?.min_duration_minutes ?? (meta.hasTimer ? 5 : 0);
  const message    = rule?.message || '';
  const exceptions = rule?.exceptions || [];

  let html = `
    <div class="mb-3">
      <div class="form-check form-switch">
        <input class="form-check-input" type="checkbox" id="notif-enabled" ${enabled ? 'checked' : ''}>
        <label class="form-check-label" for="notif-enabled">Benachrichtigungen aktiviert</label>
      </div>
    </div>`;

  if (meta.hasThreshold) {
    html += `
    <div class="mb-3">
      <label class="form-label small">Schwellwert <span class="text-muted">(Meldung wenn Wert überschritten)</span></label>
      <div class="input-group input-group-sm" style="max-width:200px">
        <input type="number" id="notif-threshold" class="form-control" value="${escHtml(threshold)}" min="0" step="1" placeholder="0">
        <span class="input-group-text">${meta.thresholdUnit}</span>
      </div>
    </div>`;
  }

  if (meta.hasSeverity) {
    const sevOptions = _currentNotifType === 'syslog'
      ? ['', 'emerg','alert','crit','err','warning','notice','info']
      : ['', 'warning','critical'];
    const sevLabels = { '':'Alle', emerg:'Emergency', alert:'Alert', crit:'Critical',
                        err:'Error', warning:'Warning', notice:'Notice', info:'Info', critical:'Critical' };
    html += `
    <div class="mb-3">
      <label class="form-label small">Schweregrad-Filter <span class="text-muted">(ab diesem Level melden)</span></label>
      <select id="notif-severity" class="form-select form-select-sm" style="max-width:200px">
        ${sevOptions.map(v => `<option value="${v}" ${sevFilter===v?'selected':''}>${sevLabels[v]||v}</option>`).join('')}
      </select>
    </div>`;
  }

  if (meta.hasTimer) {
    html += `
    <div class="mb-3">
      <label class="form-label small">Mindestdauer <span class="text-muted">(Minuten, 0 = sofort)</span></label>
      <div class="input-group input-group-sm" style="max-width:160px">
        <input type="number" id="notif-timer" class="form-control" value="${minDur}" min="0" max="60" step="1">
        <span class="input-group-text">min</span>
      </div>
      <div class="form-text" style="font-size:.68rem">Verhindert Fehlalarme: Meldung erst nach anhaltender Überschreitung.</div>
    </div>`;
  }

  if (meta.hasMessage) {
    html += `
    <div class="mb-3">
      <label class="form-label small">Benachrichtigungstext <span class="text-muted">(leer = Standard)</span></label>
      <textarea id="notif-message" class="form-control form-control-sm" rows="3"
        placeholder="Gerät ist offline – bitte prüfen.">${escHtml(message)}</textarea>
    </div>`;
  }

  // Exceptions
  html += `
    <div class="mb-2">
      <label class="form-label small d-flex justify-content-between align-items-center">
        <span>Ausnahmen <span class="text-muted">(keine Meldung für diese Einträge)</span></span>
        <button class="btn btn-sm btn-outline-secondary py-0 px-1" onclick="notifAddExcRow()"><i class="bi bi-plus-lg"></i></button>
      </label>
      <div id="notif-exc-list">
        ${exceptions.map(e => notifExcRow(e)).join('')}
        ${!exceptions.length ? '<div class="text-muted small" id="notif-exc-empty">Keine Ausnahmen</div>' : ''}
      </div>
    </div>`;

  document.getElementById('notif-modal-body').innerHTML = html;
}

function notifExcRow(exc) {
  return `<div class="input-group input-group-sm mb-1" id="notif-exc-${exc.id}">
    <input type="text" class="form-control" value="${escHtml(exc.value)}" readonly>
    <button class="btn btn-outline-danger" onclick="notifDelExc(${exc.id})"><i class="bi bi-x-lg"></i></button>
  </div>`;
}

function notifAddExcRow() {
  const list = document.getElementById('notif-exc-list');
  const empty = document.getElementById('notif-exc-empty');
  if (empty) empty.remove();
  const div = document.createElement('div');
  div.className = 'input-group input-group-sm mb-1 notif-exc-new';
  const _excPlaceholder = (NOTIF_WIDGET_META[_currentNotifType] || {}).excPlaceholder || 'IP-Adresse oder Hostname';
  div.innerHTML = `
    <input type="text" class="form-control notif-exc-input" placeholder="${_excPlaceholder}">
    <button class="btn btn-outline-success" onclick="notifSaveNewExc(this)"><i class="bi bi-check-lg"></i></button>
    <button class="btn btn-outline-secondary" onclick="this.closest('.notif-exc-new').remove()"><i class="bi bi-x-lg"></i></button>`;
  list.appendChild(div);
}

async function notifSaveNewExc(btn) {
  const input = btn.closest('.notif-exc-new').querySelector('.notif-exc-input');
  const value = input.value.trim();
  if (!value) return;
  const r = await fetch(`/api/notifications/rules/${_currentNotifType}/exceptions`, {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ value }),
  });
  if (r.ok) {
    const exc = await r.json();
    const parent = btn.closest('.notif-exc-new');
    parent.outerHTML = notifExcRow(exc);
    if (!_currentNotifRule) _currentNotifRule = { exceptions: [] };
    (_currentNotifRule.exceptions = _currentNotifRule.exceptions || []).push(exc);
  }
}

async function notifDelExc(excId) {
  await fetch(`/api/notifications/exceptions/${excId}`, { method: 'DELETE' });
  document.getElementById(`notif-exc-${excId}`)?.remove();
  if (_currentNotifRule?.exceptions) {
    _currentNotifRule.exceptions = _currentNotifRule.exceptions.filter(e => e.id !== excId);
  }
  if (!document.querySelectorAll('#notif-exc-list .input-group').length) {
    document.getElementById('notif-exc-list').innerHTML =
      '<div class="text-muted small" id="notif-exc-empty">Keine Ausnahmen</div>';
  }
}

async function saveNotifRule() {
  const msg = document.getElementById('notif-modal-msg');
  const enabled   = document.getElementById('notif-enabled')?.checked ? 1 : 0;
  const threshold = document.getElementById('notif-threshold')?.value?.trim() || '';
  const sevFilter = document.getElementById('notif-severity')?.value || '';
  const minDur    = parseInt(document.getElementById('notif-timer')?.value || '0') || 0;
  const message   = document.getElementById('notif-message')?.value?.trim() || '';
  const r = await fetch(`/api/notifications/rules/${_currentNotifType}`, {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ enabled, threshold, severity_filter: sevFilter, min_duration_minutes: minDur, message }),
  });
  msg.innerHTML = r.ok
    ? '<span class="text-success"><i class="bi bi-check-lg"></i> Gespeichert</span>'
    : '<span class="text-danger">Fehler beim Speichern</span>';
}

// ══════════════════════════════════════════════════════════════
// ── Active Alerts ─────────────────────────────────────────────
// ══════════════════════════════════════════════════════════════

const ALERT_WIDGET_LABELS = {
  status: 'Gerät Status', icmp_avg: 'Ø Latenz', device_latency: 'Latenz/Gerät',
  packet_loss: 'Paketverlust', syslog: 'Syslog', snmp: 'SNMP', dns: 'URL-Monitor',
};

let _alertsAll = [];       // cache of all active alerts
let _alertsFilter = 'all'; // 'all' | 'open' | 'acked'
let _alertsWidgetFilter = null; // null = all, string = widget_type

async function loadAlertCounts() {
  try {
    const r = await fetch('/api/alerts/unacked-counts');
    if (!r.ok) return;
    const counts = await r.json();
    let total = 0;
    // Update per-widget badges
    Object.keys(ALERT_WIDGET_LABELS).forEach(wt => {
      const cnt   = counts[wt] || 0;
      const btn   = document.getElementById(`alert-btn-${wt}`);
      const badge = document.getElementById(`alert-cnt-${wt}`);
      if (btn && badge) {
        btn.style.display  = cnt > 0 ? '' : 'none';
        badge.textContent  = cnt > 0 ? cnt : '';
      }
      total += cnt;
    });
    // Update navbar badge
    const navBtn   = document.getElementById('nav-alert-btn');
    const navCount = document.getElementById('nav-alert-count');
    if (navBtn && navCount) {
      navBtn.style.display  = total > 0 ? '' : 'none';
      navCount.textContent  = total > 0 ? total : '';
    }
  } catch (_) {}
}

// Alias so base.html can call this via openAlertsOverview → openAlertsOverviewModal
async function openAlertsOverviewModal(widgetType) {
  return openAlertsOverview(widgetType);
}

async function openAlertsOverview(widgetType) {
  _alertsWidgetFilter = widgetType || null;
  _alertsFilter = 'all';
  const title = document.getElementById('alerts-modal-title');
  if (title) {
    const wLabel = widgetType ? (ALERT_WIDGET_LABELS[widgetType] || widgetType) : 'Alle';
    title.innerHTML = `<i class="bi bi-bell-fill text-danger me-2"></i>Aktive Meldungen – ${escHtml(wLabel)}`;
  }
  const modal = new bootstrap.Modal(document.getElementById('alertsModal'));
  modal.show();
  await refreshAlerts();
}

async function refreshAlerts() {
  document.getElementById('alerts-table-body').innerHTML =
    '<div class="text-center text-muted py-3"><span class="spinner-border spinner-border-sm"></span></div>';
  try {
    const url = _alertsWidgetFilter
      ? `/api/alerts/active/${encodeURIComponent(_alertsWidgetFilter)}`
      : '/api/alerts/active';
    const r = await fetch(url);
    _alertsAll = r.ok ? await r.json() : [];
  } catch (_) { _alertsAll = []; }
  renderAlertsTable();
}

function filterAlerts(mode) {
  _alertsFilter = mode;
  ['all','open','acked'].forEach(m => {
    document.getElementById(`af-btn-${m}`)?.classList.toggle('active', m === mode);
  });
  renderAlertsTable();
}

function renderAlertsTable() {
  let list = _alertsAll;
  if (_alertsFilter === 'open')  list = list.filter(a => !a.acked);
  if (_alertsFilter === 'acked') list = list.filter(a =>  a.acked);
  const label = document.getElementById('alerts-filter-label');
  if (label) label.textContent = `${list.length} Eintr${list.length === 1 ? 'ag' : 'äge'}`;

  if (!list.length) {
    document.getElementById('alerts-table-body').innerHTML =
      `<div class="text-center text-muted py-4"><i class="bi bi-check-circle text-success fs-4"></i><div class="mt-1 small">Keine aktiven Meldungen</div></div>`;
    return;
  }

  const rows = list.map(a => {
    const sinceTs = a.triggered_at ? new Date(a.triggered_at + 'Z').toLocaleString('de-DE') : '–';
    const wLabel  = ALERT_WIDGET_LABELS[a.widget_type] || a.widget_type;
    const ackedBadge = a.acked
      ? `<span class="badge bg-secondary">Quittiert<br><small class="fw-normal">${escHtml(a.acked_by || '')} ${a.acked_at ? new Date(a.acked_at+'Z').toLocaleString('de-DE') : ''}</small></span>`
      : '<span class="badge bg-danger">Offen</span>';
    const comment = a.ack_comment ? `<div class="text-muted small mt-1"><i class="bi bi-chat-quote me-1"></i>${escHtml(a.ack_comment)}</div>` : '';
    const ackBtn = !a.acked
      ? `<button class="btn btn-sm btn-outline-warning py-0 px-2" onclick="openAckForm('${escHtml(a.widget_type)}','${escHtml(a.entity_id)}',this)"><i class="bi bi-check-lg me-1"></i>Quittieren</button>`
      : `<button class="btn btn-sm btn-outline-secondary py-0 px-2" onclick="removeAck('${escHtml(a.widget_type)}','${escHtml(a.entity_id)}')"><i class="bi bi-arrow-counterclockwise me-1"></i>Zurücksetzen</button>`;
    return `<tr>
      <td><span class="badge bg-secondary">${escHtml(wLabel)}</span></td>
      <td><strong>${escHtml(a.entity_name || a.entity_id)}</strong><div class="text-muted small font-monospace">${escHtml(a.entity_id)}</div></td>
      <td class="small text-muted">${sinceTs}</td>
      <td>${ackedBadge}${comment}</td>
      <td>${ackBtn}</td>
    </tr>`;
  }).join('');

  document.getElementById('alerts-table-body').innerHTML = `
    <table class="table table-dark table-sm table-hover mb-0">
      <thead class="text-muted" style="font-size:.75rem">
        <tr><th>Widget</th><th>Entität</th><th>Seit</th><th>Status</th><th>Aktion</th></tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function openAckForm(widgetType, entityId, btn) {
  const td = btn.closest('td');
  td.innerHTML = `
    <div class="d-flex gap-1 align-items-center flex-wrap">
      <input type="text" class="form-control form-control-sm" id="ack-comment-field"
             placeholder="Kommentar (optional)" style="max-width:200px">
      <button class="btn btn-sm btn-warning py-0 px-2"
              onclick="submitAck('${escHtml(widgetType)}','${escHtml(entityId)}')">
        <i class="bi bi-check-lg"></i> OK
      </button>
      <button class="btn btn-sm btn-outline-secondary py-0 px-2" onclick="refreshAlerts()">
        <i class="bi bi-x-lg"></i>
      </button>
    </div>`;
  document.getElementById('ack-comment-field')?.focus();
}

async function submitAck(widgetType, entityId) {
  const comment = document.getElementById('ack-comment-field')?.value?.trim() || '';
  await fetch(`/api/alerts/ack/${encodeURIComponent(widgetType)}/${encodeURIComponent(entityId)}`, {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ comment }),
  });
  await refreshAlerts();
  loadAlertCounts();
}

async function removeAck(widgetType, entityId) {
  await fetch(`/api/alerts/ack/${encodeURIComponent(widgetType)}/${encodeURIComponent(entityId)}`,
    { method: 'DELETE' });
  await refreshAlerts();
  loadAlertCounts();
}

// ══════════════════════════════════════════════════════════════
// ── Maintenance Windows ────────────────────────────────────────
// ══════════════════════════════════════════════════════════════

let _maintWindows = [];

async function loadMaintenanceWindows() {
  document.getElementById('maint-list').innerHTML =
    '<div class="text-center text-muted py-3"><span class="spinner-border spinner-border-sm"></span></div>';
  hideMaintForm();
  // Load devices for dropdown
  try {
    const dr = await fetch('/api/devices/');
    const devices = dr.ok ? await dr.json() : [];
    const sel = document.getElementById('mf-device');
    if (sel) {
      sel.innerHTML = '<option value="">— Alle Geräte (global) —</option>' +
        devices.map(d => `<option value="${d.id}">${escHtml(d.name)} (${escHtml(d.ip_address)})</option>`).join('');
    }
  } catch (_) {}
  // Load windows
  try {
    const r = await fetch('/api/maintenance/');
    _maintWindows = r.ok ? await r.json() : [];
  } catch (_) { _maintWindows = []; }
  renderMaintList();
}

function renderMaintList() {
  const el = document.getElementById('maint-list');
  if (!_maintWindows.length) {
    el.innerHTML = '<div class="text-muted small text-center py-3"><i class="bi bi-info-circle me-1"></i>Keine Wartungsfenster konfiguriert.</div>';
    return;
  }
  const now = new Date().toISOString().slice(0, 19);
  const rows = _maintWindows.map(mw => {
    const start = mw.start_dt ? mw.start_dt.replace('T',' ').slice(0,16) : '–';
    const end   = mw.end_dt   ? mw.end_dt.replace('T',' ').slice(0,16)   : '–';
    const isActive = !mw.repeat_weekly
      ? (mw.start_dt <= now && now <= mw.end_dt)
      : false;
    const statusBadge = !mw.enabled
      ? '<span class="badge bg-secondary">Inaktiv</span>'
      : isActive
        ? '<span class="badge" style="background:#e06820">Aktiv jetzt</span>'
        : '<span class="badge bg-success">Bereit</span>';
    const weeklyBadge = mw.repeat_weekly ? '<span class="badge bg-info text-dark ms-1">wöchentl.</span>' : '';
    const device = mw.device_name ? escHtml(mw.device_name) : '<span class="text-muted">Alle Geräte</span>';
    return `<tr>
      <td>${escHtml(mw.name)}</td>
      <td>${device}</td>
      <td class="small">${start}${weeklyBadge}</td>
      <td class="small">${end}</td>
      <td>${statusBadge}</td>
      <td class="text-end">
        <button class="btn btn-sm btn-outline-secondary py-0 px-1 me-1" onclick="editMaintWindow(${mw.id})" title="Bearbeiten"><i class="bi bi-pencil"></i></button>
        <button class="btn btn-sm btn-outline-danger py-0 px-1" onclick="deleteMaintWindow(${mw.id})" title="Löschen"><i class="bi bi-trash"></i></button>
      </td>
    </tr>`;
  }).join('');
  el.innerHTML = `<table class="table table-dark table-sm table-hover mb-0">
    <thead class="text-muted" style="font-size:.75rem">
      <tr><th>Name</th><th>Gerät</th><th>Beginn</th><th>Ende</th><th>Status</th><th class="text-end">Aktionen</th></tr>
    </thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function showAddMaintForm() {
  document.getElementById('mf-id').value    = '';
  document.getElementById('mf-name').value  = '';
  document.getElementById('mf-device').value = '';
  document.getElementById('mf-start').value  = '';
  document.getElementById('mf-end').value    = '';
  document.getElementById('mf-weekly').checked  = false;
  document.getElementById('mf-enabled').checked = true;
  document.getElementById('maint-form-title').textContent = 'Neues Wartungsfenster';
  document.getElementById('maint-form-msg').innerHTML = '';
  document.getElementById('maint-form').style.display = '';
  document.getElementById('mf-name').focus();
}

function hideMaintForm() {
  document.getElementById('maint-form').style.display = 'none';
}

function editMaintWindow(id) {
  const mw = _maintWindows.find(m => m.id === id);
  if (!mw) return;
  document.getElementById('mf-id').value     = mw.id;
  document.getElementById('mf-name').value   = mw.name;
  document.getElementById('mf-device').value = mw.device_id || '';
  document.getElementById('mf-start').value  = mw.start_dt ? mw.start_dt.slice(0,16) : '';
  document.getElementById('mf-end').value    = mw.end_dt   ? mw.end_dt.slice(0,16)   : '';
  document.getElementById('mf-weekly').checked  = !!mw.repeat_weekly;
  document.getElementById('mf-enabled').checked = !!mw.enabled;
  document.getElementById('maint-form-title').textContent = 'Wartungsfenster bearbeiten';
  document.getElementById('maint-form-msg').innerHTML = '';
  document.getElementById('maint-form').style.display = '';
  document.getElementById('mf-name').focus();
}

async function saveMaintWindow() {
  const msg  = document.getElementById('maint-form-msg');
  const id   = document.getElementById('mf-id').value;
  const name = document.getElementById('mf-name').value.trim();
  const start = document.getElementById('mf-start').value;
  const end   = document.getElementById('mf-end').value;
  if (!name || !start || !end) {
    msg.innerHTML = '<span class="text-danger">Name, Beginn und Ende sind Pflichtfelder.</span>';
    return;
  }
  if (start >= end) {
    msg.innerHTML = '<span class="text-danger">Ende muss nach dem Beginn liegen.</span>';
    return;
  }
  const body = {
    name,
    device_id: document.getElementById('mf-device').value ? parseInt(document.getElementById('mf-device').value) : null,
    start_dt:  start,
    end_dt:    end,
    repeat_weekly: document.getElementById('mf-weekly').checked ? 1 : 0,
    enabled:   document.getElementById('mf-enabled').checked ? 1 : 0,
  };
  const url    = id ? `/api/maintenance/${id}` : '/api/maintenance/';
  const method = id ? 'PUT' : 'POST';
  const r = await fetch(url, { method, headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
  if (r.ok) {
    hideMaintForm();
    await loadMaintenanceWindows();
  } else {
    msg.innerHTML = '<span class="text-danger">Fehler beim Speichern.</span>';
  }
}

async function deleteMaintWindow(id) {
  if (!confirm('Wartungsfenster wirklich löschen?')) return;
  await fetch(`/api/maintenance/${id}`, { method: 'DELETE' });
  await loadMaintenanceWindows();
}

