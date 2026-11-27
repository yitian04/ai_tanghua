"""Click-to-open full-window image viewer shared by image and curve previews."""
import base64
import hashlib
import io
from pathlib import Path
import streamlit as st
from PIL import Image, UnidentifiedImageError
import xml.etree.ElementTree as ET


def payload_mime(payload):
    # PNG metadata can itself contain SVG/XML snippets. Decode the actual
    # raster container first, rather than searching arbitrary header bytes.
    try:
        with Image.open(io.BytesIO(payload)) as image:
            return Image.MIME.get(image.format,'image/png')
    except UnidentifiedImageError:
        try:root=ET.fromstring(payload)
        except ET.ParseError as exc:raise ValueError('无法识别预览图片格式。') from exc
        if root.tag.split('}')[-1]!='svg':raise ValueError('预览内容不是图片或 SVG。')
        return 'image/svg+xml'


def _component(script):
    import streamlit.components.v2 as components
    return components.component('image_viewer_'+hashlib.sha256(script.encode()).hexdigest()[:12],js=script)


def image_viewer(source, key=None, filename='preview.png', **_):
    if isinstance(source,(str,Path)):
        if str(source).lstrip().startswith('<'):
            payload=str(source).encode();mime='image/svg+xml';filename=Path(filename).stem+'.svg'
        else:
            path=Path(source);payload=path.read_bytes();filename=path.name
            mime='image/svg+xml' if path.suffix.lower()=='.svg' else Image.MIME.get(Image.open(io.BytesIO(payload)).format,'image/png')
    elif isinstance(source,bytes):
        payload=source
        mime=payload_mime(payload)
    else:
        image=source if isinstance(source,Image.Image) else Image.fromarray(source)
        buffer=io.BytesIO();image.save(buffer,format='PNG');payload=buffer.getvalue();mime='image/png'
    data={'src':'data:'+mime+';base64,'+base64.b64encode(payload).decode(),'filename':filename}
    script=(Path(__file__).parent/'components/image_viewer.js').read_text(encoding='utf-8')
    position=st._main._get_delta_path_str()
    identity=str(key) if key is not None else hashlib.sha256((position+hashlib.sha256(payload).hexdigest()).encode()).hexdigest()[:16]
    _component(script)(key='image_viewer_'+identity,data=data,height='content')


def figure_viewer(figure,key=None,**_):
    buffer=io.BytesIO();figure.savefig(buffer,format='svg',bbox_inches='tight')
    image_viewer(buffer.getvalue(),key=key,filename='curves.svg')
