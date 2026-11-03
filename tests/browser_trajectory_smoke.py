"""Optional real-browser smoke check. Requires playwright and installed Chrome.

Run against the app on http://127.0.0.1:8512. No robot connection is made.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / ".artifacts" / "software_checks"


def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path="C:/Program Files/Google/Chrome/Application/chrome.exe",headless=True)
        page=browser.new_page(viewport={"width":1500,"height":1050},accept_downloads=True)
        errors=[]
        page.on("pageerror",lambda e:errors.append(str(e)))
        page.goto(sys.argv[1] if len(sys.argv)>1 else "http://127.0.0.1:8512")
        page.get_by_test_id("stSidebar").get_by_text("文字轨迹",exact=True).click()
        expect(page.get_by_label("文字内容",exact=True)).to_be_visible()
        page.get_by_label("文字内容",exact=True).fill("生日快乐\n小林22岁 Happy")
        page.get_by_role("button",name="生成文字轨迹",exact=True).click()
        expect(page.get_by_role("button",name="加入轨迹合成",exact=True)).to_be_enabled(timeout=30000)
        page.screenshot(path=str(ARTIFACTS/"text_trajectory.png"),full_page=True)
        page.get_by_role("button",name="加入轨迹合成",exact=True).click()
        page.get_by_role("button",name="添加上一步轨迹",exact=True).click()
        canvas=page.get_by_role("application",name="轨迹排布画布，使用旁边的数字输入也可修改位置与大小")
        expect(canvas).to_be_visible(timeout=20000)
        box=canvas.bounding_box()
        assert abs(box['width']-box['height'])<3,canvas.get_attribute('style')
        # Select and drag the object; compare exported canvas X against the property editor.
        rect=canvas.locator('g[data-id] > rect').first
        box=rect.bounding_box()
        page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2)
        page.mouse.down();page.mouse.move(box['x']+box['width']/2+30,box['y']+box['height']/2+15,steps=8);page.mouse.up()
        x_input=page.get_by_label("中心 X mm",exact=True)
        expect(x_input).not_to_have_value("150.00",timeout=15000)
        moved_x=float(x_input.input_value())
        assert moved_x>150,moved_x
        # Keyboard movement must also round-trip.
        canvas.focus();page.keyboard.press("ArrowRight")
        expect(x_input).not_to_have_value(str(moved_x),timeout=15000)
        page.wait_for_function("() => !document.querySelector('[data-testid=stStatusWidget]')",timeout=20000)
        # Save/download and inspect exact values rather than merely checking HTTP status.
        with page.expect_download() as download:
            page.get_by_role("button",name="下载合成工程",exact=True).click()
        path=ARTIFACTS/"composition.project.json";download.value.save_as(path)
        project=json.loads(path.read_text(encoding='utf-8'))
        assert project['items'][0]['x_mm']>moved_x
        before_scale=project['items'][0]['scale']
        # Resize by the lower-right handle, then verify backend state via download.
        handle=canvas.locator('rect[data-handle="scale"]').last
        box=handle.bounding_box()
        page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2)
        page.mouse.down();page.mouse.move(box['x']+box['width']/2+10,box['y']+box['height']/2+5,steps=5);page.mouse.up()
        expect(page.get_by_label("等比缩放",exact=True)).not_to_have_value("1.0000",timeout=15000)
        with page.expect_download() as download:
            page.get_by_role("button",name="下载合成工程",exact=True).click()
        download.value.save_as(path)
        project=json.loads(path.read_text(encoding='utf-8'))
        assert project['items'][0]['scale']>before_scale
        # Add an existing image-derived trajectory when available, and reuse the text file.
        image_files=[p for p in (ROOT/'data'/'trajectories').glob('*.json') if not p.name.startswith('direct_batch_')]
        if image_files:
            page.get_by_role("button",name="本地上传",exact=True).first.click()
            dialog=page.get_by_role("dialog")
            dialog.locator('input[type="file"]').set_input_files(image_files[0])
            dialog.get_by_role("button",name="导入轨迹",exact=True).click()
            expect(page.get_by_text("画布 300 × 300 mm · 2 个对象；重叠允许。",exact=True)).to_be_visible()
            expect(page.get_by_label("对象名称",exact=True)).to_have_value(re.compile(re.escape(image_files[0].stem)+r"(?:_[0-9a-f]+)?\.json"))
            page.get_by_label("等比缩放",exact=True).fill('0.4')
            page.get_by_label("中心 X mm",exact=True).fill('100')
            page.get_by_label("中心 Y mm",exact=True).fill('70')
            page.get_by_label("旋转 deg",exact=True).fill('15')
            page.get_by_role("button",name="应用对象修改",exact=True).click()
            expect(page.get_by_label("旋转 deg",exact=True)).to_have_value('15.00')
            page.get_by_role("button",name="↑ 提前执行",exact=True).click()
            expect(page.get_by_role("button",name="↑ 提前执行",exact=True)).to_be_disabled()
            page.get_by_role("button",name="本地上传",exact=True).first.click()
            dialog.locator('input[type="file"]').set_input_files(image_files[0])
            dialog.get_by_role("button",name="导入轨迹",exact=True).click()
            expect(page.get_by_text("画布 300 × 300 mm · 3 个对象；重叠允许。",exact=True)).to_be_visible()
            expect(page.get_by_label("对象名称",exact=True)).to_have_value(re.compile(re.escape(image_files[0].stem)+r"(?:_[0-9a-f]+)?\.json"))
            page.get_by_label("等比缩放",exact=True).fill('0.2')
            page.get_by_label("中心 X mm",exact=True).fill('220')
            page.get_by_label("中心 Y mm",exact=True).fill('70')
            page.get_by_role("button",name="应用对象修改",exact=True).click()
            expect(page.get_by_label("等比缩放",exact=True)).to_have_value('0.2000')
            page.wait_for_function("() => !document.querySelector('[data-testid=stStatusWidget]')",timeout=20000)
            with page.expect_download() as download:
                page.get_by_role("button",name="下载合成工程",exact=True).click()
            download.value.save_as(path)
            project=json.loads(path.read_text(encoding='utf-8'))
            assert len(project['items'])==3
        page.get_by_role("button",name="保存合成轨迹",exact=True).click()
        expect(page.get_by_role("button",name="下载合成轨迹 JSON",exact=True)).to_be_visible()
        page.get_by_text("显示重新生成的空走连接",exact=True).click()
        expect(canvas.locator('line').first).to_be_visible()
        page.screenshot(path=str(ARTIFACTS/"trajectory_composition.png"),full_page=True)
        # Refresh and restore the portable project including its embedded source.
        page.reload()
        page.get_by_test_id("stSidebar").get_by_text("轨迹合成",exact=True).click()
        page.get_by_role("button",name="本地上传",exact=True).nth(1).click()
        dialog=page.get_by_role("dialog")
        dialog.locator('input[type="file"]').set_input_files(path)
        dialog.get_by_role("button",name="预览上传文件",exact=True).click()
        dialog.get_by_role("button",name="导入并使用",exact=True).click()
        page.get_by_role("button",name="打开工程",exact=True).click()
        expect(page.get_by_label("中心 X mm",exact=True)).to_have_value(f"{project['items'][0]['x_mm']:.2f}",timeout=15000)
        assert not errors,errors
        assert page.get_by_test_id("stException").count()==0
        page.set_viewport_size({"width":800,"height":1050})
        expect(canvas).to_be_visible()
        page.screenshot(path=str(ARTIFACTS/"composition_narrow.png"),full_page=True)
        browser.close()
    print("PASS: text generation, drag, keyboard move, resize, export and project restore")


if __name__=="__main__": main()
