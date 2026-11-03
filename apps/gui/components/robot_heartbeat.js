export default function(component) {
  const {parentElement,setStateValue}=component;
  parentElement.innerHTML='<span style="font:12px system-ui;color:#667085">运行期间请保持本页可见；网页失联将终止任务。</span>';
  let stopped=false;
  const pulse=()=>{if(!stopped&&!document.hidden)setStateValue('pulse',Date.now());};
  pulse();const timer=setInterval(pulse,500);
  const visibility=()=>pulse();document.addEventListener('visibilitychange',visibility);
  return ()=>{stopped=true;clearInterval(timer);document.removeEventListener('visibilitychange',visibility);};
}
