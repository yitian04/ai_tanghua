"""Filesystem-backed, typed assets. Configuration and scratch files are never indexed."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import time
import uuid
import xml.etree.ElementTree as ET

from PIL import Image
from src.pipeline.trajectory_composition.composer import import_trajectory

ROOTS = ('images','generated','curves','direct_curves','direct_curve_demo','trajectories',
         'text_trajectories','compositions','exports','ai_generation/tasks','ai_generation/approved_samples')
IMAGES = {'.png','.jpg','.jpeg','.webp','.bmp'}


def classify(payload: bytes, name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in IMAGES:
        with Image.open(io.BytesIO(payload)) as image:
            expected={'.png':'PNG','.jpg':'JPEG','.jpeg':'JPEG','.webp':'WEBP','.bmp':'BMP'}[ext]
            if image.format != expected: raise ValueError('图片内容与扩展名不一致。')
            image.verify()
        return 'image'
    if ext == '.json':
        data=json.loads(payload.decode('utf-8-sig'))
        if not isinstance(data,dict): raise ValueError('不是项目素材。')
        if data.get('type') == 'trajectory_composition':
            raise ValueError('不再支持合成工程，请导入标准轨迹 JSON/CSV。')
        if 'curves' in data:
            if not isinstance(data['curves'],list) or not data['curves']: raise ValueError('曲线为空。')
            for c in data['curves']:
                if not c['points']: raise ValueError('曲线没有点。')
                for p in c['points']:
                    if len(p)!=2 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in p):
                        raise ValueError('曲线坐标无效。')
            return 'curve'
        if 'points' in data:
            import_trajectory(payload,name)
            return 'trajectory'
    if ext == '.csv':
        import_trajectory(payload,name)
        return 'trajectory'
    if ext == '.svg':
        text=payload.decode('utf-8-sig')
        if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper(): raise ValueError('不支持此 SVG。')
        root=ET.fromstring(text)
        if root.tag.split('}')[-1]!='svg' or not any(n.tag.split('}')[-1] in {'path','polyline','line','polygon','circle','ellipse','rect'} for n in root.iter()):
            raise ValueError('SVG 没有几何内容。')
        if any(n.tag.split('}')[-1] in {'script','foreignObject','image','use'} or any(k.lower().startswith('on') or 'href' in k.lower() for k in n.attrib) for n in root.iter()):
            raise ValueError('不支持包含脚本或外部引用的 SVG。')
        from src.pipeline.vectorization.svg_parser import parse_svg_to_curve_list
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'input.svg';source.write_bytes(payload)
            curves=parse_svg_to_curve_list(source)
            if not curves.curves: raise ValueError('SVG 没有可解析的路径。')
        return 'svg'
    if ext in {'.gcode','.gc','.nc'}:
        lines=payload.decode('utf-8-sig').upper().splitlines()
        if not any(re.match(r'^G[01]\s+.*[XYZ][-+\d.]',l.strip()) for l in lines): raise ValueError('未找到轨迹指令。')
        return 'gcode'
    if ext == '.urp':
        if ET.fromstring(payload).tag!='URProgram': raise ValueError('不是 URP 文件。')
        return 'program'
    if ext == '.script':
        text=payload.decode('utf-8-sig')
        if not ('def ' in text and 'end' in text): raise ValueError('不是 URScript 文件。')
        return 'program'
    raise ValueError('不支持或不符合项目格式的文件。')


def category(kind, name=''):
    if kind=='svg': return 'SVG'
    if kind=='program' and Path(name).suffix.lower()=='.urp': return '执行文件（URP）'
    return '图像' if kind=='image' else ('曲线' if kind=='curve' else '轨迹')


class AssetLibrary:
    def __init__(self, root):
        self.root=Path(root).resolve()
        # ROOTS are fixed relative names under an already canonical root.
        # Resolve the requested file once, rather than resolving every root per call.
        self._allowed=tuple(self.root/'data'/r for r in ROOTS)
        self.trash=self.root/'data'/'.asset_trash'

    def path(self, relative):
        raw=self.root/relative
        path=raw.resolve()
        if not any(path.is_relative_to(folder) for folder in self._allowed):
            raise ValueError('文件不在素材目录中。')
        if raw.is_symlink() or any(p.is_symlink() for p in raw.parents if p!=self.root.parent):
            raise ValueError('不支持链接文件。')
        return path

    def inspect(self, relative):
        path=self.path(relative)
        stat=path.stat()
        payload=path.read_bytes()
        kind=classify(payload,path.name)
        if path.is_relative_to(self.root/'data'/'ai_generation') and kind!='image': raise ValueError('仅收录任务中的图片。')
        return dict(id=path.relative_to(self.root).as_posix(),name=path.name,kind=kind,
                    category=category(kind,path.name),size=stat.st_size,mtime=stat.st_mtime,
                    fingerprint=(stat.st_mtime_ns,stat.st_size,hashlib.sha256(payload).hexdigest()))

    def scan(self):
        result=[]
        for folder in ROOTS:
            for path in (self.root/'data'/folder).rglob('*'):
                if not path.is_file() or path.suffix.lower() not in IMAGES|{'.json','.csv','.svg','.gcode','.gc','.nc','.urp','.script'}: continue
                try: result.append(self.inspect(path.relative_to(self.root)))
                except (ValueError,OSError,KeyError,TypeError,ET.ParseError,IndexError,OverflowError): pass
        return sorted(result,key=lambda a:a['mtime'],reverse=True)

    def open_folder(self, *, trash=False):
        from src.core.local_files import show_in_folder
        path=self.trash if trash else self.root/'data'
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError('素材文件夹位置无效。')
        path.mkdir(parents=True,exist_ok=True)
        show_in_folder(path)
        return path

    def read(self, asset):
        """Resolve and validate an asset at the storage boundary, not in its consumer."""
        path=self.path(asset['id'])
        payload=path.read_bytes()
        stat=path.stat()
        fingerprint=(stat.st_mtime_ns,len(payload),hashlib.sha256(payload).hexdigest())
        if tuple(fingerprint)!=tuple(asset['fingerprint']):
            raise ValueError('文件已变化，请刷新后重试。')
        if classify(payload,asset['name'])!=asset['kind']: raise ValueError('素材类型已变化。')
        return payload

    def replace_trajectory(self, asset, payload):
        """Conditional atomic replacement; no consumer needs a local path."""
        import tempfile
        if asset['kind']!='trajectory' or classify(payload,asset['name'])!='trajectory':
            raise ValueError('只能修改标准轨迹。')
        self.read(asset)
        path=self.path(asset['id']);temporary=None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as file:
                temporary=Path(file.name);file.write(payload);file.flush();os.fsync(file.fileno())
            self.read(asset)
            os.replace(temporary,path)
        finally:
            if temporary and temporary.exists(): temporary.unlink()
        return self.inspect(asset['id'])

    def reveal(self, asset):
        from src.core.local_files import show_in_folder
        if asset.get('trash_id'):
            path=self.trash_path(asset['trash_id'])/'payload'
            if path.is_symlink(): raise ValueError('不支持链接文件。')
            if hashlib.sha256(path.read_bytes()).hexdigest()!=asset['fingerprint'][2]:
                raise ValueError('文件已变化，请刷新后重试。')
        else:
            current=self.inspect(asset['id'])
            if tuple(current['fingerprint'])!=tuple(asset['fingerprint']):
                raise ValueError('文件已变化，请刷新后重试。')
            path=self.path(asset['id'])
        show_in_folder(path,select=True)
        return path

    def import_file(self,payload,name):
        kind=classify(payload,name)
        folder={'image':'images','curve':'curves','svg':'curves','trajectory':'trajectories','gcode':'exports','program':'exports'}[kind]
        safe=re.sub(r'[^\w.\-]+','_',Path(name.replace('\\','/')).name).strip('._') or 'asset'
        destination=self.root/'data'/folder/safe
        self.path(destination.relative_to(self.root))
        destination.parent.mkdir(parents=True,exist_ok=True)
        stem,ext=destination.stem,destination.suffix
        while True:
            try:
                with destination.open('xb') as file: file.write(payload)
                break
            except FileExistsError: destination=destination.with_name(f'{stem}_{uuid.uuid4().hex[:8]}{ext}')
        return self.inspect(destination.relative_to(self.root))

    def delete(self, asset):
        current=self.inspect(asset['id'])
        if tuple(current['fingerprint'])!=tuple(asset['fingerprint']): raise ValueError('文件已变化，请刷新后重试。')
        target=self.trash/uuid.uuid4().hex
        target.mkdir(parents=True)
        (target/'record.json').write_text(json.dumps({**current,'deleted_at':time.time()},ensure_ascii=False),encoding='utf-8')
        try: shutil.move(str(self.path(asset['id'])),str(target/'payload'))
        except Exception:
            (target/'record.json').unlink();target.rmdir();raise

    def trash_items(self):
        result=[]
        for path in self.trash.glob('*/record.json'):
            try:
                item=json.loads(path.read_text(encoding='utf-8'))
                item['category']=category(item['kind'],item['name'])
                if (path.parent/'payload').is_file(): result.append({**item,'trash_id':path.parent.name})
            except (ValueError,OSError,KeyError,TypeError): pass
        return sorted(result,key=lambda i:i['deleted_at'],reverse=True)

    def trash_path(self, token):
        if not re.fullmatch('[0-9a-f]{32}',token): raise ValueError('回收站编号无效。')
        path=self.trash/token
        if self.trash.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(self.trash.resolve()): raise ValueError('回收站位置无效。')
        return path

    def restore(self, token):
        folder=self.trash_path(token)
        record=json.loads((folder/'record.json').read_text(encoding='utf-8'))
        target=self.path(record['id'])
        payload=(folder/'payload').read_bytes()
        legacy=record.get('kind')=='project'
        if legacy:
            # Restore archived bytes without re-enabling engineering imports.
            from src.pipeline.trajectory_composition.composer import Composition
            Composition.from_dict(json.loads(payload.decode('utf-8-sig')))
        else:classify(payload,target.name)
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists(): target=target.with_name(f'{target.stem}_恢复_{uuid.uuid4().hex[:8]}{target.suffix}')
        with target.open('xb') as file: file.write(payload)
        self.purge(token)
        if legacy:
            stat=target.stat()
            return {**record,'id':target.relative_to(self.root).as_posix(),'name':target.name,
                    'mtime':stat.st_mtime,'size':stat.st_size,
                    'fingerprint':(stat.st_mtime_ns,stat.st_size,hashlib.sha256(payload).hexdigest())}
        return self.inspect(target.relative_to(self.root))

    def purge(self, token):
        folder=self.trash_path(token)
        (folder/'payload').unlink()
        (folder/'record.json').unlink()
        folder.rmdir()
