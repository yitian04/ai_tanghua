"""In-memory, idempotent SVG tasks; workers never access Streamlit."""
from concurrent.futures import ThreadPoolExecutor
from threading import RLock
import copy,time,uuid
from .service import ChatClient,parse_result,connected_components
_POOL=ThreadPoolExecutor(max_workers=2,thread_name_prefix='svg-generation')
_LOCK=RLock();_JOBS={};_TOKENS={}

def submit(token,base,key,model,subject,prompt,width,height,tolerance,reference=None,vision=False):
    with _LOCK:
        if token in _TOKENS:return _TOKENS[token]
        job=uuid.uuid4().hex
        _TOKENS[token]=job;_JOBS[job]={'phase':'queued','started':time.monotonic(),'result':None,'error':'','raw':''}
    def work():
        nonlocal key
        try:
            update(job,phase='requesting')
            response=ChatClient(base,key).generate(model,subject,prompt,width,height,reference,vision)
            update(job,raw=response['raw'],phase='validating')
            if response['finish_reason']!='stop':raise ValueError('模型输出未完整结束，未自动补全或重试。')
            svg,curves=parse_result(response['raw'],width,height,tolerance)
            update(job,phase='connectivity')
            groups=connected_components(curves)
            curves.metadata.update(model=response['model'],prompt=prompt,subject=subject,usage=response['usage'],connectivity=groups)
            update(job,phase='completed',result={'svg':svg,'curves':curves,'connectivity':groups,'model':response['model'],'usage':response['usage']})
        except Exception as exc:update(job,phase='failed',error=str(exc))
        finally:key=None
    _POOL.submit(work)
    return job

def update(job,**values):
    with _LOCK:_JOBS[job].update(values)

def snapshot(job):
    with _LOCK:
        if job not in _JOBS:return {'phase':'unknown','error':'任务服务已重启或记录失效；结果未知，未自动重发。','elapsed':0}
        data=copy.deepcopy(_JOBS[job]);data['elapsed']=time.monotonic()-data.pop('started');return data
