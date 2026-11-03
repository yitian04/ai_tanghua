"""Check shared file input geometry at desktop and narrow window widths."""
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]


def main():
    out=ROOT/'.artifacts'/'software_checks';out.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
        page=browser.new_page(viewport={'width':1400,'height':1100})
        page.goto(sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8517')
        sidebar=page.get_by_test_id('stSidebar')
        expect(sidebar.get_by_text('图像转曲线',exact=True)).to_be_attached(timeout=30000)
        for width in (1400,900,600):
            page.set_viewport_size({'width':width,'height':1100})
            for module in ('图像转曲线','轨迹规划','数字文件','轨迹合成'):
                # Navigation itself is tested elsewhere; do not open an overlay
                # sidebar over the narrow viewport whose geometry we measure.
                sidebar.get_by_text(module,exact=True).evaluate('node=>node.click()')
                expect(page.get_by_role('heading',name=module,exact=True)).to_be_visible(timeout=30000)
                first=page.get_by_role('button',name='本地上传',exact=True).first
                expect(first).to_be_visible()
                page.wait_for_function("() => !document.querySelector('[data-testid=stStatusWidget]')",timeout=30000)
                if module=='轨迹合成':
                    page.get_by_text('导入轨迹 / 打开工程',exact=True).click()
                    page.get_by_text('导入轨迹 / 打开工程',exact=True).click()
                groups=page.locator('[class*="st-key-asset_input_"]')
                assert groups.count()>0,'No shared input groups'
                for group in groups.all():
                    if not group.is_visible():continue
                    rects=group.locator('button').evaluate_all('nodes=>nodes.filter(n=>n.getClientRects().length).map(n=>{const b=n.getBoundingClientRect();const r=document.createRange();r.selectNodeContents(n);const t=r.getBoundingClientRect();return {x:b.x,y:b.y,r:b.right,b:b.bottom,w:b.width,h:b.height,tx:t.x,ty:t.y,tr:t.right,tb:t.bottom}})')
                    label=group.locator('strong').first.bounding_box()
                    assert min(r['y'] for r in rects)>=label['y']+label['height']+6,(label,rects)
                    for rect in rects:
                        assert rect['h']>=32,rect
                        assert rect['tx']>=rect['x']-1 and rect['tr']<=rect['r']+1,rect
                        assert rect['ty']>=rect['y']-1 and rect['tb']<=rect['b']+1,rect
                    for a,b in zip(rects,rects[1:]):
                        assert min(a['r'],b['r'])<=max(a['x'],b['x'])+1 or min(a['b'],b['b'])<=max(a['y'],b['y'])+1,(a,b)
                if module=='图像转曲线':
                    assert page.get_by_text('图像输入',exact=True).count()==1
                    page.screenshot(path=str(out/f'input_layout_{width}.png'),full_page=True)
                assert not page.get_by_test_id('stException').count()
        browser.close()
    print('PASS: one image input title; button labels contained and inputs separated at 1400/900/600px')


if __name__=='__main__':main()
