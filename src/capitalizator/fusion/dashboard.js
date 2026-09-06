'use strict';
// No simulated market data. Commands use the existing authenticated control API.
const $ = id => document.getElementById(id);
const chart = $('chart');
let stream = null, chartData = null, candles = [], lastState = null;
let streamGeneration = 0, streamConnected = false, settingsLoaded = false, sourcesLoaded = false;
let statusPromise = null, commandPending = false, lastStatusMono = null, statusError = '';
let renderPending = false, stopped = false;
const recordPanels = new Map();
const number = v => v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v)) ? Number(v) : null;
const fmt = v => number(v) === null ? '—' : new Intl.NumberFormat('ru-RU', {maximumFractionDigits:6}).format(Number(v));
const pretty = v => JSON.stringify(v ?? null, null, 2);
function decoded(v) { return typeof v === 'string' ? JSON.parse(v) : v; }
function utc(v) { const n=number(v);return n===null?'—':new Date(n*1000).toISOString().replace('T',' ').replace('.000Z',' UTC'); }
function row(parent, values) { const tr=document.createElement('tr');for(const value of values){const td=document.createElement('td');td.textContent=value??'—';tr.appendChild(td)}parent.appendChild(tr);return tr; }
function empty(parent, message, cols) { parent.replaceChildren();const tr=row(parent,[message]);tr.children[0].colSpan=cols; }
function card(parent, label, value) { const c=document.createElement('div');c.className='card';const h=document.createElement('strong');h.textContent=label;const p=document.createElement('p');p.textContent=value;c.append(h,p);parent.appendChild(c); }
async function request(path, options={}, timeout=8000) {
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout);
  try { const response=await fetch(path,{...options,signal:controller.signal,cache:'no-store'});const value=await response.json();if(!response.ok)throw new Error(value.error||'HTTP '+response.status);return value; }
  finally { clearTimeout(timer); }
}
function result(message, bad=false) { $('result').textContent=message;$('result').className='command-result'+(bad?' bad':''); }
const actionNames={mode:'Переключение счёта',pause:'Режим входов',flatten:'Закрытие позиций',settings:'Торговые лимиты',credentials:'Ключ счёта',news_credentials:'Ключ новостей',news_sources:'Источники новостей'};
async function act(action, body) {
  if(commandPending)return false;
  commandPending=true;document.querySelectorAll('[data-control]').forEach(b=>b.disabled=true);
  result((actionNames[action]||action)+': отправка…');
  try {
    const value=await request('/api/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Control-Token':token},body:JSON.stringify(body)},15000);
    const messages={close_requested:'Команда закрытия принята. Ожидайте сверки позиций и журнала команд.',pending_exchange_check:'Запрошена смена счёта. Ожидайте проверки биржи.',restart_requested:'Конфигурация сохранена. Перезапуск контуров; входы останутся на паузе.',sources_saved:'Источники сохранены. Ожидание нового получения новостей.',applied_on_next_news_fetch:'Ключ сохранён. Применится при следующем получении новостей.',unchanged:'Настройки уже действуют.'};
    result((actionNames[action]||action)+': '+(messages[value.status]||(value.saved?'Ключ сохранён.':typeof value.paused==='boolean'?(value.paused?'Входы приостановлены.':'Входы разрешены; остальные фильтры продолжают действовать.'):pretty(value))));
    if(action==='settings')settingsLoaded=false;
    await refresh();return true;
  } catch(error) {
    const uncertain=error.name==='AbortError'||error instanceof TypeError;
    result((actionNames[action]||action)+': '+(uncertain?'Ответ не получен. Результат команды неизвестен; проверьте состояние и журнал перед повтором.':error.message),true);
    return false;
  } finally { commandPending=false;document.querySelectorAll('[data-control]').forEach(b=>b.disabled=false); }
}
async function saveSettings(event) { event.preventDefault();const value=id=>Number($(id).value);await act('settings',{max_positions:value('max-positions'),trade_margin_fraction:value('trade-margin')/100,max_stop_fraction:value('max-stop')/100,leverage:value('leverage')}); }
async function saveKeys(event) { event?.preventDefault();if(await act('credentials',{mode:$('mode').value,key:$('key').value,secret:$('secret').value})){$('key').value='';$('secret').value='';} }
async function saveNewsKey(event) { event?.preventDefault();if(await act('news_credentials',{key:$('newskey').value}))$('newskey').value=''; }
function addNewsSource(source={name:'',kind:'rss',url:'',assets:[]}) {
  const container=document.createElement('div');container.className='source-row';
  function field(label,tag,cls,value){const l=document.createElement('label');l.textContent=label;const e=document.createElement(tag);e.className=cls;e.value=value;l.appendChild(e);container.appendChild(l);return e;}
  field('Название','input','source-name',source.name);
  const kind=field('Тип источника','select','source-kind','');for(const [v,t] of [['rss','RSS / Atom'],['unlocks','Анлоки Tokenomist']]){const o=document.createElement('option');o.value=v;o.textContent=t;kind.appendChild(o)}kind.value=source.kind;
  field('HTTPS URL / Tokenomist ID','input','source-address',source.url||source.token_id||'');
  field('Пары через запятую','input','source-assets',(source.assets||[]).join(', '));
  const f=field('Только упомянутые активы','input','source-filter','');f.type='checkbox';f.checked=Boolean(source.match_assets);f.parentElement.className='filter-label';
  const remove=document.createElement('button');remove.type='button';remove.textContent='Удалить источник';remove.onclick=()=>container.remove();container.appendChild(remove);$('news-sources').appendChild(container);
}
async function saveNewsSources() { const sources=Array.from(document.querySelectorAll('.source-row')).map(r=>{const kind=r.querySelector('.source-kind').value;return {name:r.querySelector('.source-name').value.trim(),kind,match_assets:r.querySelector('.source-filter').checked,[kind==='rss'?'url':'token_id']:r.querySelector('.source-address').value.trim(),assets:r.querySelector('.source-assets').value.split(',').map(v=>v.trim().toUpperCase()).filter(Boolean)}});await act('news_sources',{sources}); }
function renderNews(id, list, isEvent=false) {
  const target=$(id);target.replaceChildren();if(!list?.length){target.textContent='Нет полученных '+(isEvent?'событий.':'заголовков.');return;}
  for(const n of list){const item=document.createElement('article');item.className='news-item';let heading=document.createElement('span');
    if(n.url){try{const u=new URL(n.url);if(['https:','http:'].includes(u.protocol)){heading=document.createElement('a');heading.href=u.href;heading.target='_blank';heading.rel='noopener noreferrer';}}catch{}}
    heading.textContent=n.title||n.headline||n.event_class||n.event_id||'Событие';const meta=document.createElement('small');meta.textContent=[n.source,n.event_time||n.published_at||n.at,(n.assets||[]).join(', ')].filter(Boolean).join(' · ');item.append(heading,meta);target.appendChild(item);
  }
}
function statusClock() { return lastState?lastState.at+Math.max(0,(performance.now()-lastStatusMono)/1000):null; }
function renderFreshness() {
  if(!lastState)return;const s=lastState,now=statusClock(),age=Math.max(0,(performance.now()-lastStatusMono)/1000),connected=!statusError&&age<=8;
  $('connection-age').textContent=connected?'Состояние: '+age.toFixed(1)+' с назад':'Состояние устарело · '+age.toFixed(1)+' с';
  $('clock').textContent=utc(now);
  $('health').textContent=!connected?'Нет свежей связи с системой'+(statusError?': '+statusError:''):s.mode.toUpperCase()+' · '+(s.halted?'Остановка: '+s.reason:s.paused?'Входы приостановлены':s.broker?.ready?'Счёт подключён':'Ожидание подключения счёта')+(s.mode_request?' · Запрошен '+s.mode_request.toUpperCase():'');
  $('health').className=!connected||s.halted?'bad':'';
  const accountAge=s.account?now-s.account.at:null,accountFresh=connected&&accountAge!==null&&accountAge>=0&&accountAge<=s.config.account_age_s;
  $('account-freshness').textContent=s.account?(accountFresh?'Сверен':'Устарел')+' · '+accountAge.toFixed(1)+' с':'Нет снимка счёта';$('account-freshness').className='chip '+(accountFresh?'good':'bad');
  const gates=[['Связь с системой',connected?'Подключена':'Устарела / нет связи',connected],['Входы',s.paused?'Пауза':s.halted?'Остановлены':'Разрешены',connected&&!s.paused&&!s.halted],['Сверка счёта',accountFresh?'Свежая':'Не готова',accountFresh],['Модель',s.model?'Загружена':'Нет модели',connected&&!!s.model]];
  $('entry-gates').replaceChildren();for(const [label,value,ok] of gates){const d=document.createElement('div');d.className='gate '+(ok?'good':'bad');const l=document.createElement('small');l.textContent=label;const v=document.createElement('span');v.textContent=value;d.append(l,v);$('entry-gates').appendChild(d)}
  const table=$('coverage-rows');table.replaceChildren();for(const symbol of s.config.symbols){const m=s.markets[symbol]||{};const book=b=>!connected?'Состояние устарело':b?.status==='instrument_unavailable'?'Точная пара отсутствует':b?.valid&&now-b.book_at>=0&&now-b.book_at<=s.config.max_data_age_s&&number(b.exchange_at)!==null&&now-b.exchange_at>=0&&now-b.exchange_at<=s.config.max_data_age_s?'Свежий':'Нет свежих данных';row(table,[symbol,book(m.cross_market?.spot),book(m.cross_market?.linear),m.block?'Возраст '+Math.max(0,now-m.block.at).toFixed(1)+' с':'Нет контекста',pretty(s.news?.coverage?.[symbol]??'Нет покрытия')]);}
}
function renderStatus(s) {
  const first=!lastState,oldMode=lastState?.mode;lastState=s;lastStatusMono=performance.now();statusError='';
  $('mode-badge').textContent=s.mode.toUpperCase();$('mode-badge').className=s.mode==='live'?'bad':'';
  if(first||oldMode!==s.mode)$('mode').value=s.mode;
  const selector=$('symbol');if(!selector.options.length){for(const symbol of s.config.symbols){const option=document.createElement('option');option.value=option.textContent=symbol;selector.appendChild(option)}connectChart();}
  else if(oldMode!==s.mode){connectChart();for(const p of recordPanels.values())if(['orders','commands','executions'].includes(p.kind))loadRecords(p,null);}
  const c=$('cards');c.replaceChildren();card(c,'Эквити · '+s.mode.toUpperCase(),s.account?fmt(s.account.equity):'Нет счёта');card(c,'Реализованный P&L',fmt(s.performance?.realized_net));card(c,'Закрытые эпизоды',fmt(s.performance?.closed_episodes));card(c,'Активная модель',s.model||'Ещё не обучена');
  const cfg=s.config;if(!settingsLoaded){for(const [id,v] of Object.entries({'max-positions':cfg.max_positions,'trade-margin':cfg.trade_margin_fraction*100,'max-stop':cfg.max_stop_fraction*100,'leverage':cfg.leverage}))$(id).value=v;$('max-positions').max=cfg.symbols.length;settingsLoaded=true;}
  if(!sourcesLoaded){for(const source of s.news_sources||[])addNewsSource(source);sourcesLoaded=true;}
  $('applied-settings').textContent=(s.restart_requested?'Перезапуск для применения… ':'Применено: ')+cfg.max_positions+' пар · маржа на сделку до '+fmt(cfg.trade_margin_fraction*100)+'% · стоп до '+fmt(cfg.max_stop_fraction*100)+'% · плечо '+cfg.leverage+' · общая маржа до '+fmt(cfg.margin_fraction*100)+'%';
  $('halt-reasons').textContent=(s.halt_reasons||[]).join(' · ');
  const whales=$('whales');whales.replaceChildren();for(const [symbol,m] of Object.entries(s.markets).filter(([,m])=>m.block).sort((a,b)=>(b[1].block.context.largest_print*b[1].block.close)-(a[1].block.context.largest_print*a[1].block.close))){row(whales,[symbol,fmt(m.block.context.largest_print),fmt(m.block.flow*100)+'%',fmt(m.block.context.block_trade_volume),fmt(Math.max(0,s.at-m.block.at))]);}if(!whales.children.length)empty(whales,'Нет наблюдавшихся блоков сделок.',5);
  const markets=$('markets');markets.replaceChildren();for(const symbol of cfg.symbols){const m=s.markets[symbol]||{},b=m.block?.context||{};row(markets,[symbol,b.amd||'Накопление данных',pretty({support:b.support,resistance:b.resistance,sweep:b.sweep}),pretty({profile:b.profile,fvg:b.fvg,ote:b.pairing?.ote,anchors:b.pairing?.anchors})]);}
  const account=s.account?decoded(s.account.body):null,positions=(account?.positions||[]).filter(p=>number(p.size)!==null&&Number(p.size)!==0);const target=$('position-rows');target.replaceChildren();for(const p of positions)row(target,[p.symbol,p.side,fmt(p.size),fmt(p.avgPrice),fmt(p.markPrice),fmt(p.unrealisedPnl),fmt(p.stopLoss)]);if(!positions.length)empty(target,s.account?'В последнем снимке открытых позиций нет.':'Нет снимка счёта — позиции неизвестны.',7);
  $('positions').textContent=pretty({account_at:s.account?.at,account,orders:(s.orders||[]).map(o=>({...o,body:decoded(o.body)}))});
  $('decisions').textContent=s.decisions?.length?s.decisions.map(d=>utc(d.at)+' '+d.symbol+' '+d.kind+'\n'+pretty(decoded(d.body))).join('\n\n'):'Решений ещё нет.';
  $('diagnostics').textContent=pretty({broker:s.broker,queues:s.queues,private_queue:s.private_queue,errors:s.worker_errors,uptime_s:s.uptime_s,config_version:s.config_version,restart_requested:s.restart_requested,mode_request:s.mode_request,halt_reasons:s.halt_reasons});
  $('config-state').textContent=pretty(cfg);$('performance-state').textContent=pretty(s.performance);
  $('training-state').textContent=pretty({active_model:s.model,active_report:s.active_model_report,last_training:s.training,policy_since:s.policy_since,config_version:s.config_version});
  $('news-state').textContent=pretty(s.news);renderNews('headlines',s.news?.headlines);renderNews('events',s.news?.events,true);
  $('coverage-state').textContent=pretty({markets:s.markets,options:s.options});
  $('maintenance').textContent=s.maintenance?.commands?.join('\n\n')||'Команды обслуживания недоступны в этой версии сервера.';
  renderFreshness();scheduleDraw();
}
function refresh() {
  if(statusPromise)return statusPromise;
  statusPromise=(async()=>{try{const s=await request('/api/status');if(s.console_instance!==consoleInstance){location.reload();return;}renderStatus(s);}catch(error){statusError=error.name==='AbortError'?'тайм-аут':error.message;$('health').textContent='Нет связи с системой: '+statusError;$('health').className='bad';renderFreshness();}finally{statusPromise=null;}})();return statusPromise;
}
function clearChart(message) {
  const g=chart.getContext('2d');if(g)g.clearRect(0,0,chart.width,chart.height);
  $('chart-status').textContent=message;$('context').textContent=message;$('crosshair').textContent='OHLCV появится после получения свечей.';chart.onmousemove=null;
  for(const venue of ['spot','linear']){$(venue+'-health').textContent=message;empty($(venue+'-book'),'Ожидание нового снимка',4)}$('book-comparison').textContent=message;
}
function connectChart() {
  const generation=++streamGeneration;if(stream)stream.close();stream=null;streamConnected=false;chartData=null;candles=[];resetDepth();clearChart('Подключение выбранного инструмента…');
  const symbol=$('symbol').value,tf=$('tf').value;if(!symbol)return;
  const connection=new EventSource('/api/stream?symbol='+encodeURIComponent(symbol)+'&tf='+encodeURIComponent(tf));stream=connection;
  connection.onmessage=event=>{
    if(generation!==streamGeneration||stopped)return;
    try{const data=JSON.parse(event.data);if(data.symbol!==symbol||data.tf!==tf||!Number.isFinite(data.at))throw new Error('Снимок не соответствует выбранному графику');
      if(lastState&&data.mode!==lastState.mode){streamConnected=false;chartData=null;candles=[];resetDepth();clearChart('Смена счёта: ожидание сверки состояния…');void refresh();return;}
      data._received_mono=performance.now();chartData=data;streamConnected=true;if(data.candles)candles=data.candles;captureDepth(data);scheduleDraw();
    }catch(error){streamConnected=false;chartData=null;candles=[];resetDepth();clearChart('Ошибка потока: '+error.message);result('График: '+error.message,true);}
  };
  connection.onerror=()=>{if(generation!==streamGeneration)return;streamConnected=false;resetDepth();scheduleDraw();$('chart-status').textContent='Нет потока графика · переподключение';};
}
function scheduleDraw() { if(renderPending||document.hidden||stopped)return;renderPending=true;requestAnimationFrame(()=>{renderPending=false;if(document.hidden||stopped)return;try{draw();if(!streamConnected)$('chart-status').textContent='Нет потока графика · переподключение';drawDepth();}catch(e){result('Ошибка визуализации: '+e.message,true);}}); }
function createRecordPanel(panel) {
  const kind=panel.dataset.kind,p={kind,before:null,next:null,generation:0,busy:false,loaded:false};recordPanels.set(kind,p);
  const toolbar=document.createElement('div');toolbar.className='record-toolbar';p.status=document.createElement('span');p.status.className='record-status';p.status.textContent='Журнал ещё не загружен.';p.status.setAttribute('role','status');
  p.first=document.createElement('button');p.first.textContent='Последние записи';p.nextButton=document.createElement('button');p.nextButton.textContent='Более ранние';p.nextButton.disabled=true;
  p.first.onclick=()=>loadRecords(p,null);p.nextButton.onclick=()=>loadRecords(p,p.next);toolbar.append(p.status,p.first,p.nextButton);p.list=document.createElement('div');p.list.className='record-list';panel.append(toolbar,p.list);
  return p;
}
async function loadRecords(p,before=null) {
  const generation=++p.generation;p.busy=true;p.first.disabled=p.nextButton.disabled=true;p.status.textContent='Загрузка…';p.list.replaceChildren();
  try { const data=await request('/api/records?kind='+encodeURIComponent(p.kind)+'&limit=20'+(before===null?'':'&before='+before));
    if(generation!==p.generation)return;if(['orders','executions','commands'].includes(p.kind)&&lastState&&data.mode!==lastState.mode){p.status.textContent='Счёт изменился. Обновите журнал.';p.next=null;return;}
    p.loaded=true;p.before=before;p.next=data.next_before;p.status.textContent=(data.mode?data.mode.toUpperCase()+' · ':'Все режимы · ')+data.rows.length+' записей'+(data.next_before!==null?' · есть более ранние':' · конец журнала');
    if(!data.rows.length)p.list.textContent='Записей пока нет.';
    for(const value of data.rows){const item=document.createElement('article');item.className='record-entry';const h=document.createElement('h4');h.textContent=[value.symbol,value.state||value.kind,value.id||value.version||value.key,utc(value.at||value.created||value.received)].filter(Boolean).join(' · ');const pre=document.createElement('pre');pre.tabIndex=0;const normalized={...value};for(const k of ['body','definition','report'])if(typeof normalized[k]==='string'){try{normalized[k]=decoded(normalized[k])}catch{/* Preserve exact malformed record for operator inspection. */}}pre.textContent=pretty(normalized);item.append(h,pre);p.list.appendChild(item);}
  }catch(error){if(generation===p.generation){p.status.textContent='Не удалось получить журнал: '+error.message;p.next=null;}}
  finally{if(generation===p.generation){p.busy=false;p.first.disabled=false;p.nextButton.disabled=p.next===null;}}
}
async function statusLoop() { if(stopped)return;if(!document.hidden)await refresh();if(!stopped)setTimeout(statusLoop,2000); }
function freshnessLoop() { if(stopped)return;if(!document.hidden){renderFreshness();scheduleDraw();}setTimeout(freshnessLoop,1000); }
function init() {
  $('settings').onsubmit=saveSettings;$('keys-form').onsubmit=saveKeys;$('news-key-form').onsubmit=saveNewsKey;$('add-source').onclick=()=>addNewsSource();$('save-sources').onclick=saveNewsSources;
  $('pause-quick').onclick=()=>act('pause',{paused:true});$('resume-quick').onclick=()=>act('pause',{paused:false});
  $('switch-mode').onclick=()=>act('mode',{mode:$('mode').value});$('pause').onclick=()=>act('pause',{paused:true});$('resume').onclick=()=>act('pause',{paused:false});$('flatten').onclick=()=>act('flatten',{});
  $('symbol').onchange=$('tf').onchange=connectChart;for(const id of ['zones','fills','sessions'])$(id).onchange=scheduleDraw;$('count').oninput=scheduleDraw;
  $('copy-maintenance').onclick=async()=>{try{await navigator.clipboard.writeText($('maintenance').textContent);$('copy-status').textContent='Команды скопированы.';}catch{$('copy-status').textContent='Буфер обмена недоступен. Выделите и скопируйте команды выше.';}};
  document.querySelectorAll('pre,.table-scroll').forEach(e=>e.tabIndex=0);
  document.querySelectorAll('.records').forEach(createRecordPanel);
  // Read large journals only as their section becomes visible; each has an explicit refresh button.
  if(typeof IntersectionObserver!=='undefined'){const observer=new IntersectionObserver(entries=>{for(const entry of entries)if(entry.isIntersecting){const p=recordPanels.get(entry.target.dataset.kind);if(!p.loaded&&!p.busy)void loadRecords(p);observer.unobserve(entry.target);}},{rootMargin:'120px'});document.querySelectorAll('.records').forEach(p=>observer.observe(p));}
  const nav=()=>document.querySelectorAll('nav a').forEach(a=>{if(a.getAttribute('href')===(location.hash||'#overview'))a.setAttribute('aria-current','location');else a.removeAttribute('aria-current');});window.addEventListener('hashchange',nav);nav();
  initDepth();window.addEventListener('resize',scheduleDraw);document.addEventListener('visibilitychange',()=>{if(document.hidden){stopCamera();}else{void refresh();scheduleDraw();}});
  window.addEventListener('pagehide',()=>{stopped=true;if(stream)stream.close();stopCamera();});window.addEventListener('pageshow',e=>{if(e.persisted)location.reload();});
  void statusLoop();freshnessLoop();
}
document.addEventListener('DOMContentLoaded',init);
