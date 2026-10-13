"""新版界面专项；全部通过可见控件操作，数据仍在隔离服务中。"""
from copy import deepcopy
import io
import json
import time
from urllib.parse import urlparse

from .common import assert_excel, assert_pdf_text, dump, load
from .browser import click_api, export_ui, navigate, open_plan, reveal_plan_settings


def open_appearance(page):
    if not page.locator('#themeSelect').is_visible():
        page.locator('.side-bottom details > summary').click()


def preferences_large(page,client,root):
    from playwright.sync_api import expect
    open_plan(page,client,'C20_large_mixed')
    before=client.call('state')['plan']; target=before['students'][-1]
    expect(page.locator('#entityPager')).to_contain_text('1500')
    expect(page.locator('#entityTable tbody tr')).to_have_count(100)
    began=time.perf_counter();page.locator('#entitySearch').fill(target['name'])
    expect(page.locator('#entityTable tbody tr')).to_have_count(1)
    expect(page.locator('#entityTable')).to_contain_text(target['number'])
    search_seconds=round(time.perf_counter()-began,3)
    page.locator('#entitySearch').fill('');expect(page.locator('#entityPager')).to_contain_text('1500')
    page.locator('#entityGrade').select_option(target['grade'])
    expect(page.locator('#entityPager')).to_contain_text('500')
    page.locator('#entityPagerNext').click();expect(page.locator('#entityPager')).to_contain_text('第 2 / 5 页')
    navigate(page,'check');navigate(page,'data')
    expect(page.locator('#entityGrade')).to_have_value(target['grade'])
    expect(page.locator('#entityPager')).to_contain_text('第 2 / 5 页')
    open_appearance(page);page.emulate_media(color_scheme='dark')
    page.locator('#themeSelect').select_option('system');expect(page.locator('html')).to_have_attribute('data-theme','dark')
    page.emulate_media(color_scheme='light');expect(page.locator('html')).to_have_attribute('data-theme','light')
    page.locator('#themeSelect').select_option('dark');page.locator('#densitySelect').select_option('compact')
    for _ in range(10):page.locator('#fontPlus').click()
    expect(page.locator('#fontPercent')).to_have_text('150%');expect(page.locator('#fontPlus')).to_be_disabled()
    assert client.call('state')['plan']==before,'显示偏好修改了考务方案'
    page.set_viewport_size({'width':960,'height':720})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'),'小窗口出现整页横向溢出'
    page.screenshot(path=str(root/'暗色150字号960窗口.png'))
    page.reload();open_appearance(page)
    expect(page.locator('#themeSelect')).to_have_value('dark');expect(page.locator('#fontPercent')).to_have_text('150%')
    expect(page.locator('html')).to_have_attribute('data-density','compact')
    page.locator('#fontReset').click();expect(page.locator('#fontPercent')).to_have_text('100%')
    for _ in range(2):page.locator('#fontMinus').click()
    expect(page.locator('#fontPercent')).to_have_text('90%');expect(page.locator('#fontMinus')).to_be_disabled()
    page.locator('#resetAppearance').click();expect(page.locator('#fontPercent')).to_have_text('100%')
    expect(page.locator('#themeSelect')).to_have_value('system')
    assert client.call('state')['plan']==before
    return dict(students=1500,page_size=100,grade_filter=500,page_memory=True,search_seconds=search_seconds,
        themes=True,font_bounds=[90,150],preferences_persist=True,display_does_not_edit_plan=True,viewport=[960,720])


def selected_materials(page,keys):
    closed=page.locator('#exportChecks details:not([open]) > summary')
    while closed.count():closed.first.click()
    for item in page.locator('[data-export]').all():
        item.set_checked(item.get_attribute('data-export') in keys)


def preview_ui(page,root):
    from playwright.sync_api import expect
    with page.expect_response(lambda r:urlparse(r.url).path=='/api/export_start') as response:
        page.locator('#previewBtn').click()
    start=response.value.json();assert start['ok'],start
    def done(r):
        return urlparse(r.url).path=='/api/export_status' and r.json().get('data',{}).get('state') in ('done','error','cancelled')
    with page.expect_response(done,timeout=30000) as terminal:pass
    state=terminal.value.json()['data'];dump(root/'preview-terminal.json',state)
    assert state['state']=='done',state
    expect(page.locator('#exportStatus')).to_contain_text('预览已更新')
    return state['result']


def print_layout_scope(page,client,root):
    from playwright.sync_api import expect
    import openpyxl
    from pypdf import PdfReader
    open_plan(page,client,'C05_special_subject');before=client.call('state')['plan']
    e=next(e for e in before['exams'] if e['special_seating'])
    navigate(page,'export');selected_materials(page,['room_students','student_details'])
    page.locator('#printSection').select_option('room_students')
    page.locator('#printPaper').select_option('A3');page.locator('#printOrientation').select_option('portrait')
    page.locator('#printColumns').select_option('1');page.locator('#printFont').fill('14')
    page.locator('#printLineHeight').fill('1.6');page.locator('#printBreak').select_option('room')
    page.locator('#printOptions details > summary').click()
    page.locator('[data-margin="top"]').fill('18')
    page.locator('[data-field="考号"] [data-print-width]').fill('55')
    saved=click_api(page,'#printSave','report_layout_save')['plan'];layout=saved['report_layouts']['room_students']
    assert layout['paper']=='A3' and layout['font_size']==14 and layout['column_widths']['考号']==55
    for field in ('seats','invigilation','stale','number_sources'):assert saved.get(field)==before.get(field),field
    page.locator('#printScope').select_option('exam');page.locator('#printExam').select_option(e['id'])
    result=preview_ui(page,root)
    assert 'A3 portrait' in result['html'] and '55mm' in result['html'] and '14pt' in result['html']
    frame=page.frame_locator('#printPreview')
    expect(frame.locator('section.page')).to_have_count(1)
    expect(frame.locator('body')).to_contain_text(e['date'])
    if result['page_count']>1:
        page.locator('#printNext').click();expect(page.locator('#previewMeta')).to_contain_text('2 /')
        page.locator('#printPrev').click();expect(page.locator('#previewMeta')).to_contain_text('1 /')
    xlsx=export_ui(page,root,'xlsx');request=json.loads((root/'xlsx-request.json').read_text(encoding='utf-8'))
    actual=client.call('state')['plan']
    assert_excel(xlsx.read_bytes(),actual,request['sections'],request['layouts'],request['scope'])
    wb=openpyxl.load_workbook(io.BytesIO(xlsx.read_bytes()));ws=wb['按考场学生总表']
    assert ws.page_setup.orientation=='portrait' and str(ws.page_setup.paperSize)==ws.PAPERSIZE_A3
    assert abs(ws.page_margins.top-18/25.4)<1e-9;wb.close()
    pdf=export_ui(page,root,'pdf');assert pdf.suffix=='.pdf','专项PDF回退HTML'
    reader=PdfReader(pdf);assert len(reader.pages)==result['page_count']
    participants=[s for s in actual['students'] if s['grade']==e['grade'] and (not s['subjects'] or e['subject'] in s['subjects'])]
    text='\n'.join(p.extract_text() or '' for p in reader.pages);assert_pdf_text(text,{'students':participants})
    forbidden=[s for s in actual['students'] if s not in participants]
    assert all(s['number'] not in text for s in forbidden),'科目范围混入不参试学生'
    page.screenshot(path=str(root/'A3版式与科目预览.png'))
    return dict(saved_layout=layout,subject=e['subject'],participants=len(participants),special_seats=True,
        excel_scope_verified=True,preview_pages=result['page_count'],pdf_pages=len(reader.pages))


def unsaved_guard(page,client,root):
    from playwright.sync_api import expect
    open_plan(page,client,'C01_tiny_completed');before=client.call('state')['plan']
    reveal_plan_settings(page);page.locator('#planName').fill('虚构尚未保存的标题')
    navigate(page,'schedule');expect(page.locator('#unsavedDialog')).to_be_visible()
    page.locator('#keepEditing').click();expect(page.locator('#planName')).to_have_value('虚构尚未保存的标题')
    assert client.call('state')['plan']==before
    navigate(page,'schedule');page.locator('#discardChanges').click()
    expect(page.locator('#schedule')).to_have_class('page active');assert client.call('state')['plan']==before
    navigate(page,'data');reveal_plan_settings(page);page.locator('#planName').fill('虚构已保存并继续的标题')
    navigate(page,'schedule');click_api(page,'#saveAndContinue','save')
    expect(page.locator('#schedule')).to_have_class('page active')
    after=client.call('state')['plan'];assert after['name']=='虚构已保存并继续的标题'
    assert after['seats']==before['seats'] and after['invigilation']==before['invigilation']
    page.screenshot(path=str(root/'保存后继续.png'))
    return dict(keep_draft=True,discard_does_not_edit=True,save_and_continue=True,arrangements_preserved=True)
