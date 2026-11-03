export default function(component) {
  const {parentElement,data,setTriggerValue}=component;
  const sessions=window.__assetGridSessions ||= new Map();
  let state=sessions.get(data.owner);
  if(!state){state={queue:[],pending:null,images:new Map(),cards:new Map(),scroll:new Map()};sessions.set(data.owner,state);}
  while(sessions.size>6)sessions.delete(sessions.keys().next().value);
  if(state.pending&&state.pending.token===data.ack){state.queue.shift();state.pending=null;}
  for(const[key,value]of Object.entries(data.images||{}))state.images.set(key,value);
  const prior=parentElement.querySelector('.asset-browser');
  let root=prior;
  if(!root){
    // Streamlit can remount the component while a click is in flight. Keep
    // queued edits and resend the same token; the server deduplicates it.
    state.pending=null;
    root=document.createElement('section');root.className='asset-browser';
    root.innerHTML=`<style>
      *{box-sizing:border-box}.asset-browser{height:min(700px,calc(100dvh - 148px));min-height:220px;display:grid;grid-template-rows:minmax(0,1fr) auto;color:var(--st-text-color,#18212b);font:13px/1.4 system-ui,sans-serif}
      .asset-grid{min-height:0;overflow:auto;overscroll-behavior:contain;padding:2px 6px 8px 2px;display:grid;grid-template-columns:repeat(auto-fill,minmax(min(155px,100%),1fr));grid-auto-rows:170px;align-content:start;gap:8px;scrollbar-gutter:stable}
      .asset-tile{position:relative;min-width:0;border:1px solid #cbd5e1;border-radius:7px;overflow:hidden;background:var(--st-background-color,#fff)}.asset-tile.selected{border-color:#0369a1;box-shadow:inset 0 0 0 1px #0369a1}
      button{font:inherit;cursor:pointer;color:inherit}button:focus-visible,input:focus-visible{outline:2px solid #0369a1;outline-offset:-2px}button:disabled{cursor:default}
      .open{border:0;background:transparent;padding:0;width:100%;display:block;text-align:left}.open:disabled{opacity:1}.picture{height:112px;background:#f1f5f9;display:flex;align-items:center;justify-content:center;position:relative;color:#64748b}.picture img{width:100%;height:100%;object-fit:contain}.placeholder{width:30px;height:30px;fill:none;stroke:currentColor;stroke-width:1.5}.loading{position:absolute;bottom:3px;right:4px;font-size:11px;color:#475569}
      .name{height:34px;padding:3px 6px 0;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere;font-size:12px}.format{padding:2px 6px 5px;color:#475569;font-size:11px}
      .overlay{position:absolute;top:4px;right:4px;display:flex;gap:3px}.icon{width:30px;height:30px;border:1px solid #cbd5e1;background:var(--st-background-color,#fff);border-radius:5px;display:grid;place-items:center}.icon:hover{background:#fee2e2;color:#991b1b}.icon.restore:hover{background:#e0f2fe;color:#075985}.icon svg{width:17px;height:17px;fill:none;stroke:currentColor;stroke-width:1.7;pointer-events:none}
      .check{position:absolute;left:4px;top:4px;background:#fff;border-radius:4px;padding:5px;display:grid;place-items:center}.check input{width:18px;height:18px;accent-color:#0369a1;margin:0}
      .asset-footer{display:flex;gap:6px;justify-content:flex-end;align-items:center;border-top:1px solid #cbd5e1;padding:8px 0 0;flex-wrap:wrap;background:var(--st-background-color,#fff)}.asset-footer button,.asset-footer select{font:inherit;color:inherit;background:var(--st-background-color,#fff);border:1px solid #94a3b8;border-radius:4px;padding:5px 7px}.asset-footer button:disabled{opacity:.4}.total{margin-right:auto;color:var(--st-text-color,#334155);font-size:12px}.empty{padding:20px 8px;grid-column:1/-1;color:var(--st-text-color,#475569)}
      .purge-modal{border:1px solid #94a3b8;border-radius:10px;max-width:min(480px,90vw);color:#18212b;background:#fff;padding:20px}.purge-modal::backdrop{background:#0007}.purge-list{max-height:180px;overflow:auto;padding-left:20px;overflow-wrap:anywhere}.purge-buttons{display:flex;justify-content:flex-end;gap:8px}.purge-buttons button{padding:8px 12px;border:1px solid #94a3b8;border-radius:5px;background:#fff}.purge-buttons .danger{background:#b91c1c;color:#fff;border-color:#b91c1c}
      .asset-browser.is-trash{background:#f3f4f6}.is-trash .asset-tile{background:#f9fafb}.is-trash .picture{background:#e5e7eb}.is-trash .asset-footer{background:#f3f4f6}.is-trash .asset-footer button,.is-trash .asset-footer select,.is-trash .icon{background:#e5e7eb}
      .asset-footer button.primary{min-height:32px;margin-left:4px;padding:6px 12px;font-weight:600;background:#b42336;color:#fff;border-color:#b42336}.asset-footer button.primary:hover:not(:disabled){background:#921b2b}.asset-footer button.primary:disabled{opacity:1;background:#e5e7eb;color:#64748b;border-color:#cbd5e1}
      @media(max-width:600px){.asset-grid{grid-template-columns:repeat(auto-fill,minmax(min(125px,100%),1fr));grid-auto-rows:154px}.picture{height:96px}.asset-footer{gap:4px}.asset-footer button{padding:5px}.total{flex-basis:100%}}
    </style><div class="asset-grid" role="list" aria-label="素材列表"></div><footer class="asset-footer"></footer><dialog class="purge-modal" aria-label="永久删除确认"><h3>永久删除</h3><p class="purge-message"></p><ul class="purge-list"></ul><p>删除后无法恢复。</p><div class="purge-buttons"><button class="cancel">取消</button><button class="danger">确认永久删除</button></div></dialog>`;
    parentElement.replaceChildren(root);state.cards.clear();
  }
  const grid=root.querySelector('.asset-grid'),footer=root.querySelector('.asset-footer'),modal=root.querySelector('.purge-modal');
  root.classList.toggle('is-trash',data.view==='trash');
  window.__assetWarningKeys?.abort();
  const warningKeys=new AbortController();window.__assetWarningKeys=warningKeys;
  function escapeWarning(e){
    if(e.key!=='Escape'||!(modal.open||state.escape))return;
    e.preventDefault();e.stopImmediatePropagation();
    if(e.type==='keydown'&&modal.open&&!state.escape){state.escape=true;modal.close();send('cancel_purge');}
    if(e.type==='keyup')state.escape=false;
  }
  window.addEventListener('keydown',escapeWarning,{capture:true,signal:warningKeys.signal});
  window.addEventListener('keyup',escapeWarning,{capture:true,signal:warningKeys.signal});
  const pageKey=data.view+':'+data.filter+':'+data.page;
  if(state.pageKey!==pageKey){if(state.pageKey)state.scroll.set(state.pageKey,grid.scrollTop);state.pageKey=pageKey;grid.scrollTop=state.scroll.get(pageKey)||0;}
  grid.onscroll=()=>state.scroll.set(pageKey,grid.scrollTop);
  // Modal scroll locks cannot discover scroll containers inside a shadow root.
  // Handle wheel deltas here and never pass them to the dialog/page behind it.
  grid.onwheel=e=>{e.preventDefault();e.stopPropagation();const unit=e.deltaMode===1?18:e.deltaMode===2?grid.clientHeight:1;grid.scrollTop+=e.deltaY*unit;};
  function flush(){if(state.pending||!state.queue.length||!root.isConnected)return;state.pending=state.queue[0];setTriggerValue('event',{...state.pending,received_images:[...state.images.keys()]});}
  function send(action,extra={}){state.queue.push({action,...extra,token:crypto.randomUUID()});flush();}
  const icons={image:'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="2"/><path d="m3 17 6-6 4 4 3-3 5 5"/>',curve:'<path d="M3 18C6 2 17 22 21 4"/><circle cx="3" cy="18" r="2"/><circle cx="21" cy="4" r="2"/>',trajectory:'<path d="M3 6h12a4 4 0 0 1 0 8H9a3 3 0 0 0 0 6h12M3 3v6m15 8 3 3-3 3"/>',delete:'<path d="M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7"/>',restore:'<path d="M3 10a9 9 0 1 1 2 9M3 3v7h7"/>'};
  const svg=(kind,cls='')=>`<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">${icons[kind]||icons.trajectory}</svg>`;
  const live=new Set(data.items.map(i=>i.identity));
  for(const[id,tile]of state.cards)if(!live.has(id)){tile.remove();state.cards.delete(id);}
  if(!data.items.length){grid.replaceChildren();state.cards.clear();const empty=document.createElement('div');empty.className='empty';empty.textContent=data.pending?'正在校验素材，已完成的文件会陆续出现…':'没有符合条件的素材';grid.append(empty);}
  else grid.querySelector('.empty')?.remove();
  const optimistic=new Set(data.selected);
  if(data.multi||data.import_multi)for(const command of state.queue)if(command.action==='select'){if(command.checked)optimistic.add(command.id);else optimistic.delete(command.id);}
  data.items.forEach(item=>{
    let tile=state.cards.get(item.identity);
    if(!tile){tile=document.createElement('article');tile.className='asset-tile';tile.setAttribute('role','listitem');tile.dataset.assetId=item.identity;tile.innerHTML='<button class="open"><div class="picture"></div><div class="name"></div><div class="format"></div></button><div class="overlay"></div><label class="check"><input type="checkbox"></label>';state.cards.set(item.identity,tile);}
    const selected=optimistic.has(item.identity),pick=tile.querySelector('.open'),picture=tile.querySelector('.picture'),check=tile.querySelector('.check'),input=check.querySelector('input'),overlay=tile.querySelector('.overlay');
    tile.classList.toggle('selected',selected);tile.title=item.name;tile.querySelector('.name').textContent=item.name;tile.querySelector('.format').textContent=item.label;
    pick.disabled=data.multi;pick.setAttribute('aria-label',(data.direct_import?'选择轨迹 ':'预览 ')+item.name);
    pick.onclick=()=>{if(data.direct_import){input.checked=!input.checked;input.dispatchEvent(new Event('change',{bubbles:true}));}else send('preview',{id:item.identity,expected:item.fingerprint});};
    const uri=state.images.get(item.thumb_key),signature=uri?item.thumb_key:item.thumb_state;
    if(picture.dataset.signature!==signature){picture.replaceChildren();picture.dataset.signature=signature;if(uri){const img=document.createElement('img');img.src=uri;img.alt=item.name;picture.append(img);}else{picture.innerHTML=svg(item.kind==='image'?'image':item.kind==='curve'||item.kind==='svg'?'curve':'trajectory','placeholder');if(item.thumb_state==='loading'||item.thumb_state==='error'){const text=document.createElement('span');text.className='loading';text.textContent=item.thumb_state==='error'?'预览失败':'加载中';picture.append(text);}}}
    picture.setAttribute('aria-busy',String(item.thumb_state==='loading'));
    check.hidden=!(data.multi||data.import_multi);check.style.display=check.hidden?'none':'grid';input.checked=selected;input.setAttribute('aria-label','选择 '+item.name);input.onchange=()=>send('select',{id:item.identity,checked:input.checked,expected:item.fingerprint});
    overlay.replaceChildren();
    function icon(kind,label,action){const b=document.createElement('button');b.className='icon '+kind;b.innerHTML=svg(kind==='restore'?'restore':'delete');b.title=label;b.setAttribute('aria-label',label+' '+item.name);b.onclick=e=>{e.stopPropagation();send(action,{id:item.identity,expected:item.fingerprint});};overlay.append(b);}
    if(data.manage&&!data.multi){if(data.view==='trash')icon('restore','恢复','restore');icon('delete',data.view==='trash'?'永久删除':'移入回收站',data.view==='trash'?'ask_purge':'recycle');}
    grid.append(tile);
  });
  // append() preserves keyed nodes, restore the same scroll after page/thumbnail updates.
  grid.scrollTop=state.scroll.get(pageKey)||0;
  footer.replaceChildren();const total=document.createElement('span');total.className='total';total.textContent=`${data.total} 项${data.pending?' · 校验中 '+data.pending:''}${data.selected.length?' · 已选 '+data.selected.length:''}`;footer.append(total);
  function nav(label,number,disabled){const b=document.createElement('button');b.textContent=label;b.disabled=disabled;b.onclick=()=>send('page',{page:number});footer.append(b);}
  total.title=data.notice||'';
  if(data.errors?.length){
    const details=document.createElement('details');details.style.position='relative';details.open=!!state.errorsOpen;
    const summary=document.createElement('summary');summary.textContent=`失败 ${data.errors.length} 项`;summary.style.cssText='color:#b91c1c;cursor:pointer';
    const list=document.createElement('ul');list.style.cssText='position:absolute;bottom:24px;right:0;z-index:5;max-height:180px;overflow:auto;width:280px;max-width:70vw;background:#fff;color:#18212b;border:1px solid #94a3b8;border-radius:6px;padding:12px 12px 12px 28px;overflow-wrap:anywhere';
    for(const failure of data.errors){const li=document.createElement('li');li.textContent=failure.name+'：'+failure.error;list.append(li);}
    details.append(summary,list);details.ontoggle=()=>{state.errorsOpen=details.open;};footer.append(details);
  }
  nav('上一页',data.page-1,data.page===1);
  const select=document.createElement('select');select.setAttribute('aria-label','页码');for(let i=1;i<=data.pages;i++){const option=document.createElement('option');option.value=i;option.textContent=`${i} / ${data.pages}`;option.selected=i===data.page;select.append(option);}select.onchange=()=>send('page',{page:Number(select.value)});footer.append(select);
  nav('下一页',data.page+1,data.page===data.pages);
  if(data.batch_action){
    const action=document.createElement('button');action.className='primary';action.textContent=data.batch_action.label;
    action.disabled=!optimistic.size||state.queue.some(command=>command.action===data.batch_action.name);
    action.onclick=()=>{action.disabled=true;send(data.batch_action.name);};footer.append(action);
  }
  if(data.confirm){
    root.querySelector('.purge-message').textContent=`确认永久删除 ${data.confirm.items.length} 个文件？`;
    const list=root.querySelector('.purge-list');list.replaceChildren();for(const item of data.confirm.items){const li=document.createElement('li');li.textContent=item.name;list.append(li);}
    root.querySelector('.cancel').onclick=()=>{modal.close();send('cancel_purge');};root.querySelector('.danger').onclick=()=>{modal.close();send('confirm_purge',{confirmation:data.confirm.token});};
    modal.oncancel=e=>{e.preventDefault();e.stopPropagation();modal.close();send('cancel_purge');};
    modal.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();modal.close();send('cancel_purge');}};
    if(!modal.open)modal.showModal();
  }else if(modal.open)modal.close();
  if(state.timer)clearTimeout(state.timer);
  const needsImages=data.items.some(item=>item.thumb_state==='ready'&&!state.images.has(item.thumb_key));
  if((data.busy||needsImages)&&!modal.open)state.timer=setTimeout(()=>{const focus=document.activeElement;if(focus?.matches('input[type="text"],input:not([type]),textarea')||state.pending){state.timer=setTimeout(()=>send('poll'),700);return;}send('poll');},350);
  queueMicrotask(flush);
  // Keep keyed DOM through component renders; only disconnected trees are rebuilt.
}
