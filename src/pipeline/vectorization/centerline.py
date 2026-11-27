"""Topology-preserving thinning and exhaustive skeleton edge tracing."""
import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d


def thin(binary):
    a = np.pad((binary > 0).astype(np.uint8), 1)
    while True:
        changed = False
        for step in (0, 1):
            p = [a[:-2,1:-1], a[:-2,2:], a[1:-1,2:], a[2:,2:],
                 a[2:,1:-1], a[2:,:-2], a[1:-1,:-2], a[:-2,:-2]]
            n = sum(p)
            transitions = sum((p[i]==0)&(p[(i+1)%8]==1) for i in range(8))
            remove = (a[1:-1,1:-1]>0)&(n>=2)&(n<=6)&(transitions==1)
            if step == 0:remove &= (p[0]*p[2]*p[4]==0)&(p[2]*p[4]*p[6]==0)
            else:remove &= (p[0]*p[2]*p[6]==0)&(p[0]*p[4]*p[6]==0)
            if remove.any():a[1:-1,1:-1][remove]=0;changed=True
        if not changed:return a[1:-1,1:-1].astype(bool)


def trace(skeleton):
    pixels = set(map(tuple, np.argwhere(skeleton)))
    adj = {}
    for y,x in sorted(pixels):
        neighbors=[]
        for dy,dx in [(-1,0),(0,1),(1,0),(0,-1),(-1,1),(1,1),(1,-1),(-1,-1)]:
            q=(y+dy,x+dx)
            if q not in pixels:continue
            if dy and dx and ((y+dy,x) in pixels or (y,x+dx) in pixels):continue
            neighbors.append(q)
        adj[y,x]=neighbors
    pool={p for p in pixels if len(adj[p])!=2};groups=[]
    while pool:
        start=min(pool);pool.remove(start);todo=[start];group=[]
        while todo:
            p=todo.pop();group.append(p)
            for q in adj[p]:
                if q in pool:pool.remove(q);todo.append(q)
        groups.append(group)
    nodes={p:i for i,g in enumerate(groups) for p in g}
    centers=[tuple(np.mean(g,axis=0)) for g in groups]
    used=set();paths=[]
    edge=lambda p,q:tuple(sorted((p,q)))
    for i,g in enumerate(groups):
        for p in g:
            for q in adj[p]:
                if q in nodes and nodes[q]==i:used.add(edge(p,q));continue
                if edge(p,q) in used:continue
                pts=[centers[i]];prev,cur=p,q;used.add(edge(p,q))
                while cur not in nodes:
                    pts.append(cur)
                    nxt=[v for v in adj[cur] if v!=prev]
                    if not nxt:break
                    prev,cur=cur,nxt[0];used.add(edge(prev,cur))
                if cur in nodes:pts.append(centers[nodes[cur]])
                if len(pts)>1:paths.append(pts)
    for p in sorted(pixels):
        for q in adj[p]:
            if edge(p,q) in used:continue
            pts=[p];prev,cur=p,q;used.add(edge(p,q))
            while cur!=p:
                pts.append(cur)
                nxt=[v for v in adj[cur] if v!=prev and edge(cur,v) not in used]
                if not nxt:break
                prev,cur=cur,nxt[0];used.add(edge(prev,cur))
            if cur==p:pts.append(p)
            if len(pts)>1:paths.append(pts)
    return paths


def regularize(points, epsilon=1.2, smooth=0):
    p=np.asarray(points,dtype=float)
    if len(p)<3:return p.tolist()
    delta=p[-1]-p[0];length=np.linalg.norm(delta)
    if length>0:
        distance=np.abs((p[:,0]-p[0,0])*delta[1]-(p[:,1]-p[0,1])*delta[0])/length
        if distance.max()<=min(1.,epsilon):return [p[0].tolist(),p[-1].tolist()]
    # Subpixel low-pass filtering keeps junction endpoints fixed. Bound both
    # simplification and smoothing so a large UI tolerance cannot erase detail.
    endpoints=p[[0,-1]].copy()
    # Filter at the pixel scale before simplification, rather than interpolating
    # raster stair steps into a wavy sequence of short Bezier segments.
    p=gaussian_filter1d(p,1.6+.4*smooth,axis=0,mode='nearest')
    p[0],p[-1]=endpoints
    simplified=cv2.approxPolyDP(p.astype(np.float32).reshape(-1,1,2),min(1.,epsilon),False).reshape(-1,2)
    simplified[0]=p[0];simplified[-1]=p[-1]
    v=simplified.astype(float)
    output=[v[0].tolist()]
    for i in range(len(v)-1):
        a,b=v[i],v[i+1];before=v[max(0,i-1)];after=v[min(len(v)-1,i+2)]
        if np.linalg.norm(b-a)>18 and np.min(np.abs(b-a))<1.5:
            # Architectural straight runs inside a closed window/door loop
            # must not acquire curvature from the adjacent rounded corner.
            output.append(b.tolist())
            continue
        limit=np.linalg.norm(b-a)/3
        t1=(b-before)/6;t2=(after-a)/6
        t1*=min(1,limit/max(np.linalg.norm(t1),1e-9))
        t2*=min(1,limit/max(np.linalg.norm(t2),1e-9))
        # Preserve deliberate sharp corners; smooth gentle changes of tangent.
        if np.dot(a-before,b-a)<.5*np.linalg.norm(a-before)*np.linalg.norm(b-a):t1=(b-a)/3
        if np.dot(b-a,after-b)<.5*np.linalg.norm(b-a)*np.linalg.norm(after-b):t2=(b-a)/3
        for t in np.linspace(0,1,max(2,int(np.ceil(np.linalg.norm(b-a)))+1))[1:]:
            output.append(((1-t)**3*a+3*(1-t)**2*t*(a+t1)+3*(1-t)*t*t*(b-t2)+t**3*b).tolist())
    output[-1]=v[-1].tolist()
    return output


def refine_network(paths):
    """Snap near-axis architecture consistently at shared graph junctions."""
    paths=[np.asarray(p,float) for p in paths]
    constraints={};axes={}
    for i,p in enumerate(paths):
        if len(p)<3:continue
        span=np.ptp(p,axis=0)
        axis=int(np.argmin(span));other=1-axis
        if span[other]<18 or span[axis]>3:continue
        target=float(np.median(p[:,axis]))
        if np.quantile(abs(p[:,axis]-target),.95)>1.3:continue
        axes[i]=(axis,target)
    # Collinear runs separated by T junctions share one fitted coordinate.
    # Fitting each branch independently creates tiny zigzags along a long wall.
    by_node={}
    for i,(axis,target) in axes.items():
        for endpoint in (paths[i][0],paths[i][-1]):by_node.setdefault((axis,tuple(endpoint)),[]).append(i)
    remaining=set(axes)
    while remaining:
        seed=min(remaining);remaining.remove(seed);group=[seed];todo=[seed]
        while todo:
            i=todo.pop();axis=axes[i][0]
            for endpoint in (paths[i][0],paths[i][-1]):
                for j in by_node[axis,tuple(endpoint)]:
                    if j in remaining:remaining.remove(j);group.append(j);todo.append(j)
        axis=axes[seed][0]
        target=float(np.median(np.concatenate([paths[i][:,axis] for i in group])))
        for i in group:axes[i]=(axis,target)
    for i,(axis,target) in axes.items():
        p=paths[i]
        for endpoint in (p[0],p[-1]):
            constraints.setdefault(tuple(endpoint),{}).setdefault(axis,[]).append(target)
    mapping={}
    for node,values in constraints.items():
        point=np.array(node)
        for axis,targets in values.items():point[axis]=np.median(targets)
        mapping[node]=point
    for i,p in enumerate(paths):
        start=mapping.get(tuple(p[0]),p[0]).copy();end=mapping.get(tuple(p[-1]),p[-1]).copy()
        if i in axes:
            # Two common nodes define one exact line; this also keeps branches
            # connected when the perpendicular wall snaps its other coordinate.
            paths[i]=np.array([start,end])
        else:
            p[0]=start;p[-1]=end
    return [p.tolist() for p in paths]


def join_continuations(paths):
    """Join only strokes sharing the very same junction, never bridge a gap."""
    paths=[list(map(tuple,p)) for p in paths]
    while True:
        nodes={}
        for i,p in enumerate(paths):
            if p[0]==p[-1]:continue
            for side in (0,-1):nodes.setdefault(p[side],[]).append((i,side))
        best=None
        for node,refs in nodes.items():
            for n,(i,side) in enumerate(refs):
                a=paths[i] if side==0 else paths[i][::-1]
                u=np.array(next((pt for pt in a[1:] if np.linalg.norm(np.array(pt)-node)>=5),a[-1]))-node
                for j,end in refs[n+1:]:
                    if i==j:continue
                    b=paths[j] if end==0 else paths[j][::-1]
                    v=np.array(next((pt for pt in b[1:] if np.linalg.norm(np.array(pt)-node)>=5),b[-1]))-node
                    score=float(np.dot(u,v)/max(1e-9,np.linalg.norm(u)*np.linalg.norm(v)))
                    if score<-.965 and (best is None or score<best[0]):best=(score,i,j,a,b)
        if best is None:break
        _,i,j,a,b=best
        paths=[p for k,p in enumerate(paths) if k not in (i,j)]+[a[::-1]+b[1:]]
    return paths
