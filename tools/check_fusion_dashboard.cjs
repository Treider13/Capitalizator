// Deterministic behavior checks with a strict DOM model; this is NOT browser QA.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const root='src/capitalizator/fusion/';
const html=fs.readFileSync(root+'dashboard.html','utf8');
let draws=0,mono=1000,rafID=0;const frames=new Map(),timers=new Map();let timerID=0;
const drawing=new Proxy({}, {get:(o,k)=>o[k]||((...args)=>{for(const v of args)if(typeof v==='number')assert(Number.isFinite(v),k+' received nonfinite coordinate');draws++;}),set:(o,k,v)=>(o[k]=v,true)});
const all=[];
class Element {
  constructor(tag='div',id=''){this.tagName=tag.toUpperCase();this.id=id;this.value='';this.checked=false;this.disabled=false;this.children=[];this.attrs={};this.dataset={};this.style={};this.textContent='';this.className='';this.clientWidth=id==='depth'?1200:1100;this.clientHeight=id==='depth'?420:520;this.width=1100;this.height=520;all.push(this);}
  get options(){return this.tagName==='SELECT'?this.children:[];}
  appendChild(e){this.children.push(e);e.parentElement=this;if(this.tagName==='SELECT'&&!this.value)this.value=e.value||e.textContent;return e;}
  append(...items){items.forEach(e=>this.appendChild(e));}
  replaceChildren(...items){this.children=[];this.textContent='';this.append(...items);}
  remove(){this.parentElement.children=this.parentElement.children.filter(e=>e!==this);}
  getContext(){return drawing;}
  setAttribute(k,v){this.attrs[k]=v;}
  getAttribute(k){return this.attrs[k];}
  removeAttribute(k){delete this.attrs[k];}
  querySelectorAll(selector){const matches=[];const walk=e=>{for(const c of e.children){if(match(c,selector))matches.push(c);walk(c);}};walk(this);return matches;}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
}
function match(e,selector){return selector.split(',').some(s=>{s=s.trim();if(s.startsWith('.'))return e.className.split(' ').includes(s.slice(1));if(s==='[data-control]')return 'data-control' in e.attrs;return e.tagName===s.toUpperCase();});}
const nodes=new Map();for(const m of html.matchAll(/<(\w+)([^>]*\bid="([^"]+)"[^>]*)>/g)){assert(!nodes.has(m[3]),'duplicate id '+m[3]);const e=new Element(m[1],m[3]);e.checked=/\bchecked\b/.test(m[2]);e.value=/\bvalue="([^"]*)"/.exec(m[2])?.[1]||'';e.className=/\bclass="([^"]*)"/.exec(m[2])?.[1]||'';if(m[2].includes('data-control'))e.attrs['data-control']='';nodes.set(e.id,e);}
for(const m of html.matchAll(/<select[^>]*id="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g)){const e=nodes.get(m[1]);for(const o of m[2].matchAll(/<option(?: value="([^"]+)")?>([^<]+)/g)){const v=new Element('option');v.value=o[1]||o[2];v.textContent=o[2];e.appendChild(v);}}
for(const m of html.matchAll(/<div class="panel records" data-kind="([^"]+)">/g)){const e=new Element();e.className='records';e.dataset.kind=m[1];}
const navs=[];for(const m of html.split('<nav')[1].split('</nav>')[0].matchAll(/href="([^"]+)"/g)){const e=new Element('a');e.attrs.href=m[1];navs.push(e);}
let ready;
const document={hidden:false,getElementById(id){assert(nodes.has(id),'missing actual HTML id: '+id);return nodes.get(id);},createElement(tag){return new Element(tag);},createTextNode(text){const e=new Element('text');e.textContent=text;return e;},querySelectorAll(s){return s==='nav a'?navs:all.filter(e=>match(e,s));},addEventListener(n,fn){if(n==='DOMContentLoaded')ready=fn;}};
const cfg={symbols:['BTCUSDT','ETHUSDT','XAUUSDT','SOLUSDT','BNBUSDT','DOGEUSDT'],account_age_s:15,max_data_age_s:5,max_positions:2,trade_margin_fraction:.1,max_stop_fraction:.05,leverage:2,margin_fraction:.2};
let state={console_instance:'instance',at:100,mode:'demo',paused:true,config:cfg,markets:{},account:null,model:null,performance:{realized_net:0,closed_episodes:0},orders:[],decisions:[],news:{coverage:{},headlines:[],events:[]},news_sources:[],maintenance:{commands:['python -m example']}};
let postResult={ok:true,value:{paused:true}},posts=[],fetches=[],reloaded=0,pendingPost=null;
const streams=[];class EventSource{constructor(url){this.url=url;streams.push(this);}close(){this.closed=true;}}
const media={matches:false,addEventListener(){}};
const env={document,window:{devicePixelRatio:1,addEventListener(){},matchMedia:()=>media},location:{hash:'',reload(){reloaded++;}},EventSource,AbortController,URL,navigator:{clipboard:{writeText:async()=>{}}},performance:{now:()=>mono},requestAnimationFrame(fn){frames.set(++rafID,fn);return rafID;},cancelAnimationFrame(id){frames.delete(id);},setTimeout(fn){timers.set(++timerID,fn);return timerID;},clearTimeout(id){timers.delete(id);},fetch:async(path,options={})=>{fetches.push(path);if(options.method==='POST'){posts.push({path,body:JSON.parse(options.body),headers:options.headers});if(pendingPost)return pendingPost;return {ok:postResult.ok,json:async()=>postResult.value};}if(path.startsWith('/api/records')){const kind=new URL(path,'http://localhost').searchParams.get('kind');return {ok:true,json:async()=>({kind,mode:['orders','commands','executions'].includes(kind)?state.mode:null,rows:[],next_before:null})};}return {ok:true,json:async()=>state};},Intl,Date,Math,Number,JSON,console};
vm.createContext(env);vm.runInContext("const token='test-token';const consoleInstance='instance';",env);
for(const file of ['dashboard.js','chart.js','depth.js'])vm.runInContext(fs.readFileSync(root+file,'utf8'),env,{filename:file});
const run=code=>vm.runInContext(code,env);
async function settle(){for(let i=0;i<15;i++)await Promise.resolve();}
function render(){const list=[...frames.values()];frames.clear();list.forEach(fn=>fn(mono));}
const rows=Array.from({length:50},(_,i)=>({at:40+i,end:41+i,open:100+i*.01,high:102,low:98,close:101,volume:10+i}));
function fixture(at=100,symbol='BTCUSDT',tf='1m'){
 const linear={valid:true,book_at:at,exchange_at:at,bid:100,ask:101,imbalance:.2,spread_bps:10};return {at,max_data_age_s:5,positions:[{stopLoss:'100',avgPrice:'101',size:'1'}],mode:state.mode,symbol,tf,quote:{bid:100,valid:true,book_at:at},candles:rows,forming:null,cross_market:{linear,spot:{...linear,category:'spot',status:'streaming'},basis_bps:0},book_levels:{bids:[[100,2],[99,1]],asks:[[101,3],[102,4]]},spot_levels:{bids:[[100,20]],asks:[[101,30]]},structure:{history_gaps:1,contiguous_from:rows[40].at,bars:10,support:99,resistance:101,zones:[{low:99,high:100,side:1}],sessions:[{name:'London',boundary:'open',at:rows[10].at+.5}],geometry:{trend_segments:{high:[[rows[5].at,101],[rows[15].at,102]]},rsi_divergence:{segment:[[rows[6].at,99],[rows[18].at,98.5]]},bag:{low:100,high:101},order_block_zone:{low:99,high:100},equal_highs:[101],equal_lows:[99]}},options:{strikes:[{price:100,gross:100}]},block:{context:{amd:'fixture',pairing:{htf:'15m',ltf:'1m',ote:[99,100],poi:{low:99,high:100,kind:'OB'}},session_profiles:{london:{poc:100,val:99,vah:101,histogram:[[99,10],[100,20]]}}}},orders:[{state:'partial',stop:99,target:102}],fills:[{at:rows[20].at,side:'Buy',execPrice:100}],contracts:[{at:rows[15].at,state:'confirmed',definition:{entry:100}}]};
}
function emit(s,data){s.onmessage({data:JSON.stringify(data)});render();}
(async()=>{
 ready();await settle();render();assert.equal(streams.length,1);assert.equal(nodes.get('symbol').options.length,6);assert.equal(run('recordPanels.size'),11);assert.match(nodes.get('position-rows').children[0].children[0].textContent,/неизвестны/);
 const initial=streams.at(-1);emit(initial,fixture());assert(draws>100);assert.match(nodes.get('chart-status').textContent,/BTCUSDT/);assert.equal(JSON.parse(nodes.get('context').textContent).data_quality.history_gaps,1);assert.equal(run('depthFrames.linear.length'),1);assert.equal(run('depthFrames.linear[0].bids[0][1]'),2);assert.equal(run('depthFrames.spot[0].bids[0][1]'),20);
 // Pressure panel never carries a recovery state across stale data or symbol reset.
 const pressureFrame=fixture();pressureFrame.liquidation_pressure={mode:'observe',quality:'ready',at:100,evaluated_at:100,max_age_s:5,episodes:[{direction:'sell',state:'recovery'}]};emit(initial,pressureFrame);
 assert.match(nodes.get('pressure-status').textContent,/восстановление/);
 const pressureClock=mono;mono+=6000;run('renderPressure(chartData)');assert.match(nodes.get('pressure-status').textContent,/устарела/);assert(!nodes.get('pressure-status').textContent.includes('восстановление'));mono=pressureClock;
 pressureFrame.liquidation_pressure.valid_until=100.2;emit(initial,pressureFrame);mono+=500;run('renderPressure(chartData)');assert.match(nodes.get('pressure-status').textContent,/устарела/);mono=pressureClock;delete pressureFrame.liquidation_pressure.valid_until;
 pressureFrame.liquidation_pressure.quality='unavailable';emit(initial,pressureFrame);assert(!nodes.get('pressure-status').textContent.includes('восстановление'));
 pressureFrame.liquidation_pressure.mode='off';pressureFrame.liquidation_pressure.quality='off';emit(initial,pressureFrame);assert.match(nodes.get('pressure-status').textContent,/Выключен/);
 run('renderPressure(null)');assert.equal(nodes.get('pressure-detail').textContent,'');emit(initial,fixture());
 // Daily levels remain visible on intraday charts and expire at the UTC boundary.
 assert(nodes.get('tf').options.some(o=>o.value==='1d'));
 const dailyFrame=fixture();dailyFrame.daily={status:'ready',at:0,support:{price:99},resistance:{price:101},levels:[]};emit(initial,dailyFrame);
 assert.match(nodes.get('daily-status').textContent,/поддержка 99/);assert.match(nodes.get('daily-status').textContent,/сопротивление 101/);assert.equal(JSON.parse(nodes.get('context').textContent).daily.status,'ready');
 const dayClock=mono;mono=86400000;run('draw()');assert.match(nodes.get('daily-status').textContent,/устарели/);mono=dayClock;
 // Levels outside the visible candle scale still have explicit numeric values.
 dailyFrame.daily.support.price=50;dailyFrame.daily.resistance.price=150;emit(initial,dailyFrame);assert.match(nodes.get('daily-status').textContent,/поддержка 50/);assert.match(nodes.get('daily-status').textContent,/сопротивление 150/);
 // Layers and real OHLCV remain functional.
 for(const id of ['zones','fills','sessions'])nodes.get(id).checked=false;run('draw();chart.onmousemove({offsetX:100})');assert.match(nodes.get('crosshair').textContent,/O 100/);
 run("chart.onpointerdown({offsetX:100});chart.onkeydown({key:'Home',preventDefault(){}})");assert.match(nodes.get('crosshair').textContent,/O 100 H/);
 // Old stream callbacks cannot repopulate a newly selected symbol.
 nodes.get('symbol').value='ETHUSDT';run('connectChart()');assert(initial.closed);emit(initial,fixture());assert.equal(run('chartData'),null);assert.equal(run('depthFrames.linear.length'),0);emit(streams.at(-1),fixture(100,'ETHUSDT'));assert.equal(run('chartData.symbol'),'ETHUSDT');
 // Limit memory to real one-second snapshots; never add an interpolated frame.
 const eth=streams.at(-1);for(let i=1;i<=40;i++){mono+=1000;emit(eth,fixture(100+i,'ETHUSDT'));}assert.equal(run('depthFrames.linear.length'),24);emit(eth,fixture(140.2,'ETHUSDT'));assert.equal(run('depthFrames.linear.length'),24);
 // Slow motion ends and does not modify/replay the data stream.
 run('cameraTo(0,72)');let iterations=0;while(frames.size&&iterations++<260){mono+=16;render();}assert(iterations<260);assert.equal(run('cameraFrame'),null);assert.equal(run('camera.pitch'),72);assert.equal(run('chartData.at'),140.2);
 // Monotonic freshness expires without waiting for another network message.
 mono+=6000;run('draw();drawDepth()');assert.match(nodes.get('linear-health').textContent,/Нет свежих данных/);assert.match(nodes.get('depth-status').textContent,/Нет свежего стакана/);
 // An unavailable exact spot instrument is explicit, futures remain separate.
 const unavailable=fixture(150,'ETHUSDT');unavailable.cross_market.spot={status:'instrument_unavailable'};emit(eth,unavailable);nodes.get('depth-venue').value='spot';run('drawDepth(true)');assert.match(nodes.get('depth-status').textContent,/Точной спотовой пары нет/);assert.equal(run('depthFrames.spot.length'),0);nodes.get('depth-venue').value='linear';
 // Disconnect clears tradable tables and 3D; empty candles still show context.
 eth.onerror();render();assert.equal(run('depthFrames.linear.length'),0);assert.match(nodes.get('chart-status').textContent,/Нет потока/);const noCandles=fixture(151,'ETHUSDT');noCandles.candles=[];emit(eth,noCandles);assert.match(nodes.get('chart-status').textContent,/ожидание реальных свечей/);assert(JSON.parse(nodes.get('context').textContent).structure);
 // Errors are visible and failed credential saves retain fields for correction.
 nodes.get('key').value='sentinel-key';nodes.get('secret').value='sentinel-secret';postResult={ok:false,value:{error:'pause entries before changing credentials'}};await run('saveKeys()');assert.equal(nodes.get('secret').value,'sentinel-secret');assert.match(nodes.get('result').textContent,/pause entries/);assert(!nodes.get('result').textContent.includes('sentinel'));assert.equal(posts.at(-1).headers['X-Control-Token'],'test-token');
 postResult={ok:true,value:{saved:'demo'}};await run('saveKeys()');assert.equal(nodes.get('secret').value,'');assert.equal(nodes.get('key').value,'');
 // Concurrent button presses produce only one mutation.
 let release;pendingPost=new Promise(r=>release=r);const count=posts.length;const first=run("act('pause',{paused:true})");const second=await run("act('pause',{paused:false})");assert.equal(second,false);assert.equal(posts.length,count+1);release({ok:true,json:async()=>({paused:true})});await first;pendingPost=null;
 // Account switch closes old stream and uses actual active mode in every journal.
 state={...state,at:152,mode:'live'};await run('refresh()');assert.equal(nodes.get('mode').value,'live');assert(eth.closed);assert.equal(run('chartData'),null);assert.equal(run('depthFrames.linear.length'),0);await run("loadRecords(recordPanels.get('orders'))");assert.match(run("recordPanels.get('orders').status.textContent"),/LIVE/);
 // Source editor can round-trip values without HTML interpolation.
 run("addNewsSource({name:'<img onerror=attack()>',kind:'rss',url:'https://example.com/rss',assets:['BTCUSDT'],match_assets:true})");await run('saveNewsSources()');assert.equal(posts.at(-1).body.sources[0].name,'<img onerror=attack()>');assert.equal(posts.at(-1).body.sources[0].assets[0],'BTCUSDT');
 // Reduced motion snaps the camera; server instance changes force token renewal.
 media.matches=true;run('cameraTo(-10,20)');assert.equal(run('cameraFrame'),null);assert.equal(run('camera.yaw'),-10);
 await settle();state={...state,console_instance:'new-instance'};await run('refresh()');assert.equal(reloaded,1);
 // Audit regressions: malformed records must not freeze unrelated sections.
 await settle();state={...state,console_instance:'instance',at:200,mode:'demo',account:{at:200,equity:100,body:'{broken'},decisions:[{at:0,symbol:'BTCUSDT',kind:'test',body:'{broken'}],training:{version:'audit'},news:{coverage:{},events:[],headlines:[{title:'Actual RSS schema',published:100,assets:['BTCUSDT']}]}};
 await run('refresh()');render();assert.match(nodes.get('position-rows').children[0].children[0].textContent,/Ошибка данных счёта/);assert.match(nodes.get('training-state').textContent,/audit/);assert.match(nodes.get('decisions').textContent,/decode_error/);assert.match(nodes.get('headlines').children[0].children[1].textContent,/UTC/);assert.match(nodes.get('account-freshness').textContent,/Устарел/);assert.notEqual(run('fmt(0.00000001)'),'0');
 // A past/future fill must not be moved onto a current candle, or across a history gap.
 nodes.get('symbol').value='BTCUSDT';run('connectChart()');const auditStream=streams.at(-1);const clipped=fixture(200);clipped.fills=[];clipped.contracts=[];nodes.get('fills').checked=true;emit(auditStream,clipped);
 let beforeDraw=draws;run('draw()');const baselineDraw=draws-beforeDraw;
 env.outside=fixture(200);env.outside.fills=[{at:999,side:'Buy',execPrice:100}];env.outside.contracts=[{at:999,definition:{entry:100}}];run('chartData.fills=outside.fills;chartData.contracts=outside.contracts');beforeDraw=draws;run('draw()');assert.equal(draws-beforeDraw,baselineDraw);
 // Stale Buy/Sell cannot remain "ready", including a wall-clock rollback on the server.
 const rollback=fixture(200);rollback.monotonic_at=30;rollback.book_entry_checks={Buy:'ready',Sell:'ready'};for(const b of Object.values(rollback.cross_market))if(b&&typeof b==='object')b.received_monotonic=10;emit(auditStream,rollback);assert.match(nodes.get('book-comparison').textContent,/данные устарели/);assert(!nodes.get('book-comparison').textContent.includes('ready'));
 // A delayed SSE frame cannot make old quotes fresh against a newer status clock.
 emit(auditStream,fixture(180));assert.match(nodes.get('linear-health').textContent,/Нет свежих данных/);
 const delayedPressure=fixture(180);delayedPressure.liquidation_pressure={mode:'observe',quality:'ready',at:180,evaluated_at:180,valid_until:185,max_age_s:5,episodes:[{direction:'sell',state:'recovery'}]};emit(auditStream,delayedPressure);assert.match(nodes.get('pressure-status').textContent,/устарела/);assert(!nodes.get('pressure-status').textContent.includes('восстановление'));
 // Broken JSON closes the stream and obtains a FULL snapshot on a new connection.
 auditStream.onmessage({data:'{broken'});assert(auditStream.closed);assert.equal(run('chartData'),null);const retry=run('reconnectTimer');assert(retry!==null);timers.get(retry)();const recovered=streams.at(-1);emit(auditStream,fixture(201));assert.equal(run('chartData'),null);emit(recovered,fixture(201));assert.equal(run('candles.length'),50);
 // Missing heartbeat without an EventSource error also forces recovery.
 mono+=7000;run('freshnessLoop()');assert(recovered.closed);assert(run('reconnectTimer')!==null);
 // Parsed 200/500 transport failures are UNKNOWN command outcomes, never false refusals.
 const originalFetch=env.fetch;env.fetch=async()=>({ok:true,status:200,json:async()=>{throw new SyntaxError('truncated')}});await run("act('flatten',{})");assert.match(nodes.get('result').textContent,/Результат команды неизвестен/);env.fetch=originalFetch;
 // Successful key saving cannot erase newly typed replacement credentials.
 let finishKeys;pendingPost=new Promise(resolve=>finishKeys=resolve);nodes.get('key').value='old-key';nodes.get('secret').value='old-secret';const saving=run('saveKeys()');nodes.get('key').value='new-key';nodes.get('secret').value='new-secret';finishKeys({ok:true,json:async()=>({saved:'demo'})});await saving;pendingPost=null;assert.equal(nodes.get('key').value,'new-key');assert.equal(nodes.get('secret').value,'new-secret');await settle();
 // Source errors supplied by the actual server remain visible beside the chart.
 if(run('reconnectTimer')!==null)timers.get(run('reconnectTimer'))();const withErrors=fixture(210);withErrors.data_errors=[{source:'account',error:'object required'}];emit(streams.at(-1),withErrors);assert.match(nodes.get('chart-errors').textContent,/account/);
 // One renderer failure cannot hide the other renderer or the last command result.
 const originalDraw=run('draw');env.breakDraw=()=>{throw new Error('canvas failure')};run('draw=breakDraw;depthSignature="";scheduleDraw()');render();assert.match(nodes.get('chart-status').textContent,/canvas failure/);assert.match(nodes.get('depth-status').textContent,/снимков/);env.restoreDraw=originalDraw;run('draw=restoreDraw');

 if(process.env.BLACKBOX_RUNTIME_PAYLOAD){const actual=JSON.parse(fs.readFileSync(process.env.BLACKBOX_RUNTIME_PAYLOAD,'utf8'));await settle();state={...actual.status,console_instance:'instance'};await run('refresh()');nodes.get('symbol').value=actual.chart.symbol;nodes.get('tf').value=actual.chart.tf;run('connectChart()');emit(streams.at(-1),actual.chart);assert.equal(run('candles.length'),actual.chart.candles.length);assert.match(nodes.get('chart-status').textContent,/BTCUSDT/);assert(!nodes.get('chart-status').textContent.includes('Ошибка графика'));console.log(JSON.stringify({runtime_contract:'passed'}));}
 console.log(JSON.stringify({status:'passed',draw_calls:draws,scenarios:35,scope:'Strict DOM/canvas model; no browser rendering or live exchange execution'}));
})().catch(error=>{console.error(error);process.exitCode=1;});
