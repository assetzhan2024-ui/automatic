'use strict';

const FORMULA_TOPICS = [
  {
    id:'markowitz', title:'1 · Markowitz Portfolio', short:'Weights',
    purpose:'Определяет, как разделить стартовый капитал между выбранными активами. Модель работает как этап распределения капитала; она не говорит, сколько вы точно заработаете в будущем.',
    formulas:[
      ['Ожидаемая доходность актива', 'μᵢ = mean(Rᵢ,t) × 252', 'Средняя дневная доходность актива переводится в годовую.'],
      ['Дисперсия портфеля', 'σₚ² = wᵀΣw', 'w — веса активов; Σ — годовая covariance matrix.'],
      ['Риск портфеля', 'σₚ = √(wᵀΣw)', 'Чем выше σₚ, тем сильнее исторические колебания портфеля.'],
      ['Доходность портфеля', 'μₚ = wᵀμ', 'Взвешенная сумма ожидаемых исторических доходностей активов.'],
      ['Sharpe Ratio', 'Sharpe = (μₚ − r_f) / σₚ', 'r_f задаётся пользователем как явное годовое предположение в валюте оценки портфеля.'],
      ['Ограничения', 'Σwᵢ = 1; 0 ≤ wᵢ ≤ 1', 'Long-only, fully invested: short selling запрещён, искусственного concentration cap нет.']
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
    purpose:'Непараметрическая альтернативная модель риска. Вместо предположения GBM она переиспользует реальные исторические совместные доходности. В программе используется stationary block bootstrap; средняя длина блока задаётся пользователем (по умолчанию 21 торговый день).',
    formulas:[
      ['Историческая выборка', 'r*ₜ ∼ Empirical({r₁,…,rₙ})', 'Каждое наблюдение берётся из фактической исторической выборки доходностей.'],
      ['Block Bootstrap', 'Bⱼ = (rⱼ,…,rⱼ₊ₗ₋₁)', 'Стационарный bootstrap случайно выбирает длину блока; средняя длина задаётся параметром l, чтобы сохранять временную зависимость без фиксированного разрезания истории.'],
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
      ['CAR', 'CARₜ = Σᵢ₌₋₁₀ᵗ ARᵢ', 'Накопленный abnormal return от −10 до текущего дня.'],
      ['t-statistic', 't = ARₜ / SE', '|t| > 1.96 → флаг статистической значимости примерно на 5% уровне.']
    ]
  },
  {
    id:'risk', title:'7 · Risk Diagnostics', short:'Risk Mgmt',
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
    <div class="event-intro"><strong>Что здесь происходит?</strong> День <b>0</b> — дата публикации отчётности/новости. <b>−10</b> — десять торговых дней до неё, <b>+10</b> — десять после. Анализ строится <strong>отдельно для каждого актива</strong>, а приложение автоматически берёт последнюю доступную публикацию из календаря отчётности.</div>
    <div class="event-form event-form-v2">
      <label><span>Актив</span><select id="event-ticker" onchange="loadEventCandidates()">${options}</select></label>
      <label class="event-span-2"><span>Отчёт / информационное событие</span><select id="event-candidate"><option value="">Загрузка доступных отчётов…</option></select><small>В выборе отображаются тип и год публикации. Например: «Квартальный отчёт 2 · 2026». После расчёта дата публикации отображается как день 0.</small></label>
      <button class="btn event-run-btn" id="event-run-selected" onclick="runSelectedEventStudy()">Рассчитать событие</button>
      <button class="btn event-run-btn secondary" onclick="runAllEventStudies()">Рассчитать для всех выбранных</button>
    </div>
    <div class="event-window-badge">Оценка: −110…−11 = 100 торговых дней · Событие: −10…0…+10. Если после отчёта прошло меньше 10 дней, расчёт честно останавливается на последнем доступном дне.</div>
    <div id="event-results"></div>`);
  loadEventCandidates();
}

async function loadEventCandidates(){
  const ticker=document.getElementById('event-ticker')?.value; const sel=document.getElementById('event-candidate');
  if(!ticker || !sel) return;
  sel.disabled=true; sel.innerHTML='<option value="">Загрузка отчётов…</option>';
  try{
    const r=await fetch('/api/event-study/dates?'+new URLSearchParams({ticker}));
    const d=await r.json(); if(!r.ok||d.error) throw new Error(d.error||'Не удалось получить даты отчётности');
    const candidates=d.candidates||[];
    if(!candidates.length){ sel.innerHTML='<option value="">Нет доступных дат отчётности</option>'; return; }
    sel.innerHTML=candidates.map((x,i)=>`<option value="${x.date}" ${i===0?'selected':''}>${x.label}${x.source_name?' · '+x.source_name:''}</option>`).join('');
  }catch(e){ sel.innerHTML=`<option value="">${e.message}</option>`; }
  finally{ sel.disabled=false; }
}

async function fetchEventStudy(ticker, dateValue, rec){
  const params=new URLSearchParams({ticker});
  if(dateValue) params.set('event_date',dateValue);
  if(rec?.market) params.set('market',rec.market);
  if(rec?.region) params.set('region',rec.region);
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),25000);
  try{
    const r=await fetch('/api/event-study?'+params.toString(),{signal:controller.signal});
    const d=await r.json();
    if(!r.ok || d.error) throw new Error(d.error||'Ошибка event study');
    return d;
  }catch(e){
    if(e?.name==='AbortError') throw new Error('Event Study не ответил за 25 секунд. Проверьте доступ к рыночным данным и повторите расчёт.');
    throw e;
  }finally{ clearTimeout(timer); }
}

async function runSelectedEventStudy(){
  const ticker=document.getElementById('event-ticker')?.value; const dateValue=document.getElementById('event-candidate')?.value||'';
  const rec=allData.find(x=>x.ticker===ticker)||{}; const out=document.getElementById('event-results'); if(!out)return;
  if(!dateValue){out.innerHTML='<div class="portfolio-warning">⚠ Не удалось определить дату отчётности. Выберите другой отчёт.</div>';return;}
  out.innerHTML='<div class="chart-loading">⏳ Считаем AR / CAR / t-statistic…</div>';
  const btn=document.getElementById('event-run-selected'); if(btn) btn.disabled=true;
  try{ renderEventStudyResult(await fetchEventStudy(ticker,dateValue,rec)); }
  catch(e){out.innerHTML=`<div class="portfolio-warning">⚠ ${e.message}</div>`;}
  finally{if(btn)btn.disabled=false;}
}

async function runAllEventStudies(){
  const tickers=[...cmpSet].filter(t=>{const r=allData.find(x=>x.ticker===t);return (r?.asset_type||'stock')==='stock';}); if(!tickers.length)return;
  const out=document.getElementById('event-results'); if(!out)return;
  out.innerHTML='<div class="chart-loading">⏳ Считаем события параллельно для всех выбранных активов…</div>';
  const promises=tickers.map(async ticker=>{
    try{
      const r=await fetch('/api/event-study/dates?'+new URLSearchParams({ticker})); const d=await r.json();
      const candidate=(d.candidates||[])[0]; if(!candidate) throw new Error('Нет доступной даты отчётности');
      return await fetchEventStudy(ticker,candidate.date,allData.find(x=>x.ticker===ticker)||{});
    }catch(e){ return {ticker,error:e.message}; }
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
  let xmin=-10,xmax=10,ymin=Math.min(...ys,0),ymax=Math.max(...ys,0); const dy=Math.max(ymax-ymin,0.5); ymin-=dy*.12;ymax+=dy*.12;
  const X=x=>pad.l+(x-xmin)/(xmax-xmin)*(w-pad.l-pad.r),Y=y=>h-pad.b-(y-ymin)/(ymax-ymin)*(h-pad.t-pad.b);
  ctx.font='10px monospace';ctx.fillStyle='#8fa2cc';ctx.strokeStyle='rgba(112,131,173,.18)';ctx.lineWidth=1;
  for(let i=0;i<=5;i++){const x=xmin+(xmax-xmin)*i/5,px=X(x);ctx.beginPath();ctx.moveTo(px,pad.t);ctx.lineTo(px,h-pad.b);ctx.stroke();ctx.fillText(String(Math.round(x)),px-7,h-pad.b+18);const y=ymin+(ymax-ymin)*i/5,py=Y(y);ctx.beginPath();ctx.moveTo(pad.l,py);ctx.lineTo(w-pad.r,py);ctx.stroke();ctx.fillText(y.toFixed(1)+'%',5,py+3);}
  ctx.strokeStyle='#00d4ff';ctx.lineWidth=2.5;ctx.beginPath();rows.forEach((r,i)=>{const px=X(r.relative_day),py=Y(r.car_pct);i?ctx.lineTo(px,py):ctx.moveTo(px,py)});ctx.stroke();
  ctx.strokeStyle='rgba(248,113,113,.8)';ctx.setLineDash([5,4]);ctx.beginPath();ctx.moveTo(X(0),pad.t);ctx.lineTo(X(0),h-pad.b);ctx.stroke();ctx.setLineDash([]);
  ctx.fillStyle='#00d4ff';ctx.fillText('CAR, %',w-65,18);ctx.fillStyle='#f87171';ctx.fillText('день 0',X(0)+5,28);
}

function renderEventStudyResult(d){
  if(!d || d.error) return `<div class="portfolio-warning">⚠ ${d?.ticker||''}: ${d?.error||'Ошибка'}</div>`;
  const id=eventCanvasId(d.ticker), rows=d.observations||[];
  const sig=d.event_day_significant;
  const html=`<div class="event-result-card">
    <div class="event-result-head"><div><strong>${d.ticker}</strong><span> · benchmark ${d.benchmark}</span></div><div>Дата 0: <b>${d.event_date_used}</b></div></div>
    <div class="event-kpis">
      <div><span>α</span><strong>${(Number(d.alpha||0)*100).toFixed(3)}%</strong><small>ежедневная</small></div>
      <div><span>β</span><strong>${Number(d.beta||0).toFixed(2)}</strong><small>чувствительность к рынку</small></div>
      <div><span>SE</span><strong>${(Number(d.se||0)*100).toFixed(3)}%</strong><small>ошибка модели</small></div>
      <div><span>AR в день 0</span><strong class="${Number(d.event_day_ar_pct||0)>=0?'positive':'negative'}">${Number(d.event_day_ar_pct||0)>=0?'+':''}${Number(d.event_day_ar_pct||0).toFixed(2)}%</strong><small>аномальная доходность</small></div>
      <div><span>t-stat</span><strong class="${sig?'positive':'negative'}">${d.event_day_t_stat==null?'—':Number(d.event_day_t_stat).toFixed(2)}</strong><small>${sig?'значимо при |t| > 1.96':'не прошло порог |t| > 1.96'}</small></div>
      <div><span>CAR −10…+10</span><strong>${Number(d.car_event_window_pct||0)>=0?'+':''}${Number(d.car_event_window_pct||0).toFixed(2)}%</strong><small>накопленный эффект</small></div>
    </div>
    <div class="event-thesis"><strong>Инвестиционный тезис</strong><p>${d.thesis}</p></div>
    <div class="event-news-box">
      <div><strong>Что было опубликовано и какой был информационный драйвер?</strong><p>${d.report_context?.summary || 'Нет дополнительного контекста.'}</p></div>
      <div class="event-driver-grid">
        <div><span>Выручка</span><strong>${d.report_context?.revenue_growth_pct==null?'—':(Number(d.report_context.revenue_growth_pct)>=0?'+':'')+Number(d.report_context.revenue_growth_pct).toFixed(1)+'%'}</strong><small>рост к сопоставимому периоду</small></div>
        <div><span>Чистая прибыль</span><strong>${d.report_context?.net_income_growth_pct==null?'—':(Number(d.report_context.net_income_growth_pct)>=0?'+':'')+Number(d.report_context.net_income_growth_pct).toFixed(1)+'%'}</strong><small>рост к сопоставимому периоду</small></div>
        <div><span>Дивиденд</span><strong>${d.report_context?.dividend_per_share==null?'—':Number(d.report_context.dividend_per_share).toFixed(2)}</strong><small>${d.report_context?.dividend_date?'последний до дня 0':'нет доступных данных'}</small></div>
      </div>
      ${d.report_context?.official_source?.source_url?`<div class="event-source-box"><strong>Официальный источник:</strong> ${d.report_context.official_source.source_name||'Источник'} · <a href="${d.report_context.official_source.source_url}" target="_blank" rel="noopener noreferrer">открыть публикацию</a></div>`:''}
      ${d.data_warning?`<div class="event-data-warning">⚠ ${d.data_warning}</div>`:''}
    </div>
    <div class="event-chart-wrap"><canvas id="${id}"></canvas></div>
    <div class="event-table-wrap"><table class="event-table"><thead><tr><th>День</th><th>Дата</th><th>R акции</th><th>R рынка</th><th>E(R)</th><th>AR</th><th>CAR</th><th>t</th></tr></thead><tbody>${rows.map(r=>`<tr class="${Number(r.relative_day)===0?'event-day-zero':''}"><td>${r.relative_day}</td><td>${r.date}</td><td>${Number(r.stock_return_pct).toFixed(2)}%</td><td>${Number(r.market_return_pct).toFixed(2)}%</td><td>${Number(r.expected_return_pct).toFixed(2)}%</td><td>${Number(r.abnormal_return_pct)>=0?'+':''}${Number(r.abnormal_return_pct).toFixed(2)}%</td><td>${Number(r.car_pct)>=0?'+':''}${Number(r.car_pct).toFixed(2)}%</td><td>${r.t_stat==null?'—':Number(r.t_stat).toFixed(2)}</td></tr>`).join('')}</tbody></table></div>
    <div class="event-method-note">Окно оценки: −110…−11 = 100 торговых дней. Окно события: −10…+10 (или до последней фактически доступной сессии). В расчёте рынок используется как benchmark, чтобы отделить общерыночное движение от abnormal return.</div>
  </div>`;
  setTimeout(()=>drawEventStudyChart(id,rows),0);
  return html;
}

