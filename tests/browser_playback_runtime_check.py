"""Lifecycle and measured rendering performance against the isolated harness."""
import json
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]


def main():
    output=ROOT/'.artifacts/software_checks';output.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
        page=browser.new_page(viewport={'width':1200,'height':950});errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8526')
        player=page.get_by_role('region',name='轨迹执行模拟器',exact=True);expect(player).to_be_visible(timeout=30000)
        player.get_by_role('button',name='播放',exact=True).click()
        page.wait_for_function('() => window.__trajectoryPlayerSessions.get("runtime_test").engine.time>.15')
        page.get_by_text('触发页面重绘',exact=True).click();expect(player).to_have_attribute('data-playing','true')
        player.get_by_role('button',name='暂停',exact=True).click();paused=player.get_attribute('data-time')
        page.get_by_text('触发页面重绘',exact=True).click();expect(player).to_have_attribute('data-time',paused)
        player.get_by_role('button',name='播放',exact=True).click()
        # A hidden document pauses without catching up or auto-resuming.
        page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))")
        expect(player).to_have_attribute('data-playing','false')
        hidden=player.get_attribute('data-time');page.wait_for_timeout(200);expect(player).to_have_attribute('data-time',hidden)
        page.evaluate("delete document.hidden;document.dispatchEvent(new Event('visibilitychange'))")
        expect(player).to_have_attribute('data-playing','false')
        player.get_by_role('button',name='播放',exact=True).click();page.get_by_role('button',name='收起预览',exact=True).click()
        expect(player).not_to_be_visible()
        page.wait_for_function('() => !window.__trajectoryPlayerSessions.get("runtime_test").runtime&&!window.__trajectoryPlayerSessions.get("runtime_test").engine.playing')
        page.get_by_role('button',name='重新显示预览',exact=True).click();expect(player).to_be_visible();expect(player).to_have_attribute('data-playing','false')
        # A zero-duration source finishes immediately but still supports exact anchors.
        previous_fingerprint=player.get_attribute('data-fingerprint');choose(page,'零时长')
        expect(player).not_to_have_attribute('data-fingerprint',previous_fingerprint)
        expect(player).to_have_attribute('data-time','0');expect(player).to_have_attribute('data-point-index','0')
        jump=player.get_by_label('跳转笔号',exact=True);jump.fill('2');player.get_by_role('button',name='跳转',exact=True).click();expect(player).to_have_attribute('data-point-index','3')
        player.get_by_role('button',name='播放',exact=True).click();expect(player).to_have_attribute('data-ended','true');expect(player).to_have_attribute('data-playing','false')
        results={}
        for sample in ['真实轨迹','压力样本']:
            previous_fingerprint=player.get_attribute('data-fingerprint');choose(page,sample)
            expect(player).not_to_have_attribute('data-fingerprint',previous_fingerprint)
            expect(player).to_have_attribute('data-time','0');expect(player).to_have_attribute('data-playing','false')
            player.get_by_label('播放倍速',exact=True).select_option('8');player.get_by_role('button',name='播放',exact=True).click()
            results[sample]=player.evaluate('''async root => {
              const session=window.__trajectoryPlayerSessions.get('runtime_test'),runtime=session.runtime,start=performance.now(),initial=runtime.frameCount;
              await new Promise(resolve=>setTimeout(resolve,1800));const count=runtime.frameCount-initial;
              return {fps:count/((performance.now()-start)/1000),frames:count,points:session.engine.data.points.length};
            }''')
            assert results[sample]['fps']>=30,results[sample]
            player.get_by_role('button',name='暂停',exact=True).click()
            for stroke in [1,2,10,1,100,1]:
                jump.fill(str(stroke));player.get_by_role('button',name='跳转',exact=True).click()
                expect(player).to_have_attribute('data-stroke',str(stroke));expect(player).to_have_attribute('data-playing','false')
        page.screenshot(path=str(output/'trajectory_player_stress.png'))
        page.set_viewport_size({'width':420,'height':900});player.get_by_role('button',name='跳转',exact=True).scroll_into_view_if_needed()
        expect(player.get_by_role('button',name='跳转',exact=True)).to_be_in_viewport();expect(player.get_by_label('播放倍速',exact=True)).to_be_in_viewport()
        page.screenshot(path=str(output/'trajectory_player_runtime_narrow.png'))
        assert not errors,errors
        assert not page.get_by_test_id('stException').count()
        (output/'trajectory_player_performance.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print('PASS: reruns, hide/unmount, source changes, zero-duration anchors, repeated seeks, performance',results)
        browser.close()


def choose(page,label):
    page.get_by_role('combobox').first.click()
    page.get_by_role('option',name=label,exact=True).click()


if __name__=='__main__':main()
