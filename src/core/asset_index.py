"""Incremental filesystem index and prioritized, bounded background previews."""
from __future__ import annotations
import base64
from collections import OrderedDict
import hashlib
import itertools
import json
from pathlib import Path
from queue import PriorityQueue
from threading import RLock, Thread
import uuid

from src.core.assets import AssetLibrary, IMAGES, ROOTS, category
from src.core.asset_previews import render_preview

EXTENSIONS=IMAGES|{'.json','.csv','.svg','.gcode','.gc','.nc','.urp','.script'}


class AssetIndex:
    def __init__(self, root):
        self.lib=AssetLibrary(root)
        self.cache=self.lib.root/'data'/'.asset_cache'
        self.cache.mkdir(parents=True,exist_ok=True)
        self.lock=RLock()
        self.queue=PriorityQueue()
        self.counter=itertools.count()
        self.manifest={}
        self.records={}
        self.pending=set()
        self.wanted={}
        self.thumbs=OrderedDict()
        self.failures={}
        self.errors=[]
        self.closed=False
        try:
            saved=json.loads((self.cache/'index.json').read_text(encoding='utf-8'))
            if saved.get('version')==1 and isinstance(saved.get('records'),dict):
                for key,record in saved['records'].items():
                    if not isinstance(record,dict) or not isinstance(record.get('stamp'),list) or len(record['stamp'])!=3: continue
                    asset=record.get('asset')
                    if asset is not None and (not isinstance(asset,dict) or asset.get('id')!=key or not {'name','kind','category','mtime','size','fingerprint'}<=asset.keys()): continue
                    if asset and asset.get('kind')=='project': continue
                    if asset: asset['category']=category(asset['kind'],asset['name'])
                    self.records[key]=record
        except (OSError,ValueError,KeyError,TypeError): pass
        for n in range(2):
            Thread(target=self._worker,daemon=True,name=f'asset-worker-{n}').start()

    @staticmethod
    def stamp(path):
        stat=path.stat()
        return [stat.st_mtime_ns,stat.st_size,stat.st_ino]

    def refresh(self):
        with self.lock:
            self._refresh_locked()

    def _refresh_locked(self):
        manifest={}
        for directory in ROOTS:
            for path in (self.lib.root/'data'/directory).rglob('*'):
                if path.suffix.lower() not in EXTENSIONS or not path.is_file(): continue
                try:
                    relative=path.relative_to(self.lib.root).as_posix()
                    self.lib.path(relative)
                    manifest[relative]=self.stamp(path)
                except (ValueError,OSError): continue
        with self.lock:
            self.manifest=manifest
            self.records={k:v for k,v in self.records.items() if k in manifest}
            self.failures.clear()
            for relative,stamp in sorted(manifest.items(),key=lambda pair:pair[1][0],reverse=True):
                if self.records.get(relative,{}).get('stamp')!=stamp:
                    self._schedule(2,'validate',relative,stamp)
            self._persist()

    def _schedule(self, priority, kind, key, value):
        token=(kind,key,json.dumps(value,sort_keys=True))
        if token not in self.pending:
            self.pending.add(token)
            self.queue.put((priority,next(self.counter),token,value))

    def _persist(self):
        temporary=self.cache/(uuid.uuid4().hex+'.tmp')
        temporary.write_text(json.dumps({'version':1,'records':self.records},ensure_ascii=False),encoding='utf-8')
        temporary.replace(self.cache/'index.json')

    def snapshot(self):
        with self.lock:
            entries=[dict(v['asset']) for k,v in self.records.items()
                     if v.get('asset') and v['stamp']==self.manifest.get(k)]
            pending=sum(self.records.get(k,{}).get('stamp')!=v for k,v in self.manifest.items())
        return sorted(entries,key=lambda item:item['mtime'],reverse=True),pending

    def thumb_key(self, item):
        identity=['thumb-v2',item.get('trash_id',item['id']),item['fingerprint'],item['kind']]
        return hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()

    def previews(self, owner, items):
        with self.lock:
            keys={self.thumb_key(item) for item in items}
            self.wanted[owner]=keys
            result={}
            for item in items:
                key=self.thumb_key(item)
                if item['kind'] not in {'image','curve','trajectory','svg'}:
                    result[key]=('unsupported',None)
                    continue
                if key in self.thumbs:
                    self.thumbs.move_to_end(key)
                    result[key]=('ready',self.thumbs[key])
                elif (self.cache/(key+'.png')).is_file():
                    payload=(self.cache/(key+'.png')).read_bytes()
                    uri='data:image/png;base64,'+base64.b64encode(payload).decode()
                    self.thumbs[key]=uri
                    result[key]=('ready',uri)
                elif key in self.failures:
                    result[key]=('error',None)
                else:
                    self._schedule(0,'thumbnail',key,item)
                    result[key]=('loading',None)
            while len(self.thumbs)>256: self.thumbs.popitem(last=False)
            return result

    def release(self, owner):
        with self.lock: self.wanted.pop(owner,None)

    def _worker(self):
        while True:
            _,_,token,value=self.queue.get()
            kind,key,_=token
            try:
                with self.lock:
                    if self.closed: continue
                    if kind=='validate' and self.manifest.get(key)!=value: continue
                    if kind=='thumbnail' and not any(key in wanted for wanted in self.wanted.values()): continue
                if kind=='validate':
                    try: asset=self.lib.inspect(key)
                    except Exception: asset=None
                    try: current=self.stamp(self.lib.path(key))
                    except (OSError,ValueError): current=None
                    with self.lock:
                        if current==value and self.manifest.get(key)==value:
                            self.records[key]={'stamp':value,'asset':asset}
                            self._persist()
                        elif self.manifest.get(key)==value:
                            if current is None:
                                self.manifest.pop(key,None);self.records.pop(key,None)
                            else:
                                self.manifest[key]=current;self._schedule(2,'validate',key,current)
                else:
                    item=value
                    path=(self.lib.trash_path(item['trash_id'])/'payload' if item.get('trash_id') else self.lib.path(item['id']))
                    before=self.stamp(path)
                    payload=path.read_bytes()
                    if hashlib.sha256(payload).hexdigest()!=item['fingerprint'][2]:
                        raise ValueError('素材已变化')
                    image=render_preview(payload,item['name'],item['kind'],small=True)
                    if before!=self.stamp(path): raise ValueError('素材已变化')
                    with self.lock:
                        # A completed obsolete page may populate disk cache, never the list.
                        if image:
                            temporary=self.cache/(uuid.uuid4().hex+'.tmp')
                            temporary.write_bytes(image);temporary.replace(self.cache/(key+'.png'))
                            self.thumbs[key]='data:image/png;base64,'+base64.b64encode(image).decode()
            except Exception as exc:
                with self.lock:
                    if kind=='thumbnail': self.failures[key]=str(exc)
                    else: self.errors.append(str(exc))
            finally:
                with self.lock: self.pending.discard(token)
                self.queue.task_done()

    def close(self):
        with self.lock: self.closed=True;self.wanted.clear()


def batch_operation(library, action, items):
    """Independent per-file results; the caller owns confirmation and event deduplication."""
    succeeded=[];failed=[]
    seen=set()
    for item in items:
        identity=item.get('trash_id',item['id'])
        if identity in seen: continue
        seen.add(identity)
        try:
            if action=='recycle': library.delete(item)
            elif action in {'restore','purge'}:
                folder=library.trash_path(item['trash_id'])
                payload=(folder/'payload').read_bytes()
                if hashlib.sha256(payload).hexdigest()!=item['fingerprint'][2]: raise ValueError('文件已变化')
                if action=='restore': library.restore(item['trash_id'])
                else: library.purge(item['trash_id'])
            else: raise ValueError('不支持的素材操作')
            succeeded.append(identity)
        except Exception as exc: failed.append({'id':identity,'name':item['name'],'error':str(exc)})
    return succeeded,failed
