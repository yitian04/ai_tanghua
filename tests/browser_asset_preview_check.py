"""Owned fixture only: preview controls belong to the left rail."""
import json
import sys
import uuid
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.core.assets import AssetLibrary
from src.core.models import Trajectory,TrajectoryPoint
lib=AssetLibrary(ROOT)
name='preview_layout_'+uuid.uuid4().hex+'.json'
payload=json.dumps(Trajectory([TrajectoryPoint(0,0,10,40,False),TrajectoryPoint(0,0,0,40,False),TrajectoryPoint(10,10,0,20,True)]).to_dict()).encode()
item=lib.import_file(payload,name)
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
        page=browser.new_page(viewport={'width':1400,'height':900})
        page.goto('http://127.0.0.1:8531')
        page.get_by_test_id('stSidebar').get_by_text('素材库',exact=True).click()
        dialog=page.get_by_role('dialog')
        search=dialog.get_by_label('搜索名称',exact=True);search.fill(name);search.press('Enter')
        card=dialog.get_by_role('listitem');expect(card).to_have_count(1,timeout=30000)
        card.locator('.open').click()
        left=dialog.locator('.st-key-asset_left');right=dialog.locator('.st-key-asset_right')
        expect(dialog.get_by_label('搜索名称',exact=True)).to_have_count(0)
        expect(left.get_by_role('button',name='在文件夹中显示')).to_be_visible()
        expect(left.get_by_role('button',name='移入回收站',exact=True)).to_be_visible()
        expect(right.get_by_role('button',name='在文件夹中显示')).to_have_count(0)
        expect(right.get_by_role('spinbutton',name='绘制速度 mm/s',exact=True)).to_have_count(0)
        left.get_by_text('统一绘制速度',exact=True).click()
        speed=left.get_by_role('spinbutton',name='绘制速度 mm/s',exact=True)
        speed.fill('12');speed.press('Enter')
        expect(left.get_by_role('button',name='保存修改',exact=True)).to_be_enabled()
        assert lib.read(item)==payload
        left.get_by_role('button',name='取消 / 返回',exact=True).click()
        expect(dialog.get_by_label('搜索名称',exact=True)).to_have_value(name)
        expect(card).to_have_count(1)
        card.locator('.open').click()
        expect(left.get_by_label('统一绘制速度',exact=True)).not_to_be_checked()
        left.get_by_text('统一绘制速度',exact=True).click()
        speed=left.get_by_role('spinbutton',name='绘制速度 mm/s',exact=True)
        speed.fill('15');speed.press('Enter')
        left.get_by_role('button',name='保存修改',exact=True).click()
        left.get_by_role('button',name='确认覆盖',exact=True).click()
        expect(left.get_by_label('统一绘制速度',exact=True)).not_to_be_checked()
        saved=lib.inspect(item['id'])
        assert json.loads(lib.read(saved))['points'][-1]['speed_mm_s']==15
        page.set_viewport_size({'width':620,'height':850})
        expect(left.get_by_role('button',name='取消 / 返回',exact=True)).to_be_visible()
        assert right.bounding_box()['x']>left.bounding_box()['x']
        left.get_by_role('button',name='移入回收站',exact=True).click()
        expect(dialog.get_by_label('搜索名称',exact=True)).to_have_value(name)
        assert not lib.path(item['id']).exists()
        dialog.get_by_role('button',name='回收站 (',exact=False).click()
        expect(card).to_have_count(1)
        card.locator('.open').click()
        expect(left.get_by_role('button',name='永久删除',exact=True)).to_be_visible()
        expect(left.get_by_role('spinbutton')).to_have_count(0)
        left.get_by_role('button',name='永久删除',exact=True).click()
        expect(left.get_by_role('button',name='确认永久删除',exact=True)).to_be_visible()
        left.get_by_role('button',name='取消删除',exact=True).click()
        left.get_by_role('button',name='恢复',exact=True).click()
        assert not page.get_by_test_id('stException').count()
        browser.close()
        print('PASS: left controls, preview-only right, unsaved discard, filter restore, narrow window')
finally:
    lib.path(item['id']).unlink(missing_ok=True)
    for record in lib.trash_items():
        if record['name']==name: lib.purge(record['trash_id'])
