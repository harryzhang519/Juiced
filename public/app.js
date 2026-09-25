/**
 * app.js — EV Edge Frontend
 * ========================
 * Fetches data from the Flask API and renders the full dashboard.
 *
 * State → renderSportTabs → fetchData → renderStats + renderTable + renderParlays
 */

'use strict';

// ── State ───────────────────────────────────────────────────────
const STATE = {
  sport:       'baseball_mlb',
  sports:      [],
  allBets:     [],
  parlays:     [],
  meta:        {},
  status:      null,
  loading:     false,
  demoMode:    false,
  countdownId: null,
  noUpcomingGames: false,  // true when today's slate hasn't been posted yet
  apiMessage:  null,       // informational message from server
};

// Filter state
const FILTERS = {
  market: 'all',
  minEv:  0,
  book:   'all',
};

// ── Init ──────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  init();
});

async function init() {
  // Ledger mode: load P&L tracker only
  if (typeof loadPikkit === 'function') {
    loadPikkit();
  } else {
    // pikkit.js may not be parsed yet — wait a tick
    setTimeout(() => { if (typeof loadPikkit === 'function') loadPikkit(); }, 100);
  }
}

// ── Live Polling ──────────────────────────────────────────
let _lastAnalyzedAt  = null;
let _lastBetSnapshot = {};   // betId -> {offered_odds, fair_odds, ev_pct}
let _currentETDate   = null; // 'YYYY-MM-DD' in Eastern Time
let _pollIntervalId  = null;
let _countdownId     = null;
const POLL_INTERVAL_MS = 60_000; // check every 60s
const REFRESH_INTERVAL_MS = 30 * 60_000; // 30 min cadence display

function getETDateString() {
  return new Date().toLocaleDateString('en-US', {
    timeZone: 'America/New_York',
    year: 'numeric', month: '2-digit', day: '2-digit',
  });
}

function startLivePolling() {
  if (_pollIntervalId) clearInterval(_pollIntervalId);
  _currentETDate   = getETDateString();
  _pollIntervalId  = setInterval(pollForUpdates, POLL_INTERVAL_MS);
  startCountdown();
}

async function pollForUpdates() {
  // ── Midnight ET rollover ─────────────────────────────────
  const etDate = getETDateString();
  if (_currentETDate && etDate !== _currentETDate) {
    console.log(`[EV Edge] Date rollover ET: ${_currentETDate} → ${etDate} — force refreshing all sports`);
    _currentETDate = etDate;
    showLiveFlash('🌅 New day — loading ' + etDate + ' slate');
    // Force a live fetch from FanDuel & DraftKings for all sports
    await triggerSilentRefresh(STATE.sport);
    await fetchData(STATE.sport);
    return; // fetchData already resets countdown + snapshot
  }

  // ── Check if new data was produced by the backend ──────────────
  try {
    const res  = await fetch(`/api/last-refresh?sport=${STATE.sport}`);
    const data = await res.json();
    const ts   = data.analyzed_at;

    if (_lastAnalyzedAt && ts && ts !== _lastAnalyzedAt) {
      console.log('[EV Edge] New odds detected — updating in place');
      _lastAnalyzedAt = ts;
      // Fetch new bets and do in-place diff instead of full rebuild
      await fetchAndDiffBets(STATE.sport);
    } else {
      _lastAnalyzedAt = ts || _lastAnalyzedAt;
    }
  } catch (e) {
    // Silently ignore poll failures
  }
}

// In-place diff: update only rows whose odds / EV changed
async function fetchAndDiffBets(sport) {
  try {
    const [betsRes, parlaysRes] = await Promise.all([
      fetch(`/api/ev-bets?sport=${sport}&limit=100`),
      fetch(`/api/parlays?sport=${sport}`),
    ]);
    const betsData    = await betsRes.json();
    const parlaysData = await parlaysRes.json();
    const newBets     = betsData.bets || [];

    // Build new snapshot map
    const newSnapshot = {};
    newBets.forEach(b => {
      newSnapshot[b.game_id + '|' + b.selection + '|' + (b.line ?? '')] = {
        offered_odds: b.offered_odds,
        fair_odds:    b.fair_odds,
        ev_pct:       b.ev_pct,
        ev_pct_display: b.ev_pct_display,
        fair_odds_display: (b.fair_odds > 0 ? '+' : '') + b.fair_odds,
        offered_display:   (b.offered_odds > 0 ? '+' : '') + b.offered_odds,
      };
    });

    let anyOddsChanged = false;

    // Compare against old snapshot and flash changed cells
    Object.entries(newSnapshot).forEach(([key, cur]) => {
      const prev = _lastBetSnapshot[key];
      if (!prev) return;
      if (prev.offered_odds !== cur.offered_odds || prev.ev_pct !== cur.ev_pct) {
        anyOddsChanged = true;
        // Find the row by scanning tbody for matching game name + selection
        flashChangedOdds(key, cur, prev);
      }
    });

    // If bet count changed (new bets appeared / dropped off), do full rebuild
    const oldCount = Object.keys(_lastBetSnapshot).length;
    const newCount = Object.keys(newSnapshot).length;
    if (oldCount !== newCount || newBets.length !== STATE.allBets.length) {
      STATE.allBets = newBets;
      STATE.parlays = parlaysData.parlays || [];
      STATE.meta    = betsData.meta || {};
      _lastBetSnapshot = newSnapshot;
      _lastAnalyzedAt  = STATE.meta.analyzed_at;
      applyFilters();
      renderParlays();
      updateLastUpdated();
      renderStats();
      if (anyOddsChanged) showLiveFlash('⚡ Odds updated!');
      return;
    }

    // Odds shifted but same bets — just update the snapshot + re-render in place
    STATE.allBets = newBets;
    STATE.meta    = betsData.meta || {};
    _lastBetSnapshot = newSnapshot;
    _lastAnalyzedAt  = STATE.meta.analyzed_at;

    if (anyOddsChanged) {
      showLiveFlash('⚡ Odds updated!');
      // Re-render just the affected table cells
      STATE.allBets.forEach((b, i) => {
        const key = b.game_id + '|' + b.selection + '|' + (b.line ?? '');
        const prev = _lastBetSnapshot[key]; // already updated above
        updateRowOdds(b, i);
      });
    }
  } catch (e) {
    console.warn('[EV Edge] Diff poll failed:', e);
  }
}

function flashChangedOdds(key, cur, prev) {
  // Find cells with data-bet-key matching and flash them
  document.querySelectorAll(`[data-bet-key="${CSS.escape(key)}"]`).forEach(el => {
    el.classList.add('odds-flash');
    setTimeout(() => el.classList.remove('odds-flash'), 1500);
  });
}

function updateRowOdds(b, i) {
  const key = b.game_id + '|' + b.selection + '|' + (b.line ?? '');
  const offeredEl = document.querySelector(`[data-bet-key="${CSS.escape(key)}"].odds-offered`);
  const fairEl    = document.querySelector(`[data-bet-key="${CSS.escape(key)}"].odds-fair`);
  const evEl      = document.querySelector(`[data-bet-key="${CSS.escape(key)}"].ev-cell`);
  if (offeredEl) offeredEl.textContent = formatOdds(b.offered_odds);
  if (fairEl)    fairEl.textContent    = formatOdds(b.fair_odds) + ' fair';
  if (evEl) {
    evEl.textContent  = b.ev_pct_display;
    const grade = (b.ev_grade || 'C').toLowerCase().replace('+', 'plus');
    evEl.className    = `ev-cell grade-${grade}`;
  }
}

function startCountdown() {
  if (_countdownId) clearInterval(_countdownId);
  let secondsLeft = Math.round(POLL_INTERVAL_MS / 1000);
  updateCountdownEl(secondsLeft);
  _countdownId = setInterval(() => {
    secondsLeft = Math.max(0, secondsLeft - 1);
    updateCountdownEl(secondsLeft);
    if (secondsLeft === 0) secondsLeft = Math.round(POLL_INTERVAL_MS / 1000);
  }, 1000);
}

function updateCountdownEl(sec) {
  const el = document.getElementById('poll-countdown');
  if (el) el.textContent = `Next check in ${sec}s`;
}

function showLiveFlash(msg) {
  const el = document.getElementById('live-flash');
  if (!el) return;
  el.style.opacity = '1';
  el.textContent = msg || '⚡ New odds!';
  setTimeout(() => { el.style.opacity = '0'; }, 3000);
}

async function triggerSilentRefresh(sport) {
  try {
    await fetch(`/api/refresh?sport=${sport}`, { method: 'POST' });
    // Wait for backend to process (3 seconds)
    await new Promise(r => setTimeout(r, 3000));
  } catch (e) {
    console.warn('Silent refresh failed:', e);
  }
}

// ── Sport Tabs ────────────────────────────────────────────────
async function fetchSports() {
  try {
    const res = await fetch('/api/sports');
    const data = await res.json();
    STATE.sports = data.sports || [];
    STATE.demoMode = data.demo_mode || false;
    renderSportTabs();

    if (STATE.demoMode) {
      document.getElementById('demo-badge')?.classList.add('visible');
      const demoEl = document.getElementById('demo-status');
      if (demoEl) demoEl.style.display = 'flex';
    }
  } catch (e) {
    console.error('Failed to fetch sports:', e);
    STATE.sports = defaultSports();
    renderSportTabs();
  }
}

function renderSportTabs() {
  const container = document.getElementById('sport-tabs');
  if (!container) return;
  container.innerHTML = STATE.sports.map(s => `
    <button
      class="sport-tab ${s.key === STATE.sport ? 'active' : ''}"
      role="tab"
      aria-selected="${s.key === STATE.sport}"
      id="tab-${s.key}"
      onclick="switchSport('${s.key}')"
    >
      <span>${s.label}</span>
      <span class="tab-count" id="count-${s.key}">0</span>
    </button>
  `).join('');
}

async function switchSport(sportKey) {
  if (sportKey === STATE.sport && STATE.allBets.length > 0) return;
  STATE.sport = sportKey;

  // Update active tab
  document.querySelectorAll('.sport-tab').forEach(t => {
    t.classList.toggle('active', t.id === `tab-${sportKey}`);
    t.setAttribute('aria-selected', t.id === `tab-${sportKey}`);
  });

  await fetchData(sportKey);
}

// ── Data Fetching ─────────────────────────────────────────────
async function fetchData(sport) {
  if (STATE.loading) return;
  STATE.loading = true;
  showLoading();

  try {
    const [betsRes, parlaysRes] = await Promise.all([
      fetch(`/api/ev-bets?sport=${sport}&limit=100`),
      fetch(`/api/parlays?sport=${sport}`),
    ]);

    const betsData    = await betsRes.json();
    const parlaysData = await parlaysRes.json();

    STATE.allBets = betsData.bets    || [];
    STATE.parlays = parlaysData.parlays || [];
    STATE.meta    = betsData.meta    || {};
    STATE.noUpcomingGames = betsData.no_upcoming_games || false;
    STATE.apiMessage      = betsData.message || null;

    // Track analyzed_at and seed bet snapshot for in-place diff
    _lastAnalyzedAt = STATE.meta.analyzed_at || _lastAnalyzedAt;
    _lastBetSnapshot = {};
    STATE.allBets.forEach(b => {
      const key = b.game_id + '|' + b.selection + '|' + (b.line ?? '');
      _lastBetSnapshot[key] = {
        offered_odds: b.offered_odds,
        fair_odds:    b.fair_odds,
        ev_pct:       b.ev_pct,
        ev_pct_display: b.ev_pct_display,
      };
    });

    // Reset countdown after fresh data load
    startCountdown();

    // Update tab count badge
    const countEl = document.getElementById(`count-${sport}`);
    if (countEl) countEl.textContent = STATE.allBets.length;

    renderStats();
    applyFilters();
    renderParlays();
    updateLastUpdated();

  } catch (e) {
    console.error('Failed to fetch data:', e);
    showError('Failed to load odds data. Is the server running?');
  } finally {
    STATE.loading = false;
  }
}

async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    STATE.status = data;
    renderStatus(data);
  } catch (e) {
    // Silently ignore status failures
  }
}

// ── Filters & Sort ─────────────────────────────────────────────
function applyFilters() {
  FILTERS.market = document.getElementById('filter-market')?.value || 'all';
  FILTERS.minEv  = parseFloat(document.getElementById('filter-min-ev')?.value) || 0;
  FILTERS.book   = document.getElementById('filter-book')?.value || 'all';

  let bets = [...STATE.allBets];

  if (FILTERS.market !== 'all') {
    bets = bets.filter(b => b.market_key === FILTERS.market);
  }
  if (FILTERS.minEv > 0) {
    bets = bets.filter(b => b.ev_pct >= FILTERS.minEv);
  }
  if (FILTERS.book !== 'all') {
    bets = bets.filter(b => b.target_book.toLowerCase().includes(FILTERS.book));
  }

  // Re-rank after filter
  bets.forEach((b, i) => { b.rank = i + 1; });

  const numEl = document.getElementById('results-number');
  if (numEl) numEl.textContent = bets.length;
  renderTable(bets);
}

// ── Render: Stats ─────────────────────────────────────────────
function renderStats() {
  const meta = STATE.meta;
  const bets = STATE.allBets;

  // Hero stats block
  animateNumber('hero-stat-bets',  bets.length);
  setText('hero-stat-ev',    meta.best_ev_pct_display || '—');
  setText('hero-stat-games', meta.total_games != null ? meta.total_games : '—');
}

// ── Render: Table ─────────────────────────────────────────────
function renderTable(bets) {
  const container = document.getElementById('bets-container');

  if (!bets || bets.length === 0) {
    const isNoSlate = STATE.noUpcomingGames;
    container.innerHTML = `
      <div class="state-container">
        <div class="state-icon">${isNoSlate ? '🌙' : '🔍'}</div>
        <div class="state-title">${isNoSlate ? "Today's slate hasn't posted yet" : 'No +EV bets found'}</div>
        <div class="state-sub">
          ${isNoSlate
            ? (STATE.apiMessage || "The Odds API typically posts today's games after ~10 AM ET. Check back soon — the app will auto-refresh.")
            : 'Try adjusting the filters, or check back after a refresh.'}
          ${STATE.demoMode ? '<br><strong>Demo mode:</strong> Using mock MLB data.' : ''}
        </div>
      </div>`;
    return;
  }

  container.innerHTML = `
    <table class="bets-table" aria-label="Positive EV bets">
      <thead>
        <tr>
          <th class="col-rank">#</th>
          <th>Game</th>
          <th>Selection</th>
          <th>Market</th>
          <th>Book</th>
          <th>Offered / Fair</th>
          <th class="sort-active">EV %</th>
        </tr>
      </thead>
      <tbody id="bets-tbody">
        ${bets.map((b, i) => renderRow(b, i)).join('')}
      </tbody>
    </table>`;
}

function renderRow(b, i) {
  const delay    = Math.min(i * 35, 500);
  const gameTime = formatGameTime(b.commence_time);
  const lineStr  = b.line != null ? ` (${b.line > 0 ? '+' : ''}${b.line})` : '';
  const grade    = (b.ev_grade || 'C').toLowerCase().replace('+', 'plus');
  const betKey   = `${b.game_id}|${b.selection}|${b.line ?? ''}`;

  return `
    <tr style="animation-delay:${delay}ms">
      <td class="col-rank">${b.rank}</td>
      <td class="col-game">
        <div class="game-name">${escHtml(b.game)}</div>
        <div class="game-time">${gameTime}</div>
      </td>
      <td class="col-selection">
        <div style="display:inline-block;background:rgba(212,168,67,0.16);border:1px solid rgba(212,168,67,0.4);color:var(--amber);font-size:13px;font-weight:700;padding:4px 10px;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,0.2)">
          🎯 ${escHtml(b.selection)}${escHtml(lineStr)}
        </div>
      </td>
      <td><span class="market-tag">${escHtml(b.market)}</span></td>
      <td class="col-book">${escHtml(b.target_book)}</td>
      <td class="col-odds">
        <div class="odds-offered" data-bet-key="${escHtml(betKey)}">${formatOdds(b.offered_odds)}</div>
        <div class="odds-fair"    data-bet-key="${escHtml(betKey)}">${formatOdds(b.fair_odds)} fair</div>
      </td>
      <td>
        <span class="ev-cell grade-${grade}" data-bet-key="${escHtml(betKey)}">${escHtml(b.ev_pct_display)}</span>
      </td>
    </tr>`;
}

function marketPill(key, label) {
  return `<span class="market-tag">${escHtml(label)}</span>`;
}

// ── Render: Parlays ────────────────────────────────────────────
function renderParlays() {
  const container = document.getElementById('parlays-grid');
  const parlays   = STATE.parlays;

  if (!parlays || parlays.length === 0) {
    container.innerHTML = `
      <div class="state-container" style="grid-column:1/-1">
        <div class="state-icon">🎰</div>
        <div class="state-title">No parlays available</div>
        <div class="state-sub">Parlays require at least 2 qualifying +EV bets from different games on the same book.</div>
      </div>`;
    return;
  }

  container.innerHTML = parlays.map((p, i) => renderParlayCard(p, i)).join('');
}

function renderParlayCard(p, i) {
  const delay    = i * 100;
  const legsHtml = p.legs.map(leg => {
    const lineStr = leg.line != null ? ` (${leg.line > 0 ? '+' : ''}${leg.line})` : '';
    return `
      <li class="parlay-leg">
        <div class="leg-bullet"></div>
        <div class="leg-text">${escHtml(leg.selection)}${escHtml(lineStr)} · <span style="color:var(--text-muted)">${escHtml(leg.market)}</span></div>
        <div class="leg-odds">${formatOdds(leg.offered_odds)}</div>
      </li>`;
  }).join('');

  return `
    <div class="parlay-card" style="animation-delay:${delay}ms">
      <div class="parlay-header">
        <div>
          <div class="parlay-name">${escHtml(p.name)}</div>
          <div class="parlay-meta">${p.n_legs}-Leg Parlay · ${escHtml(p.book)}</div>
        </div>
        <div class="parlay-ev">
          <div class="parlay-ev-value">${escHtml(p.ev_pct_display)}</div>
          <div class="parlay-ev-label">Combined EV</div>
        </div>
      </div>
      <ul class="parlay-legs">${legsHtml}</ul>
      <div class="parlay-footer">
        <div class="parlay-combined">
          Payout: <strong>${formatOdds(p.combined_odds)}</strong>
          <span style="color:var(--text-dim);font-size:11px"> (${p.combined_decimal}x)</span>
        </div>
        <div class="parlay-book">${escHtml(p.book)}</div>
      </div>
    </div>`;
}

// ── Render: Status bar ─────────────────────────────────────────
function renderStatus(data) {
  const dot    = document.getElementById('status-dot');
  const text   = document.getElementById('status-text');
  const liveDot = document.getElementById('live-dot');
  const liveLabel = document.getElementById('live-label');

  if (data.demo_mode) {
    dot.className       = 'status-dot warning';
    text.textContent    = 'Demo mode — mock data';
    if (liveDot)   liveDot.className = 'live-dot warning';
    if (liveLabel) liveLabel.textContent = 'Demo';
  } else {
    dot.className       = 'status-dot ok';
    text.textContent    = 'Live — FanDuel & DraftKings';
    if (liveDot)   liveDot.className = 'live-dot';
    if (liveLabel) liveLabel.textContent = 'Live';
  }

  const quota    = data.quota || {};
  const quotaEl  = document.getElementById('quota-item');
  const quotaTxt = document.getElementById('quota-text');
  if (quota.quota_remaining != null && !data.demo_mode) {
    quotaEl.style.display = 'flex';
    quotaTxt.textContent  = `${quota.quota_remaining} API calls left`;
  }
}

// ── Refresh ────────────────────────────────────────────────────
async function triggerRefresh() {
  const btn  = document.getElementById('btn-refresh');
  const icon = document.getElementById('refresh-icon');
  btn.classList.add('spinning');
  btn.disabled = true;

  try {
    await fetch(`/api/refresh?sport=${STATE.sport}`, { method: 'POST' });
    // Give the server 3 seconds to refresh then refetch
    setTimeout(async () => {
      await fetchData(STATE.sport);
      btn.classList.remove('spinning');
      btn.disabled = false;
    }, 3000);
  } catch (e) {
    btn.classList.remove('spinning');
    btn.disabled = false;
    console.error('Refresh failed:', e);
  }
}

// ── UI helpers ─────────────────────────────────────────────────
function showLoading() {
  document.getElementById('bets-container').innerHTML = `
    <div class="state-container">
      <div class="spinner"></div>
      <div class="state-title">Analyzing lines...</div>
      <div class="state-sub">Devigging FanDuel vs DraftKings</div>
    </div>`;
  document.getElementById('parlays-grid').innerHTML = '';
}

function showError(msg) {
  document.getElementById('bets-container').innerHTML = `
    <div class="state-container">
      <div class="state-icon">⚠️</div>
      <div class="state-title">Error</div>
      <div class="state-sub">${escHtml(msg)}</div>
    </div>`;
}

function updateLastUpdated() {
  const el = document.getElementById('last-updated-nav');
  if (STATE.meta.analyzed_at) {
    const d = new Date(STATE.meta.analyzed_at);
    el.textContent = `Updated ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
  }
}

function formatOdds(n) {
  if (n == null) return '--';
  return n > 0 ? `+${n}` : `${n}`;
}

function formatGameTime(iso) {
  if (!iso) return '';
  try {
    const gameDate = new Date(iso);

    // All times displayed in Eastern Time
    const ET_OPTS = { timeZone: 'America/New_York' };

    // Get today's calendar date in ET
    const nowET   = new Date(new Date().toLocaleString('en-US', ET_OPTS));
    const gameET  = new Date(gameDate.toLocaleString('en-US', ET_OPTS));

    const todayMidnight = new Date(nowET);
    todayMidnight.setHours(0, 0, 0, 0);

    const gameMidnight = new Date(gameET);
    gameMidnight.setHours(0, 0, 0, 0);

    const dayDiff = Math.round((gameMidnight - todayMidnight) / 86_400_000);

    let dayLabel;
    if (dayDiff === 0) {
      dayLabel = 'Today';
    } else if (dayDiff === 1) {
      dayLabel = 'Tomorrow';
    } else if (dayDiff > 1 && dayDiff <= 6) {
      // Show weekday name for games within the week
      dayLabel = gameDate.toLocaleDateString('en-US', { weekday: 'long', timeZone: 'America/New_York' });
    } else {
      // Farther out: show full date
      dayLabel = gameDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'America/New_York' });
    }

    const timeStr = gameDate.toLocaleTimeString('en-US', {
      hour: '2-digit', minute: '2-digit',
      timeZone: 'America/New_York',
      timeZoneName: 'short',
    });

    return `${dayLabel}, ${timeStr}`;
  } catch { return iso; }
}

function escHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function truncate(str, n) {
  return str.length > n ? str.slice(0, n) + '…' : str;
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function colorElement(id, cls) {
  const el = document.getElementById(id);
  if (el) el.className = `stat-value ${cls}`;
}

function animateNumber(id, target) {
  const el = document.getElementById(id);
  if (!el) return;
  let current = 0;
  const step  = Math.ceil(target / 20);
  const timer = setInterval(() => {
    current = Math.min(current + step, target);
    el.textContent = current;
    if (current >= target) clearInterval(timer);
  }, 30);
}

function defaultSports() {
  return [
    { key: 'baseball_mlb',          label: 'MLB',    emoji: '⚾' },
    { key: 'americanfootball_nfl',   label: 'NFL',    emoji: '🏈' },
    { key: 'basketball_nba',         label: 'NBA',    emoji: '🏀' },
    { key: 'basketball_wnba',        label: 'WNBA',   emoji: '🏀' },
    { key: 'icehockey_nhl',          label: 'NHL',    emoji: '🏒' },
    { key: 'americanfootball_ncaaf', label: 'NCAAF',  emoji: '🏈' },
    { key: 'basketball_ncaab',       label: 'NCAAB',  emoji: '🏀' },
    { key: 'soccer_epl',             label: 'EPL',    emoji: '⚽' },
    { key: 'soccer_mls',             label: 'MLS',    emoji: '⚽' },
    { key: 'mma_mixed_martial_arts', label: 'MMA',    emoji: '🥊' },
    { key: 'tennis_atp_wimbledon',   label: 'Tennis', emoji: '🎾' },
  ];
}

// ═══════════════════════════════════════════════════════════════
// TRACKER MODULE
// ═══════════════════════════════════════════════════════════════

// ── View Switcher ───────────────────────────────────────────────
// Ledger mode — single view, no switching needed
function switchView(view) { /* no-op — Ledger is single-view */ }

// ═══════════════════════════════════════════════════════════════
// SHARP MONEY & RLM MODULE
// ═══════════════════════════════════════════════════════════════

async function loadSharpSignals() {
  const container = document.getElementById('sharp-table-container');
  if (container) {
    container.innerHTML = `
      <div class="state-container">
        <div class="spinner"></div>
        <div class="state-title">Scanning betting markets...</div>
        <div class="state-sub">Analyzing ticket splits, money flow, and line movements</div>
      </div>`;
  }

  try {
    const res = await fetch(`/api/sharp?sport=${STATE.sport}`);
    const data = await res.json();
    renderSharpTable(data.signals || []);
  } catch (e) {
    console.error('Failed to load sharp signals:', e);
    if (container) {
      container.innerHTML = `
        <div class="state-container">
          <div class="state-icon">⚠️</div>
          <div class="state-title">Failed to load sharp signals</div>
          <div class="state-sub">${escHtml(e.message)}</div>
        </div>`;
    }
  }
}

function renderSharpTable(signals) {
  const container = document.getElementById('sharp-table-container');
  if (!container) return;

  if (!signals || signals.length === 0) {
    container.innerHTML = `
      <div class="state-container">
        <div class="state-icon">⚖️</div>
        <div class="state-title">No sharp signals detected</div>
        <div class="state-sub">Public betting splits and lines are currently balanced.</div>
      </div>`;
    return;
  }

  const rows = signals.map((s, i) => {
    const delay = Math.min(i * 30, 400);
    const sigClass = getSignalBadgeClass(s.signal);
    const confClass = getConfidenceBadgeClass(s.confidence);

    let deltaHtml = '--';
    if (s.sharp_delta !== null && s.sharp_delta !== undefined) {
      const isPos = s.sharp_delta >= 0;
      const isHeavy = s.sharp_delta >= 15;
      const color = isHeavy ? 'var(--accent)' : (isPos ? '#4CAF50' : 'var(--text-muted)');
      deltaHtml = `<span style="color:${color};font-weight:600">${isPos ? '+' : ''}${s.sharp_delta}%</span>`;
    }

    return `
      <tr style="animation-delay:${delay}ms">
        <td class="col-game">
          <div class="game-name" style="font-size:13px">${escHtml(s.matchup)}</div>
          <div style="color:var(--accent);font-size:13px;font-weight:600;margin-top:2px">${escHtml(s.selection)}</div>
        </td>
        <td class="col-odds">
          <div style="font-size:13px"><strong>Ticket:</strong> ${escHtml(s.ticket_split)}</div>
          <div style="font-size:11px;color:var(--text-muted)"><strong>Handle:</strong> ${escHtml(s.handle_split)}</div>
        </td>
        <td style="font-family:var(--font-mono);font-size:12px;color:var(--text-main)">
          ${escHtml(s.line_movement_display)}
        </td>
        <td>
          <span class="signal-badge ${sigClass}">${escHtml(s.signal)}</span>
        </td>
        <td>
          <span class="conf-badge ${confClass}">${escHtml(s.confidence)}</span>
        </td>
      </tr>`;
  }).join('');

  container.innerHTML = `
    <table class="bets-table" aria-label="Sharp signals summary table">
      <thead>
        <tr>
          <th>Matchup &amp; Selection</th>
          <th>Bet % vs. Money %</th>
          <th>Line Movement (Open ➔ Curr)</th>
          <th>Identified Signal</th>
          <th>Confidence Rating</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function getSignalBadgeClass(sig) {
  switch (sig) {
    case 'Sharp Lock':
    case 'Sharp Steam Move':
      return 'sig-steam';
    case 'Reverse Line Movement':
      return 'sig-rlm';
    case 'Sharp Money':
      return 'sig-sharp';
    case 'Public Heavy':
      return 'sig-public';
    default:
      return 'sig-neutral';
  }
}

function getConfidenceBadgeClass(conf) {
  switch (conf) {
    case 'High': return 'conf-high';
    case 'Medium': return 'conf-med';
    default: return 'conf-low';
  }
}

function toggleSharpInputForm() {
  const panel = document.getElementById('sharp-input-panel');
  if (panel) {
    panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
  }
}

async function submitCustomSharpAnalysis() {
  const statusEl = document.getElementById('sharp-form-status');
  const matchup = document.getElementById('sharp-matchup').value.trim();
  const selection = document.getElementById('sharp-selection').value.trim();
  const betPct = parseFloat(document.getElementById('sharp-bet-pct').value);
  const moneyPct = parseFloat(document.getElementById('sharp-money-pct').value);
  const lineOpenRaw = document.getElementById('sharp-line-open').value.trim();
  const lineCurrRaw = document.getElementById('sharp-line-curr').value.trim();

  if (!matchup || !selection) {
    if (statusEl) {
      statusEl.className = 'form-status err';
      statusEl.textContent = '✗ Matchup and Selection are required.';
    }
    return;
  }

  const payload = {
    games: [{
      matchup: matchup,
      selection: selection,
      bet_pct: !isNaN(betPct) ? betPct : null,
      money_pct: !isNaN(moneyPct) ? moneyPct : null,
      line_open: lineOpenRaw ? parseFloat(lineOpenRaw) : null,
      line_current: lineCurrRaw ? parseFloat(lineCurrRaw) : null,
    }]
  };

  try {
    const res = await fetch('/api/sharp/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.signals) {
      renderSharpTable(data.signals);
      if (statusEl) {
        statusEl.className = 'form-status ok';
        statusEl.textContent = '✓ Signal analyzed successfully!';
      }
    }
  } catch (e) {
    if (statusEl) {
      statusEl.className = 'form-status err';
      statusEl.textContent = `✗ ${e.message}`;
    }
  }
}

// ── Load Tracker Data ────────────────────────────────────────────
async function triggerTrackerScoreSync() {
  const container = document.getElementById('tracker-table-container');
  if (container) {
    container.innerHTML = `
      <div class="state-container">
        <div class="spinner"></div>
        <div class="state-title">Searching game scores...</div>
        <div class="state-sub">Evaluating win/loss results for pending bets</div>
      </div>`;
  }
  try {
    await fetch('/api/resolve-scores', { method: 'POST' });
    await loadTracker(false);
  } catch (e) {
    console.error('Score sync failed:', e);
    await loadTracker(false);
  }
}

async function loadTracker(autoSync = true) {
  if (autoSync) {
    try {
      await fetch('/api/resolve-scores', { method: 'POST' });
    } catch (e) {
      console.warn('Auto score sync background failed:', e);
    }
  }

  const resultFilter = document.getElementById('t-filter-result')?.value || '';
  const url = `/api/tracker/bets${resultFilter ? '?result=' + resultFilter : ''}`;

  try {
    const [betsRes, summaryRes] = await Promise.all([
      fetch(url),
      fetch('/api/tracker/summary'),
    ]);
    const betsData    = await betsRes.json();
    const summaryData = await summaryRes.json();

    renderTrackerStats(summaryData);
    renderTrackerTable(betsData.bets || []);
  } catch (e) {
    console.error('Tracker load failed:', e);
    document.getElementById('tracker-table-container').innerHTML = `
      <div class="state-container">
        <div class="state-icon">⚠️</div>
        <div class="state-title">Failed to load bets</div>
        <div class="state-sub">${escHtml(e.message)}</div>
      </div>`;
  }
}

// ── Render: Tracker Stats Strip ──────────────────────────────────
function renderTrackerStats(s) {
  const roiClass = (s.roi_pct >= 0) ? 'positive' : '';

  setText('t-stat-record',   s.record || '--');
  setText('t-stat-winrate',  `${s.win_rate_pct ?? '--'}% win rate`);
  setText('t-stat-roi',      s.settled > 0 ? `${s.roi_pct > 0 ? '+' : ''}${s.roi_pct}% ROI` : '--');
  setText('t-stat-pnl',      s.settled > 0 ? `${s.total_pnl > 0 ? '+' : ''}${s.total_pnl} units profit` : '--');
  setText('t-stat-wagered',  s.settled > 0 ? `${s.total_staked} units wagered` : '-- wagered');
  setText('t-stat-exp-roi',  s.settled > 0 ? `+${s.expected_roi_pct}%` : '--');
  setText('t-stat-variance', s.settled > 0
    ? `${s.variance_vs_exp > 0 ? '+' : ''}${s.variance_vs_exp}% vs expected`
    : 'No settled bets yet');
  setText('t-stat-clv',      s.settled > 0 ? `${s.avg_clv_pct > 0 ? '+' : ''}${s.avg_clv_pct}%` : '--');
  setText('t-stat-clv-rate', `${s.clv_positive_rate ?? '--'}% positive CLV rate`);
  setText('t-stat-pending',  s.pending ?? '--');
  setText('t-stat-settled',  `${s.settled ?? '--'} settled`);

  // Color ROI
  const roiEl = document.getElementById('t-stat-roi');
  if (roiEl && s.settled > 0) {
    roiEl.className = `stat-value ${s.roi_pct >= 0 ? 'positive' : ''}`;
    if (s.roi_pct < 0) roiEl.style.color = 'var(--red)';
  }
}

// ── Render: Tracker History Table ────────────────────────────────
function renderTrackerTable(bets) {
  const container = document.getElementById('tracker-table-container');

  if (!bets || bets.length === 0) {
    container.innerHTML = `
      <div class="state-container">
        <div class="state-icon">📋</div>
        <div class="state-title">No bets logged yet</div>
        <div class="state-sub">Use the "Log New Bet" form above to add your first bet.<br>Your July 23 recommended bets are pre-loaded — click Tracker to see them.</div>
      </div>`;
    return;
  }

  const rows = bets.map((b, i) => renderTrackerRow(b, i)).join('');

  container.innerHTML = `
    <table class="bets-table" aria-label="Bet history log">
      <thead>
        <tr>
          <th>Date</th>
          <th>Game / Selection</th>
          <th>Market</th>
          <th>Book</th>
          <th>Offered</th>
          <th>Fair</th>
          <th>EV%</th>
          <th>CLV</th>
          <th>Result</th>
          <th>P&amp;L</th>
          <th>Variance</th>
          <th></th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderTrackerRow(b, i) {
  const delay  = Math.min(i * 30, 400);
  const result = b.result || 'pending';

  // CLV display
  let clvHtml = '<span class="clv-na">No data</span>';
  if (b.clv_display) {
    const cls = b.clv_confirmed ? 'clv-positive' : 'clv-negative';
    clvHtml = `<span class="${cls}" title="${b.clv_confirmed ? 'Edge confirmed' : 'Edge eroded'}">${escHtml(b.clv_display)}</span>`;
  }

  // P&L display
  let pnlHtml = '<span class="pnl-nil">--</span>';
  if (b.pnl !== null && b.pnl !== undefined) {
    const cls = b.pnl > 0 ? 'pnl-pos' : b.pnl < 0 ? 'pnl-neg' : 'pnl-nil';
    pnlHtml = `<span class="${cls}">${b.pnl > 0 ? '+' : ''}${b.pnl}u</span>`;
  }

  // Variance badge
  const vtype = (b.variance_type || 'pending').replace(/[^a-z_]/g, '');
  const vlabel = b.variance_label || 'Pending';
  const vdetail = (b.variance_detail || '').replace(/"/g, '&quot;');
  const vbadge = `<span class="variance-badge ${vtype}" title="${vdetail}">${escHtml(vlabel)}</span>`;

  return `
    <tr id="row-${b.id}" style="animation-delay:${delay}ms">
      <td style="font-size:12px;color:var(--text-muted);white-space:nowrap">${escHtml(b.date)}</td>
      <td class="col-game" style="padding:10px 12px;">
        <div style="font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.04em;margin-bottom:4px;font-weight:500">${escHtml(b.game)}</div>
        <div style="display:inline-block;background:rgba(212,168,67,0.16);border:1px solid rgba(212,168,67,0.4);color:var(--amber);font-size:13px;font-weight:700;padding:4px 10px;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,0.2)">
          🎯 ${escHtml(b.selection)}
        </div>
      </td>
      <td>${marketPillTracker(b.market)}</td>
      <td class="col-book" style="font-size:11px">${escHtml(b.target_book)}</td>
      <td class="col-odds"><span class="odds-offered">${formatOdds(b.offered_odds)}</span></td>
      <td class="col-odds"><span class="odds-fair">${formatOdds(b.fair_odds)}</span></td>
      <td><span class="ev-cell grade-${evGradeClass(b.ev_pct)}">${escHtml(b.ev_pct_display)}</span></td>
      <td>${clvHtml}</td>
      <td><span class="result-badge ${result}">${result}</span></td>
      <td>${pnlHtml}</td>
      <td>${vbadge}</td>
      <td><button class="btn-update" onclick="showUpdateForm('${b.id}')">Update</button></td>
    </tr>
    <tr id="update-row-${b.id}" style="display:none">
      <td colspan="12" style="background:var(--ink-2);padding:16px 20px;border-bottom:1px solid var(--rule)">
        <div style="font-size:11px;font-weight:700;color:var(--amber);margin-bottom:12px;text-transform:uppercase;letter-spacing:0.06em">Edit Bet Details</div>
        <div class="form-grid" style="margin-bottom:12px">
          <div class="form-group">
            <label>Date</label>
            <input type="date" id="upd-date-${b.id}" class="form-input" value="${escHtml(b.date || '')}" />
          </div>
          <div class="form-group">
            <label>Game</label>
            <input type="text" id="upd-game-${b.id}" class="form-input" value="${escHtml(b.game || '')}" placeholder="NYY @ BOS" />
          </div>
          <div class="form-group">
            <label>Selection</label>
            <input type="text" id="upd-selection-${b.id}" class="form-input" value="${escHtml(b.selection || '')}" placeholder="Boston Red Sox" />
          </div>
          <div class="form-group">
            <label>Sport</label>
            <select id="upd-sport-${b.id}" class="form-input">
              <option value="MLB" ${b.sport==='MLB'?'selected':''}>MLB</option>
              <option value="NFL" ${b.sport==='NFL'?'selected':''}>NFL</option>
              <option value="NBA" ${b.sport==='NBA'?'selected':''}>NBA</option>
              <option value="WNBA" ${b.sport==='WNBA'?'selected':''}>WNBA</option>
              <option value="NHL" ${b.sport==='NHL'?'selected':''}>NHL</option>
              <option value="MMA" ${b.sport==='MMA'?'selected':''}>MMA</option>
              <option value="Soccer" ${b.sport==='Soccer'?'selected':''}>Soccer</option>
              <option value="Other" ${!['MLB','NFL','NBA','WNBA','NHL','MMA','Soccer'].includes(b.sport)?'selected':''}>Other</option>
            </select>
          </div>
          <div class="form-group">
            <label>Market</label>
            <input type="text" id="upd-market-${b.id}" class="form-input" value="${escHtml(b.market || 'Moneyline')}" placeholder="Moneyline" />
          </div>
          <div class="form-group">
            <label>Book</label>
            <input type="text" id="upd-book-${b.id}" class="form-input" value="${escHtml(b.target_book || 'DraftKings')}" placeholder="DraftKings" />
          </div>
          <div class="form-group">
            <label>Offered Odds</label>
            <input type="number" id="upd-offered-${b.id}" class="form-input" value="${b.offered_odds != null ? b.offered_odds : ''}" placeholder="-118" />
          </div>
          <div class="form-group">
            <label>Fair Odds (No-Vig)</label>
            <input type="number" id="upd-fair-${b.id}" class="form-input" value="${b.fair_odds != null ? b.fair_odds : ''}" placeholder="-128" />
          </div>
          <div class="form-group">
            <label>Stake (units)</label>
            <input type="number" id="upd-stake-${b.id}" class="form-input" step="0.5" value="${b.stake != null ? b.stake : 1.0}" placeholder="1.0" />
          </div>
          <div class="form-group">
            <label>Closing Odds <span class="optional">(CLV)</span></label>
            <input type="number" id="upd-closing-${b.id}" class="form-input" value="${b.closing_odds != null ? b.closing_odds : ''}" placeholder="-132" />
          </div>
          <div class="form-group">
            <label>Result</label>
            <select id="upd-result-${b.id}" class="form-input">
              <option value="pending" ${result==='pending'?'selected':''}>Pending</option>
              <option value="win" ${result==='win'?'selected':''}>Win</option>
              <option value="loss" ${result==='loss'?'selected':''}>Loss</option>
              <option value="push" ${result==='push'?'selected':''}>Push</option>
            </select>
          </div>
          <div class="form-group form-group--full">
            <label>Recap / Notes</label>
            <input type="text" id="upd-recap-${b.id}" class="form-input" value="${escHtml(b.recap || '')}" placeholder="Variance notes, injuries, bullpen collapse..." />
          </div>
        </div>
        <div style="display:flex;gap:10px;align-items:center;margin-top:12px">
          <button class="btn-submit" style="padding:6px 16px;font-size:12px" onclick="submitUpdate('${b.id}')">Save Changes</button>
          <button class="btn-secondary" style="padding:6px 14px;font-size:12px" onclick="hideUpdateForm('${b.id}')">Cancel</button>
          <button class="btn-danger" style="padding:6px 14px;font-size:12px;margin-left:auto" onclick="deleteTrackerBet('${b.id}')">Delete Bet</button>
        </div>
      </td>
    </tr>`;
}

function marketPillTracker(market) {
  return `<span class="market-tag">${escHtml(market)}</span>`;
}

function evGradeClass(evPct) {
  if (evPct >= 0.07) return 'aplus';
  if (evPct >= 0.05) return 'a';
  if (evPct >= 0.03) return 'bplus';
  if (evPct >= 0.01) return 'b';
  return 'c';
}

// ── Log Form Toggle ──────────────────────────────────────────────
function toggleLogForm() {
  const form   = document.getElementById('log-bet-form');
  const toggle = document.getElementById('log-bet-toggle');
  const open   = form.style.display !== 'none';
  form.style.display  = open ? 'none' : 'block';
  toggle.textContent  = open ? 'Show Form' : 'Hide Form';
}

// ── Submit New Bet ───────────────────────────────────────────────
async function submitBet() {
  const status  = document.getElementById('form-status');
  const today   = new Date().toISOString().slice(0,10);

  const payload = {
    date:         document.getElementById('lb-date').value || today,
    game:         document.getElementById('lb-game').value.trim(),
    sport:        document.getElementById('lb-sport').value,
    market:       document.getElementById('lb-market').value,
    selection:    document.getElementById('lb-selection').value.trim(),
    target_book:  document.getElementById('lb-book').value,
    offered_odds: parseInt(document.getElementById('lb-offered').value) || null,
    fair_odds:    parseInt(document.getElementById('lb-fair').value) || null,
    stake:        parseFloat(document.getElementById('lb-stake').value) || 1.0,
    closing_odds: parseInt(document.getElementById('lb-closing').value) || null,
    result:       document.getElementById('lb-result').value,
    recap:        document.getElementById('lb-recap').value.trim(),
  };

  if (!payload.game || !payload.selection || !payload.offered_odds || !payload.fair_odds) {
    status.className   = 'form-status err';
    status.textContent = '✗ Game, Selection, Offered Odds, and Fair Odds are required.';
    return;
  }

  try {
    const res = await fetch('/api/tracker/bets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!res.ok) throw new Error(await res.text());

    status.className   = 'form-status ok';
    status.textContent = '✓ Bet logged successfully!';

    // Clear form
    ['lb-game','lb-selection','lb-offered','lb-fair','lb-closing','lb-recap'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    document.getElementById('lb-stake').value = '1';
    document.getElementById('lb-result').value = 'pending';

    await loadTracker();
    setTimeout(() => { status.textContent = ''; }, 4000);

  } catch (e) {
    status.className   = 'form-status err';
    status.textContent = `✗ ${e.message}`;
  }
}

// ── Inline Update Form ───────────────────────────────────────────
function showUpdateForm(id) {
  document.getElementById(`update-row-${id}`).style.display = 'table-row';
}

function hideUpdateForm(id) {
  document.getElementById(`update-row-${id}`).style.display = 'none';
}

async function submitUpdate(id) {
  const payload = {
    date:         document.getElementById(`upd-date-${id}`)?.value || '',
    game:         document.getElementById(`upd-game-${id}`)?.value.trim() || '',
    selection:    document.getElementById(`upd-selection-${id}`)?.value.trim() || '',
    sport:        document.getElementById(`upd-sport-${id}`)?.value || 'MLB',
    market:       document.getElementById(`upd-market-${id}`)?.value.trim() || 'Moneyline',
    target_book:  document.getElementById(`upd-book-${id}`)?.value.trim() || 'DraftKings',
    offered_odds: parseInt(document.getElementById(`upd-offered-${id}`)?.value) || null,
    fair_odds:    parseInt(document.getElementById(`upd-fair-${id}`)?.value) || null,
    stake:        parseFloat(document.getElementById(`upd-stake-${id}`)?.value) || 1.0,
    closing_odds: parseInt(document.getElementById(`upd-closing-${id}`)?.value) || null,
    result:       document.getElementById(`upd-result-${id}`)?.value || 'pending',
    recap:        document.getElementById(`upd-recap-${id}`)?.value.trim() || '',
  };

  try {
    const res = await fetch(`/api/tracker/bets/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(await res.text());
    await loadTracker();
  } catch (e) {
    alert(`Update failed: ${e.message}`);
  }
}

async function deleteTrackerBet(id) {
  if (!confirm('Are you sure you want to delete this bet? This action cannot be undone.')) return;
  try {
    const res = await fetch(`/api/tracker/bets/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(await res.text());
    await loadTracker();
  } catch (e) {
    alert(`Delete failed: ${e.message}`);
  }
}
