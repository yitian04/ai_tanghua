"""Browser checks target the substitute-only fixture, never a real robot."""
from playwright.sync_api import sync_playwright,expect


with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
    page=browser.new_page(viewport={'width':1320,'height':1000});page.goto('http://127.0.0.1:8533')
    stop=page.get_by_role('button',name='停止并关料',exact=True)
    expect(stop).to_be_enabled(timeout=20000)
    page.get_by_role('button',name='模拟持续运行',exact=True).click()
    page.get_by_role('button',name='模拟在线',exact=True).click()
    page.get_by_text('我已核对轨迹、工作区示教、TCP、接线与现场条件，允许本次任务',exact=True).click()
    page.get_by_role('button',name='关料试运行',exact=True).click()
    expect(page.get_by_text('任务状态：运行中',exact=True)).to_be_visible(timeout=15000)
    expect(stop).to_be_enabled()
    page.evaluate('window.scrollTo(0,document.body.scrollHeight)')
    box=stop.bounding_box();assert box['y']>=0 and box['y']+box['height']<=page.viewport_size['height']
    # The task survives normal redraw, while another browser cannot duplicate it.
    second=browser.new_page();second.goto('http://127.0.0.1:8533')
    expect(second.get_by_role('button',name='关料试运行',exact=True)).to_be_disabled(timeout=15000)
    stop.click()
    expect(page.get_by_text('任务状态：已停止',exact=True)).to_be_visible(timeout=15000)
    second.close()
    # A new explicit confirmation is needed after the first task.
    page.get_by_text('我已核对轨迹、工作区示教、TCP、接线与现场条件，允许本次任务',exact=True).click()
    page.get_by_role('button',name='关料试运行',exact=True).click()
    expect(page.get_by_text('任务状态：运行中',exact=True)).to_be_visible(timeout=15000)
    page.close()
    observer=browser.new_page(viewport={'width':620,'height':900});observer.goto('http://127.0.0.1:8533')
    expect(observer.get_by_text('任务状态：已停止',exact=True)).to_be_visible(timeout=15000)
    expect(observer.get_by_role('button',name='停止并关料',exact=True)).to_be_enabled()
    assert not observer.get_by_test_id('stException').count()
    browser.close()
    print('PASS: asynchronous run, independent stop, cross-session lock, owner-page loss, narrow window')
