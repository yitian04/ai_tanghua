"""Direct batch import and independent SVG/URP categories, using owned fixtures."""
import csv
import io
import json
from pathlib import Path
import sys
import uuid
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.core.assets import AssetLibrary
from src.core.models import Trajectory,TrajectoryPoint


def main():
    lib=AssetLibrary(ROOT);prefix='direct_batch_'+uuid.uuid4().hex[:8]
    trajectory=Trajectory([TrajectoryPoint(0,0,1,10,True),TrajectoryPoint(12,8,1,10,True)])
    payload=json.dumps(trajectory.to_dict()).encode()
    rows=[point.to_dict() for point in trajectory.points]
    buffer=io.StringIO();writer=csv.DictWriter(buffer,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    first=lib.import_file(payload,prefix+'_a.json')
    second=lib.import_file(buffer.getvalue().encode(),prefix+'_b.csv')
    lib.import_file(b'<URProgram/>',prefix+'.urp')
    lib.import_file(b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L20 10"/></svg>',prefix+'.svg')
    output=ROOT/'.artifacts/software_checks';output.mkdir(parents=True,exist_ok=True)
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            page=browser.new_page(viewport={'width':1450,'height':950},accept_downloads=True)
            page.goto(sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8525')
            sidebar=page.get_by_test_id('stSidebar');sidebar.get_by_text('轨迹合成',exact=True).click()
            expect(page.get_by_role('heading',name='轨迹合成',exact=True)).to_be_visible()
            assert not page.get_by_role('button',name='添加已确认轨迹',exact=True).count()
            page.get_by_role('button',name='从素材库选择',exact=True).first.click()
            dialog=page.get_by_role('dialog').filter(has=page.locator('.st-key-asset_shell'))
            search=dialog.get_by_label('搜索名称',exact=True);search.fill(prefix);search.press('Enter')
            cards=dialog.get_by_role('listitem');expect(cards).to_have_count(2,timeout=30000)
            action=dialog.locator('.asset-footer').get_by_role('button',name='导入轨迹',exact=True)
            expect(action).to_be_disabled()
            cards.filter(has_text=first['name']).locator('.open').click()
            cards.filter(has_text=second['name']).get_by_role('checkbox').check()
            expect(dialog.get_by_text('已选 2 项（跨页保留）',exact=True)).to_be_visible()
            expect(action).to_be_enabled();expect(action).to_have_css('background-color','rgb(180, 35, 54)')
            footer,button=action.evaluate('(n)=>[n.closest("footer").getBoundingClientRect().toJSON(),n.getBoundingClientRect().toJSON()]')
            assert abs(button['x']+button['width']-footer['x']-footer['width'])<3
            page.screenshot(path=str(output/'batch_import_ready.png'))
            action.click();expect(dialog).not_to_be_visible()
            objects=page.get_by_role('list',name='对象管理，按从上到下的顺序绘制').get_by_role('listitem')
            expect(objects).to_have_count(2)
            expect(objects.nth(0)).to_contain_text(first['name']);expect(objects.nth(1)).to_contain_text(second['name'])
            # One undo removes the whole batch; redo restores it.
            canvas=page.get_by_role('application');canvas.focus();page.keyboard.press('Control+z')
            expect(objects).to_have_count(0);canvas.focus();page.keyboard.press('Control+Shift+z');expect(objects).to_have_count(2)
            page.wait_for_function('() => [...window.__tanghuaLayoutSessions.values()].every(s=>!s.pending&&!s.queue.length)',timeout=20000)
            page.wait_for_function("() => !document.querySelector('[data-testid=stStatusWidget]')",timeout=20000)
            # Upload multiple files directly, without a preview-confirmation step.
            upload=page.get_by_role('button',name='本地上传',exact=True).first
            expander=page.locator('details').filter(has=page.get_by_text('导入轨迹 / 打开工程',exact=True))
            expander.locator('summary').scroll_into_view_if_needed()
            if expander.get_attribute('open') is None: expander.locator('summary').click()
            expect(expander).to_have_attribute('open','')
            page.get_by_test_id('stMain').evaluate('node=>node.scrollTop=0')
            upload.click();import_upload=dialog.get_by_role('button',name='导入轨迹',exact=True)
            expect(import_upload).to_be_disabled()
            dialog.locator('input[type="file"]').set_input_files([
                {'name':prefix+'_upload_a.json','mimeType':'application/json','buffer':payload},
                {'name':prefix+'_upload_b.csv','mimeType':'text/csv','buffer':buffer.getvalue().encode()}])
            expect(import_upload).to_be_enabled()
            bar=dialog.locator('.st-key-asset_upload_footer').bounding_box();pane=dialog.locator('.st-key-asset_detail').bounding_box()
            assert pane['height']>600,pane
            assert abs(bar['y']+bar['height']-pane['y']-pane['height'])<12,(bar,pane)
            page.screenshot(path=str(output/'batch_upload_ready.png'))
            import_upload.click();expect(dialog).not_to_be_visible();expect(objects).to_have_count(4)
            sidebar.get_by_text('素材库',exact=True).click()
            search.fill(prefix);search.press('Enter');expect(cards).to_have_count(6,timeout=30000)
            dialog.get_by_text('SVG',exact=True).click();expect(cards).to_have_count(1)
            expect(cards.first).to_contain_text('.svg')
            dialog.get_by_text('执行文件（URP）',exact=True).click();expect(cards).to_have_count(1)
            expect(cards.first).to_contain_text('.urp')
            page.screenshot(path=str(output/'urp_category.png'))
            assert not page.get_by_test_id('stException').count()
            browser.close()
        print('PASS: ordered JSON/CSV batch import, direct multi-upload, footer highlight, single-step undo, SVG/URP categories')
    finally:
        for item in lib.scan():
            if item['name'].startswith(prefix): lib.delete(item)
        for item in lib.trash_items():
            if item['name'].startswith(prefix): lib.purge(item['trash_id'])


if __name__=='__main__':main()
