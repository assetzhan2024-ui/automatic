'use strict';

const EVENT_STUDY_CLIENT_CACHE = new Map();

const FORMULA_TOPICS = [
  {
    id:'markowitz', title:'1 · Markowitz Portfolio', short:'Weights',
    purpose:'Определяет, как разделить стартовый капитал между выбранными активами. Модель работает как этап распределения капитала; она не говорит, сколько вы точно заработаете в будущем.',
    formulas:[
      ['Ожидаемая доходность актива', 'μᵢ = mean(Rᵢ,t) × 252', 'Средняя дневная доходность актива переводится в годовую.'],
      ['Дисперсия портфеля', 'σₚ² = wᵀΣw', 'w — веса активов; Σ — годовая covariance matrix.'],
      ['Риск портфеля', 'σₚ = √(wᵀΣw)', 'Чем выше σₚ, тем сильнее исторические колебания портфеля.'],
      ['Доходность портфеля', 'μₚ = wᵀμ', 'Взвешенная сумма ожидаемых исторических доходностей активов.'],
      ['Sharpe Ratio', 'Sharpe = (μₚ − r_f) / σₚ', 'r_f автоматически обновляется по U.S. 13-week Treasury bill, потому что базовая валюта портфеля — USD.'],
      ['Ограничения', 'Σwᵢ = 1; 0 ≤ wᵢ ≤ cap', 'Long-only, fully invested. Academic mode допускает 0–100%; practical mode использует согласованный concentration cap по числу активов.']
    ]
  },
  {
    id:'cov', title:'2 · Covariance & Correlation', short:'Diversification',
    purpose:'Показывает, насколько активы движутся вместе. Это основа диверсификации и риска портфеля.',
    formulas:[
      ['Корреляция', 'ρᵢⱼ = Cov(Rᵢ,Rⱼ) / (σᵢσⱼ)', 'Диапазон от −1 до +1.'],
      ['Ковариация', 'Cov(X,Y) = E[(X−μₓ)(Y−μᵧ)]', 'Положительная — обычно движутся в одну сторону; отрицательная — в разные.'],
      ['Годовая covariance', 'Σₐₙₙ = Cov(daily returns) × 252', 'Используется в Markowitz и correlated Monte Carlo.']
    ]
  },
  {
    id:'gbm', title:'3 · GBM', short:'Future Paths',
    purpose:'Геометрическое броуновское движение создаёт возможные траектории цены на будущее. Это модельный сценарий, а не точный прогноз.',
    formulas:[
      ['GBM', 'dSₜ = μSₜdt + σSₜdWₜ', 'μ — drift, σ — volatility, Wₜ — Wiener process.'],
      ['Дискретная форма', 'Sₜ₊Δt = Sₜ · exp[(μ−½σ²)Δt + σ√Δt·Z]', 'Z ~ N(0,1).'],
      ['Коррелированные шоки', 'ε = LZ;  LLᵀ = Σ', 'Cholesky-разложение сохраняет историческую зависимость активов.']
    ]
  },
  {
    id:'mcvar', title:'4 · Monte Carlo & VaR 95%', short:'Risk',
    purpose:'Monte Carlo повторяет GBM много раз (по умолчанию 10 000 сценариев) и получает распределение возможных конечных значений капитала.',
    formulas:[
      ['Best Case', 'P95 = 95-й перцентиль', 'Не «вероятная прибыль», а верхняя граница внутри модельного распределения.'],
      ['Median Case', 'P50 = 50-й перцентиль', 'Центральный результат модельного распределения.'],
      ['Worst Case', 'P05 = 5-й перцентиль', 'Нижний хвост распределения.'],
      ['VaR 95%', 'VaR₉₅ = Start − P05', 'Сколько капитала отделяет старт от 5-го перцентиля.'],
      ['CVaR / Expected Shortfall 95%', 'CVaR₉₅ = E[L | L ≥ VaR₉₅]', 'Средняя потеря внутри худших 5% сценариев; обычно CVaR ≥ VaR для loss-oriented определения.']
    ]
  },
  {
    id:'bootstrap', title:'5 · Statistical Bootstrap', short:'Bootstrap',
    purpose:'Непараметрическая альтернативная модель риска. Вместо предположения GBM она переиспользует реальные исторические совместные доходности. В программе используется stationary block bootstrap со средней длиной блока 21 торговый день.',
    formulas:[
      ['Историческая выборка', 'r*ₜ ∼ Empirical({r₁,…,rₙ})', 'Каждое наблюдение берётся из фактической исторической выборки доходностей.'],
      ['Block Bootstrap', 'Bⱼ = (rⱼ,…,rⱼ₊ₗ₋₁)', 'Стационарный bootstrap случайно выбирает длину блока; в проекте E[L] = 21 торговый день.'],
      ['Доходность портфеля', 'rₚ,t = Σwᵢrᵢ,t', 'Исторические доходности всех выбранных активов пересэмплируются совместно, поэтому их cross-asset dependence сохраняется.'],
      ['Будущая стоимость', 'Vₜ = Vₜ₋₁(1+rₚ,t)', 'Исторические наблюдения компаундируются в 10 000 альтернативных траекторий.'],
      ['VaR 95%', 'VaR₉₅ = Q₉₅(L)', '95-й перцентиль распределения потерь L = Start − Terminal Value.'],
      ['CVaR 95%', 'CVaR₉₅ = E[L | L ≥ VaR₉₅]', 'Средняя потеря в самых плохих 5% Bootstrap-сценариев.']
    ]
  },
  {
    id:'event', title:'6 · Event Study', short:'Information',
    purpose:'Измеряет, отклонилась ли доходность акции от того, что объясняет рынок, вокруг даты отчётности.',
    formulas:[
      ['Окно оценки', 'T₀ = −110 … T₁ = −11', '100 торговых наблюдений до события.'],
      ['Market Model', 'Rᵢ,t = α + βRₘ,t + eₜ', 'Нормальная доходность акции оценивается по рыночному фактору.'],
      ['Beta', 'β = Σ(Rᵢ−R̄ᵢ)(Rₘ−R̄ₘ) / Σ(Rₘ−R̄ₘ)²', 'Чувствительность акции к движению рынка.'],
      ['Alpha', 'α = R̄ᵢ − βR̄ₘ', 'Средняя часть доходности, не объяснённая рынком.'],
      ['Standard Error', 'SE = √[Σeₜ² / (n−2)]', 'Типичный масштаб ошибки market model.'],
      ['Expected Return', 'E(Rᵢ,t) = α + βRₘ,t', 'Что модель ожидала бы без отдельного события.'],
      ['Abnormal Return', 'ARₜ = Rᵢ,t − E(Rᵢ,t)', 'Избыточная доходность, связанная с событием в день t.'],
      ['CAR', 'CARₜ = Σᵢ₌₋₅ᵗ ARᵢ', 'Накопленный abnormal return от −5 до текущего дня.'],
      ['t-statistic', 't = ARₜ / SE', '|t| > 1.96 → флаг статистической значимости примерно на 5% уровне.']
    ]
  },
  {
    id:'capm', title:'7 · CAPM', short:'CAPM',
    purpose:'Оценивает required return / cost of equity относительно локального рынка. Benchmark нужен для beta; sovereign/default risk и CRP учитываются отдельно, без двойного счёта.',
    formulas:[
      ['Local CAPM', 'Kₑ = (Sovereign Yield − Default Spread) + β × Mature ERP + CRP', 'Единая currency-consistent схема: sovereign default spread отделяется от Rf, country premium добавляется один раз. Для стран с CRP≈0 формула сводится к обычному CAPM.'],
      ['Rolling Beta', 'β = Cov(Rᵢ,Rₘ) / Var(Rₘ)', 'В проекте — weekly returns, rolling 104 weeks, минимум 52 совместных наблюдения.'],
      ['Expected Alpha', 'α_expected = Research Expected Return − CAPM Required Return', 'Появится после Bull/Base/Bear; CAPM сам по себе не создаёт research expected return.']
    ]
  },
  {
    id:'risk', title:'8 · Risk Diagnostics', short:'Risk Mgmt',
    purpose:'Дополнительные метрики, которые помогают не путать «исторический риск» с риском будущего убытка.',
    formulas:[
      ['Maximum Drawdown', 'MDD = min[(Vₜ − Peakₜ)/Peakₜ]', 'Максимальная просадка от предыдущего максимума.'],
      ['Portfolio Return', 'Rₚ,t = ΣwᵢRᵢ,t', 'Доходность портфеля в отдельный день.'],
      ['Historical Volatility', 'σ = Std(Rdaily) × √252', 'Годовая оценка разброса дневных доходностей.']
    ]
  }
];

function openResearchModal(title, html){
  const modal=document.getElementById('researchov');
  const root=document.getElementById('research-mi');
  if(!modal || !root) return;
  root.innerHTML=`<div class="research-title">${title}</div>${html}`;
  modal.classList.add('open');
}
function closeResearchModal(){ document.getElementById('researchov')?.classList.remove('open'); }


function researchEsc(v){
  return String(v ?? '').replace(/[&<>"']/g, ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
function researchMissing(v){return v===null||v===undefined||v==='';}
function researchNum(v,d=2){if(researchMissing(v))return '—';const n=Number(v);return Number.isFinite(n)?n.toFixed(d):'—';}
function researchPct(v,d=1){if(researchMissing(v))return '—';const n=Number(v);return Number.isFinite(n)?n.toFixed(d)+'%':'—';}
function researchMoney(v){if(researchMissing(v))return '—';const n=Number(v);if(!Number.isFinite(n))return '—';const a=Math.abs(n);return a>=1e12?(n/1e12).toFixed(2)+'T':a>=1e9?(n/1e9).toFixed(2)+'B':a>=1e6?(n/1e6).toFixed(1)+'M':n.toLocaleString('en-US',{maximumFractionDigits:0});}

function selectedStockTickers(){
  return [...cmpSet].filter(t=>{const r=allData.find(x=>x.ticker===t);return !r || (r.asset_type||'stock')==='stock';});
}

function openSimilarCompaniesFromSelection(){
  const selected=selectedStockTickers();
  if(!selected.length){alert('Сначала выберите хотя бы одну акцию галочкой. Для ETF и облигаций peer analysis не используется.');return;}
  if(selected.length===1){openSimilarCompanies(selected[0]);return;}
  openResearchModal('🔎 Сравнить похожие компании', `
    <div class="formula-intro">Вы выбрали несколько акций. Укажите, для какой именно компании искать альтернативы. Существующая функция «Сравнить» не изменяется.</div>
    <div class="peer-picker">${selected.map(t=>`<button class="btn similar-btn" onclick="openSimilarCompanies('${researchEsc(t)}')">${researchEsc(t)} → peers</button>`).join('')}</div>`);
}

async function openSimilarCompanies(ticker){
  ticker=String(ticker||'').toUpperCase();
  openResearchModal(`🔎 Similar Companies · ${researchEsc(ticker)}`, `
    <div class="formula-intro">Фильтр: same/close industry · similar business model · similar market cap · similar geography when relevant · enough financial data.</div>
    <div id="similar-company-results"><div class="chart-loading">⏳ Ищем и проверяем peers…</div></div>`);
  const out=document.getElementById('similar-company-results');
  try{
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),22000);
    const r=await fetch('/api/similar-companies?'+new URLSearchParams({ticker,limit:'8'}),{signal:controller.signal});
    clearTimeout(timer);
    const d=await r.json();if(!r.ok||d.error)throw new Error(d.error||'Не удалось получить похожие компании');
    (d.peers||[]).forEach(p=>{
      if(!allData.some(x=>x.ticker===p.ticker)) allData.push({...p,asset_type:'stock',ratings:{},region_medians:{},error:null});
    });
    if(!(d.peers||[]).length){out.innerHTML='<div class="portfolio-warning">⚠ Подходящие peers не найдены среди доступных данных. Критерии специально не ослабляются до случайных компаний из сектора.</div>';return;}
    const target=d.target||{ticker};
    out.innerHTML=`
      <div class="peer-target"><strong>${researchEsc(target.name||target.ticker)}</strong><span>${researchEsc(target.ticker)} · ${researchEsc(target.market||'—')} · ${researchEsc(target.industry||target.sector||'—')}</span></div>
      <div class="peer-explain">Peer score используется только для <strong>ранжирования сходства</strong>, а не как инвестиционный рейтинг.</div>
      <div style="overflow-x:auto"><table class="bmt peer-table"><thead><tr>
        <th>Компания</th><th>Почему похожа</th><th>Market Cap</th><th>P/E</th><th>EV/EBITDA</th><th>ROE</th><th>D/E</th><th>FCF</th><th>Действие</th>
      </tr></thead><tbody>${d.peers.map(p=>{
        const m=p.match||{};const reasons=[];
        if(m.same_industry)reasons.push('same industry');else if(m.same_sector)reasons.push('same sector');
        if(m.business_similarity>0)reasons.push(`business ${(m.business_similarity*100).toFixed(0)}%`);
        if(m.market_cap_ratio!=null)reasons.push(`${Number(m.market_cap_ratio).toFixed(2)}× cap`);
        if(m.same_market)reasons.push('same market');else if(m.same_region)reasons.push('same region');
        return `<tr><td><strong>${researchEsc(p.ticker)}</strong><br><small>${researchEsc(p.name)}</small></td><td><span class="peer-score">${researchNum(p.peer_score,0)}/100</span><br><small>${reasons.map(researchEsc).join(' · ')}</small></td><td>${researchMoney(p.market_cap)}</td><td>${researchNum(p.pe_ratio)}</td><td>${researchNum(p.ev_ebitda)}</td><td>${researchPct(p.roe_pct)}</td><td>${researchNum(p.de_ratio)}</td><td>${researchMoney(p.fcf)}</td><td><button class="btn peer-use-btn" onclick="replaceSelectedWithPeer('${researchEsc(ticker)}','${researchEsc(p.ticker)}')">Выбрать вместо ${researchEsc(ticker)}</button></td></tr>`;
      }).join('')}</tbody></table></div>
      <div class="portfolio-note">Это отдельный research workflow. Старое ручное сравнение выбранных активов осталось без изменений.</div>`;
  }catch(e){
    if(out)out.innerHTML=`<div class="portfolio-warning">⚠ ${e?.name==='AbortError'?'Peer search не ответил за 22 секунды. Повторите позже.':researchEsc(e.message)}</div>`;
  }
}

function replaceSelectedWithPeer(oldTicker,newTicker){
  if(cmpSet.has(oldTicker)) cmpSet.delete(oldTicker);
  cmpSet.add(newTicker);
  document.querySelectorAll('.cmpck').forEach(cb=>{cb.checked=cmpSet.has(cb.dataset.ticker);});
  renderTray();
  const box=document.getElementById('similar-company-results');
  if(box){const n=document.createElement('div');n.className='peer-selected-note';n.textContent=`✓ ${oldTicker} заменён на ${newTicker} в выбранных активах.`;box.prepend(n);}
}

const fundamentalTrendClientCache=new Map();
async function loadFundamentalTrends(ticker,containerId){
  const root=document.getElementById(containerId);if(!root)return;
  root.innerHTML='<div class="chart-loading">⏳ Считаем YoY / CAGR / margins / cash conversion…</div>';
  try{
    let d=fundamentalTrendClientCache.get(ticker);
    if(!d){const r=await fetch('/api/fundamental-trends?'+new URLSearchParams({ticker}));d=await r.json();if(!r.ok||d.error)throw new Error(d.error||'Недостаточно фундаментальной истории');fundamentalTrendClientCache.set(ticker,d);}
    const labels={revenue:'Revenue',net_income:'Net Income',eps:'EPS',fcf:'Free Cash Flow',total_debt:'Total Debt'};
    const trendTxt={growth_accelerating:'Рост ускоряется',growth_decelerating:'Рост замедляется',growing:'Растёт',decline_moderating:'Снижение замедляется',declining:'Снижается',flat:'Без изменения',insufficient_data:'Недостаточно данных'};
    const years=(d.years||[]).slice(-5);
    const rows=Object.entries(labels).map(([k,label])=>{const m=d.metrics?.[k]||{};return `<tr><td><strong>${label}</strong></td><td>${researchPct(m.latest_yoy_pct)}</td><td>${researchPct(m.cagr_pct)}</td><td>${researchEsc(trendTxt[m.trend]||m.trend||'—')}</td></tr>`}).join('');
    const latest=years[years.length-1];
    const marginDefs=[['Gross Margin','gross_margin_pct'],['Operating Margin','operating_margin_pct'],['Net Margin','net_margin_pct'],['FCF Margin','fcf_margin_pct']];
    const marginCards=marginDefs.map(([label,k])=>`<div class="trend-kpi"><span>${label}</span><strong>${researchPct(d.margins?.[k]?.[latest])}</strong><small>${researchEsc(latest||'')}</small></div>`).join('');
    root.innerHTML=`<div class="trend-head"><div><strong>Fundamental Trend Engine</strong><p>Только расчёты из опубликованных годовых отчётов; отсутствующие поля не заполняются искусственно.</p></div></div>
      <div class="trend-kpis">${marginCards}</div>
      <div class="msec">Growth & quality trends</div><div style="overflow-x:auto"><table class="bmt"><thead><tr><th>Metric</th><th>Latest YoY</th><th>CAGR</th><th>Interpretation</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="msec">Cash conversion · ${researchEsc(latest||'latest')}</div>
      <div class="trend-kpis"><div class="trend-kpi"><span>OCF / Net Income</span><strong>${researchPct(d.cash_conversion?.ocf_to_net_income_pct?.[latest])}</strong></div><div class="trend-kpi"><span>FCF / Net Income</span><strong>${researchPct(d.cash_conversion?.fcf_to_net_income_pct?.[latest])}</strong></div></div>
      <div class="portfolio-note">CAGR не показывается, если начальное или конечное значение ≤ 0: в таком случае классическая CAGR математически некорректна.</div>`;
  }catch(e){root.innerHTML=`<div class="portfolio-warning">⚠ Fundamental Trend: ${researchEsc(e.message)}</div>`;}
}

const CAPM_CLIENT_CACHE=new Map();
async function loadCapmPanel(ticker,market,containerId){
  const root=document.getElementById(containerId);if(!root)return;
  const key=`${ticker}|${market||''}`;const cached=CAPM_CLIENT_CACHE.get(key);
  if(cached && Date.now()-cached.ts<15*60*1000){renderCapmPanel(root,cached.data);return;}
  root.innerHTML='<div class="chart-loading">⏳ Risk-free → beta → ERP/CRP → Required Return…</div>';
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),22000);
  try{
    const r=await fetch('/api/capm?'+new URLSearchParams({ticker,market:market||''}),{signal:controller.signal});const d=await r.json();if(!r.ok||d.error)throw new Error(d.error||'CAPM unavailable');
    CAPM_CLIENT_CACHE.set(key,{ts:Date.now(),data:d});renderCapmPanel(root,d);
  }catch(e){root.innerHTML=`<div class="portfolio-warning">⚠ CAPM: ${researchEsc(e?.name==='AbortError'?'расчёт не ответил за 22 секунды':e.message)}</div>`;}
  finally{clearTimeout(timer);}
}

function renderCapmPanel(root,d){
  const rf=d.risk_free||{},erp=d.erp||{};
  const method='Country-risk-consistent local CAPM';
  const required=d.required_return_pct;
  const crpRaw=erp.country_risk_premium_pct;
  const crp=researchMissing(crpRaw)?NaN:Number(crpRaw);
  const showCrp=Number.isFinite(crp)&&Math.abs(crp)>0.0001;
  const canvasId=`capm-beta-${String(d.ticker).replace(/[^a-zA-Z0-9_-]/g,'_')}-${Date.now()}`;
  const kzRfBridge=!researchMissing(rf.sovereign_yield_pct)
    ? `<div class="portfolio-note"><strong>Risk-free bridge:</strong> sovereign yield ${researchPct(rf.sovereign_yield_pct,2)} − default spread ${researchPct(rf.default_spread_deduction_pct,2)} = estimated local risk-free ${researchPct(rf.rate_pct,2)}. Это предотвращает двойной учёт sovereign risk перед добавлением CRP.</div>`
    : '';
  root.innerHTML=`
    <div class="capm-summary">
      <div class="capm-kpi"><span>Required Return</span><strong>${researchPct(required,2)}</strong><small>${researchEsc(method)}</small></div>
      <div class="capm-kpi"><span>Rolling β</span><strong>${researchNum(d.beta,2)}</strong><small>${researchEsc(d.benchmark_name||d.benchmark)}</small></div>
      <div class="capm-kpi"><span>Risk-Free</span><strong>${researchPct(rf.rate_pct,2)}</strong><small>${researchEsc(rf.as_of||'—')}</small></div>
      <div class="capm-kpi"><span>${showCrp?'Mature ERP':'Equity Risk Premium'}</span><strong>${researchPct(showCrp?erp.base_erp_pct:erp.total_erp_pct,2)}</strong><small>${researchEsc(erp.as_of||'—')}</small></div>
      ${showCrp?`<div class="capm-kpi"><span>Country Risk Premium</span><strong>${researchPct(erp.country_risk_premium_pct,2)}</strong><small>country adjustment</small></div>`:''}
    </div>
    <div class="capm-formula"><code>${researchEsc(d.formula)}</code><span>Benchmark: ${researchEsc(d.benchmark_name||'—')} (${researchEsc(d.benchmark||'—')})${d.benchmark_fallback_used?' · fallback used':''} · ${researchEsc(d.currency||'')}</span></div>
    ${kzRfBridge}
    ${required==null?'<div class="portfolio-warning">⚠ Required Return не рассчитан: один из обязательных inputs недоступен. Программа не подставляет выдуманное значение.</div>':''}
    <div class="capm-research-gap"><div><span>Research Expected Return</span><strong>—</strong><small>появится после Bull / Base / Bear</small></div><div><span>Expected Alpha</span><strong>—</strong><small>Research Return − Required Return</small></div></div>
    <div class="msec">Historical rolling Beta</div>
    <div class="capm-beta-chart"><canvas id="${canvasId}"></canvas></div>
    <div class="portfolio-model-meta"><span>β obs: <strong>${d.beta_diagnostics?.observations??d.beta_observations??'—'}</strong></span><span>R²: <strong>${researchNum(d.beta_diagnostics?.r_squared,3)}</strong></span><span>SE β: <strong>${researchNum(d.beta_diagnostics?.beta_se,3)}</strong></span><span>t β: <strong>${researchNum(d.beta_diagnostics?.beta_t_stat,2)}</strong></span></div>
    <div class="portfolio-note">${researchEsc(d.history_note||'')}${rf.stale?' ⚠ Risk-free observation is stale; auto-refresh checks the source but cannot invent a newer publisher observation.':''}${erp.stale?' ⚠ ERP/CRP source is stale.':''}</div>
    <div class="capm-source"><span>Rf: ${researchEsc(rf.source||'—')} · as of ${researchEsc(rf.as_of||'—')}</span><span>ERP/CRP: ${researchEsc(erp.source||'—')} · as of ${researchEsc(erp.as_of||'—')}</span></div>`;
  setTimeout(()=>drawCapmBetaChart(canvasId,d.beta_history||[]),20);
}

function drawCapmBetaChart(id,rows){
  const canvas=document.getElementById(id);if(!canvas)return;
  const data=(rows||[]).filter(x=>Number.isFinite(Number(x.beta)));
  if(data.length<2){canvas.parentElement.innerHTML='<div class="chart-na">Недостаточно point-in-time beta history для графика</div>';return;}
  const dpr=window.devicePixelRatio||1,w=Math.max(560,canvas.parentElement.clientWidth||720),h=220,p={l:50,r:18,t:18,b:36};
  canvas.width=w*dpr;canvas.height=h*dpr;canvas.style.width=w+'px';canvas.style.height=h+'px';const c=canvas.getContext('2d');c.scale(dpr,dpr);
  const vals=data.map(x=>Number(x.beta)),min=Math.min(...vals),max=Math.max(...vals),span=Math.max(max-min,.2),lo=min-span*.2,hi=max+span*.2;
  const X=i=>p.l+i/(data.length-1)*(w-p.l-p.r),Y=v=>h-p.b-(v-lo)/(hi-lo)*(h-p.t-p.b);
  c.font='10px monospace';c.fillStyle='#8fa2cc';c.strokeStyle='rgba(112,131,173,.18)';
  for(let i=0;i<=4;i++){const y=lo+(hi-lo)*i/4,py=Y(y);c.beginPath();c.moveTo(p.l,py);c.lineTo(w-p.r,py);c.stroke();c.fillText(y.toFixed(2),5,py+3);}
  c.strokeStyle='#00d4ff';c.lineWidth=2.3;c.beginPath();data.forEach((r,i)=>{const x=X(i),y=Y(Number(r.beta));i?c.lineTo(x,y):c.moveTo(x,y)});c.stroke();
  data.forEach((r,i)=>{const x=X(i),y=Y(Number(r.beta));c.fillStyle='#00d4ff';c.beginPath();c.arc(x,y,3.5,0,Math.PI*2);c.fill();c.fillStyle='#8fa2cc';c.fillText(String(r.year),x-13,h-12);});
  if(lo<1&&hi>1){c.strokeStyle='rgba(251,191,36,.55)';c.setLineDash([4,4]);c.beginPath();c.moveTo(p.l,Y(1));c.lineTo(w-p.r,Y(1));c.stroke();c.setLineDash([]);}
}

function openFormulaLibrary(){
  const tabs=FORMULA_TOPICS.map((t,i)=>`<button class="formula-tab ${i===0?'active':''}" onclick="selectFormulaTopic('${t.id}')">${t.short}</button>`).join('');
  openResearchModal('∑ Библиотека формул', `<div class="formula-intro">Все формулы, которые реально используются в программе. Сначала — простое объяснение, затем математическая запись и роль формулы в модели.</div><div class="formula-layout"><div class="formula-tabs">${tabs}</div><div id="formula-topic"></div></div>`);
  renderFormulaTopic('markowitz');
}
function selectFormulaTopic(id){
  document.querySelectorAll('.formula-tab').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.formula-tab').forEach(b=>{ if(b.textContent===FORMULA_TOPICS.find(t=>t.id===id)?.short) b.classList.add('active'); });
  renderFormulaTopic(id);
}
function renderFormulaTopic(id){
  const t=FORMULA_TOPICS.find(x=>x.id===id)||FORMULA_TOPICS[0];
  const root=document.getElementById('formula-topic'); if(!root) return;
  root.innerHTML=`<div class="formula-topic-head"><div><strong>${t.title}</strong><p>${t.purpose}</p></div></div><div class="formula-grid">${t.formulas.map(([name,formula,desc])=>`<div class="formula-card"><span>${name}</span><code>${formula}</code><small>${desc}</small></div>`).join('')}</div>`;
}

function openEventStudy(){
  const selected=[...cmpSet].filter(t=>{const r=allData.find(x=>x.ticker===t);return (r?.asset_type||'stock')==='stock';});
  if(!selected.length){alert('Event Study отчётности доступен только для выбранных акций. ETF и облигации здесь не используются.');return;}
  const options=selected.map(t=>`<option value="${t}">${t}</option>`).join('');
  openResearchModal('📅 Событийный анализ отчётности', `
    <div class="event-intro"><strong>Что здесь происходит?</strong> День <b>0</b> — дата публикации отчётности/новости. Основное окно — <b>−5…0…+5</b>, то есть 11 торговых сессий. Каждый выбранный актив рассчитывается <strong>отдельно</strong> против своего market benchmark: собственные α, β, residual risk, AR, CAR и t-stat.</div>
    <div class="event-form event-form-v2">
      <label><span>Актив</span><select id="event-ticker" onchange="loadEventCandidates()">${options}</select></label>
      <label class="event-span-2"><span>Отчёт / информационное событие</span><select id="event-candidate" onchange="prefetchSelectedEventStudy()"><option value="">Загрузка доступных отчётов…</option></select><small>Используется реальная дата выбранного события из официального/доступного источника.</small></label>
      <button class="btn event-run-btn" id="event-run-selected" onclick="runSelectedEventStudy()">Рассчитать событие</button>
      <button class="btn event-run-btn secondary" onclick="runAllEventStudies()">Рассчитать для всех выбранных</button>
    </div>
    <div class="event-window-badge">Оценка: −110…−11 = 100 торговых дней · Buffer: −10…−6 · Событие: −5…0…+5. Если публикация вышла после закрытия рынка, t=0 не переносится — реакция может проявиться на t=+1. Будущие дни не моделируются.</div>
    <div id="event-results"></div>`);
  loadEventCandidates();
}

async function loadEventCandidates(){
  const ticker=document.getElementById('event-ticker')?.value; const sel=document.getElementById('event-candidate');
  if(!ticker || !sel) return;
  sel.disabled=true; sel.innerHTML='<option value="">Загрузка отчётов…</option>';
  const controller=new AbortController(); const timer=setTimeout(()=>controller.abort(),6000);
  try{
    const r=await fetch('/api/event-study/dates?'+new URLSearchParams({ticker}),{signal:controller.signal});
    const d=await r.json(); if(!r.ok||d.error) throw new Error(d.error||'Не удалось получить даты отчётности');
    const candidates=(d.candidates||[]).filter(x=>!x.date || x.date<=new Date().toISOString().slice(0,10));
    if(!candidates.length){ sel.innerHTML='<option value="">Нет доступных прошлых дат отчётности</option>'; return; }
    sel.innerHTML=candidates.map((x,i)=>`<option value="${x.date}" ${i===0?'selected':''}>${x.label}${x.source_name?' · '+x.source_name:''}</option>`).join('');
    setTimeout(()=>prefetchSelectedEventStudy(),0);
  }catch(e){ sel.innerHTML=`<option value="">${e?.name==='AbortError'?'Календарь не ответил за 6 секунд — повторите запрос позже':e.message}</option>`; }
  finally{ clearTimeout(timer); sel.disabled=false; }
}

function eventStudyClientKey(ticker,dateValue,rec){
  return [String(ticker||'').toUpperCase(),String(dateValue||''),String(rec?.market||''),String(rec?.region||'')].join('|');
}

function prefetchSelectedEventStudy(){
  const ticker=document.getElementById('event-ticker')?.value;
  const dateValue=document.getElementById('event-candidate')?.value||'';
  if(!ticker||!dateValue)return;
  const rec=allData.find(x=>x.ticker===ticker)||{};
  // Warm the same request the Calculate button will use. Server-side price
  // range caching plus this in-flight client cache makes the visible click
  // nearly immediate when the data source has already answered.
  fetchEventStudy(ticker,dateValue,rec).catch(()=>{});
}

async function fetchEventStudy(ticker, dateValue, rec){
  const key=eventStudyClientKey(ticker,dateValue,rec);
  const cached=EVENT_STUDY_CLIENT_CACHE.get(key);
  if(cached) return await cached;

  const request=(async()=>{
    const params=new URLSearchParams({ticker});
    if(dateValue) params.set('event_date',dateValue);
    if(rec?.market) params.set('market',rec.market);
    if(rec?.region) params.set('region',rec.region);
    const controller=new AbortController();
    const timer=setTimeout(()=>controller.abort(),16000);
    try{
      const r=await fetch('/api/event-study?'+params.toString(),{signal:controller.signal});
      const d=await r.json();
      if(!r.ok || d.error) throw new Error(d.error||'Ошибка event study');
      if(!d.verification?.passed) throw new Error('Event Study не прошёл внутреннюю повторную проверку');
      return d;
    }catch(e){
      if(e?.name==='AbortError') throw new Error('Event Study не ответил за 16 секунд. Расчёт остановлен вместо бесконечной загрузки. Проверьте доступ к market-data source и повторите.');
      throw e;
    }finally{ clearTimeout(timer); }
  })();
  EVENT_STUDY_CLIENT_CACHE.set(key,request);
  try{
    return await request;
  }catch(e){
    EVENT_STUDY_CLIENT_CACHE.delete(key);
    throw e;
  }
}

async function runSelectedEventStudy(){
  const ticker=document.getElementById('event-ticker')?.value; const dateValue=document.getElementById('event-candidate')?.value||'';
  const rec=allData.find(x=>x.ticker===ticker)||{}; const out=document.getElementById('event-results'); if(!out)return;
  if(!dateValue){out.innerHTML='<div class="portfolio-warning">⚠ Выберите реальное событие из списка.</div>';return;}
  out.innerHTML='<div class="chart-loading">⏳ Считаем AR / CAR / t-statistic…</div>';
  const btn=document.getElementById('event-run-selected'); if(btn) btn.disabled=true;
  try{ out.innerHTML=renderEventStudyResult(await fetchEventStudy(ticker,dateValue,rec)); }
  catch(e){out.innerHTML=`<div class="portfolio-warning">⚠ ${e.message}</div>`;}
  finally{if(btn)btn.disabled=false;}
}

async function runAllEventStudies(){
  const tickers=[...cmpSet].filter(t=>{const r=allData.find(x=>x.ticker===t);return (r?.asset_type||'stock')==='stock';}); if(!tickers.length)return;
  const out=document.getElementById('event-results'); if(!out)return;
  out.innerHTML='<div class="chart-loading">⏳ Считаем события параллельно для всех выбранных активов…</div>';
  const promises=tickers.map(async ticker=>{
    const controller=new AbortController();
    const timer=setTimeout(()=>controller.abort(),6000);
    try{
      const r=await fetch('/api/event-study/dates?'+new URLSearchParams({ticker}),{signal:controller.signal});
      const d=await r.json();
      if(!r.ok||d.error) throw new Error(d.error||'Не удалось получить дату отчётности');
      const candidate=(d.candidates||[])[0]; if(!candidate) throw new Error('Нет доступной даты отчётности');
      return await fetchEventStudy(ticker,candidate.date,allData.find(x=>x.ticker===ticker)||{});
    }catch(e){
      return {ticker,error:e?.name==='AbortError'?'Календарь отчётности не ответил за 6 секунд':e.message};
    }finally{clearTimeout(timer);}
  });
  const rows=await Promise.all(promises);
  out.innerHTML=rows.map(renderEventStudyResult).join('');
}

function eventCanvasId(t){return `event-chart-${String(t).replace(/[^a-zA-Z0-9_-]/g,'_')}-${Date.now()}`;}
function drawEventStudyChart(id,rows){
  const canvas=document.getElementById(id); if(!canvas || !rows?.length)return;
  const dpr=window.devicePixelRatio||1, w=Math.max(760,canvas.parentElement.clientWidth||900), h=300;
  canvas.width=w*dpr;canvas.height=h*dpr;canvas.style.width=w+'px';canvas.style.height=h+'px';
  const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);
  const pad={l:60,r:24,t:28,b:44};
  const xs=rows.map(r=>Number(r.relative_day)), ys=rows.map(r=>Number(r.car_pct));
  let xmin=Math.min(...xs,-5),xmax=Math.max(...xs,5),ymin=Math.min(...ys,0),ymax=Math.max(...ys,0); const dy=Math.max(ymax-ymin,0.5); ymin-=dy*.12;ymax+=dy*.12;
  const X=x=>pad.l+(x-xmin)/(xmax-xmin)*(w-pad.l-pad.r),Y=y=>h-pad.b-(y-ymin)/(ymax-ymin)*(h-pad.t-pad.b);
  ctx.font='10px monospace';ctx.fillStyle='#8fa2cc';ctx.strokeStyle='rgba(112,131,173,.18)';ctx.lineWidth=1;
  for(let i=0;i<=5;i++){const x=xmin+(xmax-xmin)*i/5,px=X(x);ctx.beginPath();ctx.moveTo(px,pad.t);ctx.lineTo(px,h-pad.b);ctx.stroke();ctx.fillText(String(Math.round(x)),px-7,h-pad.b+18);const y=ymin+(ymax-ymin)*i/5,py=Y(y);ctx.beginPath();ctx.moveTo(pad.l,py);ctx.lineTo(w-pad.r,py);ctx.stroke();ctx.fillText(y.toFixed(1)+'%',5,py+3);}
  ctx.strokeStyle='#00d4ff';ctx.lineWidth=2.5;ctx.beginPath();rows.forEach((r,i)=>{const px=X(r.relative_day),py=Y(r.car_pct);i?ctx.lineTo(px,py):ctx.moveTo(px,py)});ctx.stroke();
  ctx.strokeStyle='rgba(248,113,113,.8)';ctx.setLineDash([5,4]);ctx.beginPath();ctx.moveTo(X(0),pad.t);ctx.lineTo(X(0),h-pad.b);ctx.stroke();ctx.setLineDash([]);
  ctx.fillStyle='#00d4ff';ctx.fillText('CAR, %',w-65,18);ctx.fillStyle='#f87171';ctx.fillText('день 0',X(0)+5,28);
}

function eventP(v){
  const n=Number(v);
  if(!Number.isFinite(n)) return '—';
  return n<0.0001?'&lt;0.0001':n.toFixed(4);
}

function renderEventStudyResult(d){
  if(!d || d.error) return `<div class="portfolio-warning">⚠ ${d?.ticker||''}: ${d?.error||'Ошибка'}</div>`;
  const id=eventCanvasId(d.ticker), rows=d.observations||[], reg=d.regression||{};
  const sig=d.event_day_significant, carSig=d.car_event_window_significant;
  const html=`<div class="event-result-card">
    <div class="event-result-head"><div><strong>${d.ticker}</strong><span> · benchmark ${d.benchmark}</span></div><div>Дата 0: <b>${d.event_date_used}</b></div></div>
    <div class="event-kpis">
      <div><span>α</span><strong>${Number(d.alpha_pct_daily||0).toFixed(3)}%</strong><small>ежедневная</small></div>
      <div><span>β</span><strong>${Number(d.beta||0).toFixed(2)}</strong><small>чувствительность к рынку</small></div>
      <div><span>Residual Std</span><strong>${Number(d.se_pct_daily||0).toFixed(3)}%</strong><small>обычный unexplained noise</small></div>
      <div><span>AR в день 0</span><strong class="${Number(d.event_day_ar_pct||0)>=0?'positive':'negative'}">${Number(d.event_day_ar_pct||0)>=0?'+':''}${Number(d.event_day_ar_pct||0).toFixed(2)}%</strong><small>аномальная доходность</small></div>
      <div><span>AR significance</span><strong>${d.event_day_t_stat==null?'—':Number(d.event_day_t_stat).toFixed(2)}</strong><small>${sig?'statistically significant':'not significant'} · t-stat</small></div>
      <div><span>CAR −5…+5</span><strong class="${Number(d.car_event_window_pct||0)>=0?'positive':'negative'}">${Number(d.car_event_window_pct||0)>=0?'+':''}${Number(d.car_event_window_pct||0).toFixed(2)}%</strong><small>${carSig?'significant':'not significant'} · t=${d.car_event_window_t_stat==null?'—':Number(d.car_event_window_t_stat).toFixed(2)}</small></div>
    </div>
    <div class="event-thesis"><strong>Инвестиционный тезис</strong><p>${d.thesis}</p></div>
    <div class="msec">Regression Summary — estimation window −110…−11</div>
    <div class="event-table-wrap"><table class="event-table event-regression-table"><thead><tr><th>Statistic</th><th>Value</th><th>SE</th><th>t-stat</th><th>p-value</th></tr></thead><tbody>
      <tr><td>Observations / df</td><td>${Number(reg.observations||0)} / ${Number(reg.degrees_of_freedom||0)}</td><td>—</td><td>—</td><td>—</td></tr>
      <tr><td>Alpha</td><td>${Number(reg.alpha_pct_daily||0).toFixed(4)}%</td><td>${Number(reg.se_alpha_pct_daily||0).toFixed(4)}%</td><td>${Number(reg.t_alpha||0).toFixed(3)}</td><td>${eventP(reg.p_alpha)}</td></tr>
      <tr><td>Beta</td><td>${Number(reg.beta||0).toFixed(4)}</td><td>${Number(reg.se_beta||0).toFixed(4)}</td><td>${Number(reg.t_beta||0).toFixed(3)}</td><td>${eventP(reg.p_beta)}</td></tr>
      <tr><td>R²</td><td>${(Number(reg.r_squared||0)*100).toFixed(2)}%</td><td>—</td><td>—</td><td>—</td></tr>
      <tr><td>SSE</td><td>${Number(reg.sse||0).toExponential(4)}</td><td>—</td><td>—</td><td>—</td></tr>
      <tr><td>Residual variance</td><td>${Number(reg.residual_variance||0).toExponential(4)}</td><td>—</td><td>—</td><td>—</td></tr>
      <tr><td>Residual Std / SEE</td><td>${Number(reg.residual_std_pct_daily||0).toFixed(4)}%</td><td>—</td><td>—</td><td>—</td></tr>
    </tbody></table></div>
    <div class="event-news-box">
      <div><strong>Контекст события</strong><p>${d.report_context?.summary || 'Нет дополнительного контекста.'}</p></div>
      ${d.after_close_convention?`<div class="event-data-warning">Методология: ${d.after_close_convention}</div>`:''}
      ${d.report_context?.official_source?.source_url?`<div class="event-source-box"><strong>Официальный источник:</strong> ${d.report_context.official_source.source_name||'Источник'} · <a href="${d.report_context.official_source.source_url}" target="_blank" rel="noopener noreferrer">открыть публикацию</a></div>`:''}
      ${d.data_warning?`<div class="event-data-warning">⚠ ${d.data_warning}</div>`:''}
    </div>
    <div class="event-chart-wrap"><canvas id="${id}"></canvas></div>
    <div class="event-table-wrap"><table class="event-table event-observation-table"><thead><tr><th>День</th><th>Дата</th><th>R акции</th><th>R рынка</th><th>E(R)</th><th>AR</th><th>SE(AR)</th><th>t AR</th><th>CAR</th><th>t CAR</th></tr></thead><tbody>${rows.map(r=>`<tr class="${Number(r.relative_day)===0?'event-day-zero':''}"><td>${r.relative_day}</td><td>${r.date}</td><td>${Number(r.stock_return_pct).toFixed(2)}%</td><td>${Number(r.market_return_pct).toFixed(2)}%</td><td>${Number(r.expected_return_pct).toFixed(2)}%</td><td>${Number(r.abnormal_return_pct)>=0?'+':''}${Number(r.abnormal_return_pct).toFixed(2)}%</td><td>${Number(r.se_ar_pct||0).toFixed(3)}%</td><td>${r.t_stat==null?'—':Number(r.t_stat).toFixed(2)}</td><td>${Number(r.car_pct)>=0?'+':''}${Number(r.car_pct).toFixed(2)}%</td><td>${r.car_t_stat==null?'—':Number(r.car_t_stat).toFixed(2)}</td></tr>`).join('')}</tbody></table></div>
    <div class="event-method-note">Каждый актив рассчитывается отдельно. Окно оценки: −110…−11 = 100 торговых дней. Основное окно события: −5…+5 = 11 сессий. SE(AR) учитывает residual variance и uncertainty оценённых α/β; t-statistics используют Student-t framework с df=N−2. CAR накапливается от −5 до текущего дня. Используются только реальные historical prices.</div>
  </div>`;
  setTimeout(()=>drawEventStudyChart(id,rows),0);
  return html;
}
