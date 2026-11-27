"""Normalize a deliberately small SVG stylesheet subset before sampling."""
import re

PROPERTIES = {'fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin',
              'stroke-miterlimit', 'fill-rule', 'opacity', 'fill-opacity',
              'stroke-opacity', 'display', 'visibility'}


def normalize_styles(root):
    rules=[]
    for node in list(root.iter()):
        if node.tag.split('}')[-1] != 'style':continue
        text=re.sub(r'/\*.*?\*/','',node.text or '',flags=re.S)
        if '@' in text or re.search(r'url\s*\(',text,re.I):
            raise ValueError('SVG 样式不支持外部引用或复杂规则，请先展开为普通路径。')
        blocks=list(re.finditer(r'([^{}]+)\{([^{}]*)\}',text))
        if re.sub(r'[^{}]+\{[^{}]*\}','',text).strip():
            raise ValueError('SVG 样式语法不受支持。')
        for block in blocks:
            declarations={}
            for declaration in block[2].split(';'):
                if not declaration.strip():continue
                if ':' not in declaration:raise ValueError('SVG 样式声明无效。')
                name,value=map(str.strip,declaration.split(':',1))
                if name not in PROPERTIES or '!important' in value:
                    raise ValueError('SVG 尚不支持此样式：'+name+'。请先展开为普通路径。')
                declarations[name]=value
            for selector in block[1].split(','):
                selector=selector.strip()
                if not re.fullmatch(r'(?:[A-Za-z_][\w-]*)?(?:[.#][\w-]+)*|\*',selector) or not selector:
                    raise ValueError('SVG 尚不支持此样式选择器：'+selector)
                specificity=(selector.count('#'),selector.count('.'),int(bool(re.match(r'^[A-Za-z_]',selector))))
                rules.append((specificity,len(rules),selector,declarations))
    for node in root.iter():
        tag=node.tag.split('}')[-1]
        if tag in {'metadata','style','defs'}:continue
        computed={}
        for _,__,selector,declarations in sorted(rules):
            kind=re.match(r'^[A-Za-z_][\w-]*',selector)
            if kind and kind[0]!=tag:continue
            if any(v!=node.get('id') for v in re.findall(r'#([\w-]+)',selector)):continue
            if not set(re.findall(r'\.([\w-]+)',selector))<=set(node.get('class','').split()):continue
            computed.update(declarations)
        # Stylesheets override presentation attributes; inline style overrides both.
        for declaration in node.get('style','').split(';'):
            if ':' in declaration:
                name,value=map(str.strip,declaration.split(':',1));computed[name]=value
        for name,value in computed.items():node.set(name,value)
        node.attrib.pop('style',None)
    def strip(parent):
        for child in list(parent):
            tag=child.tag.split('}')[-1]
            if tag in {'metadata','style'}:parent.remove(child)
            elif tag=='defs':
                if any(n.tag.split('}')[-1]!='style' for n in list(child)):
                    raise ValueError('SVG defs 含尚不支持的图形定义，请先展开引用、裁切或蒙版。')
                parent.remove(child)
            else:strip(child)
    strip(root)
    return root
