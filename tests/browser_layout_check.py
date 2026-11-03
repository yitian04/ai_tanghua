"""Real browser regression check for layout editing (requires Playwright + Chrome)."""
import json
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.core.models import Trajectory, TrajectoryPoint
from src.pipeline.trajectory_composition.composer import Composition, make_item


def main():
    directory=ROOT/'.artifacts'/'software_checks';directory.mkdir(parents=True,exist_ok=True)
    doc=Composition()
    item=make_item(Trajectory([TrajectoryPoint(0,0,1,10,True),TrajectoryPoint(40,20,1,10,True)]),'对象 A',doc.plane)
    item.x_mm=item.y_mm=100;doc.items.append(item)
    path=directory/'layout_input.project.json';path.write_text(json.dumps(doc.to_dict()),encoding='utf-8')
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
        page=browser.new_page(viewport={'width':1600,'height':1100},accept_downloads=True)
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8514')
        page.get_by_test_id('stSidebar').get_by_text('轨迹合成',exact=True).click()
        page.get_by_role('button',name='本地上传',exact=True).nth(1).click()
        dialog=page.get_by_role('dialog')
        dialog.locator('input[type="file"]').set_input_files(path)
        dialog.get_by_role('button',name='预览上传文件',exact=True).click()
        dialog.get_by_role('button',name='导入并使用',exact=True).click()
        page.get_by_role('button',name='打开工程',exact=True).click()
        canvas=page.get_by_role('application');expect(canvas).to_be_visible()
        rows=page.get_by_role('listitem');expect(rows).to_have_count(1)
        page.wait_for_function("() => !document.querySelector('[data-testid=stStatusWidget]')",timeout=20000)
        handle=canvas.locator('[data-handle="rotate"]').last
        handle.scroll_into_view_if_needed()
        expect(handle).to_have_css('cursor',__import__('re').compile('.*data:image/svg.*'))
        box=handle.bounding_box()
        # Bottom-right outer hotspot (125,115), rotated 90 degrees around (100,100).
        target=canvas.evaluate('(svg)=>{let p=new DOMPoint(85,125).matrixTransform(svg.getScreenCTM());return {x:p.x,y:p.y}}')
        page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2)
        page.keyboard.down('Shift')
        page.mouse.down();page.mouse.move(target['x'],target['y'],steps=12);page.mouse.up()
        page.keyboard.up('Shift')
        try:
            expect(page.get_by_label('旋转 deg',exact=True)).to_have_value('90.00',timeout=15000)
        except AssertionError:
            print('ROTATION STATE',page.evaluate('() => [...(window.__tanghuaLayoutSessions||new Map()).entries()]'))
            print('ERRORS',errors)
            page.screenshot(path=str(directory/'layout_failure.png'),full_page=True)
            raise
        canvas.focus()
        page.keyboard.press('Control+c');page.keyboard.press('Control+v')
        try:
            expect(rows).to_have_count(2,timeout=15000)
        except AssertionError:
            print('FRONTEND',page.evaluate('() => [...(window.__tanghuaLayoutSessions||new Map()).entries()]'))
            print('ERRORS',errors)
            page.screenshot(path=str(directory/'layout_failure.png'),full_page=True)
            raise
        expect(page.get_by_label('中心 X mm',exact=True)).to_have_value('110.00')
        canvas.focus();page.keyboard.press('Delete')
        expect(rows).to_have_count(1)
        canvas.focus();page.keyboard.press('Control+z')
        expect(rows).to_have_count(2)
        canvas.focus();page.keyboard.press('Control+z')
        expect(rows).to_have_count(1)
        canvas.focus();page.keyboard.press('Control+Shift+z')
        expect(rows).to_have_count(2)
        # Reorder by dragging the second grip above the first row.
        grip=rows.nth(1).locator('.grip');target=rows.first
        grip.drag_to(target,target_position={'x':20,'y':2})
        expect(rows.first.locator('.pick')).to_have_text('1. 对象 A 副本')
        # Typing Delete / Ctrl+Z in the properties must not remove a layout object.
        name=page.get_by_label('对象名称',exact=True);name.focus();page.keyboard.press('Control+a');page.keyboard.press('Delete')
        expect(rows).to_have_count(2)
        # Row deletion, then undo from the canvas.
        rows.first.locator('.remove').click();expect(rows).to_have_count(1)
        canvas.focus();page.keyboard.press('Control+z');expect(rows).to_have_count(2)
        with page.expect_download() as download:page.get_by_role('button',name='下载合成工程',exact=True).click()
        download.value.save_as(directory/'layout_checked.project.json')
        saved=json.loads((directory/'layout_checked.project.json').read_text(encoding='utf-8'))
        assert saved['items'][0]['name']=='对象 A 副本'
        assert abs(saved['items'][0]['rotation_deg']-90)<1e-6
        assert len({i['id'] for i in saved['items']})==2
        page.screenshot(path=str(directory/'layout_editing.png'),full_page=True)
        assert not errors,errors
        assert page.get_by_test_id('stException').count()==0
        page.get_by_test_id('stSidebar').get_by_text('素材库',exact=True).click()
        assets=page.get_by_role('dialog').filter(has=page.locator('.st-key-asset_shell'))
        expect(assets).to_be_visible()
        page.keyboard.press('Delete')
        assets.get_by_role('button',name='Close',exact=True).click()
        expect(rows).to_have_count(2)
        browser.close()
    print('PASS: rotation, rapid copy/paste, delete, undo/redo, drag reorder, input isolation, export')


if __name__=='__main__':main()
