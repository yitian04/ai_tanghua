export function itemOutside(item,width,height) {
  const angle=item.rotation_deg*Math.PI/180,cos=Math.cos(angle),sin=Math.sin(angle),epsilon=1e-7;
  return item.paths.some(path=>path.some(([x,y])=>{
    const px=item.x_mm+item.scale*(x*cos-y*sin),py=item.y_mm+item.scale*(x*sin+y*cos);
    return px < -epsilon || py < -epsilon || px > width+epsilon || py > height+epsilon;
  }));
}

export default function(component) {
  const {data,parentElement,setTriggerValue}=component, ns='http://www.w3.org/2000/svg';
  const sessions=window.__tanghuaLayoutSessions ||= new Map(), key=data.editor_id;
  let session=sessions.get(key);
  if(!session||session.editorId!==data.editor_id){session={editorId:data.editor_id,queue:[],pending:null};sessions.set(key,session);}
  for(const[id,old]of sessions){if(sessions.size<=16)break;if(id!==key&&!old.mount){old.host=null;sessions.delete(id);}}
  if(session.pending&&data.ack===session.pending.token){session.queue.shift();session.pending=null;}
  const mount={};session.mount=mount;
  const host=session.host||document.createElement('section');session.host=host;host.tabIndex=0;host.setAttribute('aria-label','自由布局编辑器');
  if(!host.querySelector('.workspace'))host.innerHTML=`<style>
    *{box-sizing:border-box}button{font:inherit;color:inherit;cursor:pointer;background:transparent;border:1px solid #cbd5e1;border-radius:5px;padding:5px 9px}button:hover{background:#e2e8f0}button:focus-visible,[tabindex]:focus-visible{outline:2px solid #0369a1;outline-offset:2px}button:disabled{opacity:.45;cursor:default}
    .toolbar{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}.workspace{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-start}.objects{flex:1 1 170px;min-width:0;max-height:400px;overflow:auto;position:relative;overflow-anchor:none;overscroll-behavior:contain}.surface{flex:3 1 280px;min-width:0}
    .row{display:flex;align-items:center;gap:4px;border-bottom:1px solid #cbd5e1;padding:5px 2px;color:var(--st-text-color,#18212b)}.row.active{background:#e0f2fe;color:#0c4a6e}.row.drop-before{border-top:3px solid #0369a1}.row.drop-after{border-bottom:3px solid #0369a1}
    .row.outside,.row.active.outside{color:#b91c1c;background:#fef2f2}.row.outside .pick{color:#b91c1c}.row.outside .grip{color:#b91c1c}
    .pick{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:left;border:0;padding:6px 2px}.grip{cursor:grab;user-select:none;padding:6px 3px}.remove{border:0;color:#991b1b}.hint{font-size:12px;line-height:1.6;margin:0 0 8px;color:var(--st-text-color,#334155)}
  </style><div class="toolbar"></div><div class="workspace"><div class="objects" role="list" aria-label="对象管理，按从上到下的顺序绘制"></div><div class="surface"><p class="hint">拖动移动 · 角点缩放 · 角外旋转（Shift 吸附 15°）</p></div></div><p class="hint status" role="status"></p>`;
  if(host.parentElement!==parentElement)parentElement.replaceChildren(host);
  const objects=host.querySelector('.objects'),toolbar=host.querySelector('.toolbar'),status=host.querySelector('.status'),svg=host.querySelector('svg[role="application"]')||document.createElementNS(ns,'svg');
  svg.setAttribute('viewBox',`0 0 ${data.width} ${data.height}`);svg.tabIndex=0;svg.setAttribute('role','application');svg.setAttribute('aria-label','轨迹排布画布，使用旁边的数字输入也可修改位置与大小');
  svg.style.cssText=`width:100%;max-width:${560*data.width/data.height}px;height:auto;aspect-ratio:${data.width}/${data.height};background:white;border:1px solid #64748b;touch-action:none;display:block`;if(!svg.parentElement)host.querySelector('.surface').append(svg);
  let items=structuredClone(data.items),selected=data.selected,gesture=null,dragged=null;const controller=new AbortController();
  window.__tanghuaLayoutController?.abort();window.__tanghuaLayoutController=controller;
  function captureScroll(){
    const top=objects.scrollTop,rows=[...objects.querySelectorAll('.row')],anchor=rows.find(row=>row.offsetTop+row.offsetHeight>top);
    return {top,pinned:objects.scrollHeight-objects.clientHeight-top<=2,anchor:anchor?.dataset.objectId,gap:anchor?anchor.offsetTop-top:0};
  }
  objects.onscroll=()=>{if(host.isConnected)session.listScroll=captureScroll();};
  // The modal's scroll lock cannot discover this scroller through a shadow root.
  objects.onwheel=e=>{e.preventDefault();e.stopPropagation();objects.scrollTop+=e.deltaY*(e.deltaMode===1?18:e.deltaMode===2?objects.clientHeight:1);};
  function flush(){if(session.pending||!session.queue.length||!host.isConnected)return;session.pending=session.queue[0];setTriggerValue('edit',{...session.pending,revision:data.revision});}
  function send(action,details={}){session.queue.push({action,...details,token:crypto.randomUUID()});status.textContent='正在同步排布…';flush();}
  function button(label,action,disabled=false){const b=document.createElement('button');b.textContent=label;b.disabled=disabled;b.onclick=()=>send(action);toolbar.append(b);}
  toolbar.replaceChildren();button('撤回','undo',!data.can_undo);button('重做','redo',!data.can_redo);button('复制','copy',!selected);button('粘贴','paste',!data.can_paste);button('删除','delete',!selected);
  function renderObjects(){
    const scroll=session.listScroll||{top:0,pinned:false},existing=new Map([...objects.querySelectorAll('.row')].map(row=>[row.dataset.objectId,row])),live=new Set(items.map(item=>item.id));
    objects.querySelector('.empty')?.remove();
    for(const[id,row]of existing)if(!live.has(id))row.remove();
    if(!items.length){const empty=document.createElement('p');empty.className='empty';empty.textContent='暂无对象，请先导入轨迹。';objects.append(empty);}
    items.forEach((item,index)=>{
      const row=existing.get(item.id)||document.createElement('div');row.className='row'+(item.id===selected?' active':'');row.dataset.objectId=item.id;row.setAttribute('role','listitem');
      if(!row.children.length)row.innerHTML='<span class="grip" draggable="true">⠿</span><button class="pick"></button><button class="remove">×</button>';
      const grip=row.querySelector('.grip');grip.title='拖动调整绘制顺序';grip.setAttribute('aria-label',`拖动排序 ${item.name}`);
      const pick=row.querySelector('.pick');pick.textContent=`${index+1}. ${item.name}`;pick.title=item.name;pick.setAttribute('aria-pressed',String(item.id===selected));pick.onclick=()=>{selected=item.id;draw();renderObjects();send('select',{id:item.id});};
      const remove=row.querySelector('.remove');remove.title='删除对象';remove.setAttribute('aria-label',`删除 ${item.name}`);remove.onclick=()=>send('delete',{id:item.id});
      markOutside(row,item);
      grip.ondragstart=e=>{dragged=item.id;e.dataTransfer.setData('text/plain',item.id);e.dataTransfer.effectAllowed='move';};
      grip.ondragend=()=>{dragged=null;host.querySelectorAll('.row').forEach(r=>r.classList.remove('drop-before','drop-after'));};
      row.ondragover=e=>{e.preventDefault();const after=e.clientY>row.getBoundingClientRect().top+row.getBoundingClientRect().height/2;row.classList.toggle('drop-after',after);row.classList.toggle('drop-before',!after);};
      row.ondragleave=()=>row.classList.remove('drop-before','drop-after');
      row.ondrop=e=>{e.preventDefault();const id=dragged||e.dataTransfer.getData('text/plain');if(id!==item.id&&items.some(i=>i.id===id)){const order=items.map(i=>i.id).filter(i=>i!==id),after=e.clientY>row.getBoundingClientRect().top+row.getBoundingClientRect().height/2;order.splice(order.indexOf(item.id)+(after?1:0),0,id);send('reorder',{order});}row.classList.remove('drop-before','drop-after');dragged=null;};
      if(objects.children[index]!==row)objects.insertBefore(row,objects.children[index]||null);
    });
    const anchor=[...objects.querySelectorAll('.row')].find(row=>row.dataset.objectId===scroll.anchor);
    objects.scrollTop=scroll.pinned?objects.scrollHeight:anchor?anchor.offsetTop-scroll.gap:scroll.top;
    // Follow newly added objects, but do not move the viewport on selection/edit.
    if(session.knownIds&&selected&&!session.knownIds.has(selected)){
      const added=[...objects.querySelectorAll('.row')].find(row=>row.dataset.objectId===selected);
      if(added){if(added.offsetTop<objects.scrollTop)objects.scrollTop=added.offsetTop;else if(added.offsetTop+added.offsetHeight>objects.scrollTop+objects.clientHeight)objects.scrollTop=added.offsetTop+added.offsetHeight-objects.clientHeight;}
    }
    session.knownIds=live;session.listScroll=captureScroll();
  }
  function markOutside(row,item,bad=itemOutside(item,data.width,data.height)){row.classList.toggle('outside',bad);row.title=bad?'超出画布，请调整位置或大小':item.name;row.dataset.outside=String(bad);}
  function el(tag,attrs,parent=svg){const n=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,String(v));parent.append(n);return n;}
  const cursorIcon='<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><path d="M18 8A7 7 0 1 0 19 15M18 3v6h-6" fill="none" stroke="white" stroke-width="4"/><path d="M18 8A7 7 0 1 0 19 15M18 3v6h-6" fill="none" stroke="#0c4a6e" stroke-width="2"/></svg>';
  const rotateCursor=`url("data:image/svg+xml,${encodeURIComponent(cursorIcon)}") 12 12, crosshair`;
  function draw(){
    svg.replaceChildren();const defs=el('defs',{}),pattern=el('pattern',{id:'grid',width:10,height:10,patternUnits:'userSpaceOnUse'},defs);
    el('path',{d:'M10 0 L0 0 0 10',fill:'none',stroke:'#e2e8f0','stroke-width':.3},pattern);el('rect',{width:data.width,height:data.height,fill:'url(#grid)'});
    const travelLayer=el('g',{'pointer-events':'none'}),layers=[],objectRows=new Map([...objects.querySelectorAll('.row')].map(row=>[row.dataset.objectId,row]));let previousEnd=null;
    for(const item of items){
      const active=item.id===selected,a=item.rotation_deg*Math.PI/180,globalPoint=([x,y])=>[item.x_mm+item.scale*(x*Math.cos(a)-y*Math.sin(a)),item.y_mm+item.scale*(x*Math.sin(a)+y*Math.cos(a))];
      const bad=itemOutside(item,data.width,data.height);
      const row=objectRows.get(item.id);if(row)markOutside(row,item,bad);
      const group=el('g',{'data-id':item.id,transform:`translate(${item.x_mm} ${item.y_mm}) rotate(${item.rotation_deg}) scale(${item.scale})`});layers.push([group,active]);
      el('rect',{x:-item.width/2,y:-item.height/2,width:Math.max(item.width,1),height:Math.max(item.height,1),fill:'transparent',stroke:active?'#0369a1':'none','stroke-width':.6/item.scale,'data-id':item.id,cursor:'move'},group);
      for(const path of item.paths){const start=globalPoint(path[0]);if(data.show_travel&&previousEnd)el('line',{x1:previousEnd[0],y1:previousEnd[1],x2:start[0],y2:start[1],stroke:'#64748b','stroke-width':.3,'stroke-dasharray':'1 1'},travelLayer);el('polyline',{points:path.map(p=>p.join(',')).join(' '),fill:'none',stroke:bad?'#b91c1c':active?'#0369a1':'#334155','stroke-width':.65/item.scale,'stroke-linecap':'round','stroke-linejoin':'round','pointer-events':'none'},group);previousEnd=globalPoint(path.at(-1));}
      if(active)for(const[x,y]of[[-1,-1],[1,-1],[-1,1],[1,1]]){const size=3/item.scale,outer=el('circle',{cx:x*(item.width/2+5/item.scale),cy:y*(item.height/2+5/item.scale),r:4/item.scale,fill:'transparent','data-id':item.id,'data-handle':'rotate'},group);outer.style.cursor=rotateCursor;outer.appendChild(document.createElementNS(ns,'title')).textContent='拖动旋转；Shift 吸附 15°';el('rect',{x:x*item.width/2-size/2,y:y*item.height/2-size/2,width:size,height:size,fill:'#0369a1',stroke:'#fff','stroke-width':.4/item.scale,'data-id':item.id,'data-handle':'scale',cursor:x===y?'nwse-resize':'nesw-resize'},group);}
    }
    for(const[group,active]of layers)if(active)svg.append(group);
  }
  function position(e){return new DOMPoint(e.clientX,e.clientY).matrixTransform(svg.getScreenCTM().inverse());}
  svg.onpointerdown=e=>{const id=e.target.getAttribute('data-id');if(!id||session.pending)return;selected=id;svg.focus({preventScroll:true});const item=items.find(i=>i.id===id),p=position(e);gesture={id,start:p,x:item.x_mm,y:item.y_mm,scale:item.scale,rotation:item.rotation_deg,angle:Math.atan2(p.y-item.y_mm,p.x-item.x_mm),mode:e.target.getAttribute('data-handle'),radius:Math.hypot(p.x-item.x_mm,p.y-item.y_mm)};svg.setPointerCapture(e.pointerId);draw();renderObjects();e.preventDefault();};
  svg.onpointermove=e=>{if(!gesture)return;const item=items.find(i=>i.id===gesture.id),p=position(e);if(gesture.mode==='scale')item.scale=Math.max(.01,gesture.scale*Math.hypot(p.x-item.x_mm,p.y-item.y_mm)/Math.max(.001,gesture.radius));else if(gesture.mode==='rotate'){const a=Math.atan2(p.y-item.y_mm,p.x-item.x_mm)-gesture.angle;item.rotation_deg=gesture.rotation+Math.atan2(Math.sin(a),Math.cos(a))*180/Math.PI;if(e.shiftKey)item.rotation_deg=Math.round(item.rotation_deg/15)*15;}else{item.x_mm=gesture.x+p.x-gesture.start.x;item.y_mm=gesture.y+p.y-gesture.start.y;}draw();};
  svg.onpointerup=()=>{if(!gesture)return;const item=items.find(i=>i.id===gesture.id);gesture=null;send('transform',{id:item.id,x_mm:item.x_mm,y_mm:item.y_mm,scale:item.scale,rotation_deg:item.rotation_deg});};
  svg.onpointercancel=()=>{if(gesture){const item=items.find(i=>i.id===gesture.id);Object.assign(item,{x_mm:gesture.x,y_mm:gesture.y,scale:gesture.scale,rotation_deg:gesture.rotation});gesture=null;draw();}};
  document.addEventListener('keydown',e=>{
    if(!host.isConnected)return;
    // A global asset dialog must not send Delete/undo/copy to the layout behind it.
    if(document.querySelector('[role="dialog"],[aria-modal="true"]'))return;
    if(e.defaultPrevented||e.composedPath().some(n=>n instanceof HTMLElement&&(n.matches('input,textarea,select,[role="textbox"],[role="combobox"]')||n.isContentEditable)))return;
    const mod=e.ctrlKey||e.metaKey,k=e.key.toLowerCase();let action=null;
    if(mod&&k==='z')action=e.shiftKey?'redo':'undo';else if(mod&&k==='y')action='redo';else if(mod&&k==='c')action='copy';else if(mod&&k==='v')action='paste';else if(e.key==='Delete'&&!mod)action='delete';
    if(action){e.preventDefault();send(action);return;}
    if(!e.composedPath().includes(host))return;const delta={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[e.key];if(delta&&selected&&!mod){e.preventDefault();const step=e.shiftKey?10:1;send('move',{dx:delta[0]*step,dy:delta[1]*step});}
  },{signal:controller.signal});
  renderObjects();draw();status.textContent=session.queue.length?'正在同步排布…':'Ctrl+Z 撤回 · Ctrl+Shift+Z 重做 · Ctrl+C / V 复制粘贴 · Delete 删除';queueMicrotask(flush);
  return ()=>{controller.abort();queueMicrotask(()=>{if(session.mount===mount){host.remove();session.host=null;session.mount=null;}});};
}
