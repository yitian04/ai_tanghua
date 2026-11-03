"""Pure trajectory speed editing, independent of storage."""
import copy
import csv
import io
import json
import math


def adjust_speeds(trajectory, drawing=None, travel=None):
    for value in (drawing, travel):
        if value is not None and (not math.isfinite(value) or value <= 0):
            raise ValueError('速度必须为有限正数。')
    result=copy.deepcopy(trajectory)
    for point in result.points:
        value=drawing if point.drawing else travel
        if value is not None: point.speed_mm_s=float(value)
    return result


def edit_payload(payload,name,drawing=None,travel=None):
    from src.pipeline.trajectory_composition.composer import import_trajectory
    result=adjust_speeds(import_trajectory(payload,name),drawing,travel)
    if name.lower().endswith('.json'):
        data=json.loads(payload.decode('utf-8-sig'))
        for raw,point in zip(data['points'],result.points):
            raw['speed_mm_s']=point.speed_mm_s
            if 'speed' in raw: raw['speed']=point.speed_mm_s
        return json.dumps(data,ensure_ascii=False,indent=2).encode('utf-8')
    reader=csv.DictReader(io.StringIO(payload.decode('utf-8-sig')))
    rows=list(reader);out=io.StringIO(newline='')
    writer=csv.DictWriter(out,fieldnames=reader.fieldnames);writer.writeheader()
    for row,point in zip(rows,result.points):
        row['speed_mm_s']=point.speed_mm_s;writer.writerow(row)
    return out.getvalue().encode('utf-8')
