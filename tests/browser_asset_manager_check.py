"""Exercise compact asset management against owned, disposable fixtures only."""
import io
from pathlib import Path
import sys
import time
import uuid
from PIL import Image,ImageDraw
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.core.assets import AssetLibrary


def main():
    lib=AssetLibrary(ROOT);prefix='batch_check_'+uuid.uuid4().hex[:8]
    fixtures=[];out=ROOT/'.artifacts'/'software_checks';out.mkdir(parents=True,exist_ok=True)
    for n in range(31):
        image=Image.new('RGB',(120,80),'white');ImageDraw.Draw(image).line([(10,60),(60,10),(110,60)],fill='#0369a1',width=3)
        buffer=io.BytesIO();image.save(buffer,format='PNG');fixtures.append(lib.import_file(buffer.getvalue(),f'{prefix}_{n:02}.png'))
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            page=browser.new_page(viewport={'width':1450,'height':800});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8519')
            sidebar=page.get_by_test_id('stSidebar');sidebar.get_by_text('图像转曲线',exact=True).click();expect(page.get_by_role('heading',name='图像转曲线',exact=True)).to_be_visible()
            sidebar.get_by_text('素材库',exact=True).click()
            dialog=page.get_by_role('dialog').filter(has=page.locator('.st-key-asset_shell'))
            expect(dialog).to_be_visible()
            assert not dialog.get_by_role('button',name='关闭',exact=True).count()
            search=dialog.get_by_label('搜索名称',exact=True);search.fill(prefix);search.press('Enter')
            cards=dialog.get_by_role('listitem');expect(cards).to_have_count(24,timeout=30000)
            grid=dialog.locator('.asset-grid');left=dialog.locator('.st-key-asset_left');footer=dialog.locator('.asset-footer')
            expect(footer).to_contain_text('31 项',timeout=30000)
            expect(grid.locator('.picture img')).to_have_count(24,timeout=20000)
            initial=left.bounding_box();footer_initial=footer.bounding_box()
            outer_scroll=dialog.evaluate('n=>n.scrollTop')
            grid.hover();page.mouse.wheel(0,450)
            expect(grid).not_to_have_js_property('scrollTop',0,timeout=10000)
            assert abs(left.bounding_box()['y']-initial['y'])<2
            assert abs(footer.bounding_box()['y']-footer_initial['y'])<2
            assert dialog.evaluate('n=>n.scrollTop')==outer_scroll
            saved_scroll=grid.evaluate('n=>n.scrollTop')
            dialog.get_by_role('button',name='多选',exact=True).click()
            batch=footer.get_by_role('button',name='放入回收站',exact=True)
            expect(batch).to_be_disabled()
            expect(cards.first.locator('.open')).to_be_disabled()
            cards.first.get_by_role('checkbox').check();cards.nth(1).get_by_role('checkbox').check()
            expect(dialog.get_by_text('已选 2 项（跨页保留）',exact=True)).to_be_visible()
            expect(batch).to_be_enabled()
            expect(batch).to_have_css('background-color','rgb(180, 35, 54)')
            page_start=time.perf_counter()
            dialog.get_by_role('button',name='下一页',exact=True).click();expect(cards).to_have_count(7)
            print('Browser page change seconds',round(time.perf_counter()-page_start,3))
            cards.first.get_by_role('checkbox').check();expect(dialog.get_by_text('已选 3 项（跨页保留）',exact=True)).to_be_visible()
            search.fill(prefix+'_00');search.press('Enter');expect(cards).to_have_count(1)
            expect(dialog.get_by_text('已选 3 项（跨页保留）',exact=True)).to_be_visible()
            batch.click()
            expect(dialog.get_by_text('成功 3 项',exact=True)).to_be_visible()
            assert len([i for i in lib.trash_items() if i['name'].startswith(prefix)])==3
            assert not dialog.locator('.purge-modal[open]').count()
            # Cancel permanent deletion via Escape; library must remain open.
            dialog.get_by_role('button',name=__import__('re').compile(r'^回收站')).click()
            expect(dialog.locator('.asset-browser')).to_have_class(__import__('re').compile('is-trash'))
            expect(dialog.get_by_role('button',name='返回素材库',exact=True)).to_have_css('background-color','rgb(255, 255, 255)')
            search.fill(prefix);search.press('Enter');expect(cards).to_have_count(3)
            page.screenshot(path=str(out/'asset_trash_gray.png'))
            restored_name=cards.first.get_attribute('title')
            cards.first.get_by_role('button',name=__import__('re').compile('^恢复')).click()
            expect(cards).to_have_count(2)
            dialog.get_by_role('button',name='返回素材库',exact=True).click()
            expect(dialog).to_have_css('background-color','rgb(255, 255, 255)')
            expect(dialog.locator('.asset-browser')).not_to_have_class(__import__('re').compile('is-trash'))
            search.fill(restored_name);search.press('Enter');expect(cards).to_have_count(1)
            cards.first.get_by_role('button',name=__import__('re').compile('^移入回收站')).click()
            try: expect(cards).to_have_count(0)
            except AssertionError:
                print('RECYCLE physical',[(i['name'],lib.path(i['id']).exists()) for i in fixtures if i['name']==restored_name])
                print('RECYCLE dialog',dialog.inner_text())
                print('RECYCLE frontend',page.evaluate('() => [...window.__assetGridSessions.entries()].map(([id,s])=>({id,pending:s.pending,queue:s.queue}))'))
                raise
            dialog.get_by_role('button',name=__import__('re').compile(r'^回收站')).click()
            search.fill(prefix);search.press('Enter');expect(cards).to_have_count(3)
            dialog.get_by_role('button',name='清空回收站',exact=True).click()
            warning=dialog.locator('.purge-modal');expect(warning).to_be_visible()
            warning.get_by_role('button',name='取消',exact=True).click();expect(warning).not_to_be_visible()
            cards.first.get_by_role('button',name=__import__('re').compile('^永久删除')).click()
            warning=dialog.locator('.purge-modal');expect(warning).to_be_visible()
            page.keyboard.press('Escape');expect(warning).not_to_be_visible();expect(dialog).to_be_visible()
            dialog.get_by_role('button',name='多选',exact=True).click()
            dialog.get_by_role('button',name='全选本页',exact=True).click()
            footer.get_by_role('button',name='永久删除',exact=True).click();expect(warning).to_be_visible()
            warning.get_by_role('button',name='确认永久删除',exact=True).click();expect(cards).to_have_count(0)
            # Return and verify card click, preview, and retained search/page.
            dialog.get_by_role('button',name='返回素材库',exact=True).click()
            expect(dialog).to_have_css('background-color','rgb(255, 255, 255)')
            for _ in range(3):
                dialog.get_by_role('button',name=__import__('re').compile(r'^回收站')).click()
                expect(dialog).to_have_css('background-color','rgb(243, 244, 246)')
                expect(dialog.locator('.asset-browser')).to_have_class(__import__('re').compile('is-trash'))
                dialog.get_by_role('button',name='返回素材库',exact=True).click()
                expect(dialog).to_have_css('background-color','rgb(255, 255, 255)')
                expect(dialog.locator('.asset-browser')).not_to_have_class(__import__('re').compile('is-trash'))
            search.fill(prefix);search.press('Enter');expect(cards).to_have_count(24)
            cards.first.locator('.open').click();expect(dialog.get_by_role('button',name='下载文件',exact=True)).to_be_visible()
            dialog.get_by_role('button',name='返回素材',exact=True).click();expect(cards).to_have_count(24)
            search.fill('');search.press('Enter')
            page.wait_for_function("() => !document.querySelector('[data-testid=stStatusWidget]')",timeout=30000)
            page.screenshot(path=str(out/'asset_manager_compact.png'),full_page=True)
            page.set_viewport_size({'width':650,'height':850})
            page.screenshot(path=str(out/'asset_manager_narrow.png'),full_page=True)
            assert not page.get_by_test_id('stException').count()
            assert not errors,errors
            dialog.get_by_role('button',name='Close',exact=True).click()
            page.set_viewport_size({'width':1450,'height':1000})
            start=time.perf_counter();sidebar.get_by_text('素材库',exact=True).evaluate('node=>node.click()')
            expect(dialog.get_by_role('listitem').first).to_be_visible()
            print('WARM browser first cards seconds',round(time.perf_counter()-start,3))
            browser.close()
        print('PASS: fixed controls/scroll, card preview, cross-page selection, batch recycle/purge, Escape cancellation')
    finally:
        for item in fixtures:
            try: lib.delete(lib.inspect(item['id']))
            except (ValueError,OSError): pass
        for item in lib.trash_items():
            if item['name'].startswith(prefix): lib.purge(item['trash_id'])


if __name__=='__main__':main()
