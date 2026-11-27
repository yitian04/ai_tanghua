export default function({parentElement,data}) {
  const root=document.createElement('div');
  root.innerHTML=`<style>
  .iv-thumb{display:block;width:100%;max-height:520px;object-fit:contain;cursor:zoom-in;background:white;border:0}
  .iv-thumb:focus-visible,.iv-tool:focus-visible{outline:3px solid #38bdf8;outline-offset:3px}
  .iv-modal{position:fixed;inset:0;width:100vw;height:100dvh;max-width:none;max-height:none;margin:0;padding:0;border:0;background:#fff;overflow:hidden}
  .iv-modal::backdrop{background:#fff}.iv-stage{position:absolute;inset:0;overflow:hidden;touch-action:none;cursor:grab;background:#fff}
  .iv-stage:active{cursor:grabbing}.iv-large{position:absolute;left:50%;top:50%;max-width:none;transform-origin:center;pointer-events:none;user-select:none}
  .iv-tools{position:absolute;right:18px;top:18px;display:flex;gap:6px;padding:6px;border:1px solid #ffffff24;border-radius:9px;background:#242a33;z-index:2}
  .iv-tool{width:38px;height:38px;display:grid;place-items:center;background:transparent;border:0;border-radius:5px;color:white;cursor:pointer;text-decoration:none}
  .iv-tool:hover{background:#ffffff20}.iv-tool svg{width:21px;height:21px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
  </style><img class="iv-thumb" tabindex="0" role="button" aria-label="放大预览"/><dialog class="iv-modal" aria-label="图像预览"><div class="iv-stage"><img class="iv-large" alt="" draggable="false"/></div><div class="iv-tools"></div></dialog>`;
  const thumb=root.querySelector('.iv-thumb'),modal=root.querySelector('dialog'),stage=root.querySelector('.iv-stage'),large=root.querySelector('.iv-large'),tools=root.querySelector('.iv-tools');
  thumb.src=large.src=data.src;parentElement.replaceChildren(root);
  let zoom=1,x=0,y=0,base=1,pointer=null,origin=null;
  const render=()=>{large.style.width=large.naturalWidth*base+'px';large.style.height=large.naturalHeight*base+'px';large.style.transform=`translate(calc(-50% + ${x}px),calc(-50% + ${y}px)) scale(${zoom})`;};
  const fit=()=>{base=Math.min(stage.clientWidth/large.naturalWidth,stage.clientHeight/large.naturalHeight)*.92;zoom=1;x=y=0;render();};
  const scale=(factor,px=0,py=0)=>{const next=Math.min(32,Math.max(.1,zoom*factor)),ratio=next/zoom;x=px-(px-x)*ratio;y=py-(py-y)*ratio;zoom=next;render();};
  function button(label,path,action){const b=document.createElement('button');b.className='iv-tool';b.setAttribute('aria-label',label);b.innerHTML=`<svg viewBox="0 0 24 24">${path}</svg>`;b.onclick=action;tools.append(b);return b;}
  button('缩小','<path d="M5 12h14"/>',()=>scale(1/1.3));
  button('放大','<path d="M5 12h14M12 5v14"/>',()=>scale(1.3));
  button('适应窗口','<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>',fit);
  const download=document.createElement('a');download.className='iv-tool';download.setAttribute('aria-label','下载');download.href=data.src;download.download=data.filename;download.innerHTML='<svg viewBox="0 0 24 24"><path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/></svg>';tools.append(download);
  button('关闭','<path d="m6 6 12 12M18 6 6 18"/>',()=>modal.close());
  function open(){modal.showModal();if(large.complete)fit();else large.onload=fit;}
  thumb.onclick=open;thumb.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open();}};
  stage.addEventListener('wheel',e=>{e.preventDefault();e.stopPropagation();const r=stage.getBoundingClientRect();scale(Math.exp(-e.deltaY*.0015),e.clientX-r.left-r.width/2,e.clientY-r.top-r.height/2);},{passive:false});
  stage.onpointerdown=e=>{if(e.button!==0)return;pointer=e.pointerId;origin=[e.clientX,e.clientY,x,y];stage.setPointerCapture(pointer);};
  stage.onpointermove=e=>{if(e.pointerId!==pointer||!origin)return;x=origin[2]+e.clientX-origin[0];y=origin[3]+e.clientY-origin[1];render();};
  stage.onpointerup=stage.onpointercancel=()=>{pointer=null;origin=null;};stage.ondblclick=fit;
  modal.addEventListener('keydown',e=>{if(e.key==='Escape')e.stopPropagation();if(e.key==='+'||e.key==='=')scale(1.3);if(e.key==='-')scale(1/1.3);});
  modal.addEventListener('close',()=>thumb.focus());
  const resize=()=>{if(modal.open)fit();};window.addEventListener('resize',resize);
  return ()=>{window.removeEventListener('resize',resize);if(modal.open)modal.close();root.remove();};
}
