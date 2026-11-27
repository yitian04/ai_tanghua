"""Immutable result packages with explicit, idempotent publication."""
from __future__ import annotations
from dataclasses import dataclass,field
import hashlib
import json
from pathlib import Path
from threading import RLock
import uuid
import shutil

from src.core.assets import AssetLibrary,classify

_LOCK=RLock()


@dataclass
class Artifact:
    name:str
    payload:bytes
    folder:str
    source:str=''


@dataclass
class Draft:
    artifacts:list[Artifact]
    revision:str
    valid:bool=True
    error:str=''
    id:str=field(default_factory=lambda:uuid.uuid4().hex)
    published:list[dict]=field(default_factory=list)

    @property
    def dirty(self):return not self.published


class DraftStore:
    def __init__(self,root):self.library=AssetLibrary(root)

    def from_paths(self,paths,revision=None):
        artifacts=[]
        for path in paths:
            path=Path(path)
            payload=path.read_bytes();classify(payload,path.name)
            artifacts.append(Artifact(path.name,payload,path.parent.name,str(path)))
        digest=hashlib.sha256(b''.join(a.name.encode()+a.payload for a in artifacts)).hexdigest()
        return Draft(artifacts,revision or digest)

    def publish(self,draft):
        if not draft.valid:raise ValueError(draft.error or '当前成果不能保存。')
        if not draft.artifacts:raise ValueError('没有可保存的成果。')
        with _LOCK:
            if draft.published:
                for asset in draft.published:self.library.read(asset)
                return draft.published
            for artifact in draft.artifacts:classify(artifact.payload,artifact.name)
            planned=[]
            for artifact in draft.artifacts:
                folder=artifact.folder
                kind=classify(artifact.payload,artifact.name)
                if kind=='svg':folder='images'
                elif folder not in {'images','curves','trajectories','text_trajectories','compositions','exports'}:folder={'image':'images','curve':'curves','trajectory':'trajectories','project':'compositions','gcode':'exports','program':'exports'}[kind]
                target=self.library.path(Path('data')/folder/Path(artifact.name).name)
                while target.exists() or target in planned:target=target.with_name(f'{target.stem}_{uuid.uuid4().hex[:8]}{target.suffix}')
                planned.append(target)
            mapping={a.source:str(p) for a,p in zip(draft.artifacts,planned) if a.source}
            def rewrite(value):
                if isinstance(value,str):return mapping.get(value,value)
                if isinstance(value,list):return [rewrite(v) for v in value]
                if isinstance(value,dict):return {k:rewrite(v) for k,v in value.items()}
                return value
            created=[]
            try:
                for artifact,target in zip(draft.artifacts,planned):
                    payload=artifact.payload
                    if target.suffix.lower()=='.json':payload=json.dumps(rewrite(json.loads(payload)),ensure_ascii=False,indent=2).encode()
                    target.parent.mkdir(parents=True,exist_ok=True)
                    with target.open('xb') as handle:
                        created.append(target);handle.write(payload)
                result=[self.library.inspect(p.relative_to(self.library.root)) for p in created]
            except Exception:
                for path in created:path.unlink(missing_ok=True)
                raise
            draft.published=result
            return result

    def discard_files(self,paths):
        private=self.library.root/'data'/'.drafts'
        for value in paths:
            path=Path(value)
            if path.is_symlink() or not path.resolve().is_relative_to(private):continue
            if not path.is_file():continue
            for record in path.parent.glob('*.remote.json'):
                archive=self.library.root/'data'/'ai_generation'/'tasks'/'recovery_records'
                archive.mkdir(parents=True,exist_ok=True)
                target=archive/(hashlib.sha256(str(record).encode()).hexdigest()[:16]+'.remote.json')
                shutil.copy2(record,target)
            path.unlink()
        for value in paths:
            path=Path(value).parent
            while path!=private and path.is_relative_to(private):
                try:path.rmdir()
                except OSError:break
                path=path.parent
