/* Cross-asset UI extensions: one selection checkbox, ETF history and selected-assets portfolio builder. */
'use strict';

let lastPortfolioAmount = null;
let lastPortfolioResult = null;
let portfolioForecastResults = { gbm: null, bootstrap: null };
let activeForecastModel = "gbm";

function assetTypeLabel(t) {
  return t === 'bond' ? 'Облигация' : t === 'etf' ? 'ETF' : 'Акция';
}

function selectionCheckbox(b) {
  return `<input type="checkbox" class="cmpck" data-ticker="${b.ticker}"
    onclick="event.stopPropagation();toggleCmp('${b.ticker}')"
    ${cmpSet.has(b.ticker) ? 'checked' : ''}
    title="Выбрать для сравнения и готового портфеля">`;
}

// One checkbox only. It serves both Compare and Portfolio Builder.
function stockNameCell(b) {
  const kzBadge = b.is_kase ? '<span class="kz-badge">KASE</span>' : '';
  return `<div class="tc">
    ${selectionCheckbox(b)}
    <div class="av">${ini(b.name)}</div>
    <div><div class="tn">${b.name || b.ticker}${kzBadge}</div>
    <div class="td2">${b.ticker}${b.currency ? ' · ' + b.currency : ''}${b.market ? ' · ' + marketLabel(b.market) : ''}</div></div>
  </div>`;
}

function selectableAssetNameCell(b, showCurrency=true) {
  const sub = `${b.ticker}${showCurrency && b.currency ? ' · ' + b.currency : ''}`;
  return `<div class="tc">
    ${selectionCheckbox(b)}
    <div class="av">${ini(b.name)}</div><div>
      <div class="tn">${b.name || b.ticker}</div>
      <div class="td2">${sub}</div>
    </div>
  </div>`;
}

function renderTableHeader() {
  const head = document.getElementById('table-head');
  if (!head) return 1;
  const asset = currentAsset();
  let cells;
  if (asset === 'etf') {
    cells = [
      th('name','ETF'), th('market','Рынок'), th('fund_category','Категория'), th('price','Цена'),
      th('nav_price','NAV'), th('yield_pct','Yield %'), th('ytd_return_pct','YTD %'),
      th('three_year_return_pct','3Y Avg %'), th('five_year_return_pct','5Y Avg %'),
      th('beta_3y','Beta'), th('volume','Volume'), th(null,'52W Range'),
      th(null,'История цены'), th(null,'Дата источника')
    ];
  } else if (asset === 'bond') {
    cells = [
      th('name','Облигация'), th('market','Рынок'), th('issuer','Эмитент'), th('bond_type','Тип'),
      th('coupon_pct','Купон %', true), th('maturity','Погашение'), th('yield_pct','Yield %'),
      th(null,'Дата данных')
    ];
  } else {
    cells = [
      th('name','Компания'), th('region','Регион'), th('sector','Сектор'), th('score_pct','Score', true),
      th('price','Цена'), th('market_cap','Mkt Cap'), th('pe_ratio','P/E'), th('pb_ratio','P/B'),
      th('de_ratio','D/E'), th('ev_ebitda','EV/EBITDA'), th('net_debt_ebitda','ND/EBITDA'),
      th('roe_pct','ROE %'), th('roa_pct','ROA %'), th('ps_ratio','P/S'), th('ebitda','EBITDA'),
      th('net_income','Net Income'), th('fcf','FCF'), th('eps_trailing','EPS'),
      th(null,'52W Range'), th(null,'Дата источника')
    ];
  }
  head.innerHTML = `<tr>${cells.join('')}</tr>`;
  return cells.length;
}

function renderEtfRow(b) {
  return `<tr>
    <td>${selectableAssetNameCell(b)}</td>
    <td>${marketLabel(b.market)}</td>
    <td><span class="stag" title="${b.fund_family || ''}">${b.fund_category || b.sector || 'ETF'}</span></td>
    <td>${priceCell(b)}</td>
    <td class="bignum">${navCell(b)}</td>
    <td>${b.yield_pct != null ? fP(b.yield_pct) : '<span class="vn">N/A</span>'}</td>
    <td>${b.ytd_return_pct != null ? fP(b.ytd_return_pct) : '<span class="vn">N/A</span>'}</td>
    <td>${b.three_year_return_pct != null ? fP(b.three_year_return_pct) : '<span class="vn">N/A</span>'}</td>
    <td>${b.five_year_return_pct != null ? fP(b.five_year_return_pct) : '<span class="vn">N/A</span>'}</td>
    <td>${b.beta_3y != null ? fN(b.beta_3y) : '<span class="vn">N/A</span>'}</td>
    <td class="bignum">${b.volume != null ? fBraw(Number(b.volume)) : '<span class="vn">N/A</span>'}</td>
    <td>${w52Cell(b)}</td>
    <td><button class="history-btn" onclick="event.stopPropagation();showEtfHistory('${b.ticker}')">📈 1Y</button></td>
    <td class="srcdate">${b.source_date || '—'}</td>
  </tr>`;
}

function renderBondRow(b) {
  const coupon = b.coupon_text
    ? `<span title="${b.coupon_text}">${b.coupon_pct != null ? fP(b.coupon_pct) : b.coupon_text}</span>`
    : (b.coupon_pct != null ? fP(b.coupon_pct) : '<span class="vn">N/A</span>');
  const yld = b.yield_pct != null ? fP(b.yield_pct) : '<span class="vn">N/A</span>';
  const dataDate = b.price_date || b.source_date || '—';
  return `<tr>
    <td>${selectableAssetNameCell(b, false)}</td>
    <td>${marketLabel(b.market)}</td>
    <td>${b.issuer || '—'}</td>
    <td><span class="stag">${b.bond_type || 'Bond'}</span></td>
    <td style="font-family:var(--mono);font-weight:700">${coupon}</td>
    <td>${b.maturity || '—'}</td>
    <td style="font-family:var(--mono);font-weight:700;color:var(--a)">${yld}</td>
    <td class="srcdate" title="${b.source || ''}">${dataDate}</td>
  </tr>`;
}

function setSortOptions(asset) {
  if (asset === 'etf') sortState = { key: 'three_year_return_pct', dir: -1 };
  else if (asset === 'bond') sortState = { key: 'coupon_pct', dir: -1 };
  else sortState = { key: 'score_pct', dir: -1 };
}

// Column-header sorting remains; the old AUM/sort dropdown is intentionally removed.
function applyF() {
  const q     = (document.getElementById('search').value || '').toLowerCase();
  const qf    = document.getElementById('qsel').value;
  const rf    = document.getElementById('rsel').value;
  const mf    = document.getElementById('msel').value;
  const asset = currentAsset();
  const sf    = document.getElementById('ssel').value;
  const sortKey = sortState.key;
  const sortDir = sortState.dir;

  let d = allData.filter(b => {
    if ((b.asset_type || 'stock') !== asset) return false;
    const hay = `${b.name||''} ${b.ticker||''} ${b.sector||''} ${b.region||''} ${b.industry||''} ${b.fund_category||''} ${b.fund_family||''} ${b.issuer||''} ${b.maturity||''}`.toLowerCase();
    if (q && !hay.includes(q)) return false;
    if (mf !== 'All' && b.market !== mf) return false;
    if (asset === 'stock') {
      if (qf === 'high' && (b.score_pct || 0) < 70) return false;
      if (qf === 'mid' && ((b.score_pct || 0) < 40 || (b.score_pct || 0) >= 70)) return false;
      if (qf === 'low' && (b.score_pct || 0) >= 40) return false;
      if (rf !== 'all' && b.region !== rf) return false;
      if (sf !== 'all' && b.sector !== sf) return false;
    }
    return true;
  });

  d.sort((a,b) => {
    let av=a[sortKey], bv=b[sortKey];
    if (typeof av === 'string' || typeof bv === 'string') { av=(av||'').toLowerCase(); bv=(bv||'').toLowerCase(); }
    if (av == null) return 1; if (bv == null) return -1;
    return (av < bv ? -1 : av > bv ? 1 : 0) * sortDir;
  });
  filteredData = d; curPage = 1;
  updateStats(asset === 'bond' ? filteredData : allData);
  renderTable(filteredData);
}

function updateStats(data) {
  const asset = currentAsset();
  const rows = data.filter(b => (b.asset_type || 'stock') === asset);
  const ok = rows.filter(b => !b.error);
  document.getElementById('st0').textContent = rows.length;

  const l1=document.getElementById('st1l'), l2=document.getElementById('st2l'), l3=document.getElementById('st3l');
  const s2=document.getElementById('st2s'), s3=document.getElementById('st3s');
  const v1=document.getElementById('st1'), v1n=document.getElementById('st1n');
  const v2=document.getElementById('st2'), v3=document.getElementById('st3');

  if (asset === 'etf') {
    l1.textContent='Avg Yield'; l2.textContent='Avg 3Y Return'; l3.textContent='Avg 5Y Return';
    s2.textContent='% средняя'; s3.textContent='% средняя'; v1n.textContent='ETF';
    const y=avgField(ok,'yield_pct'), r3=avgField(ok,'three_year_return_pct'), r5=avgField(ok,'five_year_return_pct');
    v1.textContent=y==null?'—':y.toFixed(2)+'%';
    v2.textContent=r3==null?'—':r3.toFixed(1)+'%';
    v3.textContent=r5==null?'—':r5.toFixed(1)+'%';
  } else if (asset === 'bond') {
    l1.textContent='Max Yield'; l2.textContent='Avg Coupon'; l3.textContent='Corporate';
    s2.textContent='% по выпускам'; s3.textContent='в выборке'; v1n.textContent='Bonds';
    const ys=ok.map(b=>Number(b.yield_pct)).filter(Number.isFinite), cps=ok.map(b=>Number(b.coupon_pct)).filter(Number.isFinite);
    v1.textContent=ys.length?Math.max(...ys).toFixed(2)+'%':'—';
    v2.textContent=cps.length?(cps.reduce((a,v)=>a+v,0)/cps.length).toFixed(2)+'%':'—';
    v3.textContent=String(ok.filter(b=>b.bond_class==='Corporate').length);
  } else {
    l1.textContent='Лучший Score'; l2.textContent='Avg ROE'; l3.textContent='Ideal метрик';
    s2.textContent='% по выборке'; s3.textContent='avg / компания';
    const scored=ok.filter(b=>b.score_pct!=null);
    if (scored.length) { const best=[...scored].sort((a,b)=>(b.score_pct||0)-(a.score_pct||0))[0]; v1.textContent=best.score_pct+'%'; v1n.textContent=best.ticker; }
    else { v1.textContent='—'; v1n.textContent='—'; }
    const roes=ok.filter(b=>b.roe_pct!=null).map(b=>Number(b.roe_pct));
    v2.textContent=roes.length?(roes.reduce((a,v)=>a+v,0)/roes.length).toFixed(1)+'%':'—';
    v3.textContent=ok.length?(ok.reduce((sum,b)=>sum+Object.values(b.ratings||{}).filter(v=>v==='ideal').length,0)/ok.length).toFixed(1):'—';
  }

  const sel=document.getElementById('ssel');
  if (asset==='stock') {
    const secs=[...new Set(rows.map(b=>b.sector).filter(Boolean))].sort(); const cur=sel.value;
    sel.innerHTML='<option value="all">Все секторы</option>'+secs.map(x=>`<option value="${x}"${x===cur?' selected':''}>${x}</option>`).join('');
  } else sel.innerHTML='<option value="all">Все секторы</option>';
}

function clearSelectedAssets(){
  if(!cmpSet.size){alert('Выбранных активов сейчас нет.');return;}
  cmpSet.clear();
  lastPortfolioResult=null;
  document.querySelectorAll('.cmpck').forEach(cb=>{cb.checked=false;});
  const btn=document.getElementById('clear-assets-btn');
  if(btn){btn.textContent='↺ Выбор очищен';setTimeout(()=>{btn.textContent='↺ Очистить выбранные';},1200);}
}

function toggleCmp(ticker) {
  lastPortfolioResult = null;
  if (cmpSet.has(ticker)) cmpSet.delete(ticker);
  else {
    cmpSet.add(ticker);
  }
  document.querySelectorAll('.cmpck').forEach(cb => { cb.checked = cmpSet.has(cb.dataset.ticker); });
  renderTray();
}

function renderTray() {
  const tray=document.getElementById('cmp-tray'), chips=document.getElementById('cmp-tray-chips'), goBtn=document.getElementById('cmp-tray-go');
  if (!tray || !chips) return;
  const arr=[...cmpSet];
  if (!arr.length) { tray.style.display='none'; document.body.classList.remove('tray-open'); return; }
  tray.style.display='flex'; document.body.classList.add('tray-open');
  const colors=['#00d4ff','#7b61ff','#00e5a0','#fbbf24','#f87171','#fb923c','#22c55e','#38bdf8','#e879f9','#f59e0b','#a3e635','#f43f5e'];
  chips.innerHTML=arr.map((ticker,i)=>{
    const rec=allData.find(x=>x.ticker===ticker), name=rec?.name||ticker, col=colors[i%colors.length];
    return `<span class="cmp-chip" style="border-color:${col}33"><span class="cmp-chip-dot" style="background:${col}"></span><span style="font-weight:600;color:${col}">${ticker}</span><span style="color:var(--sub);margin-left:2px;max-width:100px;overflow:hidden;text-overflow:ellipsis">${name!==ticker?name:''}</span><button class="cmp-chip-remove" onclick="removeFromCmp('${ticker}')">×</button></span>`;
  }).join('');
  if (goBtn) goBtn.textContent=`Сравнить (${arr.length})`;
  const hBtn=document.getElementById('cmpbtn'); if(hBtn) hBtn.textContent=`Сравнить (${arr.length})`;
}

function showEtfHistory(ticker) {
  const b=allData.find(x=>x.ticker===ticker);
  if (!b) return;
  const id=`etf-history-${safeId(ticker)}`;
  document.getElementById('mi').innerHTML=`
    <div class="mt">${b.name || ticker}</div>
    <div class="msub"><span>${ticker}</span><span>ETF</span><span>${marketLabel(b.market)}</span></div>
    <div class="msec">Историческая цена · последние 12 месяцев</div>
    <div class="chart-wrap"><div id="${id}"><div class="chart-loading">⏳ Загрузка…</div></div></div>
    <div class="portfolio-note">История строится по adjusted daily close. Прошлая доходность не гарантирует будущую.</div>`;
  document.getElementById('ov').classList.add('open');
  setTimeout(()=>loadChartInto(ticker,id),50);
}

function selectedRecords() {
  return [...cmpSet].map(t=>allData.find(x=>x.ticker===t)).filter(Boolean);
}

function matrixHtml(payload, digits=2, percent=false) {
  const labels=payload?.labels||[], matrix=payload?.matrix||[];
  if(!labels.length) return '<div class="portfolio-note">Недостаточно данных для матрицы.</div>';
  return `<div class="matrix-wrap"><table class="matrix-table"><thead><tr><th></th>${labels.map(x=>`<th>${x}</th>`).join('')}</tr></thead><tbody>${labels.map((lab,i)=>`<tr><th>${lab}</th>${(matrix[i]||[]).map(v=>`<td>${v==null?'—':(percent?(Number(v)*100).toFixed(digits)+'%':Number(v).toFixed(digits))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}

function openPortfolioBuilder() {
  if (cmpSet.size < 1) { alert('Сначала выберите акции, облигации или ETF галочками в таблице.'); return; }
  const selected=[...cmpSet];
  document.getElementById('portfolio-mi').innerHTML=`
    <div class="mt">🧩 Собрать портфель → рассчитать будущий риск</div>
    <div class="portfolio-note"><strong>Выбрано:</strong> ${selected.join(', ')}.<br>
      Markowitz-анализ будет выполнен <strong>строго между этими активами</strong>. Другие бумаги не добавляются. ETF look-through показывается только как информация и не ограничивает веса оптимизации.</div>
    <div class="portfolio-form-grid">
      <label class="portfolio-field"><span>На какую сумму хотите инвестировать?</span><div class="money-input"><input id="portfolio-amount" type="text" inputmode="numeric" autocomplete="off" value="${lastPortfolioAmount ? formatMoneyInput(lastPortfolioAmount) : ''}" placeholder="5 000 000"><b>₸</b></div></label>
      <label class="portfolio-field"><span>Цель оптимизации</span><select id="portfolio-objective"><option value="max_sharpe">Maximum Sharpe</option><option value="min_variance">Minimum Variance</option><option value="equal_weight">1/N Equal Weight</option></select></label>
      <label class="portfolio-field"><span>Covariance</span><select id="portfolio-covariance-method"><option value="ledoit_wolf">Ledoit–Wolf — устойчивее к шуму</option><option value="sample">Sample Covariance — академическое сравнение</option></select></label>
      <label class="portfolio-field"><span>Режим концентрации</span><select id="portfolio-concentration-mode"><option value="constrained">Практический лимит концентрации</option><option value="unconstrained">Без лимита концентрации (академический benchmark)</option></select><small>Практический режим: 2 актива — 60%, 3 — 45%, 4 — 35%, 5+ — 25% максимум на один актив.</small></label>
    </div>
    <div class="portfolio-risk-note"><strong>Два последовательных шага:</strong> <strong>Markowitz</strong> отвечает на вопрос «как распределить деньги между выбранными активами с учётом исторического риска и доходности?». После этого вы отдельно выбираете <strong>GBM Monte Carlo</strong> или <strong>Статистический Bootstrap</strong>. Обе модели получают одни и те же веса, но остаются независимыми.</div>
    <button class="btn portfolio-btn portfolio-calc" onclick="calculatePortfolio()">Рассчитать оптимальный портфель</button>
    <div id="portfolio-result"></div>`;
  portfolioForecastResults={gbm:null,bootstrap:null};
  activeForecastModel='gbm';
  document.getElementById('portfolioov').classList.add('open');
  bindMoneyInput();
}

function closePortfolioBuilder(){ document.getElementById('portfolioov').classList.remove('open'); }

function formatMoneyInput(v){
  const digits=String(v ?? '').replace(/\D/g,'');
  return digits ? Number(digits).toLocaleString('ru-RU') : '';
}
function parseMoneyInput(v){
  const digits=String(v ?? '').replace(/\D/g,'');
  return digits ? Number(digits) : 0;
}
function bindMoneyInput(){
  const el=document.getElementById('portfolio-amount'); if(!el) return;
  el.addEventListener('input',()=>{
    const pos=el.selectionStart ?? el.value.length;
    const before=(el.value.slice(0,pos).match(/\d/g)||[]).length;
    const raw=el.value.replace(/\D/g,'');
    el.value=raw ? Number(raw).toLocaleString('ru-RU') : '';
    let idx=0, seen=0;
    while(idx<el.value.length && seen<before){ if(/\d/.test(el.value[idx])) seen++; idx++; }
    try{ el.setSelectionRange(idx,idx); }catch(e){}
  });
}
function fmtKzt(v){ return Math.round(Number(v)||0).toLocaleString('ru-RU')+' ₸'; }
function assetIcon(t){ return t==='bond'?'🏦':t==='etf'?'📦':'🏢'; }

async function calculatePortfolio(){
  const amount=parseMoneyInput(document.getElementById('portfolio-amount')?.value||0);
  if(!(amount>0)){alert('Введите сумму инвестирования');return;}
  if(cmpSet.size<1){alert('Выберите хотя бы один актив');return;}
  lastPortfolioAmount=amount;
  portfolioForecastResults={gbm:null,bootstrap:null};
  activeForecastModel='gbm';
  const out=document.getElementById('portfolio-result');
  out.innerHTML='<div class="chart-loading">⏳ Загружаем историю выбранных активов и рассчитываем веса Markowitz…</div>';
  const objective=document.getElementById('portfolio-objective')?.value||'max_sharpe';
  const concentrationMode=document.getElementById('portfolio-concentration-mode')?.value||'constrained';
  const covarianceMethod=document.getElementById('portfolio-covariance-method')?.value||'ledoit_wolf';
  const params=new URLSearchParams({assets:[...cmpSet].join(','),amount:String(amount),objective,concentration_mode:concentrationMode,covariance_method:covarianceMethod});
  try{
    const r=await fetch('/api/portfolio?'+params.toString()); const d=await r.json();
    if(!r.ok || d.error) throw new Error(d.error||'Ошибка расчёта');
    lastPortfolioResult=d; renderPortfolioResult(d);
  }catch(e){ out.innerHTML=`<div class="portfolio-warning">⚠ ${e.message}</div>`; }
}

function drawEfficientFrontier(canvasId, ef){
  const canvas=document.getElementById(canvasId); if(!canvas) return;
  const pts=(ef?.points||[]).filter(p=>Number.isFinite(Number(p.risk_pct))&&Number.isFinite(Number(p.return_pct)));
  if(!pts.length){canvas.parentElement.innerHTML='<div class="portfolio-note">Недостаточно точек для графика эффективной границы.</div>';return;}
  const dpr=window.devicePixelRatio||1, cssW=Math.max(640,canvas.parentElement.clientWidth||900), cssH=330;
  canvas.width=cssW*dpr; canvas.height=cssH*dpr; canvas.style.width=cssW+'px'; canvas.style.height=cssH+'px';
  const ctx=canvas.getContext('2d'); ctx.scale(dpr,dpr);
  const pad={l:60,r:24,t:24,b:52};
  const xs=pts.map(p=>Number(p.risk_pct)), ys=pts.map(p=>Number(p.return_pct));
  const special=[ef?.max_sharpe,ef?.minimum_variance].filter(Boolean);
  special.forEach(p=>{xs.push(Number(p.risk_pct));ys.push(Number(p.return_pct));});
  let xmin=Math.min(...xs), xmax=Math.max(...xs), ymin=Math.min(...ys), ymax=Math.max(...ys);
  const dx=Math.max(xmax-xmin,1), dy=Math.max(ymax-ymin,1); xmin-=dx*.08; xmax+=dx*.08; ymin-=dy*.12; ymax+=dy*.12;
  const X=x=>pad.l+(x-xmin)/(xmax-xmin)*(cssW-pad.l-pad.r);
  const Y=y=>cssH-pad.b-(y-ymin)/(ymax-ymin)*(cssH-pad.t-pad.b);
  ctx.font='10px monospace'; ctx.fillStyle='#7083ad'; ctx.strokeStyle='rgba(112,131,173,.18)'; ctx.lineWidth=1;
  for(let i=0;i<=5;i++){
    const x=xmin+(xmax-xmin)*i/5, px=X(x); ctx.beginPath();ctx.moveTo(px,pad.t);ctx.lineTo(px,cssH-pad.b);ctx.stroke();ctx.fillText(x.toFixed(1)+'%',px-14,cssH-pad.b+18);
    const y=ymin+(ymax-ymin)*i/5, py=Y(y); ctx.beginPath();ctx.moveTo(pad.l,py);ctx.lineTo(cssW-pad.r,py);ctx.stroke();ctx.fillText(y.toFixed(1)+'%',6,py+3);
  }
  ctx.fillStyle='#8fa2cc';ctx.fillText('Исторический риск σ →',cssW/2-70,cssH-12);
  ctx.save();ctx.translate(14,cssH/2+55);ctx.rotate(-Math.PI/2);ctx.fillText('Историческая модельная доходность →',0,0);ctx.restore();
  const sorted=[...pts].sort((a,b)=>Number(a.risk_pct)-Number(b.risk_pct));
  ctx.strokeStyle='#00d4ff';ctx.lineWidth=2.5;ctx.beginPath();sorted.forEach((p,i)=>{const x=X(Number(p.risk_pct)),y=Y(Number(p.return_pct));i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();
  sorted.forEach(p=>{ctx.fillStyle='#00d4ff';ctx.beginPath();ctx.arc(X(Number(p.risk_pct)),Y(Number(p.return_pct)),2.3,0,Math.PI*2);ctx.fill();});
  const drawPoint=(p,color,label)=>{if(!p)return;const x=X(Number(p.risk_pct)),y=Y(Number(p.return_pct));ctx.fillStyle=color;ctx.beginPath();ctx.arc(x,y,6,0,Math.PI*2);ctx.fill();ctx.font='bold 10px monospace';const tw=ctx.measureText(label).width;const lx=(x+tw+18>cssW-pad.r)?x-tw-9:x+9;ctx.fillText(label,lx,y-8);};
  drawPoint(ef.minimum_variance,'#fbbf24','Min Variance');
  drawPoint(ef.max_sharpe,'#00e5a0','Maximum Sharpe');
}

function renderPortfolioResult(d){
  const selected=d.selected||[];
  const alloc=(d.allocation||[]).map((a,i)=>`
    <div class="portfolio-check-item ${Number(a.weight_pct)===0?'zero-weight':''}">
      <div class="portfolio-check-num">${i+1}</div>
      <div class="portfolio-check-main"><strong>${assetIcon(a.asset_type)} ${a.name || a.ticker} (${a.ticker})</strong><span>${assetTypeLabel(a.asset_type)} · ${a.market || '—'}</span></div>
      <div class="portfolio-check-weight">Вес: <strong>${Number(a.weight_pct).toFixed(1)}%</strong></div>
      <div class="portfolio-check-amount">Инвестировать: <strong>${fmtKzt(a.amount_kzt)}</strong></div>
    </div>`).join('');
  const zero=(d.zero_weight_assets||[]).length?`
    <div class="msec">Почему некоторые выбранные активы получили 0%?</div>
    <div class="zero-weight-list">${d.zero_weight_assets.map(z=>`<div><strong>${z.ticker} — 0%</strong><span>${z.reason}</span></div>`).join('')}</div>`:'';
  const warnings=(d.warnings||[]).length?`<div class="portfolio-warning">${d.warnings.map(w=>'⚠ '+w).join('<br>')}</div>`:'';
  const totalWeight=(d.allocation||[]).reduce((s,a)=>s+Number(a.weight_pct||0),0);
  const selectedText=selected.join(', ');
  const exp=d.exposure_analysis||{};
  const etfLines=Object.entries(exp.etf_holdings||{}).filter(([k])=>k!=='_missing_etf_holdings').map(([ticker,v])=>`<div><strong>${ticker}</strong>: ${Number(v.holdings_count||0)} позиций в look-through</div>`).join('');
  const missingEtf=(exp.etf_holdings||{})._missing_etf_holdings||[];
  const topExp=(exp.top_effective_exposures||[]).slice(0,8).map(x=>`<div><strong>${x.underlying}</strong><span>эффективная экспозиция: ${Number(x.effective_weight_pct||0).toFixed(1)}%</span></div>`).join('');
  const exposureHtml=(etfLines||missingEtf.length||topExp)?`<div class="msec">🧩 Look-through ETF</div><div class="portfolio-human-text">Состав ETF показывается только для прозрачности. Он <strong>не ограничивает</strong> веса Markowitz.</div>${topExp?`<div class="zero-weight-list">${topExp}</div>`:''}${etfLines?`<div class="portfolio-note">${etfLines}</div>`:''}${missingEtf.length?`<div class="portfolio-warning">⚠ Не удалось получить полный состав: ${missingEtf.join(', ')}.</div>`:''}`:'';
  document.getElementById('portfolio-result').innerHTML=`
    <div class="portfolio-result-card">
      <div class="portfolio-result-title">✅ Структура портфеля рассчитана</div>
      <div class="portfolio-model-meta">
        <span>Markowitz: <strong>${d.portfolio?.objective==='min_variance'?'Minimum Variance':d.portfolio?.objective==='equal_weight'?'1/N Equal Weight':'Maximum Sharpe'}</strong></span>
        <span>Covariance: <strong>${d.covariance?.label || d._engine?.covariance_method || d.portfolio?.covariance_method || '—'}</strong></span>
        <span>Short selling: <strong>нет</strong></span>
        <span>Выбрано активов: <strong>${selected.length}</strong></span><span>Base: <strong>USD</strong></span><span>U.S. RF: <strong>${Number(d.risk_free?.rate_pct ?? d.portfolio?.risk_free_rate_pct ?? 0).toFixed(2)}%</strong>${d.risk_free?.as_of?` <small>(${d.risk_free.as_of})</small>`:''}</span><span>Лимит позиции: <strong>${d.portfolio?.concentration_mode==='unconstrained'?'100%':Number(d.portfolio?.max_position_weight_pct||100).toFixed(0)+'%'}</strong></span><span>Snapshot: <strong>${String(d.snapshot_id||'—').slice(0,8)}</strong></span>
      </div>
      <div class="portfolio-human-text"><strong>Главная идея:</strong> Markowitz отвечает только на вопрос <em>«как разделить ваш капитал между выбранными активами?»</em>. Он не обещает прибыль. После получения весов этот капитал передаётся в scenario simulation для оценки возможного будущего диапазона.</div>
      <div class="portfolio-note"><strong>USD-модель:</strong> доходности иностранных активов приводятся к USD до Markowitz. Для Sharpe/Maximum Sharpe автоматически используется текущая ставка 13-недельного U.S. Treasury bill${d.risk_free?.source?` · источник: ${d.risk_free.source}`:''}${d.risk_free?.stale?' · ⚠ используется последнее сохранённое значение':''}.</div>
      <div class="msec">📋 Распределение капитала</div>
      <div class="portfolio-checklist">${alloc}</div>
      <div class="portfolio-total"><strong>Итого: ${totalWeight.toFixed(1)}%</strong> распределено строго между выбранными активами: ${selectedText}.</div>
      ${zero}
      ${exposureHtml}
      <div class="portfolio-human-text danger"><strong>⚠ Важно:</strong> веса Markowitz основаны на прошлом поведении активов. Они нужны для построения модельной структуры, а не являются гарантией будущей доходности.</div>

      <div class="msec">Portfolio Risk Decomposition</div>
      <div id="portfolio-risk-contribution"><div class="chart-loading">⏳ MRC / Risk Contribution…</div></div>

      <div class="msec">Position Size Frontier · new investment idea</div>
      <div class="portfolio-note">Existing weights stay frozen and are funded proportionally: w′ⱼ=(1−x)wⱼ. The candidate is tested from 0% to 20%.</div>
      <div class="portfolio-form-grid">
        <label class="portfolio-field"><span>Candidate ticker</span><input id="psf-candidate" type="text" placeholder="GOOGL" autocomplete="off"></label>
        <label class="portfolio-field"><span>Candidate weight</span><select id="psf-weight">${[1,2,3,4,5,6,8,10,12,15,20].map(x=>`<option value="${x}" ${x===5?'selected':''}>${x}%</option>`).join('')}</select></label>
      </div>
      <button class="btn event-run-btn" onclick="runPositionSizeFrontier()">Analyze Portfolio Addition</button>
      <div id="position-size-frontier-result"></div>

      <div class="forecast-callout">
        <div>
          <div class="forecast-callout-title">🔮 Следующий шаг: выберите модель сценарного анализа</div>
          <div class="forecast-callout-text">Начальные веса Markowitz фиксируются в Portfolio Snapshot. Затем обе модели используют buy-and-hold: веса не ребалансируются и могут естественно дрейфовать по мере движения цен. Вы можете последовательно посчитать <strong>GBM Monte Carlo</strong> и <strong>Статистический Bootstrap</strong>; результаты останутся в этом окне, пока вы его не закроете.</div>
        </div>
        <div class="portfolio-note">Bootstrap: средняя длина блока — <strong>21 торговый день</strong>.</div>
        <div class="forecast-model-action-row"><button class="btn forecast-btn" onclick="runPortfolioForecast('gbm', true)">GBM Monte Carlo</button><button class="btn event-run-btn" onclick="runPortfolioForecast('bootstrap', true)">Статистический Bootstrap</button></div>
      </div>
      <div id="portfolio-forecast-result"></div>

      ${warnings}
      <button class="btn excel-plan-btn" onclick="downloadPortfolioExcel()">🟩 Скачать готовый план в Excel</button>
    </div>`;
  setTimeout(loadPortfolioRiskContribution, 0);
}

async function loadPortfolioRiskContribution(){
  const out=document.getElementById('portfolio-risk-contribution');
  const sid=lastPortfolioResult?.snapshot_id; if(!out||!sid) return;
  try{
    const r=await fetch('/api/portfolio/risk-contribution?'+new URLSearchParams({snapshot_id:sid}));
    const d=await r.json(); if(!r.ok||d.error) throw new Error(d.error||'Risk decomposition error');
    const rows=(d.rows||[]).map(x=>`<tr><td><strong>${x.ticker}</strong></td><td>${Number(x.weight_pct||0).toFixed(2)}%</td><td>${Number(x.mrc||0).toFixed(4)}</td><td>${Number(x.risk_contribution||0).toFixed(4)}</td><td>${Number(x.risk_share_pct||0).toFixed(1)}%</td></tr>`).join('');
    out.innerHTML=`<div class="portfolio-model-meta"><span>Volatility: <strong>${Number(d.portfolio_volatility_pct||d.portfolio_volatility*100||0).toFixed(2)}%</strong></span><span>HHI: <strong>${Number(d.hhi||0).toFixed(3)}</strong></span><span>Effective N: <strong>${Number(d.effective_n||0).toFixed(2)}</strong></span><span>Σ RC = σ: <strong>${Math.abs(Number(d.identity_check?.sum_risk_share_pct||0)-100)<0.01?'verified':'check'}</strong></span></div><div class="matrix-wrap"><table class="matrix-table"><thead><tr><th>Asset</th><th>Weight</th><th>MRC</th><th>RC</th><th>Risk share</th></tr></thead><tbody>${rows}</tbody></table></div><div class="portfolio-note">MRC uses the covariance matrix Σ selected for this snapshot. Ledoit–Wolf is preferred for stability, but MRC does not mathematically require it.</div>`;
  }catch(e){out.innerHTML=`<div class="portfolio-warning">⚠ ${e.message}</div>`;}
}

function psfFmt(v,d=2){const n=Number(v);return Number.isFinite(n)?n.toFixed(d):'—';}
function drawPositionSizeFrontier(canvasId, points){
  const canvas=document.getElementById(canvasId); if(!canvas) return;
  const pts=(points||[]).filter(x=>Number.isFinite(Number(x.candidate_weight_pct))&&Number.isFinite(Number(x.sharpe)));
  if(!pts.length) return;
  const w=Math.max(650,canvas.parentElement.clientWidth||850),h=300,dpr=window.devicePixelRatio||1;canvas.width=w*dpr;canvas.height=h*dpr;canvas.style.width=w+'px';canvas.style.height=h+'px';
  const c=canvas.getContext('2d');c.scale(dpr,dpr);const pad={l:52,r:20,t:22,b:42};
  const xs=pts.map(p=>Number(p.candidate_weight_pct)),ys=pts.map(p=>Number(p.sharpe));let ymin=Math.min(...ys),ymax=Math.max(...ys);if(ymax-ymin<.05){ymin-=.03;ymax+=.03;}
  const X=x=>pad.l+(x-Math.min(...xs))/(Math.max(...xs)-Math.min(...xs)||1)*(w-pad.l-pad.r);const Y=y=>h-pad.b-(y-ymin)/(ymax-ymin)*(h-pad.t-pad.b);
  c.font='10px monospace';c.strokeStyle='rgba(112,131,173,.18)';c.fillStyle='#7083ad';for(let i=0;i<=5;i++){const x=Math.min(...xs)+(Math.max(...xs)-Math.min(...xs))*i/5,px=X(x);c.beginPath();c.moveTo(px,pad.t);c.lineTo(px,h-pad.b);c.stroke();c.fillText(x.toFixed(0)+'%',px-8,h-pad.b+18);}
  c.strokeStyle='#00d4ff';c.lineWidth=2.5;c.beginPath();pts.forEach((p,i)=>{const x=X(Number(p.candidate_weight_pct)),y=Y(Number(p.sharpe));i?c.lineTo(x,y):c.moveTo(x,y)});c.stroke();pts.forEach(p=>{c.fillStyle='#00e5a0';c.beginPath();c.arc(X(Number(p.candidate_weight_pct)),Y(Number(p.sharpe)),3,0,Math.PI*2);c.fill();});c.fillStyle='#8fa2cc';c.fillText('Candidate weight →',w/2-55,h-10);c.fillText('Sharpe',7,18);
}
async function runPositionSizeFrontier(){
  const out=document.getElementById('position-size-frontier-result');const sid=lastPortfolioResult?.snapshot_id;if(!out||!sid)return;
  const candidate=(document.getElementById('psf-candidate')?.value||'').trim().toUpperCase();const weight=document.getElementById('psf-weight')?.value||'5';
  if(!candidate){out.innerHTML='<div class="portfolio-warning">⚠ Enter a candidate ticker.</div>';return;}
  out.innerHTML='<div class="chart-loading">⏳ Position Size Frontier · 0–20%…</div>';
  try{
    const r=await fetch('/api/portfolio/position-size-frontier?'+new URLSearchParams({snapshot_id:sid,candidate,weight_pct:weight}));const d=await r.json();if(!r.ok||d.error)throw new Error(d.error||'Position Size Frontier error');
    const k=d.key_points||{},m=d.marginal_impact||{},b=m.before||{},a=m.after||{},cd=m.candidate||{};const metric=(label,key,suffix='%')=>`<tr><td>${label}</td><td>${b[key]==null?'—':psfFmt(b[key])}${suffix}</td><td>${a[key]==null?'—':psfFmt(a[key])}${suffix}</td></tr>`;
    out.innerHTML=`<div class="portfolio-result-card"><div class="portfolio-result-title">Position Size Frontier · ${candidate}</div><div class="forecast-chart-wrap"><canvas id="psf-chart"></canvas></div><div class="portfolio-model-meta"><span>Maximum Sharpe: <strong>${psfFmt(k.maximum_sharpe_weight_pct)}%</strong></span><span>Minimum Volatility: <strong>${psfFmt(k.minimum_volatility_weight_pct)}%</strong></span><span>CVaR starts worsening: <strong>${k.cvar_starts_worsening_weight_pct==null?'—':psfFmt(k.cvar_starts_worsening_weight_pct)+'%'}</strong></span><span>Risk contribution &gt;15%: <strong>${k.risk_share_above_15_weight_pct==null?'—':psfFmt(k.risk_share_above_15_weight_pct)+'%'}</strong></span></div><div class="msec">Marginal Portfolio Impact · ${psfFmt(d.selected_weight_pct)}%</div><div class="matrix-wrap"><table class="matrix-table"><thead><tr><th>Metric</th><th>Before</th><th>After</th></tr></thead><tbody>${metric('Expected Return','expected_return_pct')}${metric('Volatility','volatility_pct')}${metric('Sharpe','sharpe','')}${metric('CVaR 95%','cvar95_pct')}${metric('Portfolio Beta','portfolio_beta','')}${metric('HHI','hhi','')}${metric('Effective N','effective_n','')}</tbody></table></div><div class="portfolio-model-meta"><span>Capital Weight: <strong>${psfFmt(cd.capital_weight_pct)}%</strong></span><span>Risk Contribution: <strong>${psfFmt(cd.risk_contribution_pct_points,4)}</strong></span><span>Risk Share: <strong>${psfFmt(cd.risk_share_pct)}%</strong></span><span>MRC: <strong>${psfFmt(cd.mrc,4)}</strong></span><span>Correlation Portfolio: <strong>${psfFmt(cd.correlation_with_current_portfolio,3)}</strong></span></div><div class="portfolio-note">HHI = Σw² · Effective N = 1/HHI. No composite score is used.</div></div>`;
    setTimeout(()=>drawPositionSizeFrontier('psf-chart',d.frontier||d.points||[]),0);
  }catch(e){out.innerHTML=`<div class="portfolio-warning">⚠ ${e.message}</div>`;}
}

async function runPortfolioForecast(model='gbm', force=false){
  if(!lastPortfolioResult){ alert('Сначала рассчитайте портфель через Markowitz'); return; }
  activeForecastModel=model;
  const out=document.getElementById('portfolio-forecast-result'); if(!out) return;
  if(!force && portfolioForecastResults[model]){
    renderPortfolioForecastTabs();
    return;
  }
  const horizon=252;
  const simulations=10000;
  const blockSize=21;
  out.innerHTML=`<div class="chart-loading">⏳ Считаем ${simulations.toLocaleString('ru-RU')} сценариев: ${model==='gbm'?'GBM Monte Carlo':'Статистический Bootstrap'}, горизонт ${horizon} торговых дней.</div>`;
  const snapshotId=lastPortfolioResult?.snapshot_id;
  if(!snapshotId){out.innerHTML='<div class="portfolio-warning">⚠ Portfolio snapshot отсутствует. Рассчитайте Markowitz заново.</div>';return;}
  const params=new URLSearchParams({
    snapshot_id:snapshotId, horizon:String(horizon), simulations:String(simulations), block_size:String(blockSize), model
  });
  try{
    const r=await fetch('/api/portfolio/forecast?'+params.toString());
    const d=await r.json();
    if(!r.ok || d.error) throw new Error(d.error||'Ошибка прогнозирования');
    portfolioForecastResults[model]=d.forecast?.primary || d.forecast || d;
    renderPortfolioForecastTabs();
  }catch(e){ out.innerHTML=`<div class="portfolio-warning">⚠ ${e.message}</div>`; }
}

function forecastPct(v){ const n=Number(v||0); return `${n>=0?'+':''}${n.toFixed(1)}%`; }
function forecastScenarioCard(title, value, pct, subtitle, cls){
  const sign = Number(pct||0)>=0 ? '+' : '';
  return `<div class="forecast-scenario ${cls}"><span class="forecast-scenario-label">${title}</span><strong>${fmtKzt(value)}</strong><b>${sign}${Number(pct||0).toFixed(1)}%</b><small>${subtitle}</small></div>`;
}
function drawForecastChart(canvasId, chart, startAmount){
  const canvas=document.getElementById(canvasId); if(!canvas || !Array.isArray(chart) || chart.length<2) return;
  const dpr=window.devicePixelRatio||1, cssW=Math.max(640,canvas.parentElement.clientWidth||900), cssH=300;
  canvas.width=cssW*dpr; canvas.height=cssH*dpr; canvas.style.width=cssW+'px'; canvas.style.height=cssH+'px';
  const ctx=canvas.getContext('2d'); ctx.scale(dpr,dpr); const pad={l:58,r:20,t:24,b:36};
  const xs=chart.map(p=>Number(p.day)), ys=chart.flatMap(p=>[Number(p.worst_kzt),Number(p.median_kzt),Number(p.best_kzt),startAmount]);
  let xmin=Math.min(...xs), xmax=Math.max(...xs), ymin=Math.min(...ys), ymax=Math.max(...ys); const dy=Math.max(1,ymax-ymin); ymin-=dy*.08; ymax+=dy*.08;
  const X=x=>pad.l+(x-xmin)/Math.max(1,xmax-xmin)*(cssW-pad.l-pad.r), Y=y=>cssH-pad.b-(y-ymin)/(ymax-ymin)*(cssH-pad.t-pad.b);
  ctx.font='10px monospace'; ctx.fillStyle='#7083ad'; ctx.strokeStyle='rgba(112,131,173,.18)'; ctx.lineWidth=1;
  for(let i=0;i<=5;i++){ const x=xmin+(xmax-xmin)*i/5,px=X(x); ctx.beginPath();ctx.moveTo(px,pad.t);ctx.lineTo(px,cssH-pad.b);ctx.stroke();ctx.fillText(`${Math.round(x)} td`,px-12,cssH-pad.b+18); const y=ymin+(ymax-ymin)*i/5,py=Y(y);ctx.beginPath();ctx.moveTo(pad.l,py);ctx.lineTo(cssW-pad.r,py);ctx.stroke();ctx.fillText(Math.round(y).toLocaleString('ru-RU')+' ₸',4,py+3); }
  const line=(key,stroke,dash=[])=>{ctx.save();ctx.strokeStyle=stroke;ctx.lineWidth=key==='median_kzt'?2.8:1.7;ctx.setLineDash(dash);ctx.beginPath();chart.forEach((p,i)=>{const x=X(Number(p.day)),y=Y(Number(p[key]));i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();ctx.restore();};
  line('worst_kzt','#f87171',[6,5]); line('median_kzt','#00e5a0'); line('best_kzt','#00d4ff',[2,4]);
  ctx.fillStyle='#8fa2cc';ctx.fillText('Торг. дни',cssW-42,cssH-10);ctx.fillText('Капитал',8,16);ctx.fillStyle='#f87171';ctx.fillText('Worst / P05',pad.l+10,18);ctx.fillStyle='#00e5a0';ctx.fillText('Median / P50',pad.l+120,18);ctx.fillStyle='#00d4ff';ctx.fillText('Best / P95',pad.l+245,18);
}

function renderPortfolioForecastTabs(){
  const out=document.getElementById('portfolio-forecast-result'); if(!out) return;
  const gbm=portfolioForecastResults.gbm, boot=portfolioForecastResults.bootstrap;
  const active=portfolioForecastResults[activeForecastModel];
  const gs=active?.scenarios||{}; const amount=Number(active?.amount_kzt||lastPortfolioAmount||0); const chartId='forecast-chart-'+activeForecastModel+'-'+Date.now();
  const gbmTabLabel = gbm ? '✓ GBM Monte Carlo' : 'GBM Monte Carlo';
  const bootTabLabel = boot ? '✓ Статистический Bootstrap' : 'Статистический Bootstrap';
  const tabs=`<div class="forecast-model-tabs"><button class="forecast-model-tab ${activeForecastModel==='gbm'?'active':''} ${gbm?'calculated':''}" onclick="runPortfolioForecast('gbm')">${gbmTabLabel}</button><button class="forecast-model-tab ${activeForecastModel==='bootstrap'?'active':''} ${boot?'calculated':''}" onclick="runPortfolioForecast('bootstrap')">${bootTabLabel}</button></div><div class="forecast-tab-note">✓ означает, что результат уже рассчитан и сохранён в этом окне. Переключение вкладки не запускает расчёт повторно.</div>`;
  const comparable=gbm&&boot&&gbm.snapshot_id===boot.snapshot_id&&Number(gbm.horizon_days)===Number(boot.horizon_days)&&gbm.rebalancing===boot.rebalancing;
  const comparison=(gbm&&boot)?(comparable?`<div class="model-disagreement"><strong>Сравнение на одинаковых условиях</strong><p>Обе модели используют один snapshot, один горизонт и одну buy-and-hold политику. Отличается только способ генерации будущих доходностей.</p><div class="model-delta-row"><span>VaR GBM: <b>${fmtKzt(gbm.scenarios.var95_kzt)}</b></span><span>VaR Bootstrap: <b>${fmtKzt(boot.scenarios.var95_kzt)}</b></span><span>CVaR GBM: <b>${fmtKzt(gbm.scenarios.cvar95_kzt)}</b></span><span>CVaR Bootstrap: <b>${fmtKzt(boot.scenarios.cvar95_kzt)}</b></span></div></div>`:`<div class="portfolio-warning">⚠ GBM и Bootstrap рассчитаны с разными настройками. Прямое сравнение VaR/CVaR скрыто. Пересчитайте обе модели с одинаковым горизонтом.</div>`):'';
  const assetRows=(active?.asset_scenarios||[]).map((a,i)=>`<tr><td><strong>${i+1}. ${a.ticker}</strong></td><td>${Number(a.weight_pct).toFixed(1)}%</td><td>${fmtKzt(a.initial_amount_kzt)}</td><td class="forecast-positive">${fmtKzt(a.best_case_kzt)}</td><td>${fmtKzt(a.median_case_kzt)}</td><td class="forecast-negative">${fmtKzt(a.worst_case_kzt)}</td><td class="forecast-negative">${fmtKzt(a.var95_kzt)}</td><td class="forecast-negative">${fmtKzt(a.cvar95_kzt||0)}</td></tr>`).join('');
  out.innerHTML=`<div class="forecast-result-card"><div class="forecast-header"><div><div class="forecast-title">🔮 Сценарный анализ: ${activeForecastModel==='gbm'?'GBM Monte Carlo':'Статистический Bootstrap'}</div><div class="forecast-meta"><span>${Number(active?.simulations||0).toLocaleString('ru-RU')} сценариев</span><span>${Number(active?.horizon_days||0)} торговых дней</span>${activeForecastModel==='bootstrap'?`<span>Block ≈ ${Number(active?.block_size_days||0)}d</span>`:''}<span>VaR 95%</span><span>CVaR 95%</span></div></div><div class="forecast-method">Один Portfolio Snapshot → те же веса → buy-and-hold → выбранная модель риска</div></div>${tabs}<div class="forecast-scenarios">${forecastScenarioCard('Оптимистичный · Best Case',gs.best_case_kzt,gs.best_case_pct,'P95 · 95-й перцентиль','best')}${forecastScenarioCard('Реалистичный · Median Case',gs.median_case_kzt,gs.median_case_pct,'P50 · медиана','median')}${forecastScenarioCard('Худший · Worst Case',gs.worst_case_kzt,gs.worst_case_pct,'P05 · нижняя 5%-граница','worst')}</div><div class="forecast-risk-pair"><div class="forecast-var-box"><div><span class="forecast-var-label">VaR 95%</span><strong>${fmtKzt(gs.var95_kzt||0)}</strong><small>${Number(gs.var95_pct||0).toFixed(1)}% от старта</small></div><p>Порог потенциальной потери: расстояние от стартового капитала до P05.</p></div><div class="forecast-var-box cvar-box"><div><span class="forecast-var-label">CVaR 95%</span><strong>${fmtKzt(gs.cvar95_kzt||0)}</strong><small>${Number(gs.cvar95_pct||0).toFixed(1)}% от старта</small></div><p>Средняя потеря внутри самых плохих 5% сценариев.</p></div></div>${gs.worst_case_is_gain?`<div class="forecast-soft-warning">P05 выше стартового капитала. Поэтому loss-oriented VaR/CVaR равны 0 ₸: нижний хвост модели всё ещё находится выше старта.</div>`:''}${comparison}<div class="forecast-explain"><div><strong>Почему модели не противоречат друг другу?</strong></div><div>Markowitz отвечает только за <strong>веса</strong>.</div><div>${activeForecastModel==='gbm'?'GBM Monte Carlo строит синтетические траектории из исторических μ, volatility и covariance; исходные веса задаются один раз и затем дрейфуют как buy-and-hold.':'Bootstrap переиспользует реальные совместные исторические доходности через stationary bootstrap и применяет ту же buy-and-hold политику; средняя длина блока зафиксирована на 21 торговом дне.'}</div><div>Если две оценки VaR/CVaR сильно расходятся, это сигнал чувствительности риска к предпосылкам модели.</div></div><div class="forecast-chart-title">${activeForecastModel==='gbm'?'GBM Monte Carlo':'Historical Block Bootstrap'} · распределение траекторий</div><div class="forecast-chart-wrap"><canvas id="${chartId}"></canvas></div><div class="msec">Результат по каждому активу · ${activeForecastModel==='gbm'?'GBM':'Bootstrap'}</div><div class="forecast-table-wrap"><table class="forecast-table"><thead><tr><th>Актив</th><th>Вес</th><th>Старт</th><th>Best P95</th><th>Median P50</th><th>Worst P05</th><th>VaR 95%</th><th>CVaR 95%</th></tr></thead><tbody>${assetRows}</tbody></table></div></div>`;
  setTimeout(()=>drawForecastChart(chartId,active?.chart||[],amount),0);
}

async function downloadPortfolioExcel(){
  if(!lastPortfolioResult){alert('Сначала рассчитайте портфель');return;}
  const snapshotId=lastPortfolioResult?.snapshot_id;
  if(!snapshotId){alert('Portfolio snapshot отсутствует. Рассчитайте портфель заново.');return;}
  const params=new URLSearchParams({snapshot_id:snapshotId});
  try{
    const r=await fetch('/api/portfolio/export?'+params.toString()); if(!r.ok) throw new Error(await r.text());
    const blob=await r.blob(), a=document.createElement('a');
    a.href=URL.createObjectURL(blob); a.download=`portfolio_plan_${new Date().toISOString().slice(0,10)}.xlsx`; document.body.appendChild(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(a.href),1000);
  }catch(e){alert('Ошибка Excel: '+e.message);}
}

// Stock Excel export now uses the same selection checkbox, but only stock rows.
async function exportExcel(mode) {
  const menu=document.getElementById('xls-menu'); if(menu) menu.classList.remove('open');
  const stockRows=allData.filter(b=>(b.asset_type||'stock')==='stock');
  const selectedStocks=stockRows.filter(b=>cmpSet.has(b.ticker));
  const selected=selectedStocks.length?selectedStocks.map(b=>b.ticker):stockRows.map(b=>b.ticker);
  if(!selected.length){alert('Нет загруженных акций для экспорта');return;}
  const isDcf=mode==='dcf', endpoint=isDcf?'/api/export/dcf':'/api/export';
  try{
    const r=await fetch(`${endpoint}?${new URLSearchParams({tickers:selected.join(',')})}`); if(!r.ok) throw new Error(await r.text());
    const blob=await r.blob(), a=document.createElement('a'), date=new Date().toISOString().slice(0,10);
    a.href=URL.createObjectURL(blob); a.download=isDcf?`dcf_valuation_${date}.xlsx`:`screener_${date}.xlsx`; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(a.href);
  }catch(e){alert('Ошибка экспорта: '+e.message);}
}
