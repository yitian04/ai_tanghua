"""Pure preview rendering. Never calls Streamlit from worker threads."""
import io
import json
from pathlib import Path
from threading import RLock

_GEOMETRY_LOCK=RLock()

def render_preview(payload, name, kind, small=False):
    if kind == "image":
        return _render(payload,name,kind,small)
    with _GEOMETRY_LOCK:
        return _render(payload,name,kind,small)

def _render(payload, name, kind, small=False):
    from PIL import Image
    if kind=='image':
        with Image.open(io.BytesIO(payload)) as image:
            image.thumbnail((320,220) if small else (640,400));output=io.BytesIO();image.convert('RGB').save(output,format='PNG');return output.getvalue()
    if kind not in {'curve','trajectory','svg'}: return None
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    fig=Figure(figsize=(5,3),dpi=65 if small else 100);FigureCanvasAgg(fig);ax=fig.add_subplot(111)
    paths=[]
    if kind=='curve':
        paths=[(c['points'],True) for c in json.loads(payload)['curves']]
    elif kind=='trajectory':
        from src.pipeline.trajectory_composition.composer import import_trajectory
        points=import_trajectory(payload,name).points
        for a,b in zip(points,points[1:]):
            draw=a.drawing and b.drawing and a.curve_id==b.curve_id
            paths.append(([(a.x_mm,a.y_mm),(b.x_mm,b.y_mm)],draw))
    elif kind=='svg':
        import tempfile
        from src.pipeline.vectorization.svg_parser import parse_svg_to_curve_list
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'preview.svg';path.write_bytes(payload)
            paths=[(c.points,True) for c in parse_svg_to_curve_list(path).curves]
    from matplotlib.collections import LineCollection
    for drawing,color in ((False,'#94a3b8'),(True,'#0369a1')):
        lines=[p for p,d in paths if d==drawing and len(p)>1]
        if lines: ax.add_collection(LineCollection(lines,colors=color,linewidths=1.1 if drawing else .5,linestyles='solid' if drawing else 'dashed'))
    ax.autoscale();ax.set_aspect('equal');ax.invert_yaxis();ax.axis('off');fig.tight_layout(pad=.3)
    out=io.BytesIO();fig.savefig(out,format='png');return out.getvalue()

