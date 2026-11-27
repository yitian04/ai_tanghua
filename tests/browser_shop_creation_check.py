"""Exercise the real shop component without spending image-model calls."""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]


def main():
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
        page=browser.new_page(viewport={'width':1500,'height':1000},has_touch=True);errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto('http://127.0.0.1:8531')
        page.get_by_text('理想小店（白盒）',exact=True).first.click()
        region=page.get_by_role('region',name='理想小店创作');expect(region).to_be_visible(timeout=30000)
        def ready():expect(region.locator('.notice')).to_have_text('',timeout=15000)
        def stroke(offset):
            canvas=region.locator('canvas');r=canvas.bounding_box()
            page.mouse.move(r['x']+r['width']*.15,r['y']+r['height']*(.2+offset))
            page.mouse.down();page.mouse.move(r['x']+r['width']*.7,r['y']+r['height']*(.4+offset),steps=16);page.mouse.up()
            expect(region.locator('.compose')).to_be_enabled(timeout=15000)
        stroke(0)
        # Use real touch events so pointer capture and touch-action are exercised.
        box=region.locator('canvas').bounding_box();cdp=page.context.new_cdp_session(page)
        x=box['x']+box['width']*.2;y=box['y']+box['height']*.65
        cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':x,'y':y}]})
        for i in range(1,8):
            cdp.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':x+i*12,'y':y+i*3}]})
        cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
        expect(region.locator('.compose')).to_be_enabled(timeout=15000)
        region.get_by_role('button',name='合成并预览',exact=True).click()
        expect(page.get_by_text('完整小店 · 合成预览',exact=True)).to_be_visible(timeout=15000)
        expect(page.get_by_role('button',name='保存手绘与合并曲线到素材库',exact=True)).to_be_enabled()
        with page.expect_download() as download:
            page.get_by_role('button',name='下载手绘原稿 JSON',exact=True).click()
        import json
        source=json.loads(Path(download.value.path()).read_text(encoding='utf-8'))
        assert len(source['curves'])==2,source
        region.get_by_role('button',name='撤销',exact=True).click()
        expect(page.get_by_role('button',name='保存手绘与合并曲线到素材库',exact=True)).to_be_disabled(timeout=15000)
        expect(region.locator('.compose')).to_be_enabled()
        region.get_by_role('button',name='✧ 描述生成',exact=True).click();ready()
        prompt=region.get_by_role('textbox');original=prompt.input_value()
        region.get_by_role('button',name='试试灵感 ↻',exact=True).click();ready()
        assert prompt.input_value()!=original
        region.get_by_role('button',name='几何折线',exact=True).click();ready()
        first=prompt.input_value();prompt.fill('测试自定义主题，不调用模型')
        region.get_by_role('button',name='舒展流线',exact=True).click();ready()
        expect(prompt).to_have_value('测试自定义主题，不调用模型')
        region.screenshot(path=str(ROOT/'.artifacts/shop/ai.png'))
        region.get_by_role('button',name='♧ 抽签',exact=True).click();ready()
        for _ in range(2):
            region.get_by_role('button',name='↻ 转动抽取',exact=True).click()
            expect(region.locator('.spin')).to_be_disabled()
            expect(region.locator('.spin')).to_be_enabled(timeout=15000)
            expect(region.locator('.result')).to_contain_text('今日好天气')
        region.screenshot(path=str(ROOT/'.artifacts/shop/wheel.png'))
        region.get_by_role('button',name='✎ 绘制',exact=True).click();ready()
        expect(region.locator('.compose')).to_be_enabled()
        region.get_by_role('button',name='清空',exact=True).click();ready()
        expect(region.locator('.compose')).to_be_disabled()
        region.get_by_role('button',name='撤销',exact=True).click();ready()
        expect(region.locator('.compose')).to_be_enabled()
        toggle=page.get_by_test_id('stSidebarCollapseButton')
        if toggle.is_visible():toggle.click()
        page.set_viewport_size({'width':390,'height':1000})
        page.wait_for_timeout(350)
        assert region.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
        region.screenshot(path=str(ROOT/'.artifacts/shop/mobile.png'))
        assert not page.locator('[data-testid=stException]').count()
        assert not errors,errors
        print('Browser checks passed: draw, compose, stale result, undo, clear, modes, inspiration, style, wheel, responsive layout')
        browser.close()


if __name__=='__main__':main()
