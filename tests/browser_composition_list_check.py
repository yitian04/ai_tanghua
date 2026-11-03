"""Long object lists retain their nodes and scroll viewport during edits."""
import json
from pathlib import Path
import sys
import uuid
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.core.assets import AssetLibrary
from src.core.models import Trajectory,TrajectoryPoint
from src.pipeline.trajectory_composition.composer import Composition,make_item


def main():
    prefix='list_check_'+uuid.uuid4().hex[:8];lib=AssetLibrary(ROOT)
    output=ROOT/'.artifacts/software_checks';output.mkdir(parents=True,exist_ok=True)
    doc=Composition();trajectory=Trajectory([TrajectoryPoint(0,0,1,10,True),TrajectoryPoint(20,10,1,10,True)])
    for index in range(45):
        item=make_item(trajectory,f'元素 {index+1:02}',doc.plane)
        item.x_mm=100;item.y_mm=100
        if index==44:item.x_mm=-10
        doc.items.append(item)
    source=output/(prefix+'.project.json');source.write_text(json.dumps(doc.to_dict()),encoding='utf-8')
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            page=browser.new_page(viewport={'width':1500,'height':1100});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8527')
            page.get_by_test_id('stSidebar').get_by_text('轨迹合成',exact=True).click()
            page.get_by_role('button',name='本地上传',exact=True).nth(1).click()
            dialog=page.get_by_role('dialog');dialog.locator('input[type="file"]').set_input_files(source)
            dialog.get_by_role('button',name='预览上传文件',exact=True).click();dialog.get_by_role('button',name='导入并使用',exact=True).click()
            page.get_by_role('button',name='打开工程',exact=True).click()
            objects=page.get_by_role('list',name='对象管理，按从上到下的顺序绘制');rows=objects.get_by_role('listitem');expect(rows).to_have_count(45)
            assert not page.get_by_text('对象管理 · 从上到下绘制',exact=True).count()
            expect(rows.last).to_have_attribute('data-outside','true');expect(rows.last.locator('.pick')).to_have_css('color','rgb(185, 28, 28)')
            expect(rows.first).to_have_attribute('data-outside','false')
            objects.evaluate('n=>{window.__savedObjectList=n;n.scrollTop=n.scrollHeight}')
            bottom=objects.evaluate('n=>n.scrollTop');assert bottom>500,bottom
            objects.evaluate('''n=>{window.__listScrollWatch={samples:[],stop:false};const watch=()=>{if(window.__listScrollWatch.stop)return;window.__listScrollWatch.samples.push(n.isConnected?n.scrollTop:-1);requestAnimationFrame(watch)};watch()}''')
            rows.last.locator('.pick').click();expect(page.get_by_label('对象名称',exact=True)).to_have_value('元素 45')
            idle(page);page.wait_for_timeout(150)
            assert objects.evaluate('n=>n===window.__savedObjectList')
            assert abs(objects.evaluate('n=>n.scrollTop')-bottom)<2
            samples=page.evaluate('window.__listScrollWatch.stop=true;window.__listScrollWatch.samples')
            assert min(samples)>=bottom-2,samples
            # Correcting an out-of-bounds selected object immediately clears red.
            page.get_by_label('中心 X mm',exact=True).fill('100');page.get_by_role('button',name='应用对象修改',exact=True).click()
            expect(rows.last).to_have_attribute('data-outside','false');idle(page)
            assert abs(objects.evaluate('n=>n.scrollTop')-bottom)<2
            # Red updates during a captured canvas drag, then undo clears it.
            canvas=page.get_by_role('application');selected_id=rows.last.get_attribute('data-object-id')
            handle=canvas.locator(f'g[data-id="{selected_id}"] > rect').first;handle.scroll_into_view_if_needed()
            box=handle.bounding_box();target=canvas.evaluate('n=>{const p=new DOMPoint(-20,100).matrixTransform(n.getScreenCTM());return {x:p.x,y:p.y}}')
            page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2);page.mouse.down();page.mouse.move(target['x'],target['y'],steps=8)
            expect(rows.last).to_have_attribute('data-outside','true');page.mouse.up();idle(page)
            canvas.evaluate('n=>n.focus({preventScroll:true})');page.keyboard.press('Control+z')
            expect(rows.last).to_have_attribute('data-outside','false');idle(page);at_bottom(objects)
            # Reorder adjacent bottom rows, then delete/undo without losing bottom.
            rows.last.locator('.grip').drag_to(rows.nth(43),target_position={'x':20,'y':2})
            expect(rows.nth(43).locator('.pick')).to_have_text('44. 元素 45');idle(page);at_bottom(objects)
            rows.last.locator('.remove').click();expect(rows).to_have_count(44);idle(page);at_bottom(objects)
            canvas=page.get_by_role('application');canvas.evaluate('n=>n.focus({preventScroll:true})');page.keyboard.press('Control+z')
            expect(rows).to_have_count(45);idle(page);at_bottom(objects)
            # Copy/paste adds an independent object and follows the new bottom row.
            canvas.evaluate('n=>n.focus({preventScroll:true})');page.keyboard.press('Control+c');page.keyboard.press('Control+v')
            expect(rows).to_have_count(46);idle(page);at_bottom(objects)
            # A middle viewport remains anchored after selecting another visible row.
            objects.evaluate('n=>n.scrollTop=(n.scrollHeight-n.clientHeight)/2');middle=objects.evaluate('n=>n.scrollTop')
            visible_id=objects.evaluate('n=>[...n.querySelectorAll(".row")].find(r=>r.offsetTop>n.scrollTop+10).dataset.objectId')
            objects.locator(f'[data-object-id="{visible_id}"] .pick').click();idle(page)
            assert abs(objects.evaluate('n=>n.scrollTop')-middle)<2
            # Leaving the page releases the DOM; returning restores its viewport.
            sidebar=page.get_by_test_id('stSidebar');sidebar.get_by_text('数字文件',exact=True).click()
            expect(page.get_by_role('heading',name='数字文件',exact=True)).to_be_visible()
            sidebar.get_by_text('轨迹合成',exact=True).click();expect(rows).to_have_count(46)
            assert abs(objects.evaluate('n=>n.scrollTop')-middle)<2
            page.screenshot(path=str(output/'composition_list_scroll.png'),full_page=True)
            assert not errors,errors
            assert not page.get_by_test_id('stException').count()
            browser.close()
        print('PASS: 45-object list, red bounds, no scroll-to-top frames, stable edit/reorder/delete/undo/paste and middle anchor')
    finally:
        for item in lib.scan():
            if item['name'].startswith(prefix):lib.delete(item)
        for item in lib.trash_items():
            if item['name'].startswith(prefix):lib.purge(item['trash_id'])


def idle(page):
    page.wait_for_function('() => [...window.__tanghuaLayoutSessions.values()].every(s=>!s.pending&&!s.queue.length)',timeout=20000)


def at_bottom(objects):
    assert objects.evaluate('n=>Math.abs(n.scrollHeight-n.clientHeight-n.scrollTop)<2')


if __name__=='__main__':main()
