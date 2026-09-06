'use strict';
// Bounded in-session samples of actual L2. Animation never interpolates market data.
const depthFrames={linear:[],spot:[]};
let cameraFrame=null,depthSignature='',depthVisible=true;
const camera={yaw:-25,pitch:35};
function resetDepth(){depthFrames.linear=[];depthFrames.spot=[];depthSignature='';stopCamera();drawDepth();}
function captureDepth(data){
  for(const venue of ['linear','spot']){
    const book=data.cross_market?.[venue],frames=depthFrames[venue];
    if(!bookFresh(book,data)){frames.length=0;continue;}
    const last=frames.at(-1);if(last&&book.book_at-last.at>data.max_data_age_s)frames.length=0;
    if(frames.length&&book.book_at-frames.at(-1).at<1)continue;
    const levels=venue==='linear'?data.book_levels:data.spot_levels;
    const clean=side=>(levels?.[side]||[]).slice(0,20).filter(p=>Array.isArray(p)&&p.length===2&&p.every(Number.isFinite)&&p[0]>0&&p[1]>0).map(p=>[...p]);
    const bids=clean('bids'),asks=clean('asks');if(!bids.length||!asks.length){frames.length=0;continue;}
    frames.push({at:book.book_at,bids,asks});if(frames.length>24)frames.shift();
  }
}
function stopCamera(){if(cameraFrame!==null)cancelAnimationFrame(cameraFrame);cameraFrame=null;}
function cameraTo(yaw,pitch){
  stopCamera();const reduced=window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  if(!$('motion').checked||reduced){camera.yaw=yaw;camera.pitch=pitch;syncCamera();drawDepth(true);return;}
  const from={...camera},start=performance.now(),duration=$('slowmo').checked?3600:650;
  const step=now=>{if(document.hidden||!depthVisible){cameraFrame=null;return;}const t=Math.max(0,Math.min(1,(now-start)/duration)),ease=t*t*(3-2*t);camera.yaw=from.yaw+(yaw-from.yaw)*ease;camera.pitch=from.pitch+(pitch-from.pitch)*ease;syncCamera();drawDepth(true);cameraFrame=t<1?requestAnimationFrame(step):null;};
  cameraFrame=requestAnimationFrame(step);
}
function syncCamera(){$('camera-yaw').value=camera.yaw;$('camera-pitch').value=camera.pitch;}
function drawDepth(force=false){
  const canvas=$('depth');if(!canvas||document.hidden||!depthVisible)return;
  const venue=$('depth-venue').value||'linear',d=chartData,frames=depthFrames[venue],fresh=!!d&&bookFresh(d.cross_market?.[venue],d),w=Math.max(320,canvas.clientWidth),h=canvas.clientHeight||420;
  $('depth-symbol').textContent=d?.symbol||$('symbol').value||'—';
  const unavailable=d?.cross_market?.[venue]?.status==='instrument_unavailable';
  const message=!fresh?(unavailable?'Точной спотовой пары нет. 3D этого рынка недоступен.':'Нет свежего стакана. Ожидание реальных уровней.'):
    !frames.length?'Свежий статус без доступных уровней. Ожидание L2.':`${venue==='linear'?'Фьючерсы':'Спот'} · ${frames.length}/24 снимков · ${utc(frames.at(-1).at)} · окно ${Math.max(0,frames.at(-1).at-frames[0].at).toFixed(1)} с`;
  $('depth-status').textContent=message;$('depth-status').className=fresh?'':'bad';
  const signature=[venue,d?.symbol,fresh,frames.at(-1)?.at,w,h,camera.yaw,camera.pitch].join(':');if(!force&&signature===depthSignature)return;depthSignature=signature;
  const ratio=Math.min(window.devicePixelRatio||1,2);canvas.width=Math.round(w*ratio);canvas.height=Math.round(h*ratio);const g=canvas.getContext('2d');if(!g)return;g.scale(ratio,ratio);g.clearRect(0,0,w,h);g.font='11px system-ui';
  const yaw=camera.yaw*Math.PI/180,pitch=camera.pitch*Math.PI/180;
  function raw(x,y,z){const rx=x*Math.cos(yaw)-z*Math.sin(yaw),rz=x*Math.sin(yaw)+z*Math.cos(yaw);const ry=y*Math.cos(pitch)-rz*Math.sin(pitch),depth=y*Math.sin(pitch)+rz*Math.cos(pitch),perspective=3.8/(3.8-depth);return [rx*perspective,ry*perspective,depth];}
  // Fit the entire volume and axis labels for every camera angle and viewport.
  const bounds=[];for(const x of [-1.07,1.07])for(const y of [0,.8])for(const z of [-.9,.95])bounds.push(raw(x,y,z));
  const minX=Math.min(...bounds.map(p=>p[0])),maxX=Math.max(...bounds.map(p=>p[0])),minY=Math.min(...bounds.map(p=>p[1])),maxY=Math.max(...bounds.map(p=>p[1]));
  const scale=Math.min((w-70)/(maxX-minX),(h-50)/(maxY-minY)),originX=(w-(maxX-minX)*scale)/2-minX*scale,originY=(h-(maxY-minY)*scale)/2+maxY*scale;
  function project(x,y,z){const p=raw(x,y,z);return [originX+p[0]*scale,originY-p[1]*scale,p[2]];}
  function path(points,fill,stroke){g.beginPath();points.forEach((p,i)=>i?g.lineTo(p[0],p[1]):g.moveTo(p[0],p[1]));if(fill){g.closePath();g.fillStyle=fill;g.fill();}if(stroke){g.strokeStyle=stroke;g.lineWidth=.7;g.stroke();}}
  for(let i=0;i<=8;i++){const k=-.9+i*.225;path([project(k,0,-.65),project(k,0,.65)],null,'#2c3a48');}
  for(let i=0;i<=6;i++){const k=-.65+i*.2167;path([project(-.9,0,k),project(.9,0,k)],null,'#2c3a48');}
  if(!fresh||!frames.length){g.fillStyle='#a4b0bc';g.textAlign='center';g.fillText(unavailable?'Нет точной спотовой пары':'Ожидание реального L2',w/2,h*.38);g.textAlign='left';return;}
  const all=frames.flatMap(f=>[...f.bids,...f.asks]),low=Math.min(...all.map(p=>p[0])),high=Math.max(...all.map(p=>p[0])),span=high-low||high*.001,peak=Math.max(...all.map(p=>p[1]));
  const start=frames[0].at,end=frames.at(-1).at,timeSpan=end-start||1;
  const bars=[];for(const f of frames){const z=frames.length===1?0:-.65+(f.at-start)/timeSpan*1.3;for(const side of ['bids','asks'])for(const [price,qty] of f[side]){const x=-.86+(price-low)/span*1.72,y=qty/peak*.64;bars.push({x,y,z,side,depth:project(x,y/2,z)[2]});}}
  bars.sort((a,b)=>a.depth-b.depth);
  const halfWidth=Math.min(.012,.5/Math.max(frames[0].bids.length,frames[0].asks.length)),halfZ=.012;
  for(const b of bars){const {x,y,z}=b,pts=[project(x-halfWidth,0,z-halfZ),project(x+halfWidth,0,z-halfZ),project(x+halfWidth,0,z+halfZ),project(x-halfWidth,0,z+halfZ),project(x-halfWidth,y,z-halfZ),project(x+halfWidth,y,z-halfZ),project(x+halfWidth,y,z+halfZ),project(x-halfWidth,y,z+halfZ)];const buy=b.side==='bids';
    path([pts[0],pts[1],pts[5],pts[4]],buy?'#527967':'#87565e');path([pts[1],pts[2],pts[6],pts[5]],buy?'#729d88':'#bb7e88');path([pts[2],pts[3],pts[7],pts[6]],buy?'#608d7a':'#9c6772');path([pts[3],pts[0],pts[4],pts[7]],buy?'#6b9581':'#ad737d');path([pts[4],pts[5],pts[6],pts[7]],buy?'#a5d7bf':'#ffc0ad');
  }
  g.fillStyle='#a4b0bc';g.font='10px ui-monospace,monospace';
  const label=(text,x,y,z)=>{const p=project(x,y,z);g.fillText(text,Math.max(6,Math.min(w-text.length*6,p[0])),Math.max(15,Math.min(h-12,p[1])));};
  label(fmt(low),-.9,0,.82);label(fmt(high),.68,0,.82);label('ЦЕНА',0,0,.91);label('РАНЬШЕ',-.98,0,-.68);label('СЕЙЧАС',-.98,0,.62);
  path([project(-.98,0,-.68),project(-.98,.64,-.68)],null,'#8696a6');label('ОБЪЁМ ≤ '+fmt(peak)+' ед.',-.98,.7,-.68);
}
function initDepth(){
  $('depth-venue').onchange=()=>{depthSignature='';drawDepth(true);};$('camera-front').onclick=()=>cameraTo(0,22);$('camera-orbit').onclick=()=>cameraTo(-35,35);$('camera-top').onclick=()=>cameraTo(0,72);$('camera-stop').onclick=stopCamera;
  for(const [id,key] of [['camera-yaw','yaw'],['camera-pitch','pitch']])$(id).oninput=()=>{stopCamera();camera[key]=Number($(id).value);drawDepth(true);};
  $('motion').onchange=()=>{if(!$('motion').checked)stopCamera();};
  const reduced=window.matchMedia?.('(prefers-reduced-motion: reduce)');if(reduced){$('motion').checked=!reduced.matches;reduced.addEventListener?.('change',event=>{if(event.matches){$('motion').checked=false;stopCamera();}});}
  if(typeof IntersectionObserver!=='undefined'){const observer=new IntersectionObserver(entries=>{depthVisible=entries[0].isIntersecting;if(depthVisible)drawDepth(true);else stopCamera();});observer.observe($('depth'));}
  drawDepth();
}
