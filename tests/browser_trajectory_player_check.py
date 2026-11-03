"""Real browser integration for the three shared player entry points."""
import json
from pathlib import Path
import sys
import uuid
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.core.assets import AssetLibrary
from src.core.models import Trajectory,TrajectoryPoint as P


def main():
    lib=AssetLibrary(ROOT);prefix='SIM'+uuid.uuid4().hex[:7]
    trajectory=Trajectory([P(0,0,10,1,False),P(0,0,0,1,False),P(0,0,0,2,True),P(10,0,0,2,True),P(10,0,10,1,False),P(10,5,10,1,False),P(10,5,0,1,False),P(10,5,0,2,True,curve_id=8),P(20,5,0,2,True,curve_id=8),P(20,5,10,1,False,curve_id=8)])
    item=lib.import_file(json.dumps(trajectory.to_dict()).encode(),prefix+'.json')
    output=ROOT/'.artifacts/software_checks';output.mkdir(parents=True,exist_ok=True)
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            page=browser.new_page(viewport={'width':1450,'height':950});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8525')
            sidebar=page.get_by_test_id('stSidebar');sidebar.get_by_text('素材库',exact=True).click()
            dialog=page.get_by_role('dialog').filter(has=page.locator('.st-key-asset_shell'))
            search=dialog.get_by_label('搜索名称',exact=True);search.fill(item['name']);search.press('Enter')
            card=dialog.get_by_role('listitem');expect(card).to_have_count(1,timeout=30000);card.locator('.open').click()
            player=page.get_by_role('region',name='轨迹执行模拟器',exact=True)
            expect(player).to_be_visible(timeout=15000)
            expect(player).to_have_attribute('data-playing','false');expect(player).to_have_attribute('data-point-index','0')
            expect(player.locator('.swatch')).to_have_css('background-color','rgb(194, 65, 12)')
            expect(player.get_by_role('button',name='上一笔',exact=True)).to_be_disabled()
            jump=player.get_by_label('跳转笔号',exact=True);jump.fill('2');player.get_by_role('button',name='跳转',exact=True).click()
            expect(player).to_have_attribute('data-point-index','7');expect(player).to_have_attribute('data-playing','false')
            expect(player.locator('.swatch')).to_have_css('background-color','rgb(3, 105, 161)')
            def path_pixel():
                return player.locator('canvas').evaluate('''c=>{const w=c.clientWidth,h=c.clientHeight,s=Math.min((w-48)/20,(h-48)/5),x=w/2-5*s,y=h/2-2.5*s;return [...c.getContext('2d').getImageData(Math.round(x*c.width/w),Math.round(y*c.height/h),1,1).data];}''')
            assert path_pixel()[0]<100,path_pixel()
            expect(player.get_by_role('button',name='下一笔',exact=True)).to_be_disabled()
            player.get_by_role('button',name='上一笔',exact=True).click();expect(player).to_have_attribute('data-point-index','2')
            assert path_pixel()[0]>150,path_pixel()
            jump.fill('0');expect(player.get_by_role('button',name='跳转',exact=True)).to_be_disabled();expect(player).to_have_attribute('data-point-index','2')
            jump.fill('1');player.get_by_label('播放倍速',exact=True).select_option('8')
            player.get_by_role('button',name='重新开始',exact=True).click();expect(player).to_have_attribute('data-time','0');expect(player).to_have_attribute('data-playing','false')
            player.get_by_role('button',name='播放',exact=True).click();expect(player).to_have_attribute('data-playing','true')
            page.wait_for_function('() => [...window.__trajectoryPlayerSessions.values()].some(s=>s.engine.time>.5&&s.engine.playing)')
            player.get_by_role('button',name='暂停',exact=True).click();paused=player.get_attribute('data-time')
            page.wait_for_timeout(250);expect(player).to_have_attribute('data-time',paused)
            # Native parent reruns must retain the cursor and multiplier.
            dialog.get_by_role('button',name='刷新',exact=True).click()
            expect(player).to_have_attribute('data-time',paused);expect(player.get_by_label('播放倍速',exact=True)).to_have_value('8')
            player.get_by_role('button',name='播放',exact=True).click();jump.fill('2');player.get_by_role('button',name='跳转',exact=True).click()
            expect(player).to_have_attribute('data-playing','true');expect(player).to_have_attribute('data-stroke','2')
            dialog.get_by_role('button',name='刷新',exact=True).click();expect(player).to_have_attribute('data-playing','true')
            player.get_by_role('button',name='重新开始',exact=True).click();expect(player).to_have_attribute('data-playing','true')
            player.get_by_role('button',name='暂停',exact=True).click()
            dialog.get_by_role('button',name='返回素材',exact=True).click();expect(card).to_have_count(1);card.locator('.open').click()
            expect(player).to_have_attribute('data-time','0');expect(player).to_have_attribute('data-playing','false')
            page.screenshot(path=str(output/'trajectory_player_library.png'))
            page.set_viewport_size({'width':680,'height':900})
            player.get_by_role('button',name='跳转',exact=True).scroll_into_view_if_needed()
            expect(player.get_by_role('button',name='跳转',exact=True)).to_be_in_viewport()
            page.screenshot(path=str(output/'trajectory_player_narrow.png'))
            dialog.get_by_role('button',name='Close',exact=True).click()
            page.wait_for_function('() => [...window.__trajectoryPlayerSessions.values()].every(s=>!s.engine.playing&&!s.runtime)')
            page.set_viewport_size({'width':1450,'height':1000})
            # Reopening is a new preview instance and starts paused at the start.
            sidebar.get_by_text('素材库',exact=True).click();search.fill(item['name']);search.press('Enter');expect(card).to_have_count(1);card.locator('.open').click()
            expect(player).to_have_attribute('data-time','0');expect(player).to_have_attribute('data-playing','false')
            dialog.get_by_role('button',name='Close',exact=True).click();page.set_viewport_size({'width':1450,'height':1000})
            sidebar.get_by_text('文字轨迹',exact=True).click();page.get_by_label('文字内容',exact=True).fill(prefix)
            page.get_by_role('button',name='生成文字轨迹',exact=True).click();expect(player).to_be_visible(timeout=30000)
            expect(player).to_have_attribute('data-playing','false')
            sidebar.get_by_text('轨迹规划',exact=True).click();expect(player).to_be_visible(timeout=15000)
            page.get_by_text('XY 预览',exact=True).click();expect(player).not_to_be_visible()
            page.get_by_text('执行模拟',exact=True).click();expect(player).to_be_visible();expect(player).to_have_attribute('data-playing','false')
            assert not page.get_by_test_id('stException').count()
            assert not errors,errors
            browser.close()
        print('PASS: three preview entry points, colors, pause, speed, navigation, restart, reruns, disposal and narrow controls')
    finally:
        for asset in lib.scan():
            if asset['name'].startswith(prefix):lib.delete(asset)
        for asset in lib.trash_items():
            if asset['name'].startswith(prefix):lib.purge(asset['trash_id'])


if __name__=='__main__':main()
