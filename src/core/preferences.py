"""Profile-scoped parameter storage, separate from project defaults and assets."""
from __future__ import annotations
import json
from pathlib import Path
from threading import RLock
import uuid

_LOCK=RLock()


class PreferenceStore:
    def __init__(self,root,profile='local'):
        if not profile.replace('_','').replace('-','').isalnum():raise ValueError('Invalid preference profile')
        self.path=Path(root)/'data'/'.preferences'/f'{profile}.json'

    def _load(self):
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
            return data if isinstance(data,dict) else {}
        except (OSError,ValueError):return {}

    def _write(self,data):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');temporary.replace(self.path)

    def values(self,group,layer='recent'):
        with _LOCK:return dict(self._load().get(group,{}).get(layer,{}))

    def current(self,group):
        with _LOCK:
            data=self._load().get(group,{})
            return {**data.get('initial',{}),**data.get('defaults',{}),**data.get('recent',{})}

    def seed(self,group,field,value):
        with _LOCK:
            data=self._load();entry=data.setdefault(group,{})
            initial=entry.setdefault('initial',{})
            if field not in initial:initial[field]=value;self._write(data)

    def remember(self,group,values):
        with _LOCK:
            data=self._load();data.setdefault(group,{}).setdefault('recent',{}).update(values);self._write(data)

    def save_defaults(self,group):
        with _LOCK:
            values=self.current(group);data=self._load();data.setdefault(group,{})['defaults']=values;self._write(data)
            return values

    def patch_defaults(self,group,values):
        """Explicitly update selected defaults and recent values atomically."""
        with _LOCK:
            data=self._load();entry=data.setdefault(group,{})
            entry.setdefault('defaults',{}).update(values)
            entry.setdefault('recent',{}).update(values)
            self._write(data)

    def restore(self,group):
        with _LOCK:
            data=self._load();entry=data.setdefault(group,{})
            values={**entry.get('initial',{}),**entry.get('defaults',{})}
            entry['recent']=values;self._write(data);return values
