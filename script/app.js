/* =======================================================
   Stock Screener v5  —  app.js

   Fixes vs previous version:
   • Pagination uses correct id "pgbar-table", not "pagination"
   • filteredData stored so goPage() re-renders without re-filtering
   • Sort: column-click sort and dropdown sort are independent; no
     accidental key override
   • Chart canvas id: dots in ticker symbols sanitised → underscores
   • Canvas drawPriceChart: uses setTimeout(0) after modal open so
     offsetWidth is non-zero
   • Compare: uses .cmp-header-row / .cmp-ticker-card (matches CSS)
   • toggleCmp: reads ticker from data-ticker attribute, not inner text
   ======================================================= */

'use strict';

// ── Constants ──────────────────────────────────────────
const PAGE_SIZE  = 25;
const CMP_MAX    = 6;
const CMP_COLORS = ['var(--a)', 'var(--a2)', 'var(--g)', 'var(--y)', 'var(--r)', 'var(--o)'];

// ── State ───────────────────────────────────────────────
let allData      = [];   // full dataset from server
let filteredData = [];   // after filters + sort (used for pagination)
let sortState    = { key: 'score_pct', dir: -1 };
let curPage      = 1;
let pollTimer    = null;
let cmpSet       = new Set();   // up to CMP_MAX ticker strings — для панели сравнения
let selectedSet  = new Set();   // для экспорта в Excel (отдельные чекбоксы)

// Chart data cache: { TICKER: { ts: epochMs, data: {...} } }
const chartCache = {};


// ── Format helpers ──────────────────────────────────────
function fB(v, currency) {
  if (v == null) return 'N/A';
  const a = Math.abs(v);
  const sym = currency === 'KZT' ? '₸' : (currency || '');
  if (a >= 1e12) return (v / 1e12).toFixed(2) + 'T ' + sym;
  if (a >= 1e9)  return (v / 1e9).toFixed(2)  + 'B ' + sym;
  if (a >= 1e6)  return (v / 1e6).toFixed(2)  + 'M ' + sym;
  return v.toFixed(0) + (sym ? ' ' + sym : '');
}
function fBraw(v) {
  if (v == null) return 'N/A';
  const a = Math.abs(v);
  if (a >= 1e12) return (v / 1e12).toFixed(2) + 'T';
  if (a >= 1e9)  return (v / 1e9).toFixed(2)  + 'B';
  if (a >= 1e6)  return (v / 1e6).toFixed(2)  + 'M';
  return v.toFixed(0);
}
const fN  = (v, d = 2) => v == null ? 'N/A' : parseFloat(v).toFixed(d);
const fP  = v => v == null ? 'N/A' : parseFloat(v).toFixed(1) + '%';
const ini = n => (n || '??').split(' ').slice(0, 2).map(w => w[0]).join('').toUpperCase().slice(0, 2);
const clr = r => r === 'ideal' ? 'var(--g)' : r === 'good' ? 'var(--y)' : r === 'warn' ? 'var(--r)' : 'var(--m)';

const CUR_SYM = { KZT: '₸', USD: '$', GBP: '£', GBp: 'p', EUR: '€', JPY: '¥', HKD: 'HK$', ZAR: 'R', ZAc: 'c' };
const fCurSym = c => CUR_SYM[c] || c || '';

// ── USD helpers ──────────────────────────────────────────
// Предпочитаем _usd поле если оно есть, иначе оригинал (уже USD).
function usdVal(b, field) {
  const u = b[field + '_usd'];
  return u != null ? u : (b.currency === 'USD' || !b.currency ? b[field] : null);
}
// Форматирование денежного значения в USD для таблицы
function fBusd(b, field) {
  const v = usdVal(b, field);
  if (v == null) return fB(b[field], b.currency);  // fallback — локальная валюта
  return fB(v, 'USD');
}

function fPrice(b) {
  if (b.price == null) return 'N/A';
  const sym = fCurSym(b.currency);
  const dec = (b.currency === 'KZT' || b.currency === 'JPY') ? 0 : 2;
  const num = parseFloat(b.price).toFixed(dec);
  return b.currency === 'KZT' ? `${sym} ${num}` : `${num} ${sym}`;
}

// Есть ли валидный курс конвертации к USD?
function hasFx(b) {
  return b.fx_rate_to_usd != null && b.currency && b.currency !== 'USD';
}
// Цена в USD: только если fx_rate реально есть. Иначе null.
function getPriceUsd(b) {
  if (b.currency === 'USD' || !b.currency) return b.price;
  return b.price_usd != null ? b.price_usd : null;
}
// Форматировать цену в USD для отображения
function fPriceUsd(b) {
  const v = getPriceUsd(b);
  if (v == null) return null;  // конвертация недоступна
  return `$${parseFloat(v).toFixed(2)}`;
}

function priceCell(b) {
  if (b.price == null) return '<span class="vn" style="font-family:var(--mono)">N/A</span>';
  const ch  = b.price_change_p;
  const cls = ch == null ? 'pfl' : ch > 0 ? 'pup' : ch < 0 ? 'pdn' : 'pfl';
  const arr = ch == null ? '' : ch > 0 ? '▲' : ch < 0 ? '▼' : '';
  const chS = ch != null ? `${arr}${Math.abs(ch).toFixed(2)}%` : '';

  const isUsd   = b.currency === 'USD' || !b.currency;
  const usdStr  = fPriceUsd(b);   // null если нет fx
  const localStr = fPrice(b);

  let mainPrice, subPrice;
  if (isUsd) {
    // Нативно USD — просто показываем
    mainPrice = `$${parseFloat(b.price).toFixed(2)}`;
    subPrice  = '';
  } else if (usdStr) {
    // Есть конвертация — главное USD, под ним локальная
    mainPrice = usdStr;
    subPrice  = `<span class="plocal">${localStr}</span>`;
  } else {
    // Нет fx — показываем локальную без претензий на USD
    mainPrice = localStr;
    subPrice  = '';
  }

  return `<div class="pcell"><span class="pmain">${mainPrice}</span>${subPrice}${chS ? `<span class="pch ${cls}">${chS}</span>` : ''}</div>`;
}

function mpill(val, rating, fmt) {
  const c  = rating || 'na';
  const d  = val != null ? (fmt ? fmt(val) : fN(val)) : 'N/A';
  const dc = { ideal:'di', good:'dg', warn:'dw', na:'dn' }[c] || 'dn';
  const vc = { ideal:'vi', good:'vg', warn:'vw', na:'vn' }[c] || 'vn';
  return `<span class="mp"><span class="dot ${dc}"></span><span class="${vc}">${d}</span></span>`;
}
function scoreBadge(s) {
  const cls = s >= 70 ? 'sh' : s >= 40 ? 'sm' : 'sl';
  const sym = s >= 70 ? '★' : s >= 40 ? '◆' : '▼';
  return `<span class="sc ${cls}">${sym} ${s}%</span>`;
}
function regBadge(r) {
  const safe  = (r || 'Other').replace(/[^a-zA-Z]/g, '');
  const flags = { US:'🇺🇸', Europe:'🇪🇺', Asia:'🌏', Emerging:'🌍', KZ:'🇰🇿', Other:'🌐' };
  return `<span class="rb r${safe}">${flags[r] || '🌐'} ${r || '?'}</span>`;
}

// Sanitise ticker string for use in DOM ids (dots → underscores, etc.)
const safeId = t => t.replace(/[^a-zA-Z0-9_]/g, '_');


// ── TABLE ────────────────────────────────────────────────
function renderTable(data) {
  const tb = document.getElementById('tbody');

  if (!data.length) {
    tb.innerHTML = `<tr><td colspan="19" style="text-align:center;padding:36px;color:var(--sub)">Нет результатов</td></tr>`;
    renderPager(0);
    return;
  }

  const total = data.length;
  const pages = Math.ceil(total / PAGE_SIZE);
  if (curPage > pages) curPage = pages;
  const start = (curPage - 1) * PAGE_SIZE;
  const slice = data.slice(start, start + PAGE_SIZE);

  tb.innerHTML = slice.map(b => {
    const r   = b.ratings || {};
    const w52 = b.week52_low != null && b.week52_high != null
      ? `<div style="font-family:var(--mono);font-size:10px;color:var(--sub)">${fN(b.week52_low,2)}–${fN(b.week52_high,2)}${b.currency ? ' <span style="font-size:8px;opacity:.6">'+b.currency+'</span>' : ''}</div>`
      : '<span class="vn">N/A</span>';

    const kzBadge = b.is_kase ? '<span class="kz-badge">KASE</span>' : '';

    return `<tr onclick="showMod('${b.ticker}')">
      <td><div class="tc">
        <input type="checkbox" class="selck"
          data-ticker="${b.ticker}"
          onclick="event.stopPropagation();toggleSel('${b.ticker}')"
          ${selectedSet.has(b.ticker) ? 'checked' : ''}
          title="Выбрать для экспорта в Excel"
          style="accent-color:#1D6F42">
        <input type="checkbox" class="cmpck"
          data-ticker="${b.ticker}"
          onclick="event.stopPropagation();toggleCmp('${b.ticker}')"
          ${cmpSet.has(b.ticker) ? 'checked' : ''}
          title="Сравнить (до ${CMP_MAX})">
        <div class="av">${ini(b.name)}</div>
        <div>
          <div class="tn">${b.name || b.ticker}${kzBadge}</div>
          <div class="td2">${b.ticker}${b.currency ? ' · ' + b.currency : ''}</div>
        </div>
      </div></td>
      <td>${regBadge(b.region)}</td>
      <td><span class="stag" title="${b.industry || ''}">${b.sector || '—'}</span></td>
      <td>${scoreBadge(b.score_pct || 0)}</td>
      <td>${priceCell(b)}</td>
      <td class="bignum">${fBusd(b, 'market_cap')}</td>
      <td>${mpill(b.pe_ratio,  r.pe_ratio)}</td>
      <td>${mpill(b.pb_ratio,  r.pb_ratio)}</td>
      <td>${mpill(b.de_ratio,  r.de_ratio)}</td>
      <td>${mpill(b.ev_ebitda, r.ev_ebitda)}</td>
      <td>${mpill(b.net_debt_ebitda, r.net_debt_ebitda)}</td>
      <td>${mpill(b.roe_pct,   r.roe_pct, fP)}</td>
      <td class="bignum">${b.roa_pct != null ? fP(b.roa_pct) : '<span class="vn">N/A</span>'}</td>
      <td>${mpill(b.ps_ratio,  r.ps_ratio)}</td>
      <td class="bignum">${fBusd(b, 'ebitda')}</td>
      <td class="bignum">${fBusd(b, 'net_income')}</td>
      <td class="bignum">${b.fcf != null ? fBusd(b, 'fcf') : '<span class="vn">N/A</span>'}</td>
      <td class="bignum" title="Trailing EPS">${
        b.eps_trailing_usd != null ? '$'+fN(b.eps_trailing_usd) :
        b.eps_trailing     != null ? fN(b.eps_trailing)+' '+fCurSym(b.currency) :
        '<span class="vn">N/A</span>'}</td>
      <td>${w52}</td>
      <td class="srcdate">${b.source_date || '—'}</td>
    </tr>`;
  }).join('');

  renderPager(total);
  document.getElementById('clabel').textContent = `${total} / ${allData.length}`;
}


// ── PAGINATION ───────────────────────────────────────────
// Uses id="pgbar-table" which exists in index.html
function renderPager(total) {
  const el = document.getElementById('pgbar-table');
  if (!el) return;
  if (total <= PAGE_SIZE) { el.innerHTML = ''; return; }

  const pages = Math.ceil(total / PAGE_SIZE);

  // Build visible page number list with ellipsis
  const nums = [];
  for (let i = 1; i <= pages; i++) {
    if (i === 1 || i === pages || (i >= curPage - 2 && i <= curPage + 2)) {
      nums.push(i);
    } else if (nums[nums.length - 1] !== '…') {
      nums.push('…');
    }
  }

  const btns = nums.map(p =>
    p === '…'
      ? `<span class="pg-info">…</span>`
      : `<button class="pg-btn${p === curPage ? ' act' : ''}" onclick="goPage(${p})">${p}</button>`
  ).join('');

  el.innerHTML = `
    <button class="pg-btn" onclick="goPage(1)"          ${curPage === 1      ? 'disabled' : ''}>«</button>
    <button class="pg-btn" onclick="goPage(${curPage-1})" ${curPage === 1    ? 'disabled' : ''}>‹</button>
    ${btns}
    <button class="pg-btn" onclick="goPage(${curPage+1})" ${curPage === pages ? 'disabled' : ''}>›</button>
    <button class="pg-btn" onclick="goPage(${pages})"   ${curPage === pages  ? 'disabled' : ''}>»</button>
    <span class="pg-info">${(curPage-1)*PAGE_SIZE+1}–${Math.min(curPage*PAGE_SIZE,total)} из ${total}</span>
  `;
}

// goPage: changes page and re-renders from already-computed filteredData
function goPage(p) {
  const pages = Math.ceil(filteredData.length / PAGE_SIZE);
  if (p < 1 || p > pages) return;
  curPage = p;
  renderTable(filteredData);
  document.getElementById('tw').scrollIntoView({ behavior: 'smooth', block: 'start' });
}


// ── FILTER + SORT ────────────────────────────────────────
// Sort state comes from sortState (updated by sb() for column clicks,
// and by applyF itself when the dropdown changes).
function applyF() {
  const q    = (document.getElementById('search').value || '').toLowerCase();
  const qf   = document.getElementById('qsel').value;
  const rf   = document.getElementById('rsel').value;
  const sf   = document.getElementById('ssel').value;
  // Dropdown controls default sort key only when no column has been clicked
  const ddKey = document.getElementById('sortsel').value;

  // If the column sort hasn't been set by a column click use the dropdown
  const sortKey = sortState.key || ddKey;
  const sortDir = sortState.dir;

  let d = allData.filter(b => {
    if (q && !`${b.name} ${b.ticker} ${b.sector||''} ${b.region||''} ${b.industry||''}`.toLowerCase().includes(q)) return false;
    if (qf === 'high' && (b.score_pct || 0) < 70)  return false;
    if (qf === 'mid'  && ((b.score_pct || 0) < 40 || (b.score_pct || 0) >= 70)) return false;
    if (qf === 'low'  && (b.score_pct || 0) >= 40) return false;
    if (rf !== 'all'  && b.region !== rf) return false;
    if (sf !== 'all'  && b.sector !== sf) return false;
    return true;
  });

  d.sort((a, b2) => {
    let av = a[sortKey], bv = b2[sortKey];
    if (typeof av === 'string' || typeof bv === 'string') {
      av = (av || '').toLowerCase(); bv = (bv || '').toLowerCase();
    }
    if (av == null) return 1;
    if (bv == null) return -1;
    return (av < bv ? -1 : av > bv ? 1 : 0) * sortDir;
  });

  filteredData = d;   // store for goPage()
  curPage = 1;        // reset to page 1 on every new filter/sort
  renderTable(filteredData);
}

// Column-click sort; independent from the dropdown
function sb(key) {
  if (sortState.key === key) {
    sortState.dir *= -1;
  } else {
    sortState.key = key;
    sortState.dir = -1;
  }
  // Visual feedback on headers
  document.querySelectorAll('thead th').forEach(th => th.classList.remove('act'));
  document.querySelectorAll('.arr').forEach(el => el.textContent = '↕');
  const arrEl = document.getElementById('a-' + key);
  if (arrEl) {
    arrEl.textContent = sortState.dir < 0 ? '↓' : '↑';
    arrEl.closest('th').classList.add('act');
  }
  applyF();
}

function updateStats(data) {
  const ok = data.filter(b => !b.error);
  document.getElementById('st0').textContent = data.length;
  document.getElementById('st4').textContent = data.filter(b => b.error).length;
  if (!ok.length) return;

  const best = [...ok].sort((a, b) => (b.score_pct || 0) - (a.score_pct || 0))[0];
  document.getElementById('st1').textContent  = best.score_pct + '%';
  document.getElementById('st1n').textContent = best.ticker;

  const roes = ok.filter(b => b.roe_pct != null).map(b => b.roe_pct);
  document.getElementById('st2').textContent = roes.length
    ? (roes.reduce((a, v) => a + v, 0) / roes.length).toFixed(1) + '%' : '—';

  const ai = (ok.reduce((s, b) =>
    s + Object.values(b.ratings || {}).filter(v => v === 'ideal').length, 0) / ok.length
  ).toFixed(1);
  document.getElementById('st3').textContent = ai;

  // Populate sector dropdown
  const secs = [...new Set(data.map(b => b.sector).filter(Boolean))].sort();
  const sel  = document.getElementById('ssel');
  const cur  = sel.value;
  sel.innerHTML = '<option value="all">Все секторы</option>' +
    secs.map(s => `<option value="${s}"${s === cur ? ' selected' : ''}>${s}</option>`).join('');
}

// ── DATA MERGE ───────────────────────────────────────────
// allData accumulates ALL tickers ever loaded across multiple fetches.
// A new batch merges in by ticker key — newer record wins.
// This means: searching "KSPI", then searching "AAPL" keeps both visible.
function mergeData(incoming) {
  const map = new Map(allData.map(r => [r.ticker, r]));
  for (const rec of incoming) map.set(rec.ticker, rec);
  return [...map.values()];
}

function applyData(incoming) {
  if (!incoming || !incoming.length) return;

  // Merge into accumulated dataset
  allData = mergeData(incoming);

  // Clean cmpSet: remove tickers that are not in allData
  // This fixes the "(2/6)" counter showing stale selections from a prior session
  const knownTickers = new Set(allData.map(r => r.ticker));
  for (const t of [...cmpSet]) {
    if (!knownTickers.has(t)) cmpSet.delete(t);
  }

  document.getElementById('empty').style.display = 'none';
  document.getElementById('tw').style.display    = 'block';
  document.getElementById('sbar').style.display  = 'grid';
  updateStats(allData);
  applyF();
  renderTray();
}


// ── 52-WEEK PRICE CHART ──────────────────────────────────
async function loadChartInto(ticker, containerId) {
  const wrap = document.getElementById(containerId);
  if (!wrap) return;
  wrap.innerHTML = `<div class="chart-loading">⏳ Загрузка графика…</div>`;

  const now = Date.now();
  let cd = null;
  if (chartCache[ticker] && (now - chartCache[ticker].ts) < 3_600_000) {
    cd = chartCache[ticker].data;
  } else {
    try {
      const r = await fetch(`/api/chart?ticker=${encodeURIComponent(ticker)}`);
      cd = await r.json();
      chartCache[ticker] = { data: cd, ts: now };
    } catch (e) {
      wrap.innerHTML = `<div class="chart-na">⚠ Ошибка загрузки данных</div>`;
      return;
    }
  }

  if (!cd || cd.error || !cd.closes || cd.closes.length < 2) {
    wrap.innerHTML = `<div class="chart-na">📊 Нет данных для ${ticker}${cd?.error === 'no_data' ? `<br><span style="font-size:9px">${ticker.endsWith('.KZ') ? 'Запрашиваем с kase.kz — попробуйте обновить позже' : 'График недоступен для этого тикера'}</span>` : ''}</div>`;
    return;
  }

  const closes   = cd.closes;
  const dates    = cd.dates;
  const n        = closes.length;
  const first    = closes[0];
  const last     = closes[n - 1];
  const chgPct   = (last - first) / first * 100;
  const isUp     = chgPct >= 0;
  const lineClr  = isUp ? '#00e5a0' : '#f87171';
  const currency = allData.find(b => b.ticker === ticker)?.currency || '';

  const labelAt = i => {
    const d = dates[i]; if (!d) return '';
    const p = d.split('-');
    return ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][+p[1]-1] + ' ' + p[0].slice(2);
  };

  const canvasId = `chart-canvas-${safeId(ticker)}`;

  wrap.innerHTML = `
    <div class="chart-header">
      <div>
        <div class="chart-title">52-неделя · Цена закрытия</div>
      </div>
      <div class="chart-stats">
        <div class="chart-stat">
          <div class="chart-stat-l">Последняя</div>
          <div class="chart-stat-v" style="color:${lineClr}">${fPrice({price:last, currency})}</div>
        </div>
        <div class="chart-stat">
          <div class="chart-stat-l">Изменение</div>
          <div class="chart-stat-v" style="color:${lineClr}">${isUp?'▲':'▼'} ${Math.abs(chgPct).toFixed(1)}%</div>
        </div>
        <div class="chart-stat">
          <div class="chart-stat-l">52W Low</div>
          <div class="chart-stat-v">${fPrice({price:cd.min_close, currency})}</div>
        </div>
        <div class="chart-stat">
          <div class="chart-stat-l">52W High</div>
          <div class="chart-stat-v">${fPrice({price:cd.max_close, currency})}</div>
        </div>
      </div>
    </div>
    <div class="chart-canvas-wrap">
      <canvas id="${canvasId}" class="price-chart"></canvas>
    </div>
    <div class="chart-x-labels">
      <span>${labelAt(0)}</span>
      <span>${labelAt(Math.floor(n*0.25))}</span>
      <span>${labelAt(Math.floor(n*0.5))}</span>
      <span>${labelAt(Math.floor(n*0.75))}</span>
      <span>${labelAt(n-1)}</span>
    </div>
  `;

  // Use setTimeout(0) so the canvas is in the layout and has real offsetWidth
  setTimeout(() => drawChart(canvasId, closes, lineClr, isUp), 0);
}

function drawChart(canvasId, closes, lineClr, isUp) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  const dpr = window.devicePixelRatio || 1;
  const W   = canvas.offsetWidth || 640;
  const H   = 150;
  canvas.width  = W * dpr;
  canvas.height = H * dpr;
  canvas.style.height = H + 'px';

  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const PAD = { top: 8, right: 10, bottom: 4, left: 10 };
  const cW  = W - PAD.left - PAD.right;
  const cH  = H - PAD.top  - PAD.bottom;
  const n   = closes.length;
  const mn  = Math.min(...closes);
  const mx  = Math.max(...closes);
  const rng = mx - mn || 1;

  const xOf = i => PAD.left + (i / (n - 1)) * cW;
  const yOf = v => PAD.top  + (1 - (v - mn) / rng) * cH;

  // Grid (3 horizontal lines)
  ctx.strokeStyle = 'rgba(26,36,56,.6)';
  ctx.lineWidth   = 1;
  for (let row = 0; row <= 2; row++) {
    const y = PAD.top + (row / 2) * cH;
    ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(W - PAD.right, y); ctx.stroke();
  }

  // Gradient fill under line
  const grad = ctx.createLinearGradient(0, PAD.top, 0, H - PAD.bottom);
  grad.addColorStop(0, isUp ? 'rgba(0,229,160,.20)' : 'rgba(248,113,113,.20)');
  grad.addColorStop(1, 'rgba(0,0,0,0)');

  ctx.beginPath();
  ctx.moveTo(xOf(0), yOf(closes[0]));
  for (let i = 1; i < n; i++) ctx.lineTo(xOf(i), yOf(closes[i]));
  ctx.lineTo(xOf(n-1), H - PAD.bottom);
  ctx.lineTo(xOf(0),   H - PAD.bottom);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  // Price line
  ctx.beginPath();
  ctx.moveTo(xOf(0), yOf(closes[0]));
  for (let i = 1; i < n; i++) ctx.lineTo(xOf(i), yOf(closes[i]));
  ctx.strokeStyle = lineClr;
  ctx.lineWidth   = 2;
  ctx.lineJoin    = 'round';
  ctx.stroke();

  // End-point dot + glow
  const ex = xOf(n-1), ey = yOf(closes[n-1]);
  ctx.beginPath(); ctx.arc(ex, ey, 6, 0, Math.PI*2);
  ctx.fillStyle = lineClr + '33'; ctx.fill();
  ctx.beginPath(); ctx.arc(ex, ey, 3.5, 0, Math.PI*2);
  ctx.fillStyle = lineClr; ctx.fill();
}


// ── DETAIL MODAL ─────────────────────────────────────────
const MLABELS = {
  pe_ratio:'P/E', pb_ratio:'P/B', ps_ratio:'P/S',
  ev_ebitda:'EV/EBITDA', roe_pct:'ROE %',
  de_ratio:'D/E', net_debt_ebitda:'Net Debt/EBITDA',
  eps_trailing:'EPS (trail.)',
};
const LOWER_B = new Set(['de_ratio', 'net_debt_ebitda']);

function showMod(ticker) {
  const b = allData.find(x => x.ticker === ticker);
  if (!b) return;
  const r  = b.ratings || {};
  const rm = b.region_medians || {};

  const rows = Object.entries(MLABELS).map(([key, label]) => {
    const val    = b[key];
    const rating = r[key] || 'na';
    const bm     = rm[key] || { median: 0, sigma: 0 };
    const disp   = val != null ? (key === 'roe_pct' ? fP(val) : fN(val)) : 'N/A';
    const color  = clr(rating);
    let pct = 50;
    if (val != null && bm.sigma > 0) {
      const lo = bm.median - 2.5 * bm.sigma, hi = bm.median + 2.5 * bm.sigma;
      pct = Math.max(3, Math.min(97, ((parseFloat(val) - lo) / (hi - lo)) * 100));
      if (LOWER_B.has(key)) pct = 100 - pct;
    }
    const rl       = { ideal:'✅ Ideal', good:'🟡 Good', warn:'🔴 Warn', na:'⚪ N/A' }[rating];
    const dirHint  = LOWER_B.has(key) ? '↓ меньше = лучше' : '± от медианы';
    return `<tr>
      <td style="color:var(--sub)">${label}</td>
      <td style="color:${color};font-weight:600">${disp}</td>
      <td style="color:var(--sub)">${bm.median} <span style="font-size:9px;opacity:.6">(±${bm.sigma})</span></td>
      <td>${rl}</td>
      <td style="min-width:100px">
        <div class="bbar"><div class="bfill" style="width:${pct}%;background:${color}"></div></div>
        <div style="font-size:8px;color:var(--sub);margin-top:2px;opacity:.6">${dirHint}</div>
      </td>
    </tr>`;
  }).join('');

  const isKZ       = b.is_kase || b.ticker === 'KSPI';
  // Unique container id, safe for use in getElementById
  const chartCtnId = `chart-ctn-${safeId(ticker)}`;

  document.getElementById('mi').innerHTML = `
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
      <div class="av" style="width:46px;height:46px;font-size:15px;border-radius:10px">${ini(b.name)}</div>
      <div>
        <div class="mt">${b.name || b.ticker}</div>
        <div class="msub">
          <span>${b.ticker}</span>
          ${regBadge(b.region)}
          ${scoreBadge(b.score_pct || 0)}
          ${b.source_date ? `<span style="font-size:9px;opacity:.7">📅 ${b.source_date}</span>` : ''}
          ${b.resolved_as ? `<span style="font-size:9px;opacity:.5">→ ${b.resolved_as}</span>` : ''}
        </div>
      </div>
    </div>

    <div class="regnote">
      📍 Рейтинг сравнивается с медианой региона <strong>${b.region || '?'}</strong> — не с другими регионами
    </div>

    <div style="display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap">
      <a href="https://finance.yahoo.com/quote/${b.ticker}" target="_blank" rel="noopener"
        style="font-family:var(--mono);font-size:10px;color:var(--a);text-decoration:none;
        padding:4px 10px;border:1px solid rgba(0,212,255,.3);border-radius:5px;background:rgba(0,212,255,.05)">
        📊 Yahoo Finance ↗</a>
      ${isKZ ? `<a href="https://kase.kz/ru/shares/show/${b.ticker.replace('.KZ','')}/" target="_blank" rel="noopener"
        style="font-family:var(--mono);font-size:10px;color:var(--g);text-decoration:none;
        padding:4px 10px;border:1px solid rgba(0,229,160,.3);border-radius:5px;background:rgba(0,229,160,.05)">
        🇰🇿 KASE ↗</a>` : ''}
      <a href="https://www.investing.com/search/?q=${encodeURIComponent(b.name||b.ticker)}" target="_blank" rel="noopener"
        style="font-family:var(--mono);font-size:10px;color:var(--y);text-decoration:none;
        padding:4px 10px;border:1px solid rgba(251,191,36,.3);border-radius:5px;background:rgba(251,191,36,.05)">
        📈 Investing.com ↗</a>
    </div>

    ${b.price != null ? `
    <div style="display:flex;align-items:baseline;gap:20px;margin-bottom:4px;
        padding:14px 16px;background:var(--surface);border-radius:10px;border:1px solid var(--border)">
      <div>
        <div style="font-family:var(--mono);font-size:8.5px;color:var(--sub);margin-bottom:3px">
          ЦЕНА АКЦИИ${b.price_usd != null ? ' (USD)' : b.currency ? ' (' + b.currency + ')' : ''}
        </div>
        <div style="font-family:var(--mono);font-size:24px;font-weight:600">
          ${b.price_usd != null ? `$${parseFloat(b.price_usd).toFixed(2)}` : fPrice(b)}
        </div>
        ${b.price_usd != null && b.currency !== 'USD' && b.currency ? `
        <div style="font-family:var(--mono);font-size:11px;color:var(--sub);margin-top:3px">
          ${fPrice(b)}
          <span style="opacity:.5;margin-left:6px">× ${b.fx_rate_to_usd.toFixed(6)}</span>
        </div>` : ''}
      </div>
      ${b.price_change_p != null ? `
      <div>
        <div style="font-family:var(--mono);font-size:8.5px;color:var(--sub);margin-bottom:3px">ИЗМЕНЕНИЕ</div>
        <div class="${b.price_change_p > 0 ? 'pup' : b.price_change_p < 0 ? 'pdn' : 'pfl'}"
          style="font-family:var(--mono);font-size:18px;font-weight:600">
          ${b.price_change_p > 0 ? '▲' : '▼'} ${Math.abs(b.price_change_p).toFixed(2)}%
          <span style="font-size:11px;font-weight:400">(${b.price_change > 0 ? '+' : ''}${
            b.currency === 'KZT' || b.currency === 'JPY'
              ? Math.round(Math.abs(b.price_change)).toLocaleString()
              : fN(b.price_change, 2)
          } ${fCurSym(b.currency)})</span>
        </div>
      </div>` : ''}
    </div>` : ''}

    <div class="msec">График цены · 52 недели</div>
    <div class="chart-wrap">
      <div id="${chartCtnId}">
        <div class="chart-loading">⏳ Загрузка…</div>
      </div>
    </div>

    <!-- Tab switcher -->
    <div style="display:flex;gap:2px;margin:16px 0 0;background:var(--surface);border-radius:8px;padding:3px;border:1px solid var(--border)">
      <button id="tab-mult-${safeId(ticker)}" onclick="switchTab('${safeId(ticker)}','mult')"
        style="flex:1;padding:6px;background:var(--card);border:1px solid rgba(0,212,255,.3);border-radius:6px;
        font-family:var(--mono);font-size:9px;color:var(--a);cursor:pointer;text-transform:uppercase;letter-spacing:.06em">
        Мультипликаторы
      </button>
      <button id="tab-hist-${safeId(ticker)}" onclick="switchTab('${safeId(ticker)}','hist')"
        style="flex:1;padding:6px;background:none;border:none;border-radius:6px;
        font-family:var(--mono);font-size:9px;color:var(--sub);cursor:pointer;text-transform:uppercase;letter-spacing:.06em">
        История фундаменталов
      </button>
      <button id="tab-fin-${safeId(ticker)}" onclick="switchTab('${safeId(ticker)}','fin')"
        style="flex:1;padding:6px;background:none;border:none;border-radius:6px;
        font-family:var(--mono);font-size:9px;color:var(--sub);cursor:pointer;text-transform:uppercase;letter-spacing:.06em">
        Финансы
      </button>
    </div>

    <!-- TAB: Multiples -->
    <div id="tabpanel-mult-${safeId(ticker)}">
      <div class="msec" style="margin-top:12px">Мультипликаторы vs. Регион ${b.region}</div>
      <table class="bmt">
        <thead><tr>
          <th>Метрика</th><th>Значение</th>
          <th>Медиана ${b.region} (σ)</th><th>Рейтинг</th><th>Позиция</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>

    <!-- TAB: Historical fundamentals (loaded async) -->
    <div id="tabpanel-hist-${safeId(ticker)}" data-ticker="${ticker}" style="display:none">
      <div id="fund-ctn-${safeId(ticker)}">
        <div class="chart-loading">⏳ Нажмите вкладку для загрузки…</div>
      </div>
    </div>

    <!-- TAB: Financials snapshot -->
    <div id="tabpanel-fin-${safeId(ticker)}" style="display:none">
      <div class="msec" style="margin-top:12px">Финансовые показатели</div>
      ${b.currency !== 'USD' && b.currency && b.fx_rate_to_usd != null ? `
      <div style="font-family:var(--mono);font-size:9px;color:var(--sub);margin-bottom:10px;
          padding:6px 10px;background:var(--surface);border-radius:6px;border:1px solid var(--border)">
        Курс: 1 ${b.currency} = ${b.fx_rate_to_usd.toFixed(6)} USD
        &nbsp;·&nbsp; Левый столбец — USD, правый — ${b.currency}
      </div>` : ''}
      <div class="mfg">
        ${[
          ['Market Cap',     'market_cap'],
          ['Net Income',     'net_income'],
          ['EBITDA',         'ebitda'],
          ['FCF',            'fcf'],
          ['Equity',         'equity'],
          ['Total Debt',     'total_debt'],
          ['Cash',           'cash'],
        ].map(([label, field]) => {
          const usd   = b[field + '_usd'];
          const local = b[field];
          const isUsd = b.currency === 'USD' || !b.currency || b.fx_rate_to_usd == null || usd == null;
          const mainVal  = isUsd ? fB(local, b.currency || 'USD') : fB(usd, 'USD');
          const localVal = (!isUsd && local != null) ? fB(local, b.currency) : null;
          return `<div class="mf">
            <div class="mfl">${label}</div>
            <div class="mfv">
              ${mainVal}
              ${localVal ? `<span class="mflocal">${localVal}</span>` : ''}
            </div>
          </div>`;
        }).join('')}
        <div class="mf"><div class="mfl">ROA %</div>         <div class="mfv">${fP(b.roa_pct)}</div></div>
        <div class="mf"><div class="mfl">Book Value/Shr</div><div class="mfv">
          ${b.book_value_per_share_usd != null
            ? `$${fN(b.book_value_per_share_usd)}${b.currency !== 'USD' && b.book_value_per_share != null ? ` <span class="mflocal">${fN(b.book_value_per_share)} ${fCurSym(b.currency)}</span>` : ''}`
            : b.book_value_per_share != null ? fN(b.book_value_per_share) + ' ' + fCurSym(b.currency) : 'N/A'}
        </div></div>
        <div class="mf"><div class="mfl">52W Low</div>       <div class="mfv">
          ${b.week52_low_usd != null
            ? `$${fN(b.week52_low_usd, 2)}${b.currency !== 'USD' && b.week52_low != null ? ` <span class="mflocal">${fPrice({price:b.week52_low, currency:b.currency})}</span>` : ''}`
            : b.week52_low != null ? fPrice({price:b.week52_low, currency:b.currency}) : 'N/A'}
        </div></div>
        <div class="mf"><div class="mfl">52W High</div>      <div class="mfv">
          ${b.week52_high_usd != null
            ? `$${fN(b.week52_high_usd, 2)}${b.currency !== 'USD' && b.week52_high != null ? ` <span class="mflocal">${fPrice({price:b.week52_high, currency:b.currency})}</span>` : ''}`
            : b.week52_high != null ? fPrice({price:b.week52_high, currency:b.currency}) : 'N/A'}
        </div></div>
        <div class="mf"><div class="mfl">Industry</div>      <div class="mfv" style="font-size:10px">${b.industry || '—'}</div></div>
      </div>
    </div>

    <div style="font-family:var(--mono);font-size:9px;color:var(--sub);margin-top:14px;opacity:.55">
      Загружено: ${(b.fetched_at || '').slice(0,16).replace('T',' ')} UTC ·
      <a href="https://kase.kz" target="_blank" style="color:var(--g);text-decoration:none">KASE</a> ·
      <a href="https://www.investing.com" target="_blank" style="color:var(--y);text-decoration:none">Investing.com</a>
    </div>
  `;

  document.getElementById('ov').classList.add('open');

  // Load chart AFTER modal is open and in layout (setTimeout beats rAF here)
  setTimeout(() => loadChartInto(ticker, chartCtnId), 50);
}

function closeMod() { document.getElementById('ov').classList.remove('open'); }
function ovc(e)     { if (e.target === document.getElementById('ov')) closeMod(); }
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { closeMod(); closeCompare(); }
});

// switchTab: handles the Мультипликаторы / История / Финансы tabs in the detail modal
function switchTab(safeTickerId, tab) {
  const tabs   = ['mult', 'hist', 'fin'];
  const panels = tabs.map(t => document.getElementById(`tabpanel-${t}-${safeTickerId}`));
  const btns   = tabs.map(t => document.getElementById(`tab-${t}-${safeTickerId}`));

  panels.forEach((p, i) => {
    if (!p) return;
    const active = tabs[i] === tab;
    p.style.display = active ? '' : 'none';
  });
  btns.forEach((b, i) => {
    if (!b) return;
    const active = tabs[i] === tab;
    b.style.background = active ? 'var(--card)' : 'none';
    b.style.border     = active ? '1px solid rgba(0,212,255,.3)' : 'none';
    b.style.color      = active ? 'var(--a)' : 'var(--sub)';
  });

  // Lazy-load historical fundamentals on first click
  if (tab === 'hist') {
    const fundCtn = document.getElementById(`fund-ctn-${safeTickerId}`);
    if (fundCtn && fundCtn.querySelector('.chart-loading')) {
      // Recover original ticker from safeId (stored as data attribute on the panel)
      const panel = document.getElementById(`tabpanel-hist-${safeTickerId}`);
      const ticker = panel?.dataset.ticker;
      if (ticker) loadFundamentals(ticker, `fund-ctn-${safeTickerId}`);
    }
  }
}


// ── COMPARE TRAY (persistent, survives page changes) ─────
// CMP_COLORS resolved to hex for the chip dots (CSS vars don't work in inline style on some browsers)
const CMP_HEX = ['#00d4ff','#7b61ff','#00e5a0','#fbbf24','#f87171','#fb923c'];

function renderTray() {
  const tray   = document.getElementById('cmp-tray');
  const chips  = document.getElementById('cmp-tray-chips');
  const goBtn  = document.getElementById('cmp-tray-go');
  if (!tray || !chips) return;

  const arr = [...cmpSet];
  if (arr.length === 0) {
    tray.style.display = 'none';
    document.body.classList.remove('tray-open');
    return;
  }

  tray.style.display = 'flex';
  document.body.classList.add('tray-open');

  chips.innerHTML = arr.map((ticker, i) => {
    const rec  = allData.find(x => x.ticker === ticker);
    const name = rec?.name || ticker;
    const col  = CMP_HEX[i % CMP_HEX.length];
    return `<span class="cmp-chip" style="border-color:${col}33">
      <span class="cmp-chip-dot" style="background:${col}"></span>
      <span style="font-weight:600;color:${col}">${ticker}</span>
      <span style="color:var(--sub);margin-left:2px;max-width:100px;overflow:hidden;text-overflow:ellipsis">${name !== ticker ? name : ''}</span>
      <button class="cmp-chip-remove" onclick="removeFromCmp('${ticker}')" title="Убрать">×</button>
    </span>`;
  }).join('');

  if (goBtn) goBtn.textContent = `Сравнить (${arr.length}/${CMP_MAX})`;

  // Update the header compare button too
  const hBtn = document.getElementById('cmpbtn');
  if (hBtn) hBtn.textContent = `Сравнить (${arr.length}/${CMP_MAX})`;
}

function removeFromCmp(ticker) {
  cmpSet.delete(ticker);
  // Uncheck in table if visible
  document.querySelectorAll('.cmpck').forEach(cb => {
    if (cb.dataset.ticker === ticker) cb.checked = false;
  });
  renderTray();
  if (cmpSet.size === 0) {
    const hBtn = document.getElementById('cmpbtn');
    if (hBtn) hBtn.textContent = 'Сравнить';
  }
}

function resetCmp() {
  cmpSet.clear();
  document.querySelectorAll('.cmpck').forEach(cb => { cb.checked = false; });
  renderTray();
  const hBtn = document.getElementById('cmpbtn');
  if (hBtn) hBtn.textContent = 'Сравнить';
}

function toggleSel(ticker) {
  if (selectedSet.has(ticker)) {
    selectedSet.delete(ticker);
  } else {
    selectedSet.add(ticker);
  }
  // Синхронизируем только видимые чекбоксы этого тикера (не все сразу)
  document.querySelectorAll(`.selck[data-ticker="${CSS.escape(ticker)}"]`).forEach(cb => {
    cb.checked = selectedSet.has(ticker);
  });
  const btn = document.getElementById('xlsbtn');
  if (btn) {
    const n = selectedSet.size;
    btn.title = n > 0
      ? `Экспорт ${n} выбранных акций`
      : 'Экспорт в Excel (нет выбранных — экспортируются все)';
  }
}

function toggleCmp(ticker) {
  if (cmpSet.has(ticker)) {
    cmpSet.delete(ticker);
  } else {
    if (cmpSet.size >= CMP_MAX) {
      alert(`Можно сравнить не более ${CMP_MAX} акций. Уберите одну из выбранных.`);
      return;
    }
    cmpSet.add(ticker);
  }
  // Sync ALL visible checkboxes
  document.querySelectorAll('.cmpck').forEach(cb => {
    cb.checked = cmpSet.has(cb.dataset.ticker);
  });
  renderTray();
}

function openCompare() {
  if (cmpSet.size < 2) { alert('Выберите 2–6 акций чекбоксами в таблице'); return; }
  const recs = [...cmpSet].map(t => allData.find(x => x.ticker === t)).filter(Boolean);
  if (recs.length < 2) { alert('Данные не найдены — дождитесь загрузки'); return; }
  renderCompare(recs);
  document.getElementById('cmpov').classList.add('open');
}
function closeCompare() { document.getElementById('cmpov').classList.remove('open'); }

function renderCompare(recs) {
  // Per-ticker header cards
  const cards = recs.map((b, i) => `
    <div class="cmp-ticker-card">
      <div class="av" style="width:36px;height:36px;font-size:12px;border-radius:8px;
        margin:0 auto 6px;background:${CMP_COLORS[i]};color:var(--bg)">${ini(b.name)}</div>
      <div style="font-family:var(--disp);font-size:14px;letter-spacing:.03em;line-height:1.1">${b.name||b.ticker}</div>
      <div style="font-family:var(--mono);font-size:9px;color:${CMP_COLORS[i]};margin:3px 0">${b.ticker}</div>
      ${regBadge(b.region)}
      <div style="margin-top:5px">${scoreBadge(b.score_pct||0)}</div>
    </div>`).join('');

  const thCells = recs.map((b, i) =>
    `<th style="color:${CMP_COLORS[i]};font-family:var(--mono);font-size:9px">${b.ticker}</th>`
  ).join('');

  function makeRows(defs) {
    return defs.map(([label, key, fmt, higherBetter]) => {
      const vals    = recs.map(b => b[key]);
      const ratings = recs.map(b => (b.ratings || {})[key]);
      let best = -1;
      vals.forEach((v, i) => {
        if (v == null) return;
        if (best === -1 || (higherBetter ? v > vals[best] : v < vals[best])) best = i;
      });
      const cells = vals.map((v, i) => {
        const d   = v != null ? (fmt ? fmt(v) : fN(v)) : 'N/A';
        const col = ratings[i] ? clr(ratings[i]) : (v != null ? CMP_COLORS[i] : 'var(--sub)');
        const bld = i === best ? 'font-weight:700' : '';
        const bg  = i === best ? 'background:rgba(255,255,255,.04);border-radius:4px;padding:1px 4px' : '';
        return `<td style="font-family:var(--mono);font-size:11px;color:${col};${bld};${bg}">${d}</td>`;
      }).join('');
      return `<tr><td style="font-family:var(--mono);font-size:10px;color:var(--sub)">${label}</td>${cells}</tr>`;
    }).join('');
  }

  const priceDefs = [
    ['Цена',       'price',       v => fBraw(v), true],
    ['52W Low',    'week52_low',  v => fBraw(v), false],
    ['52W High',   'week52_high', v => fBraw(v), true],
    ['Market Cap', 'market_cap',  v => fBraw(v), true],
  ];
  const multDefs = [
    ['Score',           'score_pct',       v => v+'%', true],
    ['P/E',             'pe_ratio',        null,  false],
    ['P/B',             'pb_ratio',        null,  false],
    ['P/S',             'ps_ratio',        null,  false],
    ['EV/EBITDA',       'ev_ebitda',       null,  false],
    ['EV/Revenue',      'ev_revenue',      null,  false],
    ['D/E',             'de_ratio',        null,  true],
    ['Net Debt/EBITDA', 'net_debt_ebitda', null,  true],
    ['ROE %',           'roe_pct',         fP,    true],
    ['ROA %',           'roa_pct',         fP,    true],
    ['EPS (trail.)',    'eps_trailing',     v => fN(v, 2), false],
  ];
  const finDefs = [
    ['EBITDA',     'ebitda',     v => fBraw(v), true],
    ['Net Income', 'net_income', v => fBraw(v), true],
    ['FCF',        'fcf',        v => fBraw(v), true],
  ];

  // ── Средние значения ────────────────────────────────────────────────────
  const AVG_KEYS = [
    ['P/E',        'pe_ratio'],
    ['P/B',        'pb_ratio'],
    ['EV/EBITDA',  'ev_ebitda'],
    ['EV/Revenue', 'ev_revenue'],
  ];
  function avgRow(key, label) {
    const vals = recs.map(b => b[key]).filter(v => v != null && isFinite(v));
    if (!vals.length) return `<tr><td style="font-family:var(--mono);font-size:10px;color:var(--sub)">${label}</td><td colspan="${recs.length}" style="font-family:var(--mono);font-size:11px;color:var(--sub)">N/A</td></tr>`;
    const avg = vals.reduce((a,b)=>a+b,0) / vals.length;
    const med = [...vals].sort((a,b)=>a-b)[Math.floor(vals.length/2)];
    return `<tr>
      <td style="font-family:var(--mono);font-size:10px;color:var(--sub)">${label}</td>
      <td colspan="${recs.length}" style="font-family:var(--mono);font-size:11px;color:var(--a)">
        <span style="font-weight:600">avg ${fN(avg)}</span>
        <span style="opacity:.5;margin-left:8px;font-size:9px">med ${fN(med)}</span>
        <span style="opacity:.5;margin-left:8px;font-size:9px">n=${vals.length}</span>
      </td>
    </tr>`;
  }
  const avgHtml = AVG_KEYS.map(([label, key]) => avgRow(key, label)).join('');

  document.getElementById('cmpmi').innerHTML = `
    <div style="font-family:var(--disp);font-size:22px;letter-spacing:.03em;margin-bottom:14px">⚖️ Сравнение акций</div>
    <div class="cmp-header-row">${cards}</div>
    <div class="msec">Цена и капитализация</div>
    <div style="overflow-x:auto">
      <table class="bmt" style="margin-top:8px">
        <thead><tr><th style="font-family:var(--mono);font-size:9px;color:var(--sub)">Метрика</th>${thCells}</tr></thead>
        <tbody>${makeRows(priceDefs)}</tbody>
      </table>
    </div>
    <div class="msec">Мультипликаторы</div>
    <div style="overflow-x:auto">
      <table class="bmt" style="margin-top:8px">
        <thead><tr><th style="font-family:var(--mono);font-size:9px;color:var(--sub)">Метрика</th>${thCells}</tr></thead>
        <tbody>${makeRows(multDefs)}</tbody>
      </table>
    </div>
    <div class="msec">Финансовые показатели</div>
    <div style="overflow-x:auto">
      <table class="bmt" style="margin-top:8px">
        <thead><tr><th style="font-family:var(--mono);font-size:9px;color:var(--sub)">Метрика</th>${thCells}</tr></thead>
        <tbody>${makeRows(finDefs)}</tbody>
      </table>
    </div>
    <div class="msec" style="margin-top:20px">📊 Средние значения группы</div>
    <div style="overflow-x:auto">
      <table class="bmt" style="margin-top:8px">
        <thead><tr>
          <th style="font-family:var(--mono);font-size:9px;color:var(--sub)">Метрика</th>
          <th colspan="${recs.length}" style="font-family:var(--mono);font-size:9px;color:var(--sub)">avg (median) по ${recs.length} акциям</th>
        </tr></thead>
        <tbody>${avgHtml}</tbody>
      </table>
    </div>
    <div style="font-family:var(--mono);font-size:9px;color:var(--sub);margin-top:12px;opacity:.6">
      Жирный = лучшее значение · Цвет = региональный рейтинг · avg = среднее, med = медиана
    </div>
  `;
}


// ── HISTORICAL FUNDAMENTALS ───────────────────────────────
const fundCache = {};

async function loadFundamentals(ticker, containerId) {
  const wrap = document.getElementById(containerId);
  if (!wrap) return;
  wrap.innerHTML = `<div class="chart-loading">⏳ Загрузка исторических данных…</div>`;

  const now = Date.now();
  let fd = null;
  if (fundCache[ticker] && (now - fundCache[ticker].ts) < 7_200_000) {
    fd = fundCache[ticker].data;
  } else {
    try {
      const r = await fetch(`/api/fundamentals?ticker=${encodeURIComponent(ticker)}`);
      fd = await r.json();
      fundCache[ticker] = { data: fd, ts: now };
    } catch (e) {
      wrap.innerHTML = `<div class="chart-na">⚠ Ошибка загрузки фундаментальных данных</div>`;
      return;
    }
  }

  if (!fd || fd.error || (!Object.keys(fd.income||{}).length && !Object.keys(fd.balance||{}).length)) {
    const isKZ = ticker.endsWith('.KZ');
    wrap.innerHTML = `<div class="chart-na">📊 Исторические данные недоступны для ${ticker}${
      isKZ ? '<br><span style="font-size:9px;opacity:.7">Yahoo Finance не покрывает KASE — данные запрашиваются с kase.kz</span>' : ''
    }</div>`;
    return;
  }

  // Key metrics to show from each statement
  const INCOME_KEYS  = ['Total Revenue','Gross Profit','Operating Income','EBITDA','Net Income'];
  const BALANCE_KEYS = ['Total Assets','Total Liabilities Net Minority Interest','Stockholders Equity','Total Debt','Cash And Cash Equivalents'];
  const CF_KEYS      = ['Operating Cash Flow','Free Cash Flow','Capital Expenditure','Investing Cash Flow'];

  // Get all years sorted newest-first
  const allYears = [...new Set([
    ...Object.keys(fd.income  || {}),
    ...Object.keys(fd.balance || {}),
    ...Object.keys(fd.cashflow|| {}),
  ])].sort().reverse().slice(0, 5);  // max 5 years

  if (!allYears.length) {
    wrap.innerHTML = `<div class="chart-na">Нет данных</div>`;
    return;
  }

  const thYears = allYears.map(y => `<th style="text-align:right;color:var(--a)">${y}</th>`).join('');

  function makeHistRows(keys, src) {
    return keys.map(key => {
      const vals = allYears.map(y => (src[y] || {})[key]);
      if (vals.every(v => v == null)) return '';
      const cells = vals.map(v => {
        if (v == null) return `<td style="text-align:right;color:var(--sub)">—</td>`;
        const abs = Math.abs(v);
        let disp = abs >= 1e9 ? (v/1e9).toFixed(2)+'B'
                 : abs >= 1e6 ? (v/1e6).toFixed(1)+'M'
                 : v.toFixed(0);
        const col = v < 0 ? 'var(--r)' : 'var(--text)';
        return `<td style="text-align:right;font-family:var(--mono);font-size:11px;color:${col}">${disp}</td>`;
      }).join('');
      // Trend arrow between first two years
      const v0 = vals[1], v1 = vals[0];
      let trend = '';
      if (v0 != null && v1 != null && v0 !== 0) {
        const chg = (v1 - v0) / Math.abs(v0) * 100;
        trend = chg >= 0
          ? `<span style="color:var(--g);font-size:9px"> ▲${chg.toFixed(0)}%</span>`
          : `<span style="color:var(--r);font-size:9px"> ▼${Math.abs(chg).toFixed(0)}%</span>`;
      }
      // Shorten key name
      const shortKey = key.replace('Total ','').replace(' Net Minority Interest','').replace('And ','& ');
      return `<tr>
        <td style="color:var(--sub);font-size:10px;font-family:var(--mono)">${shortKey}${trend}</td>
        ${cells}
      </tr>`;
    }).filter(Boolean).join('');
  }

  wrap.innerHTML = `
    <div class="msec" style="margin-top:0">Отчёт о прибылях и убытках</div>
    <div style="overflow-x:auto">
      <table class="bmt" style="margin-top:6px">
        <thead><tr>
          <th style="font-family:var(--mono);font-size:9px;color:var(--sub)">Метрика</th>${thYears}
        </tr></thead>
        <tbody>${makeHistRows(INCOME_KEYS, fd.income || {})}</tbody>
      </table>
    </div>
    <div class="msec">Балансовый отчёт</div>
    <div style="overflow-x:auto">
      <table class="bmt" style="margin-top:6px">
        <thead><tr>
          <th style="font-family:var(--mono);font-size:9px;color:var(--sub)">Метрика</th>${thYears}
        </tr></thead>
        <tbody>${makeHistRows(BALANCE_KEYS, fd.balance || {})}</tbody>
      </table>
    </div>
    <div class="msec">Денежный поток</div>
    <div style="overflow-x:auto">
      <table class="bmt" style="margin-top:6px">
        <thead><tr>
          <th style="font-family:var(--mono);font-size:9px;color:var(--sub)">Метрика</th>${thYears}
        </tr></thead>
        <tbody>${makeHistRows(CF_KEYS, fd.cashflow || {})}</tbody>
      </table>
    </div>
    <div style="font-family:var(--mono);font-size:9px;color:var(--sub);margin-top:10px;opacity:.6">
      Данные: Yahoo Finance · Ежегодные отчёты · ▲▼ = изменение за последний год
    </div>
  `;
}


// ── API / POLLING ─────────────────────────────────────────
async function startFetch() {
  const raw     = document.getElementById('tkinput').value.trim();
  const tickers = raw ? raw.toUpperCase().split(/[\s,]+/).filter(Boolean) : [];

  document.getElementById('fbtn').disabled          = true;
  document.getElementById('sbtn').style.display     = 'inline-flex';
  document.getElementById('pgbar').style.display    = 'block';
  document.getElementById('pgfill').style.width     = '0%';

  try {
    await fetch('/api/fetch' + (tickers.length ? '?tickers=' + tickers.join(',') : ''), { method: 'POST' });
  } catch (e) {}
  poll();
}

// Clear all accumulated data and reset to empty state
// ── Excel export ──────────────────────────────────────────
function toggleXlsMenu(e) {
  e.stopPropagation();
  document.getElementById('xls-menu').classList.toggle('open');
}
// Close menu when clicking outside
document.addEventListener('click', () => {
  const m = document.getElementById('xls-menu');
  if (m) m.classList.remove('open');
});

async function exportExcel(mode) {
  // Close the dropdown
  const menu = document.getElementById('xls-menu');
  if (menu) menu.classList.remove('open');

  const btn = document.getElementById('xlsbtn');

  // Determine which tickers to export
  const selected = selectedSet && selectedSet.size > 0
    ? [...selectedSet]
    : allData.map(b => b.ticker);

  if (!selected.length) {
    alert('Нет данных — сначала запустите загрузку тикеров');
    return;
  }

  const isDcf     = mode === 'dcf';
  const endpoint  = isDcf ? '/api/export/dcf' : '/api/export';
  const modeLabel = isDcf ? 'DCF…' : 'Данные…';
  const modeIcon  = isDcf ? '📈' : '📊';

  if (btn) {
    btn.innerHTML = `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg> ${modeLabel}`;
    btn.disabled = true;
  }

  try {
    const params = new URLSearchParams({ tickers: selected.join(',') });
    const r = await fetch(`${endpoint}?${params}`);
    if (!r.ok) {
      const txt = await r.text().catch(() => '');
      alert('Ошибка экспорта: ' + (txt || r.statusText));
      return;
    }
    const blob = await r.blob();
    const a    = document.createElement('a');
    const date = new Date().toISOString().slice(0, 10);
    a.href     = URL.createObjectURL(blob);
    a.download = isDcf
      ? `dcf_valuation_${date}.xlsx`
      : `screener_${date}.xlsx`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
  } catch (e) {
    alert('Ошибка экспорта: ' + e.message);
  } finally {
    if (btn) {
      btn.innerHTML = `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><polyline points="9 15 12 18 15 15"/></svg> Excel ▾`;
      btn.disabled = false;
    }
  }
}

function clearAllData() {
  // Останавливаем поллинг — иначе следующий syncUI сразу вернёт данные с сервера
  clearInterval(pollTimer);
  pollTimer = null;

  // Останавливаем фоновую загрузку на сервере синхронно,
  // чтобы /api/stop гарантированно пришёл ДО следующего /api/fetch
  // (fire-and-forget с await внутри async-обёртки)
  (async () => { try { await fetch('/api/clear', { method: 'POST' }); } catch(e) {} })();

  allData      = [];
  filteredData = [];
  cmpSet.clear();
  curPage = 1;

  // Сбрасываем DOM полностью в начальное состояние
  document.getElementById('empty').style.display = 'flex';
  document.getElementById('tw').style.display    = 'none';
  document.getElementById('sbar').style.display  = 'none';
  document.getElementById('clabel').textContent  = '';
  document.getElementById('pgbar').style.display = 'none';
  document.getElementById('pgfill').style.width  = '0%';
  document.getElementById('fbtn').disabled       = false;
  document.getElementById('sbtn').style.display  = 'none';

  const pill = document.getElementById('spill');
  const txt  = document.getElementById('stxt');
  if (pill) pill.className = '';
  if (txt)  txt.textContent = 'Готов к запуску';

  // Очищаем tbody
  const tb = document.getElementById('tbody');
  if (tb) tb.innerHTML = '';

  // Сбрасываем пагинацию
  const pg = document.getElementById('pgbar-table');
  if (pg) pg.innerHTML = '';

  // Сбрасываем счётчики статистики
  ['st0','st1','st1n','st2','st3','st4'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = id === 'st4' ? '0' : '—';
  });

  renderTray();
}

async function stopFetch() {
  try { await fetch('/api/stop', { method: 'POST' }); } catch (e) {}
}

function poll() {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const d = await (await fetch('/api/status')).json();
      syncUI(d);
      if (d.status === 'done' || d.status === 'idle') {
        clearInterval(pollTimer);
        onDone(d);
      }
    } catch (e) { clearInterval(pollTimer); }
  }, 400);
}

function syncUI(d) {
  // DEBUG: видим сколько данных реально приходит с сервера
  if (d.data) {
    console.log(`[syncUI] status=${d.status} d.data.length=${d.data.length} allData.length=${allData.length}`);
  }
  const pill = document.getElementById('spill');
  const txt  = document.getElementById('stxt');
  const fill = document.getElementById('pgfill');
  if (d.status === 'loading') {
    pill.className = 'loading';
    txt.textContent = `Загрузка ${d.progress} / ${d.total}…`;
    fill.style.width = (d.total > 0 ? d.progress / d.total * 100 : 0) + '%';
    document.getElementById('sbtn').style.display = 'inline-flex';
    document.getElementById('fbtn').disabled = true;
  } else if (d.status === 'done') {
    pill.className = 'done';
    txt.textContent = `Обновлено: ${(d.last_updated || '').slice(0, 16).replace('T', ' ')} UTC`;
    fill.style.width = '100%';
  } else {
    pill.className = '';
    txt.textContent = 'Готов к запуску';
  }
  if (d.data && d.data.length) applyData(d.data);
}

function onDone(d) {
  document.getElementById('fbtn').disabled      = false;
  document.getElementById('sbtn').style.display = 'none';
  setTimeout(() => { document.getElementById('pgbar').style.display = 'none'; }, 900);
  // БАГ-1 FIX: не вызываем applyData(d.data) повторно.
  // syncUI() уже мержил все данные во время поллинга.
  // d.data в момент done — только последний снапшот (~53 записи), не все 649.
  if (allData.length) applyF();
}

// Restore state on page load (e.g. after browser refresh mid-fetch)
(async () => {
  try {
    const d = await (await fetch('/api/status')).json();
    syncUI(d);
    if (d.status === 'loading') poll();
  } catch (e) {}
})();
