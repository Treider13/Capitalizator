// Production candle overlays. Only real runtime.chart snapshots are rendered.
function chartClock(d){const local=d.at+(d._transport_s||0)+Math.max(0,(performance.now()-d._received_mono)/1000);return typeof statusClock==='function'&&statusClock()!==null?Math.max(local,statusClock()):local;}
function bookValidAt(b,d){const now=chartClock(d),ttl=d.max_data_age_s;
  if(!b?.valid||!Number.isFinite(ttl)||ttl<=0||!Number.isFinite(b.book_at)||!Number.isFinite(b.exchange_at)||now-b.book_at<0||now-b.book_at>ttl||now-b.exchange_at<0||now-b.exchange_at>ttl||(b.category&&b.status!=='streaming'))return false;
  if(Number.isFinite(d.monotonic_at)){let nowMono=d.monotonic_at+(d._transport_s||0)+Math.max(0,(performance.now()-d._received_mono)/1000);if(typeof lastState!=='undefined'&&Number.isFinite(lastState?.monotonic_at))nowMono=Math.max(nowMono,lastState.monotonic_at+(lastState._transport_s||0)+Math.max(0,(performance.now()-lastStatusMono)/1000));const elapsed=nowMono-b.received_monotonic;if(!Number.isFinite(b.received_monotonic)||elapsed<0||elapsed>ttl)return false;}
  return true;
}
function bookFresh(b,d){return streamConnected&&bookValidAt(b,d);}
function renderBooks(d){const cross=d.cross_market||{},fmt=v=>Number.isFinite(v)?Number(v).toPrecision(7):'—';for(const venue of ['spot','linear']){const b=cross[venue]||{},fresh=bookFresh(b,d),levels=venue==='spot'?d.spot_levels:d.book_levels;const h=document.getElementById(venue+'-health');h.className=fresh?'good':'bad';h.textContent=(fresh?'Свежий':b.status==='instrument_unavailable'?'Точного спотового инструмента нет':'Нет свежих данных · '+(b.status||'ожидание'))+' · возраст '+(b.book_at?Math.max(0,chartClock(d)-b.book_at).toFixed(2)+' с':'—')+' · спред '+fmt(b.spread_bps)+' bps · дисбаланс '+(fresh?(b.imbalance*100).toFixed(1)+'%':'—');const table=document.getElementById(venue+'-book');table.replaceChildren();if(!fresh){const row=document.createElement('tr'),cell=document.createElement('td');cell.colSpan=4;cell.textContent='Нет актуальных уровней';row.appendChild(cell);table.appendChild(row)}if(fresh)for(let i=0;i<Math.max(levels?.bids?.length||0,levels?.asks?.length||0);i++){const row=document.createElement('tr');for(const v of [...(levels.bids[i]||[null,null]),...(levels.asks[i]||[null,null])]){const cell=document.createElement('td');cell.textContent=fmt(v);row.appendChild(cell)}table.appendChild(row)}}const ready=bookFresh(cross.spot,d)&&bookFresh(cross.linear,d);document.getElementById('book-comparison').textContent=d.symbol+' · базис фьючерс/спот '+(ready?fmt(cross.basis_bps)+' bps':'—')+' · '+(ready?(cross.opposed?'Давление рынков расходится':'Давление рынков согласуется'):'Новые входы заблокированы до получения двух свежих стаканов')+' · проверки Buy / Sell: '+(ready?(d.book_entry_checks?.Buy||'ожидание'):'данные устарели / не готовы')+' / '+(ready?(d.book_entry_checks?.Sell||'ожидание'):'данные устарели / не готовы');}
function dailyFresh(d){return streamConnected&&d.daily?.status==='ready'&&d.daily.at===Math.floor(chartClock(d)/86400)*86400;}
function renderDaily(d){const q=d.daily||{},ready=dailyFresh(d),fmt=p=>p&&Number.isFinite(p.price)?p.price.toPrecision(7):'нет уровня в истории';const e=document.getElementById('daily-status');e.className=ready?'hint':'bad';e.textContent=ready?'D1 · поддержка '+fmt(q.support)+' · сопротивление '+fmt(q.resistance)+' · закрытые дни UTC':'D1 · '+(q.status==='warming'||!q.status?'накапливаются закрытые дневные свечи':'дневные данные устарели / нет связи')+' · новые входы заблокированы';}
function draw(){if(!chartData)return;const d=chartData, ratio=Math.min(window.devicePixelRatio||1,2);renderBooks(d);renderDaily(d);
const w=Math.max(chart.clientWidth,320),h=520;chart.width=w*ratio;chart.height=h*ratio;const g=chart.getContext('2d');if(!g)return;g.scale(ratio,ratio);g.font='11px system-ui';
let rows=candles.slice();if(d.forming){rows=rows.filter(b=>b.at<d.forming.at);rows.push(d.forming)}rows=rows.slice(-Number(document.getElementById('count').value));
if(!rows.length){chart.onmousemove=chart.onpointerdown=chart.onkeydown=null;document.getElementById('chart-status').textContent=d.symbol+' · '+d.tf+' · ожидание реальных свечей';document.getElementById('context').textContent=JSON.stringify({daily:d.daily,structure:d.structure,block:d.block,options:d.options,news:lastState?.news?.coverage?.[d.symbol]},null,2);g.fillStyle='#cbd5e1';g.fillText('Ожидание реальных закрытых свечей / REST backfill',20,40);return;}
let min=Math.min(...rows.map(b=>b.low)),max=Math.max(...rows.map(b=>b.high)),span=max-min||max*.001;min-=span*.08;max+=span*.08;
let left=12,right=w-110,top=20,bottom=400,dx=(right-left)/rows.length;
const y=p=>bottom-(p-min)/(max-min)*(bottom-top),x=i=>left+(i+.5)*dx;
const ix=at=>rows.findIndex(b=>at>=b.at&&at<b.end);
function line(p,label,color,dash=[]){if(!Number.isFinite(p)||p<min||p>max)return;g.strokeStyle=color;g.setLineDash(dash);g.beginPath();g.moveTo(left,y(p));g.lineTo(right,y(p));g.stroke();g.setLineDash([]);g.fillStyle=color;g.fillText(label+' '+p.toPrecision(7),right+4,y(p)+4);}
function zone(lo,hi,label,color){if(!Number.isFinite(lo)||!Number.isFinite(hi)||hi<min||lo>max)return;g.globalAlpha=.14;g.fillStyle=color;g.fillRect(left,y(Math.min(hi,max)),right-left,y(Math.max(lo,min))-y(Math.min(hi,max)));g.globalAlpha=1;g.fillStyle=color;g.fillText(label,left+8,y(Math.min(hi,max))+13);}
for(let i=0;i<5;i++){let p=min+(max-min)*i/4;line(p,'','#2c3742');}
const book=d.book_levels||{},peak=Math.max(1,...(book.bids||[]).map(p=>p[1]),...(book.asks||[]).map(p=>p[1]));if(bookFresh(d.cross_market?.linear,d))for(const [side,color] of [['bids','#91c9b355'],['asks','#ec949e55']]){g.fillStyle=color;for(const [price,qty] of book[side]||[])if(price>=min&&price<=max)g.fillRect(right-qty/peak*70,y(price)-1,qty/peak*70,2);}
if(bookFresh(d.cross_market?.spot,d)){line(d.cross_market.spot.bid,'Spot bid','#38bdf8',[3,4]);line(d.cross_market.spot.ask,'Spot ask','#818cf8',[3,4]);}
const c=d.block?.context||{},s=d.structure||{};
if(document.getElementById('zones').checked){
for(let z of s.zones||[])zone(z.low,z.high,'FVG '+(z.side>0?'↑':'↓'),'#a78bfa');
for(let [name,z] of Object.entries({BAG:s.geometry?.bag,OB:s.geometry?.order_block_zone}))if(z)zone(z.low,z.high,name,'#ffc17f');
if(c.pairing?.ote)zone(...c.pairing.ote,'OTE '+c.pairing.htf+'/'+c.pairing.ltf,'#38bdf8');
if(c.pairing?.anchors){const a=c.pairing.anchors,side=c.sweep,span=a.high-a.low;for(const f of [0,.5,.618,.786,1])line(side>0?a.high-f*span:a.low+f*span,'Fib '+f,'#38bdf8',[2,5]);}
if(dailyFresh(d)){line(d.daily.support?.price,'D1 S','#22d3ee',[8,4]);line(d.daily.resistance?.price,'D1 R','#fbbf24',[8,4]);}
line(s.support,'Support','#91c9b3',[5,4]);line(s.resistance,'Resistance','#ec949e',[5,4]);
for(let p of s.geometry?.equal_highs||[])line(p,'EQH','#f472b6',[2,5]);
for(let p of s.geometry?.equal_lows||[])line(p,'EQL','#2dd4bf',[2,5]);
for(let [name,p] of Object.entries(c.session_profiles||{})){line(p.poc,name+' POC','#ffc17f');line(p.val,name+' VAL','#94a3b8',[2,4]);line(p.vah,name+' VAH','#94a3b8',[2,4]);}
for(let p of Object.values(c.session_profiles||{})){let bins=p.histogram||[],vmax=Math.max(...bins.map(b=>b[1]),1);g.fillStyle='#ffc17f40';for(let [price,v] of bins)if(price>=min&&price<=max)g.fillRect(right-v/vmax*90,y(price)-2,v/vmax*90,4);}
function segment(points,label,color){
if(!Array.isArray(points)||points.length!==2||!points.every(p=>Array.isArray(p)&&p.length===2&&p.every(Number.isFinite))||points[1][0]<=points[0][0])return;
const begin=Math.max(points[0][0],rows[0].at),end=Math.min(points[1][0],rows.at(-1).end);if(begin>=end)return;
const price=at=>points[0][1]+(points[1][1]-points[0][1])*(at-points[0][0])/(points[1][0]-points[0][0]);
const px=at=>{if(at===rows.at(-1).end)return right;const i=ix(at);return i<0?null:left+(i+(at-rows[i].at)/(rows[i].end-rows[i].at))*dx;},a=px(begin),b=px(end);if(a===null||b===null)return;
g.strokeStyle=color;g.beginPath();g.moveTo(a,y(price(begin)));g.lineTo(b,y(price(end)));g.stroke();g.fillStyle=color;g.fillText(label,b+4,y(price(end))-5);
}
for(let points of Object.values(s.geometry?.trend_segments||{}))segment(points,'Trend','#94a3b8');
segment(s.geometry?.rsi_divergence?.segment,'RSI div','#c084fc');
if(c.sweep)line(c.sweep===1?c.support:c.resistance,'Sweep '+(c.sweep>0?'↑':'↓'),'#fb923c');
if(s.bos)line(s.bos>0?s.resistance:s.support,s.choch?'CHoCH':'BOS','#60a5fa');
if(c.pairing?.poi)zone(c.pairing.poi.low,c.pairing.poi.high,'HTF '+c.pairing.poi.kind,'#60a5fa');
for(let z of (d.options?.strikes||[]).filter(z=>z.gross>0).sort((a,b)=>b.gross-a.gross).slice(0,3))line(z.price,'Γ unsigned','#d946ef',[1,4]);
}
if(document.getElementById('sessions').checked){for(let v of s.sessions||[]){
if(ix(v.at)<0)continue;
const i=ix(v.at),bar=rows[i],px=left+(i+(v.at-bar.at)/(bar.end-bar.at))*dx;
g.strokeStyle='#93c5fd';g.globalAlpha=.35;g.beginPath();g.moveTo(px,top);g.lineTo(px,bottom);g.stroke();g.globalAlpha=1;g.fillStyle='#93c5fd';g.fillText(v.name+' '+v.boundary,px+2,top+12);
}}
const vmax=Math.max(...rows.map(b=>b.volume),1);
rows.forEach((b,i)=>{g.strokeStyle=g.fillStyle=b.close>=b.open?'#91c9b3':'#ec949e';g.beginPath();g.moveTo(x(i),y(b.high));g.lineTo(x(i),y(b.low));g.stroke();g.fillRect(x(i)-Math.max(1,dx*.3),y(Math.max(b.open,b.close)),Math.max(1,dx*.6),Math.max(1,Math.abs(y(b.open)-y(b.close))));g.globalAlpha=.5;g.fillRect(x(i)-dx*.3,485-b.volume/vmax*65,Math.max(1,dx*.6),b.volume/vmax*65);g.globalAlpha=1;});
let analytics=(d.analytics||[]).filter(a=>ix(a.at)>=0);if(analytics.length>1){let lo=Math.min(...analytics.map(a=>a.cvd)),hi=Math.max(...analytics.map(a=>a.cvd)),range=hi-lo||1;g.strokeStyle='#38bdf8';g.beginPath();analytics.forEach((a,i)=>{let px=x(ix(a.at)),py=483-(a.cvd-lo)/range*60;if(i)g.lineTo(px,py);else g.moveTo(px,py);});g.stroke();g.fillStyle='#38bdf8';g.fillText('Volume / CVD',12,419);}
if(document.getElementById('fills').checked){
for(let o of d.orders||[])if(['pending','sending','unknown','accepted','partial','filled'].includes(o.state)){if(!(d.positions||[]).length)line(Number(o.stop),'SL planned','#f87171');line(Number(o.target),'TP','#4ade80');}
for(let p of d.positions||[]){line(Number(p.stopLoss),'SL venue','#f87171');line(Number(p.avgPrice),'Entry venue','#22d3ee',[3,3]);}
for(let f of d.fills||[]){if(ix(f.at)<0||f.execType==='Funding')continue;let px=Number(f.execPrice);if(px<min||px>max)continue;let a=x(ix(f.at)),b=y(px),dir=f.side==='Buy'?1:-1;g.fillStyle=dir>0?'#22d3ee':'#f97316';g.beginPath();g.moveTo(a,b);g.lineTo(a-5,b+dir*10);g.lineTo(a+5,b+dir*10);g.closePath();g.fill();}
for(let k of d.contracts||[]){let q=k.definition;if(ix(k.at)<0||q.entry<min||q.entry>max)continue;let a=x(ix(k.at)),b=y(q.entry);g.strokeStyle=k.state==='confirmed'?'#4ade80':k.state==='refuted'?'#f87171':'#a78bfa';g.beginPath();g.moveTo(a,b-5);g.lineTo(a+5,b);g.lineTo(a,b+5);g.lineTo(a-5,b);g.closePath();g.stroke();}
}
for(let event of lastState?.news?.events||[]){let at=Date.parse(event.event_time)/1000;if(ix(at)>=0&&(event.assets.includes(d.symbol)||event.assets.includes('ALL'))){g.fillStyle='#ffc17f';g.beginPath();g.arc(x(ix(at)),top+30,5,0,2*Math.PI);g.fill();g.fillText(event.event_class,x(ix(at))+7,top+34);}}
if(bookFresh(d.cross_market?.linear,d))line(Number(d.quote.bid),'Bid','#e2e8f0');
g.fillStyle='#94a3b8';for(let i=0;i<rows.length;i+=Math.max(1,Math.floor(rows.length/5)))g.fillText(new Date(rows[i].at*1000).toISOString().slice(5,16).replace('T',' '),x(i),510);
const lag=(chartClock(d)-(d.quote.book_at||0));document.getElementById('chart-status').textContent=d.mode.toUpperCase()+' · '+d.symbol+' · '+d.tf+' · AMD '+(c.amd||'данные накапливаются')+' · стакан '+(bookFresh(d.cross_market?.linear,d)?'свежий':'устарел / не готов')+' · возраст '+lag.toFixed(2)+' c · '+(d.forming?'последняя свеча формируется':'закрытые свечи');
document.getElementById('context').textContent=JSON.stringify({daily:d.daily,data_quality:{history_gaps:s.history_gaps,contiguous_from:s.contiguous_from,contiguous_bars:s.bars},pairing:c.pairing,bos:s.bos,choch:s.choch,RSI_14:s.geometry?.rsi,RSI_divergence:s.geometry?.rsi_divergence,profile:c.session_profiles,volume:c.volume_percentile,CVD:c.cvd,OI:c.oi_change_percentile,absorption_proxy:c.replenishment_absorption,gamma:d.options,news:lastState?.news?.coverage?.[d.symbol],headlines:(lastState?.news?.headlines||[]).filter(n=>!n.assets||n.assets.includes(d.symbol)||n.assets.includes('ALL')).slice(0,8),events:(lastState?.news?.events||[]).filter(e=>e.assets.includes(d.symbol)||e.assets.includes('ALL')).slice(-12)},null,2);
const inspect=i=>{const b=rows[Math.max(0,Math.min(rows.length-1,i))];inspectedAt=b.at;document.getElementById('crosshair').textContent=new Date(b.at*1000).toISOString()+'  O '+b.open+' H '+b.high+' L '+b.low+' C '+b.close+' V '+b.volume;};
chart.onpointerdown=chart.onmousemove=e=>inspect(Math.floor((e.offsetX-left)/dx));
chart.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();let i=rows.findIndex(b=>b.at===inspectedAt);if(i<0)i=rows.length-1;inspect(e.key==='Home'?0:e.key==='End'?rows.length-1:i+(e.key==='ArrowLeft'?-1:1));};
}
