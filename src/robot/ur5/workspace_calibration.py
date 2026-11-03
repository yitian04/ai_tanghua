"""Read-only geometry calculations for a horizontal, axis-aligned workspace."""
from __future__ import annotations
import copy
import math
from .path_config import validate_waypoint,finite_vector

CORNERS={'top_left':'左上角','bottom_left':'左下角','top_right':'右上角','bottom_right':'右下角'}


def empty_calibration():
    return {'prepare':None,'pen':None,'corners':{},'lift_mm':20.}


def derive_workspace(calibration):
    for key,label in (('prepare','准备姿态'),('pen','落笔姿态')):
        if not calibration.get(key):raise ValueError('尚未记录'+label)
        validate_waypoint(calibration[key])
    corners=calibration.get('corners',{})
    missing=[label for key,label in CORNERS.items() if not corners.get(key)]
    if missing:raise ValueError('尚未记录四角：'+'、'.join(missing))
    for point in corners.values():validate_waypoint(point)
    points={key:[v*1000 for v in corners[key]['tcp'][:3]] for key in CORNERS}
    z=calibration['pen']['tcp'][2]*1000
    for key,p in points.items():
        if abs(p[2]-z)>1.+1e-8:raise ValueError(CORNERS[key]+'与落笔高度相差超过 1 mm，请调平台面并重新记录。')
    keys=list(CORNERS)
    for i,a in enumerate(keys):
        for b in keys[i+1:]:
            if math.dist(points[a][:2],points[b][:2])<1e-6:raise ValueError(CORNERS[a]+'与'+CORNERS[b]+'重复，请重新记录。')
    tl,bl,tr,br=(points[k] for k in keys)
    for a,b,axis,label in ((tl,tr,0,'上边'),(bl,br,0,'下边'),(tl,bl,1,'左边'),(tr,br,1,'右边')):
        dx=b[0]-a[0];dy=b[1]-a[1];along=dx if axis==0 else dy;across=dy if axis==0 else dx
        if along<=0:raise ValueError(label+'方向不符，请按 X 向右、Y 向下重新记录四角。')
        if math.degrees(math.atan2(abs(across),along))>1.+1e-8:raise ValueError(label+'与机器人 XY 轴偏差超过 1°，不支持旋转区域，请重新记录。')
    x0=(tl[0]+bl[0])/2;x1=(tr[0]+br[0])/2;y0=(tl[1]+tr[1])/2;y1=(bl[1]+br[1])/2
    # Check opposite endpoints before fitting an aligned rectangle, never replace
    # an arbitrary quadrilateral with its enclosing box.
    for delta,label in ((abs(tl[0]-bl[0]),'左边'),(abs(tr[0]-br[0]),'右边'),(abs(tl[1]-tr[1]),'上边'),(abs(bl[1]-br[1]),'下边')):
        if delta>2.+1e-8:raise ValueError(label+'边界不一致超过 2 mm，请重新记录。')
    if abs((tr[0]-tl[0])-(br[0]-bl[0]))>2.+1e-8 or abs((bl[1]-tl[1])-(br[1]-tr[1]))>2.+1e-8:
        raise ValueError('对边尺寸不一致超过 2 mm，请重新记录四角。')
    lift=calibration.get('lift_mm')
    if not isinstance(lift,(int,float)) or isinstance(lift,bool) or not math.isfinite(lift) or lift<=0:raise ValueError('抬起高度必须为有限正数。')
    return {'center_x_mm':(x0+x1)/2,'center_y_mm':(y0+y1)/2,'width_mm':x1-x0,'height_mm':y1-y0,
            'draw_z_mm':z,'approach_z_mm':z+lift,'lift_mm':lift,'bounds':[x0,x1,y0,y1,z,z+lift],
            'orientation_deg':[math.degrees(v) for v in calibration['pen']['tcp'][3:]]}


def calibrated_config(config):
    result=copy.deepcopy(config);geometry=derive_workspace(result.get('calibration',{}))
    result.update(schema_version=2,start=copy.deepcopy(result['calibration']['prepare']),
                  prepare=copy.deepcopy(result['calibration']['prepare']),bounds=geometry['bounds'],
                  draw_z_mm=geometry['draw_z_mm'],approach_z_mm=geometry['approach_z_mm'],workspace=geometry)
    return result


def planning_defaults(config):
    g=derive_workspace(config['calibration'])
    return {'桌面中心 X mm':g['center_x_mm'],'桌面中心 Y mm':g['center_y_mm'],
            '工作区宽 mm':g['width_mm'],'工作区高 mm':g['height_mm'],'绘制 Z mm':g['draw_z_mm'],
            '工具姿态 Rx deg':g['orientation_deg'][0],'工具姿态 Ry deg':g['orientation_deg'][1],
            '工具姿态 Rz deg':g['orientation_deg'][2],'抬笔高度 mm':g['lift_mm']}


def save_planning_defaults(root,config):
    from src.core.preferences import PreferenceStore
    values=planning_defaults(config)
    PreferenceStore(root).patch_defaults('planning',values)
    return values
