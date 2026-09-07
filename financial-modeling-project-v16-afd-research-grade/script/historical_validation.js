'use strict';

/* Historical Model Validation — v15
 *
 * Reuses cmpSet from the original screener. No second asset picker exists.
 * Flow:
 *   selected screener assets -> choose test year -> train-only Markowitz
 *   -> frozen weights -> GBM/Bootstrap forecast -> Actual Market Results.
 * The actual test-year endpoint is not called until the user explicitly opens it.
 */

const HVAL_FIRST_YEAR = 2017;
const HVAL_LAST_COMPLETED_YEAR = Math.max(HVAL_FIRST_YEAR, new Date().getFullYear() - 1);
const HVAL_YEARS = Array.from({length:HVAL_LAST_COMPLETED_YEAR-HVAL_FIRST_YEAR+1},(_,i)=>HVAL_FIRST_YEAR+i);
const HVAL_WINDOWS = Object.fromEntries(
  HVAL_YEARS.map(y=>[String(y), [`${y-3}-01-01`, `${y-1}-12-31`]])
);

let hvalState = null;
let hvalLastAmount = 100000;

function hvalEscape(value){
  return String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
}
function hvalPct(value, digits=2, sign=true){
  const n=Number(value);
  if(!Number.isFinite(n)) return '—';
  return `${sign && n>0?'+':''}${n.toFixed(digits)}%`;
}
function hvalUsd(value){
  const n=Number(value);
  if(!Number.isFinite(n)) return '—';
  const abs=Math.abs(n).toLocaleString('en-US',{minimumFractionDigits:0,maximumFractionDigits:2});
  return `${n<0?'−':''}$${abs}`;
}
function hvalParseMoney(value){
  const normalized=String(value??'').replace(/[\s,_]/g,'').replace(/[^0-9.]/g,'');
  const n=Number(normalized);
  return Number.isFinite(n)?n:NaN;
}
function hvalFormatMoneyInput(el){
  if(!el) return;
  const n=hvalParseMoney(el.value);
  if(!Number.isFinite(n)) return;
  el.value=Math.round(n).toLocaleString('ru-RU').replace(/\u00a0/g,' ');
}
function hvalSelectedAssets(){ return [...cmpSet]; }
function hvalFingerprint(){
  const assets=hvalSelectedAssets().join('|');
  const year=document.getElementById('hval-test-year')?.value||'';
  const amount=hvalParseMoney(document.getElementById('hval-amount')?.value||'');
  const objective=document.getElementById('hval-objective')?.value||'';
  const concentration=document.getElementById('hval-concentration')?.value||'';
  const covariance=document.getElementById('hval-covariance')?.value||'';
  return [assets,year,amount,objective,concentration,covariance].join('::');
}

function openHistoricalModelValidation(){
  const selected=hvalSelectedAssets();
  if(selected.length<2){
    alert('Для Historical Model Validation выберите минимум 2 актива галочками в основном screener.');
    return;
  }
  const root=document.getElementById('hval-mi');
  const modal=document.getElementById('hvalov');
  if(!root||!modal) return;
  const chips=selected.map(t=>`<span class="hval-chip">${hvalEscape(t)}</span>`).join('');
  root.innerHTML=`
    <div class="mt">🧪 Historical Model Validation</div>
    <div class="hval-intro">
      <strong>Тот же portfolio workflow, но в прошлом.</strong>
      Выбранные в screener активы сначала оптимизируются только на 3-летнем training-периоде. Затем те же frozen weights идут в GBM и Stationary Bootstrap. Реальный test-year не загружается до кнопки <b>Actual Market Results</b>.
    </div>
    <div class="hval-selected-row"><span>Выбранные активы (${selected.length})</span><div>${chips}</div></div>
    <div class="portfolio-form-grid hval-form-grid">
      <label class="portfolio-field"><span>Test year</span>
        <select id="hval-test-year" onchange="hvalSettingsChanged()">
          ${HVAL_YEARS.map(y=>`<option value="${y}">${y}</option>`).join('')}
        </select>
        <small id="hval-training-label">Training: 2014–2016</small>
      </label>
      <label class="portfolio-field"><span>Стартовый капитал, USD</span>
        <div class="money-input hval-money"><input id="hval-amount" type="text" inputmode="numeric" value="${Math.round(hvalLastAmount).toLocaleString('ru-RU').replace(/\u00a0/g,' ')}" oninput="hvalSettingsChanged()" onblur="hvalFormatMoneyInput(this)"><b>$</b></div>
      </label>
      <label class="portfolio-field"><span>Цель Markowitz</span>
        <select id="hval-objective" onchange="hvalSettingsChanged()">
          <option value="max_sharpe">Maximum Sharpe</option>
          <option value="min_variance">Minimum Variance</option>
          <option value="equal_weight">1/N Equal Weight</option>
        </select>
      </label>
      <label class="portfolio-field"><span>Covariance</span>
        <select id="hval-covariance" onchange="hvalSettingsChanged()"><option value="ledoit_wolf">Ledoit–Wolf</option><option value="sample">Sample Covariance</option></select>
      </label>
      <label class="portfolio-field"><span>Режим концентрации</span>
        <select id="hval-concentration" onchange="hvalSettingsChanged()">
          <option value="constrained">Практический лимит</option>
          <option value="unconstrained">Без лимита (academic)</option>
        </select>
        <small>2 → 60% · 3 → 45% · 4 → 35% · 5+ → 25%</small>
      </label>
    </div>
    <div class="hval-integrity-note"><strong>No Look-Ahead:</strong> training → Markowitz → frozen weights → GBM/Bootstrap. Test-year prices открываются отдельным запросом только после фиксации forecast.</div>
    <div class="forecast-model-action-row"><button class="btn portfolio-btn portfolio-calc" id="hval-forecast-btn" onclick="calculateHistoricalForecast()">Рассчитать выбранный год</button><button class="btn hval-btn" id="hval-all-btn" onclick="compareAllHistoricalYears()">Сравнить все годы ${HVAL_FIRST_YEAR}–${HVAL_LAST_COMPLETED_YEAR}</button></div>
    <div id="hval-forecast-result"></div>
    <div id="hval-actual-action" class="hval-actual-action" style="display:none"></div>
    <div id="hval-actual-result"></div>`;
  hvalState=null;
  hvalUpdateTrainingLabel();
  modal.classList.add('open');
}

function closeHistoricalModelValidation(){
  document.getElementById('hvalov')?.classList.remove('open');
}

function hvalUpdateTrainingLabel(){
  const year=document.getElementById('hval-test-year')?.value||'2017';
  const row=HVAL_WINDOWS[year]||HVAL_WINDOWS['2017'];
  const label=document.getElementById('hval-training-label');
  if(label) label.textContent=`Training: ${row[0].slice(0,4)}–${row[1].slice(0,4)} → real test ${year}`;
}

function hvalSettingsChanged(){
  hvalUpdateTrainingLabel();
  hvalState=null;
  const forecast=document.getElementById('hval-forecast-result');
  const actual=document.getElementById('hval-actual-result');
  const action=document.getElementById('hval-actual-action');
  if(forecast) forecast.innerHTML='';
  if(actual) actual.innerHTML='';
  if(action){action.style.display='none';action.innerHTML='';}
}

async function hvalFetchJson(url, timeoutMs){
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),timeoutMs);
  try{
    const r=await fetch(url,{signal:controller.signal});
    const d=await r.json();
    if(!r.ok||d.error) throw new Error(d.error||`HTTP ${r.status}`);
    return d;
  }catch(e){
    if(e?.name==='AbortError') throw new Error(`Market-data request превысил ${Math.round(timeoutMs/1000)} секунд. Проверьте интернет/источник и повторите.`);
    throw e;
  }finally{clearTimeout(timer);}
}

async function calculateHistoricalForecast(){
  const selected=hvalSelectedAssets();
  const out=document.getElementById('hval-forecast-result');
  const action=document.getElementById('hval-actual-action');
  const actualOut=document.getElementById('hval-actual-result');
  const btn=document.getElementById('hval-forecast-btn');
  if(!out) return;
  if(selected.length<2){out.innerHTML='<div class="portfolio-warning">⚠ Выберите минимум 2 актива в screener.</div>';return;}
  const amount=hvalParseMoney(document.getElementById('hval-amount')?.value||0);
  if(!Number.isFinite(amount)||amount<=0){out.innerHTML='<div class="portfolio-warning">⚠ Введите положительный стартовый капитал.</div>';return;}
  const testYear=document.getElementById('hval-test-year')?.value||'2022';
  const objective=document.getElementById('hval-objective')?.value||'max_sharpe';
  const concentration=document.getElementById('hval-concentration')?.value||'constrained';
  const covariance=document.getElementById('hval-covariance')?.value||'ledoit_wolf';
  hvalLastAmount=amount;
  hvalState=null;
  if(action){action.style.display='none';action.innerHTML='';}
  if(actualOut) actualOut.innerHTML='';
  if(btn) btn.disabled=true;
  out.innerHTML='<div class="chart-loading">⏳ Training data only → Markowitz → GBM / Bootstrap…</div>';
  try{
    const p=new URLSearchParams({
      assets:selected.join(','), amount:String(amount), test_year:testYear,
      objective, concentration_mode:concentration, covariance_method:covariance,
    });
    const d=await hvalFetchJson('/api/historical-validation/forecast?'+p.toString(),60000);
    const fingerprint=hvalFingerprint();
    hvalState={validationId:d.validation_id,fingerprint,testYear,selected:[...selected],forecast:d};
    out.innerHTML=renderHistoricalForecast(d);
    if(action){
      action.style.display='flex';
      action.innerHTML=`<div><strong>Forecast зафиксирован.</strong><span> Test-year ${hvalEscape(testYear)} ещё не был открыт в расчёте.</span></div><button class="btn hval-actual-btn" id="hval-actual-btn" onclick="revealActualMarketResults()">Actual Market Results — ${hvalEscape(testYear)} →</button>`;
    }
  }catch(e){
    out.innerHTML=`<div class="portfolio-warning">⚠ ${hvalEscape(e.message)}</div>`;
  }finally{if(btn)btn.disabled=false;}
}

async function compareAllHistoricalYears(){
  const selected=hvalSelectedAssets(),out=document.getElementById('hval-forecast-result'),btn=document.getElementById('hval-all-btn');
  if(!out||selected.length<2)return;
  const amount=hvalParseMoney(document.getElementById('hval-amount')?.value||0);
  const objective=document.getElementById('hval-objective')?.value||'max_sharpe';
  const concentration=document.getElementById('hval-concentration')?.value||'constrained';
  const covariance=document.getElementById('hval-covariance')?.value||'ledoit_wolf';
  if(btn)btn.disabled=true;out.innerHTML='<div class="chart-loading">⏳ Shared history cache → rolling 3Y train / next-year test…</div>';
  try{
    const p=new URLSearchParams({assets:selected.join(','),amount:String(amount),objective,concentration_mode:concentration,covariance_method:covariance});
    const d=await hvalFetchJson('/api/historical-validation?'+p.toString(),180000);
    const rows=(d.windows||[]).map(w=>{
      const y=w.test_period?.year||'—';
      if(w.status!=='ok')return `<tr><td>${y}</td><td colspan="7" class="negative">${hvalEscape(w.error||'Unavailable')}</td></tr>`;
      const ex=(w.universe?.excluded||[]).map(x=>x.ticker).join(', ')||'—';
      return `<tr><td><strong>${y}</strong></td><td>${(w.universe?.eligible||[]).join(', ')}</td><td>${ex}</td><td>${hvalPct(w.actual?.actual_return_pct)}</td><td>${hvalPct(w.gbm?.p50_return_pct)}</td><td>${hvalPct(w.bootstrap?.p50_return_pct)}</td><td>${w.gbm?.actual_inside_90_interval?'✓':'✕'}</td><td>${w.bootstrap?.actual_inside_90_interval?'✓':'✕'}</td></tr>`;
    }).join('');
    out.innerHTML=`<div class="portfolio-result-card"><div class="portfolio-result-title">Rolling Historical Validation · ${HVAL_FIRST_YEAR}–${HVAL_LAST_COMPLETED_YEAR}</div><div class="portfolio-model-meta"><span>Successful: <strong>${d.summary?.successful_windows||0}/${d.summary?.total_windows||0}</strong></span><span>GBM coverage: <strong>${d.summary?.gbm_coverage_pct??'—'}%</strong></span><span>Bootstrap coverage: <strong>${d.summary?.bootstrap_coverage_pct??'—'}%</strong></span><span>Covariance: <strong>${hvalEscape(d.methodology?.covariance_method||covariance)}</strong></span></div><div class="hval-comparison-table-wrap"><table class="validation-table"><thead><tr><th>Year</th><th>Eligible</th><th>Excluded</th><th>Actual</th><th>GBM P50</th><th>Bootstrap P50</th><th>GBM 90%</th><th>Bootstrap 90%</th></tr></thead><tbody>${rows}</tbody></table></div><div class="hval-integrity-note">Assets automatically re-enter from the first year with sufficient history. Missing history never aborts the other eligible assets.</div></div>`;
  }catch(e){out.innerHTML=`<div class="portfolio-warning">⚠ ${hvalEscape(e.message)}</div>`;}finally{if(btn)btn.disabled=false;}
}

function hvalPl(value){
  const n=Number(value);
  if(!Number.isFinite(n)) return '—';
  return `${n>=0?'+':''}${hvalUsd(n)}`;
}

function hvalForecastMoneyTable(x){
  const row=(label,ret,value,pl,lossMetric=false)=>`<tr><td>${label}</td><td>${lossMetric?Number(ret||0).toFixed(2)+'% loss':hvalPct(ret)}</td><td>${hvalUsd(value)}</td><td class="${Number(pl)>=0?'positive':'negative'}">${hvalPl(pl)}</td></tr>`;
  return `<div class="hval-comparison-table-wrap"><table class="validation-table hval-money-table"><thead><tr><th>Metric</th><th>Return / Loss</th><th>Portfolio Value</th><th>P/L</th></tr></thead><tbody>
    ${row('P05',x.p05_return_pct,x.p05_portfolio_value_usd,x.p05_profit_loss_usd)}
    ${row('P50',x.p50_return_pct,x.p50_portfolio_value_usd,x.p50_profit_loss_usd)}
    ${row('P95',x.p95_return_pct,x.p95_portfolio_value_usd,x.p95_profit_loss_usd)}
    ${row('VaR 95%',x.var95_pct,x.var95_portfolio_value_usd,x.var95_profit_loss_usd,true)}
    ${row('CVaR 95%',x.cvar95_pct,x.cvar95_portfolio_value_usd,x.cvar95_profit_loss_usd,true)}
  </tbody></table></div>`;
}

function hvalAssetForecastTable(title, rows){
  const body=(rows||[]).map(x=>`<tr><td><strong>${hvalEscape(x.ticker)}</strong></td><td>${Number(x.weight_pct||0).toFixed(2)}%</td><td>${hvalUsd(x.start_amount_usd)}</td><td>${hvalUsd(x.p05_value_usd)}<small>${hvalPl(x.p05_profit_loss_usd)}</small></td><td>${hvalUsd(x.p50_value_usd)}<small>${hvalPl(x.p50_profit_loss_usd)}</small></td><td>${hvalUsd(x.p95_value_usd)}<small>${hvalPl(x.p95_profit_loss_usd)}</small></td></tr>`).join('');
  return `<div class="hval-asset-block"><div class="msec">${title} — asset-level forecast</div><div class="hval-comparison-table-wrap"><table class="validation-table hval-asset-table"><thead><tr><th>Asset</th><th>Weight</th><th>Start Capital</th><th>P05</th><th>P50</th><th>P95</th></tr></thead><tbody>${body}</tbody></table></div></div>`;
}

function renderHistoricalForecast(d){
  const p=d.portfolio||{}, g=d.gbm||{}, b=d.bootstrap||{};
  const excluded=(d.universe?.excluded||[]); const excludedHtml=excluded.length?`<div class="portfolio-warning">Unavailable this year: ${excluded.map(x=>`<strong>${hvalEscape(x.ticker)}</strong> — ${hvalEscape(x.reason)}`).join(' · ')}</div>`:'';
  const allocation=(p.allocation||[]).map((a,i)=>`
    <div class="portfolio-check-item ${Number(a.weight_pct||0)===0?'zero-weight':''}">
      <div class="portfolio-check-num">${i+1}</div>
      <div class="portfolio-check-main"><strong>${hvalEscape(a.ticker)}</strong><span>Frozen historical weight</span></div>
      <div class="portfolio-check-weight">Вес: <strong>${Number(a.weight_pct||0).toFixed(1)}%</strong></div>
      <div class="portfolio-check-amount">Старт: <strong>${hvalUsd(a.amount_usd)}</strong></div>
    </div>`).join('');
  const modelCard=(title,x,kind)=>`<div class="hval-model-card ${kind}"><div class="hval-model-title">${title}</div>${hvalForecastMoneyTable(x)}<div class="hval-model-foot">10,000 paths · 252 trading days · buy-and-hold</div></div>`;
  const train=d.training_period||{}, test=d.test_period||{};
  return `<div class="portfolio-result-card hval-result-card">
    <div class="portfolio-result-title">✅ Historical forecast готов — test year ещё скрыт</div>
    <div class="portfolio-model-meta"><span>Training: <strong>${hvalEscape(train.start?.slice(0,4))}–${hvalEscape(train.end?.slice(0,4))}</strong></span><span>Test: <strong>${hvalEscape(test.year)}</strong></span><span>U.S. RF: <strong>${Number(d.risk_free?.rate_pct||0).toFixed(2)}%</strong></span><span>Starting Capital: <strong>${hvalUsd(d.amount_usd)}</strong></span><span>Covariance: <strong>${hvalEscape(p.covariance_method||'ledoit_wolf')}</strong></span></div>${excludedHtml}
    <div class="hval-stage-line"><span class="done">TRAIN</span><b>→</b><span class="done">MARKOWITZ</span><b>→</b><span class="done">FROZEN WEIGHTS</span><b>→</b><span class="done">GBM / BOOTSTRAP</span><b>→</b><span>ACTUAL ${hvalEscape(test.year)} LOCKED</span></div>
    <div class="msec">Historical Markowitz allocation</div>${allocation}
    <div class="msec">Portfolio forecast — проценты + реальные суммы капитала</div><div class="hval-models">${modelCard('GBM Monte Carlo',g,'gbm')}${modelCard('Stationary Bootstrap',b,'bootstrap')}</div>
    ${hvalAssetForecastTable('GBM Monte Carlo',g.asset_breakdown)}
    ${hvalAssetForecastTable('Stationary Bootstrap',b.asset_breakdown)}
    <div class="hval-integrity-note"><strong>Integrity:</strong> no look-ahead verified · 10,000 paths · 252 trading days · buy-and-hold · Bootstrap mean block 21. VaR/CVaR показаны как loss metrics: Portfolio Value = Start − modeled loss. <b>test_market_data_loaded = ${d.integrity?.test_market_data_loaded===false?'false ✓':hvalEscape(d.integrity?.test_market_data_loaded)}</b></div>
  </div>`;
}

async function revealActualMarketResults(){
  const out=document.getElementById('hval-actual-result');
  const btn=document.getElementById('hval-actual-btn');
  if(!out) return;
  if(!hvalState){out.innerHTML='<div class="portfolio-warning">⚠ Сначала рассчитайте historical forecast.</div>';return;}
  if(hvalState.fingerprint!==hvalFingerprint()){
    out.innerHTML='<div class="portfolio-warning">⚠ Параметры изменились. Сначала пересчитайте forecast, чтобы Actual Results использовали именно эти frozen weights.</div>';
    return;
  }
  if(btn) btn.disabled=true;
  out.innerHTML=`<div class="chart-loading">⏳ Открываем реальные market data ${hvalEscape(hvalState.testYear)} и применяем уже замороженные веса…</div>`;
  try{
    const p=new URLSearchParams({validation_id:hvalState.validationId});
    const d=await hvalFetchJson('/api/historical-validation/actual?'+p.toString(),45000);
    out.innerHTML=renderActualMarketResults(d);
  }catch(e){
    out.innerHTML=`<div class="portfolio-warning">⚠ ${hvalEscape(e.message)}</div>`;
  }finally{if(btn)btn.disabled=false;}
}

function renderActualMarketResults(d){
  const a=d.actual||{}, g=d.gbm||{}, b=d.bootstrap||{}, y=d.test_period?.year||'';
  const coverage=(x)=>x?'<span class="hval-pass">✓ inside P05–P95</span>':'<span class="hval-fail">✕ outside P05–P95</span>';
  const assetRows=(a.asset_results||[]).map(x=>`<tr><td><strong>${hvalEscape(x.ticker)}</strong></td><td>${Number(x.weight_pct||0).toFixed(2)}%</td><td>${hvalUsd(x.start_amount_usd)}</td><td>${hvalUsd(x.ending_amount_usd)}</td><td class="${Number(x.profit_loss_usd)>=0?'positive':'negative'}">${hvalPl(x.profit_loss_usd)}</td><td>${hvalPct(x.actual_return_pct)}</td></tr>`).join('');
  const forecastCell=(ret,val,pl)=>`${hvalPct(ret)}<br><strong>${hvalUsd(val)}</strong><br><small>P/L ${hvalPl(pl)}</small>`;
  return `<div class="portfolio-result-card hval-actual-card">
    <div class="portfolio-result-title">📌 Actual Market Results — ${hvalEscape(y)}</div>
    <div class="hval-actual-kpis">
      <div><span>Starting Capital</span><strong>${hvalUsd(d.amount_usd)}</strong></div>
      <div><span>Ending Wealth</span><strong>${hvalUsd(a.ending_wealth_usd)}</strong></div>
      <div><span>Actual P/L</span><strong class="${Number(a.profit_loss_usd)>=0?'positive':'negative'}">${hvalPl(a.profit_loss_usd)}</strong></div>
      <div><span>Actual Return</span><strong class="${Number(a.actual_return_pct)>=0?'positive':'negative'}">${hvalPct(a.actual_return_pct)}</strong></div>
      <div><span>Max Drawdown</span><strong>${hvalPct(a.max_drawdown_pct)}</strong></div>
      <div><span>Real sessions</span><strong>${Number(a.observations||0)}</strong></div>
    </div>
    <div class="msec">Actual asset-by-asset result — same frozen weights</div>
    <div class="hval-comparison-table-wrap"><table class="validation-table hval-asset-table"><thead><tr><th>Asset</th><th>Weight</th><th>Start</th><th>Actual End</th><th>Actual P/L</th><th>Return</th></tr></thead><tbody>${assetRows}<tr class="hval-total-row"><td><strong>TOTAL</strong></td><td>100%</td><td><strong>${hvalUsd(d.amount_usd)}</strong></td><td><strong>${hvalUsd(a.ending_wealth_usd)}</strong></td><td class="${Number(a.profit_loss_usd)>=0?'positive':'negative'}"><strong>${hvalPl(a.profit_loss_usd)}</strong></td><td><strong>${hvalPct(a.actual_return_pct)}</strong></td></tr></tbody></table></div>
    <div class="msec">Forecast vs Reality</div>
    <div class="hval-comparison-table-wrap"><table class="validation-table hval-comparison-table"><thead><tr><th>Metric</th><th>GBM</th><th>Bootstrap</th><th>Actual ${hvalEscape(y)}</th></tr></thead><tbody>
      <tr><td>P05</td><td>${forecastCell(g.p05_return_pct,g.p05_portfolio_value_usd,g.p05_profit_loss_usd)}</td><td>${forecastCell(b.p05_return_pct,b.p05_portfolio_value_usd,b.p05_profit_loss_usd)}</td><td rowspan="3" class="validation-actual"><strong>${hvalUsd(a.ending_wealth_usd)}</strong><br>${hvalPct(a.actual_return_pct)}<br><small>P/L ${hvalPl(a.profit_loss_usd)}</small></td></tr>
      <tr><td>P50</td><td>${forecastCell(g.p50_return_pct,g.p50_portfolio_value_usd,g.p50_profit_loss_usd)}</td><td>${forecastCell(b.p50_return_pct,b.p50_portfolio_value_usd,b.p50_profit_loss_usd)}</td></tr>
      <tr><td>P95</td><td>${forecastCell(g.p95_return_pct,g.p95_portfolio_value_usd,g.p95_profit_loss_usd)}</td><td>${forecastCell(b.p95_return_pct,b.p95_portfolio_value_usd,b.p95_profit_loss_usd)}</td></tr>
      <tr><td>VaR 95%</td><td>${Number(g.var95_pct||0).toFixed(2)}% loss<br>${hvalUsd(g.var95_portfolio_value_usd)}<br><small>P/L ${hvalPl(g.var95_profit_loss_usd)}</small></td><td>${Number(b.var95_pct||0).toFixed(2)}% loss<br>${hvalUsd(b.var95_portfolio_value_usd)}<br><small>P/L ${hvalPl(b.var95_profit_loss_usd)}</small></td><td>—</td></tr>
      <tr><td>CVaR 95%</td><td>${Number(g.cvar95_pct||0).toFixed(2)}% loss<br>${hvalUsd(g.cvar95_portfolio_value_usd)}<br><small>P/L ${hvalPl(g.cvar95_profit_loss_usd)}</small></td><td>${Number(b.cvar95_pct||0).toFixed(2)}% loss<br>${hvalUsd(b.cvar95_portfolio_value_usd)}<br><small>P/L ${hvalPl(b.cvar95_profit_loss_usd)}</small></td><td>Max DD ${hvalPct(a.max_drawdown_pct)}</td></tr>
      <tr><td>Actual percentile</td><td>${Number(g.actual_percentile||0).toFixed(1)}th</td><td>${Number(b.actual_percentile||0).toFixed(1)}th</td><td>${Number(a.observations||0)} sessions</td></tr>
      <tr><td>P05–P95 coverage</td><td>${coverage(g.actual_inside_90_interval)}</td><td>${coverage(b.actual_inside_90_interval)}</td><td>realized</td></tr>
    </tbody></table></div>
    <div class="hval-integrity-note"><strong>Verification:</strong> forecast был заморожен до загрузки test-year · те же weights · buy-and-hold · asset-level суммы сверяются с TOTAL Ending Wealth · actual data получены только после нажатия Actual Market Results. <strong>Efficient Frontier здесь намеренно отсутствует.</strong></div>
  </div>`;
}

