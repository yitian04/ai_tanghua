"""Deterministic, robot-independent composition of window artwork curves."""
from dataclasses import dataclass
from copy import deepcopy
import math
import io
import json
import numpy as np
from PIL import Image

from src.core.models import CurveList, Curve2D
from src.core.image_pixels import white_background
from src.modules.image_process_module import vectorize_image_to_curve_list


@dataclass(frozen=True)
class Window:
    xmin: float = 38.9
    ymin: float = 144.6
    xmax: float = 482.6
    ymax: float = 397.2

    def validate(self):
        if not all(math.isfinite(v) for v in (self.xmin,self.ymin,self.xmax,self.ymax)) or self.xmax<=self.xmin or self.ymax<=self.ymin:
            raise ValueError('橱窗边界必须为有限坐标，且右、下边界大于左、上边界。')


def validate_curves(curves):
    if not curves.curves:raise ValueError('曲线为空。')
    for c in curves.curves:
        if len(c.points)<2 or any(len(p)!=2 or not all(math.isfinite(v) for v in p) for p in c.points):
            raise ValueError('曲线点列无效。')


def segments(curves):
    for c in curves.curves:
        pairs=list(zip(c.points,c.points[1:]))
        if c.closed and c.points[-1]!=c.points[0]:pairs.append((c.points[-1],c.points[0]))
        for a,b in pairs:
            a,b=np.array(a,float),np.array(b,float)
            if np.linalg.norm(b-a)>1e-9:yield a,b


def clip(a,b,window):
    d=b-a;lo,hi=0.,1.
    for p,q in ((-d[0],a[0]-window.xmin),(d[0],window.xmax-a[0]),(-d[1],a[1]-window.ymin),(d[1],window.ymax-a[1])):
        if abs(p)<1e-12:
            if q<0:return None
        elif p<0:lo=max(lo,q/p)
        else:hi=min(hi,q/p)
    if hi-lo<=1e-10:return None
    return a+lo*d,a+hi*d


def subtract_overlap(a,b,frames,tolerance):
    d=b-a;length=float(np.linalg.norm(d));intervals=[]
    for c,e in frames:
        v=e-c
        cross=lambda u,v:u[0]*v[1]-u[1]*v[0]
        if abs(cross(d,v))>1e-5*length*np.linalg.norm(v):continue
        if abs(cross(c-a,d))/length>tolerance:continue
        t0,t1=sorted((float(np.dot(c-a,d)/length**2),float(np.dot(e-a,d)/length**2)))
        lo,hi=max(0.,t0),min(1.,t1)
        if hi>lo:intervals.append((lo,hi))
    cursor=0.;pieces=[]
    for lo,hi in sorted(intervals):
        if lo>cursor+1e-9:pieces.append((a+cursor*d,a+lo*d))
        cursor=max(cursor,hi)
    if cursor<1.-1e-9:pieces.append((a+cursor*d,b))
    return pieces


def compose_window(template,content,canvas_size,window=Window(),snap_tolerance=2.,overlap_tolerance=.5,metadata=None):
    validate_curves(template);validate_curves(content);window.validate()
    width,height=canvas_size
    if not all(math.isfinite(v) and v>1 for v in (width,height)):
        raise ValueError('素材画布尺寸无效。')
    if not all(math.isfinite(v) and 0<=v<=20 for v in (snap_tolerance,overlap_tolerance)):
        raise ValueError('连接与重合容差必须在 0–20 范围内。')
    points=np.array([p for c in template.curves for p in c.points])
    if window.xmin<points[:,0].min()-1 or window.xmax>points[:,0].max()+1 or window.ymin<points[:,1].min()-1 or window.ymax>points[:,1].max()+1:
        raise ValueError('橱窗边界超出模板范围。')
    frames=[]
    for a,b in segments(template):
        # Only real template segments near the four window sides may receive endpoints.
        for axis,edge in ((0,window.xmin),(0,window.xmax),(1,window.ymin),(1,window.ymax)):
            if max(abs(a[axis]-edge),abs(b[axis]-edge))<=snap_tolerance+1e-6:
                piece=clip(a,b,window)
                if piece is not None:frames.append(piece)
                break
    if not frames:raise ValueError('橱窗边界附近没有窗框线，请校准边界。')
    scale=np.array([(window.xmax-window.xmin)/(width-1),(window.ymax-window.ymin)/(height-1)])
    shift=np.array([window.xmin,window.ymin]);mapped=[]
    for c in content.curves:
        mapped.append(Curve2D([(np.array(p)*scale+shift).tolist() for p in c.points],closed=c.closed))
    output=[];removed=0;snapped=0
    for c in mapped:
        run=[]
        def finish():
            nonlocal run,snapped
            if len(run)<2:run=[];return
            for index in (0,-1):
                p=run[index];best=p;distance=float('inf')
                for a,b in frames:
                    d=b-a;t=np.clip(np.dot(p-a,d)/np.dot(d,d),0,1);q=a+t*d
                    dist=float(np.linalg.norm(p-q))
                    if dist<distance:best=q;distance=dist
                if distance<=snap_tolerance and distance>1e-9:run[index]=best;snapped+=1
            if any(np.linalg.norm(p-run[0])>1e-9 for p in run[1:]):
                output.append(Curve2D([p.tolist() for p in run],closed=bool(np.linalg.norm(run[0]-run[-1])<1e-9)))
            run=[]
        for a,b in segments(CurveList([c])):
            piece=clip(a,b,window)
            if piece is None:finish();continue
            parts=subtract_overlap(*piece,frames,overlap_tolerance)
            removed+=max(0.,float(np.linalg.norm(piece[1]-piece[0]))-sum(float(np.linalg.norm(e-d)) for d,e in parts))
            if not parts:finish()
            for a,b in parts:
                if run and np.linalg.norm(run[-1]-a)>1e-7:finish()
                if not run:run=[a]
                run.append(b)
        finish()
    if not output:raise ValueError('素材没有可放入橱窗的有效内容。')
    merged=CurveList(deepcopy(template.curves)+output,template.coordinate_frame,deepcopy(template.metadata))
    for i,c in enumerate(merged.curves):c.curve_id=i
    stats={'template_curves':len(template.curves),'content_curves':len(output),'snapped_endpoints':snapped,'removed_overlap_length':removed}
    from src.pipeline.svg_generation.service import connected_components
    try:stats['connectivity']=connected_components(merged,tolerance=.05)
    except ValueError as exc:stats['connectivity']={'count':None,'reason':str(exc)}
    merged.metadata.update(shop_window={'version':1,'example_test':True,'window':vars(window),'canvas_size':list(canvas_size),'scale':scale.tolist(),'snap_tolerance':snap_tolerance,'overlap_tolerance':overlap_tolerance,'stats':stats,**(metadata or {})})
    return merged,stats


def build_example(template_bytes,image_bytes,window=Window(),sample_tolerance=1.2,snap_tolerance=2.,overlap_tolerance=.5,metadata=None):
    from src.core.assets import classify
    if classify(template_bytes,'template.json')!='curve':raise ValueError('请选择曲线 JSON 模板。')
    template=CurveList.from_dict(json.loads(template_bytes.decode('utf-8-sig')))
    with Image.open(io.BytesIO(image_bytes)) as source:image=white_background(source)
    content=vectorize_image_to_curve_list(np.array(image),vectorizer='skeleton_stroke_svg',line_simplify_epsilon=sample_tolerance,bridge_gap_px=0)
    if not content.curves:raise ValueError('示例图片没有可提取的线条。')
    merged,stats=compose_window(template,content,image.size,window,snap_tolerance,overlap_tolerance,metadata)
    return content,merged,stats
