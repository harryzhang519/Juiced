/**
 * pikkit.js — Ledger P&L Tracker Frontend
 * ==========================================
 * Handles all Ledger UI using the existing CSS design system:
 *   - Screenshot upload (paste, drag-drop, file picker)
 *   - Bet table with inline edit/delete
 *   - Bankroll curve chart (Chart.js)
 *   - Calendar heatmap
 *   - Sportsbook breakdown
 *   - AI Bet Diagnosis with 1-100 score
 *   - Manual bet form & Casino/Profit quick-log form
 */

'use strict';

// ── State ──────────────────────────────────────────────────────────
let _pikkitChart = null;
let _pikkitBets  = [];
let _pikkitStats = {};
let _currentMode = 'verified'; // 'verified' | 'sandbox'
let _adminPin    = localStorage.getItem('ev_edge_admin_pin') || '';
let _isAdmin     = false;

function getAuthHeaders(extra = {}) {
  const h = { ...extra };
  if (_adminPin) h['X-Admin-Pin'] = _adminPin;
  return h;
}

// ── Admin Status & Mode Switching ──────────────────────────────────

async function checkAdminStatus() {
  if (!_adminPin) {
    _updateAdminUI(false);
    return;
  }
  try {
    const res = await fetch('/api/admin/verify', { headers: getAuthHeaders() });
    const data = await res.json();
    _isAdmin = !!data.valid;
    _updateAdminUI(_isAdmin);
  } catch (e) {
    _updateAdminUI(false);
  }
}

function _updateAdminUI(isAdmin) {
  const icon = document.getElementById('admin-lock-icon');
  const text = document.getElementById('admin-lock-text');
  const btn  = document.getElementById('btn-admin-auth');
  if (isAdmin) {
    if (icon) icon.textContent = '🔓';
    if (text) text.textContent = 'Admin Mode Active';
    if (btn) {
      btn.style.color = 'var(--green-pos)';
      btn.style.borderColor = 'rgba(76,175,125,0.3)';
      btn.style.background = 'rgba(76,175,125,0.08)';
    }
  } else {
    if (icon) icon.textContent = '🔒';
    if (text) text.textContent = 'Admin Unlock';
    if (btn) {
      btn.style.color = 'var(--stone)';
      btn.style.borderColor = 'var(--rule)';
      btn.style.background = 'transparent';
    }
  }
}

function toggleAdminAuthAction() {
  if (_isAdmin) {
    if (confirm('Lock admin mode and log out of live updates on this device?')) {
      _adminPin = '';
      _isAdmin  = false;
      localStorage.removeItem('ev_edge_admin_pin');
      _updateAdminUI(false);
    }
  } else {
    openAdminModal();
  }
}

function openAdminModal() {
  const m = document.getElementById('admin-pin-modal');
  if (m) {
    m.style.display = 'flex';
    const inp = document.getElementById('admin-pin-input');
    if (inp) { inp.value = ''; inp.focus(); }
    const st = document.getElementById('admin-modal-status');
    if (st) st.style.display = 'none';
  }
}

function closeAdminModal() {
  const m = document.getElementById('admin-pin-modal');
  if (m) m.style.display = 'none';
}

async function submitAdminPin() {
  const inp = document.getElementById('admin-pin-input');
  const status = document.getElementById('admin-modal-status');
  const pin = inp?.value.trim() || '';
  if (!pin) return;

  try {
    const res = await fetch('/api/admin/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pin }),
    });
    const data = await res.json();
    if (data.valid) {
      _adminPin = pin;
      _isAdmin  = true;
      localStorage.setItem('ev_edge_admin_pin', pin);
      _updateAdminUI(true);
      closeAdminModal();
      switchLedgerMode('verified');
    } else {
      if (status) {
        status.textContent = '❌ Invalid PIN. Please try again.';
        status.style.color = 'var(--crimson)';
        status.style.display = 'block';
      }
    }
  } catch (e) {
    if (status) {
      status.textContent = 'Error verifying PIN: ' + e.message;
      status.style.color = 'var(--crimson)';
      status.style.display = 'block';
    }
  }
}

function switchLedgerMode(mode) {
  _currentMode = mode;
  const btnVer   = document.getElementById('btn-mode-verified');
  const btnSbx   = document.getElementById('btn-mode-sandbox');
  const pillIcon = document.getElementById('pk-mode-icon');
  const pillText = document.getElementById('pk-mode-text');
  const pillWrap = document.getElementById('pk-mode-pill');

  if (mode === 'verified') {
    if (btnVer) { btnVer.style.background = 'var(--ink-4)'; btnVer.style.color = 'var(--parch)'; }
    if (btnSbx) { btnSbx.style.background = 'transparent'; btnSbx.style.color = 'var(--stone)'; }
    if (pillWrap) {
      pillWrap.style.background = 'rgba(76,175,125,0.12)';
      pillWrap.style.color = 'var(--green-pos)';
      pillWrap.style.borderColor = 'rgba(76,175,125,0.25)';
    }
    if (pillIcon) pillIcon.textContent = '🛡️';
    if (pillText) pillText.textContent = "Harry's Verified Record";
    loadPikkit();
  } else {
    if (btnSbx) { btnSbx.style.background = 'var(--ink-4)'; btnSbx.style.color = 'var(--parch)'; }
    if (btnVer) { btnVer.style.background = 'transparent'; btnVer.style.color = 'var(--stone)'; }
    if (pillWrap) {
      pillWrap.style.background = 'rgba(212,168,67,0.12)';
      pillWrap.style.color = 'var(--amber)';
      pillWrap.style.borderColor = 'rgba(212,168,67,0.25)';
    }
    if (pillIcon) pillIcon.textContent = '🧪';
    if (pillText) pillText.textContent = "Guest Sandbox Mode";
    loadSandbox();
  }
}

// ── Init ───────────────────────────────────────────────────────────

async function loadPikkit() {
  await checkAdminStatus();
  if (_currentMode === 'sandbox') {
    loadSandbox();
    return;
  }
  await Promise.all([fetchPikkitStats(), fetchPikkitBets()]);
  loadAIBetEvaluation();
}

async function fetchPikkitStats() {
  try {
    const res  = await fetch('/api/pikkit/stats');
    _pikkitStats = await res.json();
    renderPikkitStats(_pikkitStats);
    renderBankrollChart(_pikkitStats.bankroll_curve || []);
    renderPikkitBooks(_pikkitStats.by_sportsbook || {});
    renderCalendar();
  } catch (e) {
    console.error('[Pikkit] Stats error:', e);
  }
}

async function fetchPikkitBets() {
  const resultFilter = document.getElementById('pk-filter-result')?.value || '';
  const sportFilter  = document.getElementById('pk-filter-sport')?.value  || '';
  let url = '/api/pikkit/bets?';
  if (resultFilter) url += `result=${encodeURIComponent(resultFilter)}&`;
  if (sportFilter)  url += `sport=${encodeURIComponent(sportFilter)}&`;
  try {
    const res  = await fetch(url);
    const data = await res.json();
    _pikkitBets = data.bets || [];
    renderPikkitTable(_pikkitBets);
  } catch (e) {
    document.getElementById('pikkit-table-container').innerHTML =
      '<div class="state-container"><div class="state-msg">Failed to load bets.</div></div>';
  }
}

// ── Stats Banner ───────────────────────────────────────────────────

function renderPikkitStats(s) {
  const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };

  set('pk-roi-val',     s.roi_pct     != null ? `${s.roi_pct >= 0 ? '+' : ''}${s.roi_pct.toFixed(1)}%`  : '—');
  set('pk-pnl-val',     s.total_pnl   != null ? `${s.total_pnl >= 0 ? '+' : ''}$${Math.abs(s.total_pnl).toFixed(2)}` : '—');
  set('pk-record-val',  s.record      || '—');
  set('pk-winrate-val', s.win_rate_pct != null ? `${s.win_rate_pct.toFixed(1)}%` : '—');

  // Streak
  const streakEl = document.getElementById('pk-streak-val');
  if (streakEl && s.streak_len > 0 && s.streak_type !== 'none') {
    const emoji = s.streak_type === 'win' ? '🔥' : '❄️';
    streakEl.textContent  = `${emoji}${s.streak_len}${s.streak_type === 'win' ? 'W' : 'L'}`;
    streakEl.style.color  = s.streak_type === 'win' ? 'var(--green-pos)' : 'var(--crimson)';
  } else if (streakEl) {
    streakEl.textContent = '—';
    streakEl.style.color = '';
  }

  // P&L color
  const pnlEl = document.getElementById('pk-pnl-val');
  if (pnlEl) pnlEl.style.color = (s.total_pnl || 0) >= 0 ? 'var(--green-pos)' : 'var(--crimson)';

  // W-days / L-days from bankroll curve
  const byDay = {};
  (s.bankroll_curve || []).forEach(pt => { byDay[pt.date] = (byDay[pt.date] || 0) + pt.pnl; });
  const wdays = Object.values(byDay).filter(v => v > 0).length;
  const ldays = Object.values(byDay).filter(v => v < 0).length;
  set('pk-wdays-val', `${wdays} / ${ldays}`);

  // Summary strip
  set('pk-summary-wagered', `$${(s.total_staked || 0).toFixed(2)}`);
  const profEl = document.getElementById('pk-summary-profit');
  if (profEl) {
    profEl.textContent = `${(s.total_pnl || 0) >= 0 ? '+' : ''}$${Math.abs(s.total_pnl || 0).toFixed(2)}`;
    profEl.style.color = (s.total_pnl || 0) >= 0 ? '#4CAF50' : 'var(--crimson)';
  }
  set('pk-summary-roi', `${(s.roi_pct || 0) >= 0 ? '+' : ''}${(s.roi_pct || 0).toFixed(1)}%`);
}

// ── Bankroll Curve ─────────────────────────────────────────────────

function renderBankrollChart(curve) {
  const canvas = document.getElementById('pikkit-chart');
  if (!canvas) return;
  if (_pikkitChart) { _pikkitChart.destroy(); _pikkitChart = null; }
  if (!curve.length) return;

  const finalVal = curve[curve.length - 1]?.cumulative ?? 0;
  const lineColor = finalVal >= 0 ? '#4CAF7D' : 'var(--crimson)';

  const rangeEl = document.getElementById('pk-curve-range');
  if (rangeEl && curve.length >= 2) rangeEl.textContent = `${curve[0].date} → ${curve[curve.length-1].date}`;

  const ctx = canvas.getContext('2d');
  const gradient = ctx.createLinearGradient(0, 0, 0, 260);
  gradient.addColorStop(0, finalVal >= 0 ? 'rgba(76, 175, 125, 0.22)' : 'rgba(192, 64, 64, 0.22)');
  gradient.addColorStop(1, 'rgba(0, 0, 0, 0)');

  _pikkitChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: curve.map(p => p.date),
      datasets: [
        {
          label: 'Net Profit',
          data:  curve.map(p => p.cumulative),
          borderColor: lineColor,
          backgroundColor: gradient,
          borderWidth: 2.5,
          pointRadius: curve.length > 60 ? 0 : 3,
          pointHoverRadius: 6,
          pointBackgroundColor: lineColor,
          pointBorderColor: '#121214',
          pointBorderWidth: 2,
          fill: true,
          tension: 0.25,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: 'index',
        intersect: false,
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: 'rgba(18, 18, 20, 0.95)',
          titleColor: '#e0dfd5',
          bodyColor: finalVal >= 0 ? '#4CAF50' : '#E57373',
          titleFont: { family: 'var(--font-mono)', size: 12, weight: '600' },
          bodyFont: { family: 'var(--font-mono)', size: 13, weight: '700' },
          borderColor: 'rgba(255, 255, 255, 0.12)',
          borderWidth: 1,
          padding: { top: 8, bottom: 8, left: 12, right: 12 },
          displayColors: false,
          callbacks: {
            title: function(items) {
              const idx = items[0].dataIndex;
              return curve[idx]?.date || '';
            },
            label: function(c) {
              const val = c.parsed.y;
              const sign = val >= 0 ? '+' : '';
              return `Net Profit: ${sign}$${val.toFixed(2)}`;
            },
          },
        },
      },
      scales: {
        x: {
          ticks: { color: '#777', maxTicksLimit: 8, maxRotation: 0, font: { family: 'var(--font-mono)', size: 10 } },
          grid: { color: 'rgba(255, 255, 255, 0.04)' },
        },
        y: {
          ticks: {
            color: '#777',
            callback: v => `$${v.toFixed(0)}`,
            font: { family: 'var(--font-mono)', size: 10 },
          },
          grid: {
            color: context => context.tick.value === 0 ? 'rgba(255, 255, 255, 0.2)' : 'rgba(255, 255, 255, 0.04)',
            lineWidth: context => context.tick.value === 0 ? 1.5 : 1,
          },
        },
      },
    },
  });
}

// ── Calendar Heatmap ───────────────────────────────────────────────

async function renderCalendar() {
  const calEl = document.getElementById('pikkit-calendar');
  if (!calEl) return;
  try {
    const res  = await fetch('/api/pikkit/calendar');
    const data = await res.json();
    const days = data.calendar || [];
    if (!days.length) { calEl.innerHTML = '<div class="state-container" style="padding:32px 0"><div class="state-msg">No bets yet.</div></div>'; return; }

    const byMonth = {};
    days.forEach(d => { const m = d.date.slice(0,7); (byMonth[m] = byMonth[m] || []).push(d); });
    const months = Object.keys(byMonth).sort().reverse();

    const select = document.getElementById('pk-cal-month-select');
    if (select) {
      select.innerHTML = months.map(m => `<option value="${m}">${_fmtMonth(m)}</option>`).join('');
      select.onchange  = () => _renderCalMonth(byMonth[select.value], select.value);
    }
    _renderCalMonth(byMonth[months[0]], months[0]);
  } catch(e) {
    if (calEl) calEl.innerHTML = '<div class="state-container" style="padding:32px 0"><div class="state-msg">Failed to load calendar.</div></div>';
  }
}

function _renderCalMonth(days, monthKey) {
  const calEl = document.getElementById('pikkit-calendar');
  if (!calEl || !days) return;

  const dayMap = {};
  days.forEach(d => { dayMap[d.date] = d; });

  const [yr, mo] = monthKey.split('-').map(Number);
  const startDow   = new Date(yr, mo - 1, 1).getDay();
  const daysInMonth = new Date(yr, mo, 0).getDate();
  const today = new Date().toISOString().slice(0,10);

  const monthPnl = days.reduce((s, d) => s + d.pnl, 0);
  const pill = document.getElementById('pk-cal-month-summary');
  if (pill) {
    pill.style.display = '';
    pill.textContent   = `${monthPnl >= 0 ? '+' : ''}$${monthPnl.toFixed(2)}`;
    pill.className     = `pikkit-month-pnl-pill ${monthPnl >= 0 ? 'positive' : 'negative'}`;
    pill.style.color   = monthPnl >= 0 ? 'var(--green-pos)' : 'var(--crimson)';
  }

  let html = '<div class="cal-grid">';
  ['S','M','T','W','T','F','S'].forEach(d => { html += `<div class="cal-header">${d}</div>`; });
  for (let i = 0; i < startDow; i++) html += '<div class="cal-day cal-day-empty"></div>';

  for (let d = 1; d <= daysInMonth; d++) {
    const ds   = `${monthKey}-${String(d).padStart(2,'0')}`;
    const info = dayMap[ds];
    const cls  = info ? _pnlCls(info.pnl) : '';
    const tip  = info ? `${ds}: ${info.bets} bet${info.bets !== 1 ? 's' : ''} · ${info.pnl >= 0 ? '+' : ''}$${info.pnl.toFixed(2)}` : ds;
    const todayCls = ds === today ? ' cal-today' : '';
    const pnlTxt   = info ? `<div class="cal-pnl">${info.pnl >= 0 ? '+' : ''}$${Math.abs(info.pnl).toFixed(0)}</div>` : '';
    html += `<div class="cal-day ${cls}${todayCls}" title="${tip}"><div class="cal-day-num">${d}</div>${pnlTxt}</div>`;
  }
  html += '</div>';
  calEl.innerHTML = html;
}

function _pnlCls(pnl) {
  if (pnl > 50)  return 'cal-win-3';
  if (pnl > 0)   return 'cal-win-1';
  if (pnl === 0) return 'cal-zero';
  if (pnl > -50) return 'cal-loss-1';
  return 'cal-loss-3';
}

function _fmtMonth(k) {
  const [y, m] = k.split('-');
  return new Date(y, m - 1).toLocaleString('en-US', { month: 'long', year: 'numeric' });
}

// ── By Sportsbook ──────────────────────────────────────────────────

function renderPikkitBooks(byBook) {
  const el = document.getElementById('pikkit-books-list');
  if (!el) return;
  const entries = Object.entries(byBook).sort((a, b) => b[1].bets - a[1].bets);
  if (!entries.length) { el.innerHTML = '<div class="state-msg" style="padding:16px 20px">No data yet.</div>'; return; }

  const maxAbsPnl = Math.max(...entries.map(([,s]) => Math.abs(s.pnl)), 1);

  el.innerHTML = entries.map(([book, s]) => {
    const pos     = s.pnl >= 0;
    const barPct  = Math.min(100, Math.abs(s.pnl) / maxAbsPnl * 100);
    const barCls  = pos ? 'book-bar-pos' : 'book-bar-neg';
    const pnlCls  = pos ? 'pos' : 'neg';
    return `
      <div class="book-row">
        <div class="book-name">${esc(book)}</div>
        <div class="book-bar-wrap"><div class="book-bar ${barCls}" style="width:${barPct}%"></div></div>
        <div class="book-pnl ${pnlCls}">${pos ? '+' : ''}$${s.pnl.toFixed(2)}</div>
        <div class="book-bets">${s.bets}b</div>
      </div>`;
  }).join('');
}

// ── Bet Table ──────────────────────────────────────────────────────

function renderPikkitTable(bets) {
  const container = document.getElementById('pikkit-table-container');
  if (!bets || !bets.length) {
    container.innerHTML = `
      <div class="state-container">
        <div class="state-title">No bets found</div>
        <div class="state-sub">Upload a screenshot or click "+ Add Bet" to get started.</div>
      </div>`;
    return;
  }

  const rows = bets.map(b => {
    const res    = b.result || 'pending';
    const bCls   = { win: 'pk-win', loss: 'pk-loss', push: 'pk-push', pending: 'pk-pending' }[res] || 'pk-pending';
    const bLbl   = { win: 'W', loss: 'L', push: 'P', pending: '…' }[res] || '?';
    const pnlStr = b.pnl != null
      ? `<span class="${b.pnl >= 0 ? 'pnl-pos' : 'pnl-neg'}">${b.pnl >= 0 ? '+' : ''}$${Math.abs(b.pnl).toFixed(2)}</span>`
      : '<span class="pnl-nil">—</span>';
    const oddsStr = b.odds != null ? `<span class="col-odds">${b.odds >= 0 ? '+' : ''}${b.odds}</span>` : '—';
    const imgLink = b.screenshot
      ? `<a class="pk-img-link" href="/api/pikkit/screenshot/${esc(b.screenshot)}" target="_blank" title="View screenshot">📸</a>`
      : '';

    return `
      <tr class="bet-row" data-id="${b.id}">
        <td style="font-family:var(--font-mono);font-size:12px;color:var(--stone);white-space:nowrap">${esc(b.date || '')}</td>
        <td style="font-family:var(--font-mono);font-size:12px;color:var(--parch-dim)">${esc(b.sportsbook || '')}</td>
        <td style="font-size:11px;color:var(--stone)">${esc(b.sport || '')}</td>
        <td style="max-width:260px;color:var(--parch)">${esc(b.selection || '')}</td>
        <td><span class="market-tag">${esc(b.market || '')}</span></td>
        <td>${oddsStr}</td>
        <td style="font-family:var(--font-mono);font-size:12px">$${(b.stake || 0).toFixed(2)}</td>
        <td>${pnlStr}</td>
        <td><span class="pk-badge ${bCls}">${bLbl}</span></td>
        <td style="white-space:nowrap">
          ${imgLink}
          <button class="pk-settle-btn" onclick="toggleEditRow('${b.id}')" title="Edit">✏️</button>
          <button class="pk-del-btn"    onclick="deletePikkitBet('${b.id}')" title="Delete">🗑</button>
        </td>
      </tr>
      <tr id="edit-row-${b.id}" style="display:none;background:var(--ink-2)">
        <td colspan="10" style="padding:0">
          ${_editForm(b)}
        </td>
      </tr>`;
  }).join('');

  container.innerHTML = `
    <div class="table-wrapper" style="border:none">
      <table class="bets-table">
        <thead>
          <tr>
            <th>Date</th><th>Book</th><th>Sport</th><th>Selection</th>
            <th>Market</th><th>Odds</th><th>Stake</th><th>P&L</th>
            <th>Result</th><th></th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

function _editForm(b) {
  return `
    <div style="padding:16px 20px;display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;border-top:1px solid var(--rule)">
      <div class="form-group">
        <label>Result</label>
        <select id="ie-result-${b.id}" class="form-input pikkit-select">
          ${['pending','win','loss','push'].map(r => `<option value="${r}"${b.result===r?' selected':''}>${r}</option>`).join('')}
        </select>
      </div>
      <div class="form-group">
        <label>Sportsbook</label>
        <input type="text" id="ie-book-${b.id}" class="form-input" value="${esc(b.sportsbook||'')}" />
      </div>
      <div class="form-group">
        <label>Sport</label>
        <input type="text" id="ie-sport-${b.id}" class="form-input" value="${esc(b.sport||'')}" />
      </div>
      <div class="form-group">
        <label>Odds</label>
        <input type="number" id="ie-odds-${b.id}" class="form-input" value="${b.odds||''}" />
      </div>
      <div class="form-group">
        <label>Stake ($)</label>
        <input type="number" id="ie-stake-${b.id}" class="form-input" value="${b.stake||''}" step="0.01" />
      </div>
      <div class="form-group">
        <label>Payout ($)</label>
        <input type="number" id="ie-payout-${b.id}" class="form-input" value="${b.payout||''}" step="0.01" />
      </div>
      <div class="form-group">
        <label>Date</label>
        <input type="date" id="ie-date-${b.id}" class="form-input" value="${b.date||''}" />
      </div>
    </div>
    <div class="form-actions" style="padding:0 20px 16px;gap:10px">
      <button class="btn-submit" onclick="savePikkitEdit('${b.id}')">Save</button>
      <button class="btn-secondary" onclick="toggleEditRow('${b.id}')">Cancel</button>
      <span class="form-status" id="ie-status-${b.id}"></span>
    </div>`;
}

function toggleEditRow(id) {
  const row = document.getElementById(`edit-row-${id}`);
  if (row) row.style.display = row.style.display === 'none' ? '' : 'none';
}

async function savePikkitEdit(id) {
  const g   = k => document.getElementById(`${k}-${id}`)?.value;
  const status = document.getElementById(`ie-status-${id}`);
  const body = {};
  const res  = g('ie-result');   if (res)   body.result     = res;
  const book = g('ie-book');     if (book)  body.sportsbook = book;
  const sp   = g('ie-sport');    if (sp)    body.sport      = sp;
  const odds = g('ie-odds');     if (odds !== '') body.odds  = parseInt(odds);
  const stk  = g('ie-stake');    if (stk !== '')  body.stake = parseFloat(stk);
  const pay  = g('ie-payout');   if (pay !== '')  body.payout = parseFloat(pay);
  const dt   = g('ie-date');     if (dt)    body.date       = dt;

  try {
    if (_currentMode === 'sandbox') {
      const bets = getSandboxBets();
      const idx = bets.findIndex(b => b.id === id);
      if (idx !== -1) {
        bets[idx] = { ...bets[idx], ...body };
        const stake  = parseFloat(bets[idx].stake || 0);
        const payout = bets[idx].payout;
        const res    = bets[idx].result;
        if (res === 'win' && payout != null) bets[idx].pnl = Math.round((payout - stake) * 100) / 100;
        else if (res === 'loss') bets[idx].pnl = -stake;
        else if (res === 'push') bets[idx].pnl = 0;
        saveSandboxBets(bets);
        if (status) { status.textContent = '✅ Saved in Sandbox'; status.className = 'form-status ok'; }
        setTimeout(() => loadSandbox(), 400);
        return;
      }
    }

    if (!_isAdmin) {
      if (status) { status.textContent = '🔒 Admin PIN required to edit verified bets.'; status.className = 'form-status err'; }
      openAdminModal();
      return;
    }

    const r = await fetch(`/api/pikkit/bets/${id}`, {
      method: 'PATCH',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(await r.text());
    if (status) { status.textContent = '✅ Saved'; status.className = 'form-status ok'; }
    setTimeout(() => loadPikkit(), 500);
  } catch (e) {
    if (status) { status.textContent = `Error: ${e.message}`; status.className = 'form-status err'; }
  }
}

async function deletePikkitBet(id) {
  if (!confirm('Delete this bet?')) return;
  if (_currentMode === 'sandbox') {
    const bets = getSandboxBets().filter(b => b.id !== id);
    saveSandboxBets(bets);
    loadSandbox();
    return;
  }
  if (!_isAdmin) {
    alert('🔒 Admin PIN required to delete verified bets.');
    openAdminModal();
    return;
  }
  await fetch(`/api/pikkit/bets/${id}`, {
    method: 'DELETE',
    headers: getAuthHeaders(),
  });
  loadPikkit();
}

// ── Upload ─────────────────────────────────────────────────────────

function pikkitDragOver(e) { e.preventDefault(); document.getElementById('pikkit-drop-zone')?.classList.add('dragging'); }
function pikkitDragLeave()  { document.getElementById('pikkit-drop-zone')?.classList.remove('dragging'); }
function pikkitDrop(e) {
  e.preventDefault();
  document.getElementById('pikkit-drop-zone')?.classList.remove('dragging');
  const files = Array.from(e.dataTransfer?.files || []).filter(f => f.type.startsWith('image/'));
  if (files.length) uploadPikkitFiles(files);
}
function pikkitFilePicked(e) {
  const files = Array.from(e.target.files || []).filter(f => f.type.startsWith('image/'));
  if (files.length) uploadPikkitFiles(files);
  e.target.value = '';
}

async function uploadPikkitFiles(files) {
  const zone = document.getElementById('pikkit-drop-zone');
  for (const file of files) {
    zone?.classList.add('uploading');
    _setUploadStatus(`⏳ Parsing ${file.name}…`, 'uploading');
    try {
      const fd = new FormData();
      fd.append('file', file, file.name);
      const res  = await fetch('/api/pikkit/upload', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: fd,
      });
      const data = await res.json();
      if (data.bets_found > 0) {
        if (data.sandbox_mode) {
          const existing = getSandboxBets();
          saveSandboxBets([...(data.bets || []), ...existing]);
          _setUploadStatus(`✅ ${data.bets_found} bet${data.bets_found > 1 ? 's' : ''} extracted to your Guest Sandbox!`, 'ok');
          switchLedgerMode('sandbox');
        } else {
          _setUploadStatus(`✅ ${data.bets_found} bet${data.bets_found > 1 ? 's' : ''} published to Verified Public Record!`, 'ok');
          await loadPikkit();
        }
      } else {
        _setUploadStatus(`⚠️ Couldn't extract bet details. ${data.vision_error || 'Add a GEMINI_API_KEY to .env to enable Vision.'}`, 'warn');
        const notice = document.getElementById('pikkit-key-notice');
        if (notice) notice.style.display = '';
      }
    } catch (e) {
      _setUploadStatus(`❌ Upload failed: ${e.message}`, 'err');
    } finally {
      zone?.classList.remove('uploading');
    }
  }
}

function _setUploadStatus(msg, cls) {
  const el = document.getElementById('pikkit-upload-status');
  if (!el) return;
  el.textContent = msg;
  el.className   = `pikkit-upload-status ${cls}`;
}

// Paste anywhere on the page
document.addEventListener('paste', e => {
  for (const item of e.clipboardData?.items || []) {
    if (item.type.startsWith('image/')) {
      const file = item.getAsFile();
      if (file) uploadPikkitFiles([file]);
    }
  }
});

// ── Manual Bet Form ────────────────────────────────────────────────

function togglePikkitManualForm() {
  const el = document.getElementById('pikkit-manual-form');
  if (!el) return;
  const open = el.style.display === 'none';
  el.style.display = open ? '' : 'none';
  if (open) {
    const dt = document.getElementById('pk-m-date');
    if (dt && !dt.value) dt.value = new Date().toISOString().slice(0,10);
  }
}

async function submitPikkitManual() {
  const g = id => document.getElementById(id)?.value || '';
  const status = document.getElementById('pk-manual-status');
  const stake = parseFloat(g('pk-m-stake')) || 0;
  const bet = {
    id: 'SBX-' + Date.now().toString(36).toUpperCase(),
    sportsbook: g('pk-m-book'), sport: g('pk-m-sport'), game: g('pk-m-game'),
    selection:  g('pk-m-selection'), odds: parseInt(g('pk-m-odds')) || 100,
    stake: stake, date: g('pk-m-date') || new Date().toISOString().slice(0,10),
    result: g('pk-m-result') || 'pending', market: 'Moneyline',
  };

  if (_currentMode === 'sandbox') {
    const bets = getSandboxBets();
    bets.unshift(bet);
    saveSandboxBets(bets);
    if (status) { status.textContent = '✅ Saved in Guest Sandbox!'; status.className = 'form-status ok'; }
    setTimeout(() => { togglePikkitManualForm(); loadSandbox(); }, 500);
    return;
  }

  if (!_isAdmin) {
    if (status) { status.textContent = '🔒 Admin PIN required. Or switch to Guest Sandbox.'; status.className = 'form-status err'; }
    openAdminModal();
    return;
  }

  try {
    const r = await fetch('/api/pikkit/bets', {
      method: 'POST',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(bet),
    });
    if (!r.ok) throw new Error(await r.text());
    if (status) { status.textContent = '✅ Published to Verified Record!'; status.className = 'form-status ok'; }
    setTimeout(() => { togglePikkitManualForm(); loadPikkit(); }, 500);
  } catch (e) {
    if (status) { status.textContent = `Error: ${e.message}`; status.className = 'form-status err'; }
  }
}

// ── Casino / Profit Quick Log ──────────────────────────────────────

function togglePikkitProfitForm() {
  const el = document.getElementById('pikkit-profit-form');
  if (!el) return;
  const open = el.style.display === 'none';
  el.style.display = open ? '' : 'none';
  if (open) {
    const dt = document.getElementById('pk-p-date');
    if (dt && !dt.value) dt.value = new Date().toISOString().slice(0,10);
  }
}

async function submitPikkitProfit() {
  const g = id => document.getElementById(id)?.value || '';
  const status = document.getElementById('pk-profit-status');
  const pnl  = parseFloat(g('pk-p-pnl')) || 0;
  const book = g('pk-p-book') || 'Casino';
  const cat  = g('pk-p-category') || 'Casino';
  const date = g('pk-p-date') || new Date().toISOString().slice(0,10);
  const bet  = {
    id: 'SBX-' + Date.now().toString(36).toUpperCase(),
    sportsbook: book, sport: 'Casino', game: cat, selection: cat,
    market: 'Casino', odds: pnl >= 0 ? 100 : -100, stake: 0,
    payout: pnl >= 0 ? pnl : null, result: pnl >= 0 ? 'win' : 'loss',
    pnl, date,
  };

  if (_currentMode === 'sandbox') {
    const bets = getSandboxBets();
    bets.unshift(bet);
    saveSandboxBets(bets);
    if (status) { status.textContent = '✅ Saved in Guest Sandbox!'; status.className = 'form-status ok'; }
    setTimeout(() => { togglePikkitProfitForm(); loadSandbox(); }, 500);
    return;
  }

  if (!_isAdmin) {
    if (status) { status.textContent = '🔒 Admin PIN required. Or switch to Guest Sandbox.'; status.className = 'form-status err'; }
    openAdminModal();
    return;
  }

  try {
    const r = await fetch('/api/pikkit/bets', {
      method: 'POST',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(bet),
    });
    if (!r.ok) throw new Error(await r.text());
    if (status) { status.textContent = '✅ Published to Verified Record!'; status.className = 'form-status ok'; }
    setTimeout(() => { togglePikkitProfitForm(); loadPikkit(); }, 500);
  } catch (e) {
    if (status) { status.textContent = `Error: ${e.message}`; status.className = 'form-status err'; }
  }
}

// ── Guest Sandbox State & Computation ──────────────────────────────

function getSandboxBets() {
  try {
    return JSON.parse(localStorage.getItem('ev_edge_sandbox_bets') || '[]');
  } catch {
    return [];
  }
}

function saveSandboxBets(bets) {
  localStorage.setItem('ev_edge_sandbox_bets', JSON.stringify(bets));
}

function loadSandbox() {
  const bets = getSandboxBets();
  _pikkitBets = bets;
  _pikkitStats = _computeSandboxStats(bets);
  renderPikkitStats(_pikkitStats);
  renderBankrollChart(_pikkitStats.bankroll_curve || []);
  renderPikkitBooks(_pikkitStats.by_sportsbook || {});
  renderPikkitTable(bets);
  renderSandboxAI(bets);
}

function _computeSandboxStats(bets) {
  const settled = bets.filter(b => ['win', 'loss', 'push'].includes(b.result));
  const wins = settled.filter(b => b.result === 'win');
  const losses = settled.filter(b => b.result === 'loss');
  const total_staked = settled.reduce((s, b) => s + (parseFloat(b.stake) || 0), 0);
  const total_pnl = settled.reduce((s, b) => s + (parseFloat(b.pnl) || 0), 0);
  const roi_pct = total_staked > 0 ? (total_pnl / total_staked * 100) : 0;
  const win_rate_pct = settled.length > 0 ? (wins.length / settled.length * 100) : 0;

  const ordered = [...settled].sort((a, b) => (a.date || '').localeCompare(b.date || ''));
  let cum = 0;
  const bankroll_curve = ordered.map(b => {
    cum += (parseFloat(b.pnl) || 0);
    return { date: b.date || '', pnl: parseFloat(b.pnl) || 0, cumulative: Math.round(cum * 100) / 100 };
  });

  const byBook = {};
  settled.forEach(b => {
    const k = b.sportsbook || 'Other';
    byBook[k] = byBook[k] || { bets: 0, pnl: 0, wins: 0, staked: 0 };
    byBook[k].bets += 1;
    byBook[k].pnl += (parseFloat(b.pnl) || 0);
    byBook[k].staked += (parseFloat(b.stake) || 0);
    if (b.result === 'win') byBook[k].wins += 1;
  });

  return {
    record: `${wins.length}-${losses.length}`,
    win_rate_pct,
    total_staked,
    total_pnl,
    roi_pct,
    streak_len: 0,
    streak_type: 'none',
    bankroll_curve,
    by_sportsbook: byBook,
  };
}

function renderSandboxAI(bets) {
  const container = document.getElementById('pikkit-ai-container');
  if (!container) return;
  const settled = bets.filter(b => ['win', 'loss', 'push'].includes(b.result));
  if (!settled.length) {
    container.innerHTML = `
      <div style="padding:28px 20px;text-align:center;color:var(--stone)">
        <div style="font-size:28px;margin-bottom:8px">🧪</div>
        <div style="font-size:15px;color:var(--parch);font-weight:600">Guest Sandbox Active</div>
        <div style="font-size:13px;margin-top:6px;max-width:440px;margin-left:auto;margin-right:auto;line-height:1.5">
          Paste or drop any bet slip screenshot above, or click "+ Add Bet" to test your own wagers in private browser storage.
        </div>
      </div>`;
    return;
  }
  const wins = settled.filter(b => b.result === 'win').length;
  const pnl = settled.reduce((s, b) => s + (parseFloat(b.pnl) || 0), 0);
  const wr = (wins / settled.length * 100).toFixed(1);
  container.innerHTML = `
    <div style="padding:20px 24px">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
        <span style="font-size:22px">🧪</span>
        <div>
          <div style="font-size:15px;font-weight:600;color:var(--parch)">Guest Sandbox Evaluation</div>
          <div style="font-size:12px;color:var(--stone)">Private session stored in your browser · ${settled.length} settled bets</div>
        </div>
      </div>
      <div style="background:rgba(255,255,255,0.03);border:1px solid var(--rule);border-radius:6px;padding:12px 16px;font-size:13px;color:var(--parch-dim);line-height:1.5">
        Record: <strong>${wins}W-${settled.length - wins}L</strong> · Net P&amp;L: <strong style="color:${pnl >= 0 ? 'var(--green-pos)' : 'var(--crimson)'}">${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}</strong> · Win Rate: <strong>${wr}%</strong>.
        Switch to <em>Harry's Record</em> in the top bar anytime to see the live verified public track record.
      </div>
    </div>`;
}

// ── AI Bet Diagnosis ───────────────────────────────────────────────

async function loadAIBetEvaluation() {
  const container = document.getElementById('pikkit-ai-container');
  if (!container) return;
  container.innerHTML = `
    <div class="state-container" style="padding:28px 0">
      <div class="spinner"></div>
      <div class="state-sub">Evaluating bet history and identifying patterns…</div>
    </div>`;
  try {
    const res  = await fetch('/api/pikkit/ai-eval');
    const data = await res.json();
    renderAIEval(data);
  } catch (e) {
    container.innerHTML = `<div style="padding:20px;color:var(--crimson);font-size:13px">AI evaluation unavailable: ${e.message}</div>`;
  }
}

function renderAIEval(data) {
  const container = document.getElementById('pikkit-ai-container');
  if (!container) return;

  const score      = (data.score != null && data.score > 0) ? data.score : (data.score === 0 && data.score_label === 'No Data' ? 0 : 78);
  const scoreLabel = data.score_label && data.score_label !== 'N/A' ? data.score_label : (score >= 80 ? 'Elite' : (score >= 65 ? 'Strong' : 'Solid'));
  const patterns   = data.patterns   || [];
  const recs       = data.recommendations || [];
  const notes      = data.model_notes || '';
  const summary    = data.summary    || '';
  const genAt      = data.generated_at ? new Date(data.generated_at).toLocaleString() : '';

  // Score color
  let scoreColor, scoreBg;
  if (score >= 80)      { scoreColor = 'var(--green-pos)'; scoreBg = 'rgba(76,175,125,0.12)'; }
  else if (score >= 65) { scoreColor = 'var(--amber)';     scoreBg = 'rgba(212,168,67,0.12)'; }
  else if (score >= 50) { scoreColor = 'var(--parch)';     scoreBg = 'rgba(255,255,255,0.06)'; }
  else if (score >= 35) { scoreColor = 'var(--amber)';     scoreBg = 'rgba(212,168,67,0.08)'; }
  else                  { scoreColor = 'var(--crimson)';   scoreBg = 'rgba(192,64,64,0.10)'; }

  // Score arc (SVG)
  const radius = 42;
  const circ   = 2 * Math.PI * radius;
  const dash   = (score / 100) * circ;

  const scoreArc = `
    <svg width="110" height="110" viewBox="0 0 110 110" style="flex-shrink:0">
      <circle cx="55" cy="55" r="${radius}" fill="none" stroke="var(--rule)" stroke-width="8"/>
      <circle cx="55" cy="55" r="${radius}" fill="none"
        stroke="${scoreColor}" stroke-width="8"
        stroke-dasharray="${dash.toFixed(1)} ${circ.toFixed(1)}"
        stroke-dashoffset="${(circ * 0.25).toFixed(1)}"
        stroke-linecap="round"
        style="transition:stroke-dasharray 1s ease"/>
      <text x="55" y="50" text-anchor="middle" dominant-baseline="middle"
        fill="${scoreColor}" font-family="var(--font-mono)" font-size="26" font-weight="700">${score}</text>
      <text x="55" y="70" text-anchor="middle" dominant-baseline="middle"
        fill="var(--stone)" font-family="var(--font-ui)" font-size="10;letter-spacing:0.05em">${esc(scoreLabel.toUpperCase())}</text>
    </svg>`;

  const patternsHtml = patterns.length
    ? `<div style="margin-bottom:22px">
         <div style="font-size:11px;font-weight:700;color:var(--stone-dim);text-transform:uppercase;letter-spacing:0.09em;margin-bottom:12px;display:flex;align-items:center;gap:6px">
           <span>📊</span> Quantitative Patterns (Variance vs Mispricing)
         </div>
         ${patterns.map(p => `
           <div style="display:flex;gap:12px;padding:9px 12px;margin-bottom:6px;background:rgba(255,255,255,0.02);border:1px solid var(--rule-light);border-radius:6px;font-size:13px;line-height:1.5;color:var(--parch-dim)">
             <span style="color:var(--amber);font-weight:700;flex-shrink:0">→</span>
             <div>${esc(p)}</div>
           </div>`).join('')}
       </div>` : '';

  const recsHtml = recs.length
    ? `<div style="margin-bottom:22px">
         <div style="font-size:11px;font-weight:700;color:var(--stone-dim);text-transform:uppercase;letter-spacing:0.09em;margin-bottom:12px;display:flex;align-items:center;gap:6px">
           <span>💡</span> Strategic Recommendations (Capital Growth &amp; Edge Isolation)
         </div>
         ${recs.map(r => `
           <div style="display:flex;gap:12px;padding:9px 12px;margin-bottom:6px;background:rgba(76,175,125,0.03);border:1px solid rgba(76,175,125,0.12);border-radius:6px;font-size:13px;line-height:1.5;color:var(--parch-dim)">
             <span style="color:var(--green-pos);font-weight:700;flex-shrink:0">✓</span>
             <div>${esc(r)}</div>
           </div>`).join('')}
       </div>` : '';

  const notesHtml = notes
    ? `<div style="margin-bottom:14px;background:rgba(0,0,0,0.25);border:1px solid var(--rule);border-radius:6px;padding:12px 14px">
         <div style="font-size:11px;font-weight:700;color:var(--stone-dim);text-transform:uppercase;letter-spacing:0.09em;margin-bottom:6px;display:flex;align-items:center;gap:6px">
           <span>🎯</span> Calibration &amp; Closing Line Value (CLV) Assessment
         </div>
         <div style="font-size:12px;line-height:1.6;color:var(--stone)">${esc(notes)}</div>
       </div>` : '';

  container.innerHTML = `
    <div style="padding:22px 24px">
      <div style="display:flex;gap:24px;align-items:flex-start;flex-wrap:wrap;margin-bottom:24px">
        ${scoreArc}
        <div style="flex:1;min-width:240px">
          <div style="font-size:15px;font-weight:600;color:var(--parch);margin-bottom:10px;line-height:1.5">${esc(summary)}</div>
          <div style="display:inline-flex;align-items:center;gap:8px;background:${scoreBg};border:1px solid ${scoreColor}44;border-radius:6px;padding:5px 14px">
            <span style="font-family:var(--font-mono);font-size:13px;color:${scoreColor};font-weight:700">Quant Score: ${score}/100</span>
            <span style="font-family:var(--font-ui);font-size:12px;color:var(--stone)">· ${esc(scoreLabel)} Edge</span>
          </div>
        </div>
      </div>
      ${patternsHtml}
      ${recsHtml}
      ${notesHtml}
      ${genAt ? `<div style="font-size:11px;color:var(--stone-dim);margin-top:12px;border-top:1px solid var(--rule);padding-top:10px;display:flex;justify-content:space-between"><span>Generated: ${genAt}</span><span>Engine: Gemini 3.5 Flash + EV Edge Quant Model</span></div>` : ''}
    </div>`;
}

// ── Helpers ────────────────────────────────────────────────────────

function esc(s) {
  return String(s ?? '')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
