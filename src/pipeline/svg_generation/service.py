from __future__ import annotations
import base64
import copy
import io
import json
import math
from pathlib import Path
import re
import tempfile
import urllib.request
import urllib.error
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
from PIL import Image
from src.pipeline.vectorization.svg_parser import parse_svg_to_curve_list,TOKEN_RE

DEFAULT_PROMPT='根据用户主题创作清晰、简洁的单线 SVG 图案。优先使用连续路径，让主体、细节与装饰彼此连通，避免悬空小块和孤立线段。使用线条表达形体，避免实心填充、阴影、渐变、纹理和依靠描边宽度形成的面域。保留必要留白，控制细节密度。只输出完整、独立的 SVG，不输出解释文字或外部资源。'
TECHNICAL='只使用 svg、g、path、line、polyline、polygon、circle、ellipse、rect。path 仅使用 M/L/H/V/C/Q/Z 及小写命令。不使用文字、CSS、style、裁剪、滤镜、图片或外部引用。不使用圆角 rect。所有可见几何必须 fill="none"、stroke="#000000"，描边宽度统一为 2；可从 svg/g 继承。不要设置 transform（请直接计算坐标）。必须提供 viewBox="0 0 宽 高"，所有几何位于画布内。'
MAX_BYTES=1024*1024


class SVGError(ValueError):pass


class Credentials:
    def __init__(self,root):self.path=Path(root)/'data'/'model_gateway'/'svg_credentials.json'
    def load(self):
        try:return json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError,ValueError):return {}
    def save(self,base,key):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps({'base':base,'api_key':key}),encoding='utf-8');temp.replace(self.path)


class ChatClient:
    def __init__(self,base,key,opener=None):
        base=base.rstrip('/');url=urlsplit(base)
        if url.scheme not in {'https','http'} or not url.hostname or url.username or url.password or url.query or url.fragment:raise SVGError('API 地址必须是无凭据、无查询参数的 HTTP(S) 地址。')
        if not key.strip():raise SVGError('请填写 API 密钥。')
        self.base=base;self.key=key;self.opener=opener or urllib.request.build_opener()
    def request(self,endpoint,payload=None):
        body=json.dumps(payload).encode() if payload is not None else None
        request=urllib.request.Request(self.base+endpoint,body,{'Authorization':'Bearer '+self.key,'Content-Type':'application/json'})
        try:
            with self.opener.open(request,timeout=180) as response:data=response.read(MAX_BYTES+1)
        except urllib.error.HTTPError as exc:raise SVGError(f'接口返回 HTTP {exc.code}；请检查模型、接口兼容性、地区限制或权限。未自动重试。') from None
        except (urllib.error.URLError,TimeoutError,OSError):raise SVGError('连接失败或超时，结果未知；未自动重试，请确认服务任务状态后再操作。') from None
        if len(data)>MAX_BYTES:raise SVGError('接口响应超过 1 MB。')
        try:return json.loads(data)
        except ValueError:raise SVGError('接口未返回有效 JSON。') from None
    def models(self):
        data=self.request('/models')
        return sorted({m['id'] for m in data.get('data',[]) if isinstance(m,dict) and isinstance(m.get('id'),str)})
    def generate(self,model,subject,prompt,width,height,reference=None,vision=False):
        if not model.strip() or not subject.strip():raise SVGError('请填写模型 ID 和主题。')
        if reference is not None and not vision:raise SVGError('带参考图生成前，请明确确认此模型支持参考图。')
        content=[{'type':'text','text':f'主题：{subject}\n画布宽 {width}，高 {height}。\n{prompt}'}]
        if reference is not None:
            if len(reference)>10*1024*1024:raise SVGError('参考图超过 10 MB。')
            with Image.open(io.BytesIO(reference)) as image:
                image.thumbnail((1536,1536));out=io.BytesIO();image.convert('RGB').save(out,format='PNG')
            content.append({'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()}})
        response=self.request('/chat/completions',{'model':model,'messages':[{'role':'system','content':TECHNICAL},{'role':'user','content':content if reference is not None else content[0]['text']}],'stream':False})
        choice=response.get('choices',[None])[0] if response.get('choices') else None
        if not isinstance(choice,dict):raise SVGError('服务未返回聊天文本结果；该模型可能需要其他接口。')
        raw=choice.get('message',{}).get('content')
        if not isinstance(raw,str):raise SVGError('服务未返回 SVG 文本。')
        return {'raw':raw,'finish_reason':choice.get('finish_reason'),'model':response.get('model',model),'usage':response.get('usage',{})}


def validate_svg(raw,width,height):
    if not isinstance(raw,str) or len(raw.encode())>MAX_BYTES:raise SVGError('SVG 响应为空或过大。')
    text=raw.strip()
    if text.startswith('```'):
        match=re.fullmatch(r'```(?:svg|xml)?\s*\n(.*?)\n```',text,re.S|re.I)
        if not match:raise SVGError('代码围栏不完整，或包含多个候选 SVG。')
        text=match.group(1).strip()
    # Ordinary XML comments are inert. Validate their syntax with the XML parser,
    # but continue rejecting declarations/entities and processing instructions.
    inspected=re.sub(r'<!--.*?-->','',text,flags=re.S)
    if re.search(r'<!|<\?',inspected):raise SVGError('不支持声明、实体或处理指令；普通 XML 注释可以保留。')
    try:root=ET.fromstring(text)
    except ET.ParseError:raise SVGError('不是单个完整 SVG，可能包含解释文字、多个 SVG 或截断内容。') from None
    if root.tag not in {'svg','{http://www.w3.org/2000/svg}svg'}:raise SVGError('根元素不是 SVG。')
    if list(map(float,re.split(r'[ ,]+',root.get('viewBox','').strip()))) != [0.,0.,float(width),float(height)]:raise SVGError('viewBox 必须与设置的画布宽高一致。')
    allowed={'svg','g','path','line','polyline','polygon','circle','ellipse','rect'}
    common={'fill','stroke','stroke-width','stroke-linecap','stroke-linejoin'}
    attrs={'svg':{'viewBox','width','height'},'g':set(),'path':{'d'},'line':{'x1','y1','x2','y2'},'polyline':{'points'},'polygon':{'points'},'circle':{'cx','cy','r'},'ellipse':{'cx','cy','rx','ry'},'rect':{'x','y','width','height'}}
    for name,expected in (('width',width),('height',height)):
        if name in root.attrib:
            try:
                if float(root.attrib[name])!=float(expected):raise ValueError()
            except ValueError:raise SVGError('SVG 宽高属性与画布设置不符。') from None
    elements=list(root.iter())
    if len(elements)>500:raise SVGError('SVG 元素超过 500 个。')
    estimated=sum(96*len(re.findall('[CcQq]',e.get('d','')))+len(TOKEN_RE.findall(e.get('d','')))+97 for e in elements)
    if estimated>20000:raise SVGError('SVG 采样预算过大，请简化路径。')
    def walk(element,paint):
        if element.tag.startswith('{') and not element.tag.startswith('{http://www.w3.org/2000/svg}'):raise SVGError('不支持外部命名空间。')
        tag=element.tag.split('}')[-1]
        if tag not in allowed or (element is not root and tag=='svg'):raise SVGError('不支持的 SVG 元素：'+tag)
        if (element.text or '').strip() or (element.tail or '').strip():raise SVGError('SVG 中不能包含文本。')
        for name,value in element.attrib.items():
            if name not in attrs[tag]|common:raise SVGError('不支持的 SVG 属性：'+name+'。请直接使用坐标，不使用样式或变换。')
            if len(value)>100000:raise SVGError('SVG 属性过长。')
        paint={**paint,**{k:v for k,v in element.attrib.items() if k in common}}
        if tag not in {'svg','g'}:
            if paint.get('fill')!='none' or paint.get('stroke') not in {'black','#000','#000000'} or paint.get('stroke-width','2')!='2':raise SVGError('可见几何必须为无填充、黑色、宽度 2 的单线。')
            if tag=='path':
                d=element.get('d','');tokens=TOKEN_RE.findall(d)
                if re.sub(TOKEN_RE,'',d).replace(',','').strip() or any(t.isalpha() and t.upper() not in 'MLHVCQZ' for t in tokens):raise SVGError('不支持的路径命令或字符。')
                if not tokens or tokens[0] not in {'M','m'} or len(tokens)>5000:raise SVGError('路径必须以 M 开始，且不能过于复杂。')
                # Validate arities before entering the legacy sampler; malformed
                # commands after Z could otherwise leave its cursor unchanged.
                command=None;count=0;arity={'M':2,'L':2,'H':1,'V':1,'C':6,'Q':4,'Z':0}
                for token in tokens+['M']:
                    if token.isalpha():
                        if command is not None and ((arity[command]==0 and count) or (arity[command]>0 and (count==0 or count%arity[command]))):raise SVGError('路径命令参数数量无效。')
                        command=token.upper();count=0
                    else:
                        if command=='Z':raise SVGError('Z 后必须有新的绘制命令。')
                        value=float(token)
                        if not math.isfinite(value) or abs(value)>10000:raise SVGError('坐标或控制点超出支持范围。')
                        count+=1
            else:
                required={'rect':('width','height'),'circle':('r',),'ellipse':('rx','ry',)}.get(tag,())
                for name in required:
                    try:
                        if float(element.get(name,'0'))<=0:raise ValueError()
                    except ValueError:raise SVGError('几何尺寸必须为正数。') from None
                if tag in {'polyline','polygon'}:
                    values=re.split(r'[ ,]+',element.get('points','').strip())
                    if len(values)<4 or len(values)%2:raise SVGError('points 必须是完整的坐标对。')
                for name in attrs[tag]:
                    value=element.get(name)
                    if value is None:continue
                    numbers=re.split(r'[ ,]+',value.strip()) if name=='points' else [value]
                    try:
                        if any(not math.isfinite(float(x)) or abs(float(x))>10000 for x in numbers):raise ValueError()
                    except ValueError:raise SVGError('几何属性必须使用有限数值，不支持百分比或单位后缀。') from None
        for child in element:walk(child,paint)
    walk(root,{})
    return text


def parse_result(raw,width,height,tolerance=2.):
    if not math.isfinite(tolerance) or not .2<=tolerance<=20:raise SVGError('采样间距必须在 0.2–20 之间。')
    text=validate_svg(raw,width,height)
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'generated.svg';path.write_text(text,encoding='utf-8')
        curves=parse_svg_to_curve_list(path,sample_tolerance_px=tolerance)
    if not curves.curves:raise SVGError('SVG 没有可绘制曲线。')
    if len(curves.curves)>100 or sum(len(c.points) for c in curves.curves)>10000:raise SVGError('SVG 采样结果过于复杂，限制为 100 条曲线／10000 个点。')
    if any(not math.isfinite(v) for c in curves.curves for p in c.points for v in p):raise SVGError('变换后坐标无效。')
    if any(not (-1e-6<=p[0]<=width+1e-6 and -1e-6<=p[1]<=height+1e-6) for c in curves.curves for p in c.points):raise SVGError('几何超出画布，不能静默裁剪。')
    for curve in curves.curves:curve.closed=math.dist(curve.points[0],curve.points[-1])<1e-6
    curves.metadata={'svg_parser':'strict_svg_v1','canvas_width':width,'canvas_height':height,'sample_tolerance':tolerance}
    return text,curves


def connected_components(curves,tolerance=1.):
    import numpy as np
    parents=list(range(len(curves.curves)));budget=0
    def find(i):
        while parents[i]!=i:i=parents[i]
        return i
    def distance(p,a,b):
        d=b-a;den=(d*d).sum(-1);u=((p-a)*d).sum(-1)/np.maximum(den,1e-30)
        return ((p-(a+np.clip(u,0,1)[...,None]*d))**2).sum(-1)
    lines=[np.asarray(c.points,dtype=float) for c in curves.curves]
    for i,one in enumerate(lines):
        for j,two in enumerate(lines[:i]):
            if find(i)==find(j):continue
            if np.any(one.max(0)+tolerance<two.min(0)) or np.any(two.max(0)+tolerance<one.min(0)):continue
            budget+=(len(one)-1)*(len(two)-1)
            if budget>2000000:raise SVGError('连通性分析过于复杂，请简化图案或增大采样间距。')
            a=one[:-1,None,:];b=one[1:,None,:];c=two[None,:-1,:];d=two[None,1:,:]
            cross=lambda x,y:x[...,0]*y[...,1]-x[...,1]*y[...,0]
            den=cross(b-a,d-c);u=np.divide(cross(c-a,d-c),den,out=np.full_like(den,np.inf),where=abs(den)>1e-12);v=np.divide(cross(c-a,b-a),den,out=np.full_like(den,np.inf),where=abs(den)>1e-12)
            touch=((u>=0)&(u<=1)&(v>=0)&(v<=1))
            near=np.minimum.reduce([distance(a,c,d),distance(b,c,d),distance(c,a,b),distance(d,a,b)])<=tolerance*tolerance
            if np.any(touch|near):parents[find(i)]=find(j)
    roots=[find(i) for i in range(len(lines))];unique=list(dict.fromkeys(roots))
    return {'count':len(unique),'curve_groups':[unique.index(x)+1 for x in roots],'tolerance':tolerance}
