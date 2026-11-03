// Pure cursor logic is exported for deterministic tests, without a browser.
export class Playback {
  constructor(data) { this.data=data;this.speed=1;this.playing=false;this.reset(); }
  reset() { this.index=0;this.fraction=0;this.time=0;this.ended=false; }
  play() { if(this.ended)this.reset();this.playing=true;this.advance(0); }
  pause() { this.playing=false; }
  restart() { const playing=this.playing;this.reset();this.playing=playing;if(playing)this.advance(0); }
  setSpeed(value) { if(![.25,.5,1,2,4,8].includes(value))return false;this.speed=value;return true; }
  seekStroke(number) {
    if(!Number.isInteger(number)||number<1||number>this.data.strokes.length)return false;
    this.index=this.data.strokes[number-1].start;this.time=this.data.times[this.index];this.fraction=0;this.ended=false;
    return true;
  }
  advance(seconds) {
    if(!this.playing)return;
    const {times,duration_s}=this.data;
    const target=Math.min(duration_s,this.time+Math.max(0,Number.isFinite(seconds)?seconds:0)*this.speed);
    let low=this.index,high=times.length;
    while(low<high){const mid=(low+high)>>>1;if(times[mid]<=target)low=mid+1;else high=mid;}
    this.index=Math.max(this.index,low-1);this.time=target;
    if(this.index===times.length-1){this.fraction=0;this.playing=false;this.ended=true;}
    else this.fraction=(target-times[this.index])/(times[this.index+1]-times[this.index]);
  }
  position() {
    const a=this.data.points[this.index],b=this.data.points[this.index+1]||a,f=this.fraction;
    return {x:a[0]+(b[0]-a[0])*f,y:a[1]+(b[1]-a[1])*f,z:a[2]+(b[2]-a[2])*f,
      drawing:(f>0?b:a)[3],stroke:this.data.point_strokes[this.index+(f>0?1:0)]};
  }
}

export default function(component) {
  const {parentElement,data}=component;
  const sessions=window.__trajectoryPlayerSessions ||= new Map();
  let session=sessions.get(data.instance);
  if(!session||session.fingerprint!==data.fingerprint){
    session?.runtime?.dispose(false);
    session={fingerprint:data.fingerprint,engine:new Playback(data),travel:true,jump:'1',runtime:null};
    sessions.set(data.instance,session);
  }
  session.runtime?.dispose(true);
  // Retain only a bounded number of inactive preview cursors.
  for(const [key,value]of sessions){if(sessions.size<=16)break;if(key!==data.instance&&!value.runtime)sessions.delete(key);}
  const engine=session.engine;
  const root=document.createElement('section');root.className='trajectory-player';root.setAttribute('role','region');root.setAttribute('aria-label','轨迹执行模拟器');root.dataset.fingerprint=data.fingerprint;
  root.innerHTML=`<style>
    *{box-sizing:border-box}.trajectory-player{color:var(--st-text-color,#18212b);font:13px/1.5 system-ui,sans-serif;min-width:0}
    .stage{height:clamp(220px,34vw,360px);position:relative;background:#f8fafc;border:1px solid #cbd5e1;border-radius:6px;overflow:hidden}.stage canvas{display:block;width:100%;height:100%}.axes{position:absolute;left:10px;bottom:7px;color:#475569;font-size:11px;pointer-events:none}
    .status-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:8px 0 5px;font-variant-numeric:tabular-nums}.phase{font-weight:600}.swatch{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px}.position,.time,.note{color:#475569}.time{margin-left:auto}.progress{width:100%;height:4px;display:block;accent-color:#0369a1;border:0;border-radius:2px;overflow:hidden}.progress::-webkit-progress-bar{background:#e2e8f0}.progress::-webkit-progress-value{background:#0369a1}
    .controls{display:flex;align-items:center;flex-wrap:wrap;gap:6px;margin-top:9px}.controls button,.controls input,.controls select{font:inherit;line-height:1.3;color:var(--st-text-color,#18212b);background:var(--st-background-color,#fff);border:1px solid #94a3b8;border-radius:5px;min-height:33px;padding:5px 9px}.controls button{cursor:pointer;white-space:nowrap}.controls button:hover:not(:disabled){background:#e2e8f0}.controls button:disabled{opacity:.45;cursor:default}.controls .play{background:#075985;color:#fff;border-color:#075985;min-width:56px}.controls .play:hover{background:#0c4a6e}.controls input{width:64px;padding:5px}.controls input[aria-invalid=true]{border-color:#b91c1c}.controls label{display:flex;align-items:center;gap:5px;white-space:nowrap}.controls label.rate{margin-left:auto}.controls :focus-visible,.travel:focus-visible{outline:2px solid #0369a1;outline-offset:2px}.travel-label{display:flex;gap:5px;align-items:center;white-space:nowrap}.travel{accent-color:#0369a1}
    .controls button.play:hover:not(:disabled){background:#0c4a6e}.controls input.travel{width:16px;height:16px;min-height:16px;padding:0;margin:0}.controls .travel-label{min-height:33px}.seek-group{display:flex;align-items:center;gap:5px}
    .note{font-size:11px;margin:7px 0 0}.warning,.error{color:#9a3412}.error{font-size:12px;min-height:0;margin:4px 0 0}.error:empty{display:none}
    @media(max-width:480px){.stage{height:240px}.time{margin-left:0}.controls{gap:5px}.controls button{padding:5px 7px}.controls label.rate{margin-left:0}.position{font-size:12px}}
  </style>
  <div class="stage"><canvas role="img" aria-label="二维轨迹：工具头蓝色表示出料，橙色表示收料"></canvas><span class="axes">X → / Y ↓ · mm</span></div>
  <div class="status-row"><span class="phase"></span><span class="stroke"></span><span class="position"></span><span class="time"></span></div>
  <progress class="progress" max="1" value="0" aria-label="轨迹播放进度"></progress>
  <div class="controls"><button class="play">播放</button><button class="restart">重新开始</button><button class="previous">上一笔</button><button class="next">下一笔</button><span class="seek-group"><label>第 <input class="jump" type="number" min="1" step="1" aria-label="跳转笔号"> 笔</label><button class="seek">跳转</button></span><label class="rate">倍速 <select aria-label="播放倍速"><option value="0.25">0.25×</option><option value="0.5">0.5×</option><option value="1">1×</option><option value="2">2×</option><option value="4">4×</option><option value="8">8×</option></select></label><label class="travel-label"><input class="travel" type="checkbox">空走</label></div>
  <p class="error" role="status"></p><p class="note">名义时间按轨迹速度估算，不含机械臂加减速等额外动作。</p><p class="note warning"></p>`;
  parentElement.replaceChildren(root);
  const find=selector=>root.querySelector(selector),canvas=find('canvas'),ctx=canvas.getContext('2d');
  const reference=document.createElement('canvas'),completed=document.createElement('canvas'),ref=reference.getContext('2d'),ink=completed.getContext('2d');
  const play=find('.play'),previous=find('.previous'),next=find('.next'),jump=find('.jump'),seek=find('.seek'),rate=find('select'),travel=find('.travel'),error=find('.error');
  jump.max=data.strokes.length;jump.value=session.jump;rate.value=engine.speed;travel.checked=session.travel;find('.warning').textContent=data.warning||'';
  let frame=null,last=performance.now(),disposed=false,width=0,height=0,dpr=1,scale=1,centerX=0,centerY=0,rendered=-1;
  let resizeObserver,intersectionObserver;
  const controller=new AbortController();
  const runtime={frameCount:0,dispose(keepPlaying){if(disposed)return;disposed=true;if(frame!==null)cancelAnimationFrame(frame);frame=null;resizeObserver?.disconnect();intersectionObserver?.disconnect();controller.abort();if(!keepPlaying)engine.pause();if(session.runtime===runtime)session.runtime=null;}};
  session.runtime=runtime;
  const xy=p=>[width/2+(p[0]-centerX)*scale,height/2+(p[1]-centerY)*scale];
  function segment(context,a,b,color,dashed=false) {
    const[x,y]=xy(a),[u,v]=xy(b);context.strokeStyle=color;context.fillStyle=color;context.lineWidth=dashed?1:1.65;context.lineCap='round';context.setLineDash(dashed?[4,4]:[]);
    if(x===u&&y===v){if(!dashed){context.beginPath();context.arc(x,y,1.1,0,Math.PI*2);context.fill();}return;}
    context.beginPath();context.moveTo(x,y);context.lineTo(u,v);context.stroke();
  }
  function referenceLayer(){
    ref.clearRect(0,0,width,height);
    if(data.points[0][3])segment(ref,data.points[0],data.points[0],'#cbd5e1');
    for(let i=1;i<data.points.length;i++)if(data.points[i][3]||session.travel)segment(ref,data.points[i-1],data.points[i],data.points[i][3]?'#cbd5e1':'#94a3b8',!data.points[i][3]);
  }
  function completedLayer(){
    if(rendered>engine.index||rendered<0){ink.clearRect(0,0,width,height);rendered=0;if(data.points[0][3])segment(ink,data.points[0],data.points[0],'#0369a1');}
    for(let i=rendered+1;i<=engine.index;i++)if(data.points[i][3])segment(ink,data.points[i-1],data.points[i],'#0369a1');
    rendered=engine.index;
  }
  function timeLabel(value){const minutes=Math.floor(value/60);return `${minutes}:${(value-minutes*60).toFixed(1).padStart(4,'0')}`;}
  function update(){
    if(disposed)return;
    const p=engine.position(),color=p.drawing?'#0369a1':'#c2410c';
    completedLayer();ctx.clearRect(0,0,width,height);ctx.drawImage(reference,0,0,width,height);ctx.drawImage(completed,0,0,width,height);
    if(engine.fraction>0){const target=data.points[engine.index+1];if(target[3]||session.travel)segment(ctx,data.points[engine.index],[p.x,p.y,p.z],target[3]?'#0369a1':'#64748b',!target[3]);}
    const[x,y]=xy([p.x,p.y]);ctx.setLineDash([]);ctx.beginPath();ctx.arc(x,y,5.5,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();ctx.lineWidth=2.5;ctx.strokeStyle='#fff';ctx.stroke();
    play.textContent=engine.playing?'暂停':'播放';previous.disabled=p.stroke<=1;next.disabled=p.stroke>=data.strokes.length;
    const phase=find('.phase'),phaseKey=String(p.drawing)+String(engine.ended);
    if(phase.dataset.key!==phaseKey){phase.dataset.key=phaseKey;phase.replaceChildren();const swatch=document.createElement('span');swatch.className='swatch';swatch.style.background=color;phase.append(swatch,document.createTextNode((engine.ended?'已完成 · ':'')+(p.drawing?'出料':'收料')));}
    find('.stroke').textContent=`第 ${p.stroke} / ${data.strokes.length} 笔`;
    find('.position').textContent=`Z ${p.z.toFixed(2)} mm`;
    find('.time').textContent=`${timeLabel(engine.time)} / ${timeLabel(data.duration_s)}`;
    find('progress').value=data.duration_s>0?engine.time/data.duration_s:(engine.ended?1:0);
    const number=Number(jump.value);seek.disabled=jump.value===''||!Number.isInteger(number)||number<1||number>data.strokes.length;
    jump.setAttribute('aria-invalid',String(seek.disabled));
    Object.assign(root.dataset,{playing:String(engine.playing),pointIndex:String(engine.index),fraction:String(engine.fraction),time:String(engine.time),speed:String(engine.speed),x:String(p.x),y:String(p.y),z:String(p.z),drawing:String(p.drawing),stroke:String(p.stroke),ended:String(engine.ended)});
  }
  function resize(){
    if(disposed)return;const rect=find('.stage').getBoundingClientRect();width=Math.max(1,rect.width-2);height=Math.max(1,rect.height-2);dpr=Math.min(window.devicePixelRatio||1,2);
    for(const layer of[canvas,reference,completed]){layer.width=Math.ceil(width*dpr);layer.height=Math.ceil(height*dpr);layer.getContext('2d').setTransform(dpr,0,0,dpr,0,0);}
    const[x0,y0,x1,y1]=data.bounds;scale=Math.min(Math.max(1,width-48)/Math.max(x1-x0,1),Math.max(1,height-48)/Math.max(y1-y0,1));centerX=x0/2+x1/2;centerY=y0/2+y1/2;
    rendered=-1;referenceLayer();update();
  }
  function stopFrame(){if(frame!==null)cancelAnimationFrame(frame);frame=null;}
  function settle(){const now=performance.now();engine.advance((now-last)/1000);last=now;}
  function schedule(){if(engine.playing&&!disposed&&frame===null)frame=requestAnimationFrame(tick);}
  function tick(now){frame=null;if(disposed)return;if(document.hidden||!root.isConnected){engine.pause();update();return;}if(now-last<1000/60-.75){schedule();return;}runtime.frameCount++;engine.advance((now-last)/1000);last=now;update();schedule();}
  function action(change){settle();stopFrame();error.textContent='';change();last=performance.now();update();schedule();}
  play.onclick=()=>action(()=>engine.playing?engine.pause():engine.play());
  find('.restart').onclick=()=>action(()=>{engine.restart();rendered=-1;});
  previous.onclick=()=>action(()=>{engine.seekStroke(engine.position().stroke-1);rendered=-1;});
  next.onclick=()=>action(()=>{engine.seekStroke(engine.position().stroke+1);rendered=-1;});
  seek.onclick=()=>action(()=>{if(!engine.seekStroke(Number(jump.value)))error.textContent=`请输入 1–${data.strokes.length} 的整数笔号。`;else rendered=-1;});
  jump.oninput=()=>{session.jump=jump.value;update();};
  jump.onkeydown=e=>{if(e.key==='Enter'&&!seek.disabled){e.preventDefault();seek.click();}};
  rate.onchange=()=>action(()=>engine.setSpeed(Number(rate.value)));
  travel.onchange=()=>{session.travel=travel.checked;referenceLayer();update();};
  function autoPause(){if(disposed)return;engine.pause();stopFrame();last=performance.now();update();}
  document.addEventListener('visibilitychange',()=>{if(document.hidden)autoPause();},{signal:controller.signal});
  resizeObserver=new ResizeObserver(resize);resizeObserver.observe(find('.stage'));
  intersectionObserver=new IntersectionObserver(entries=>{if(entries.some(entry=>!entry.isIntersecting))autoPause();});intersectionObserver.observe(root);
  resize();last=performance.now();schedule();
  return ()=>{
    runtime.dispose(true);
    // Synchronous replacement installs a new runtime; actual unmount pauses it.
    queueMicrotask(()=>{if(!session.runtime)engine.pause();});
  };
}
