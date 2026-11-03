"""Regression check for confirmed upload and read-only module picking."""
from pathlib import Path
import sys
import io
import re
import uuid
from PIL import Image
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.core.assets import AssetLibrary


def main():
    lib=AssetLibrary(ROOT);name='library_check_'+uuid.uuid4().hex[:8]+'.png'
    image=io.BytesIO();Image.new('RGB',(60,40),'white').save(image,format='PNG')
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            page=browser.new_page(viewport={'width':1400,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8519')
            sidebar=page.get_by_test_id('stSidebar');sidebar.get_by_text('图像转曲线',exact=True).click()
            expect(page.get_by_role('heading',name='图像转曲线',exact=True)).to_be_visible()
            assert not sidebar.get_by_text('一键绘制',exact=True).count()
            assert not sidebar.get_by_text('设计输入',exact=True).count()
            dialog=page.get_by_role('dialog').filter(has=page.locator('.st-key-asset_shell'))
            def stage():
                page.get_by_role('button',name='本地上传',exact=True).click()
                dialog.locator('input[type="file"]').set_input_files({'name':name,'mimeType':'image/png','buffer':image.getvalue()})
                dialog.get_by_role('button',name='预览上传文件',exact=True).click()
                expect(dialog.get_by_role('button',name='导入并使用',exact=True)).to_be_visible()
                expect(dialog.get_by_role('button',name=re.compile('在文件夹中显示$'))).to_be_disabled()
            stage()
            assert not (ROOT/'data/images'/name).exists()
            dialog.get_by_role('button',name='取消 / 返回',exact=True).click()
            dialog.get_by_role('button',name='Close',exact=True).click()
            assert not page.get_by_text('已确认：'+name,exact=True).count()
            stage();dialog.get_by_role('button',name='导入并使用',exact=True).click()
            expect(page.get_by_text('已确认：'+name,exact=True)).to_be_visible()
            assert (ROOT/'data/images'/name).is_file()
            page.get_by_role('button',name='从素材库选择',exact=True).click()
            search=dialog.get_by_label('搜索名称',exact=True);search.fill(name);search.press('Enter')
            card=dialog.get_by_role('listitem');expect(card).to_have_count(1,timeout=20000)
            assert not card.get_by_role('button',name=__import__('re').compile('移入回收站')).count()
            assert not dialog.get_by_role('button',name='多选',exact=True).count()
            card.locator('.open').click()
            reveal=dialog.get_by_role('button',name=re.compile('在文件夹中显示$'))
            expect(reveal).to_be_enabled();reveal.click()
            expect(page.get_by_text('已在本机文件夹中显示。',exact=True)).to_be_visible(timeout=20000)
            dialog.get_by_role('button',name='导入并使用',exact=True).click()
            expect(page.get_by_text('已确认：'+name,exact=True)).to_be_visible()
            sidebar.get_by_text('素材库',exact=True).click()
            dialog.get_by_role('button',name=re.compile('打开本地文件夹$')).click()
            expect(page.get_by_text('已打开本机素材文件夹。',exact=True)).to_be_visible(timeout=20000)
            search.fill(name);search.press('Enter');expect(card).to_have_count(1)
            card.get_by_role('button',name=__import__('re').compile('^移入回收站')).click()
            expect(card).to_have_count(0)
            dialog.get_by_role('button',name='Close',exact=True).click()
            expect(page.get_by_text('所选文件已删除或移动，请重新导入。',exact=True)).to_be_visible()
            assert not errors,errors
            assert not page.get_by_test_id('stException').count()
            browser.close()
        print('PASS: upload staging/cancel, import routing, read-only picker confirmation, immediate recycle and invalidation')
    finally:
        try:lib.delete(lib.inspect('data/images/'+name))
        except (ValueError,OSError):pass
        for item in lib.trash_items():
            if item['name']==name:lib.purge(item['trash_id'])


if __name__=='__main__':main()
