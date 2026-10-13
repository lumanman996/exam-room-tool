"""真实前端自动操作：上传、编排、调整、重开以及产品导出的文件。"""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import shutil
import re
from urllib.parse import urlparse

from .common import Blocked, KIT, assert_excel, assert_plan, assert_pdf_text, dump, load, service, scrub_trace


def click_api(page, locator, endpoint, ok=True,timeout=110000):
    with page.expect_response(lambda r:urlparse(r.url).path=='/api/'+endpoint,timeout=timeout) as response:
        page.locator(locator).click()
    result=response.value.json()
    assert result['ok']==ok, result.get('error', endpoint)
    return result.get('data') if ok else result


def navigate(page, destination):
    if destination=='home' and page.locator('#backHome').count(): page.locator('#backHome').click()
    else: page.locator(f'[data-page="{destination}"]').click()


def reveal_plan_settings(page):
    if page.locator('#planMenu').count() and page.locator('#planMenu').get_attribute('open') is None:
        page.locator('#planMenu > summary').click()


def import_button(page, kind):
    if page.locator('#importEntityBtn').count():
        page.locator(f'[data-kind="{kind}"]').click()
        return '#importEntityBtn'
    return f'[data-import="{kind}"]'


def open_plan(page, client, ident):
    from playwright.sync_api import expect
    page.goto(client.url)
    expect(page.locator('#importPlanBtn')).to_be_visible()
    with page.expect_file_chooser() as chooser: page.locator('#importPlanBtn').click()
    with page.expect_response(lambda r:r.url.endswith('/api/plan_import')):
        chooser.value.set_files(KIT/'fixtures'/ident/'方案.json')
    expect(page.locator('#planName')).to_have_value(load(ident)['name']+'（导入）')
    navigate(page,'data')


def solve_ui(page, client, selector, kind):
    from playwright.sync_api import expect
    result=click_api(page,selector,'solve')
    assert result['kind']==kind
    expect(page.locator('#busy')).to_have_class('busy hidden',timeout=120000)
    state=client.call('task'); assert state['task']['status'] in ('optimal','feasible'),state['task']
    # 自动求解如弹出“继续寻找最优”对话框，只关闭提示，不再发起求解。
    if page.locator('#formDialog').is_visible(): page.locator('#formCancel').click()
    return state['view']['plan']


def export_ui(page, root, kind):
    from playwright.sync_api import expect
    endpoint='#exportXlsx' if kind=='xlsx' else '#exportPdf'
    with page.expect_download(timeout=120000) as info:
        with page.expect_response(lambda r:urlparse(r.url).path in ('/api/export','/api/export_start'),timeout=110000) as response:
            page.locator(endpoint).click()
        payload=response.value.json(); assert payload['ok'],payload.get('error')
        dump(root/(kind+'-request.json'),response.value.request.post_data_json)
        if urlparse(response.value.url).path=='/api/export_start':
            state=payload['data']
            if state['state']=='running':
                def finished(r):
                    if urlparse(r.url).path!='/api/export_status': return False
                    value=r.json()
                    return value.get('ok') and value['data']['state']!='running'
                with page.expect_response(finished,timeout=110000) as terminal: pass
                state=terminal.value.json()['data']
            dump(root/(kind+'-terminal.json'),state)
            assert state['state']=='done',state.get('message',state)
    download=info.value; path=root/download.suggested_filename
    download.save_as(path); assert download.failure() is None
    expect(page.locator('#exportStatus')).to_contain_text('已生成')
    return path


def normal_flow(page,client,root):
    from playwright.sync_api import expect
    page.goto(client.url)
    page.locator('#newBtn').click(); page.locator('#newName').fill('虚构144人·浏览器全流程')
    click_api(page,'#formSave','new')
    navigate(page,'data')
    for kind,name in (('students','学生名单'),('rooms','考场资料'),('teachers','教师资料'),('exams','考试日程')):
        selector=import_button(page,kind)
        with page.expect_file_chooser() as chooser: page.locator(selector).click()
        chooser.value.set_files(KIT/'fixtures/C02_normal_144'/(name+'.xlsx'))
        expect(page.locator('#importDialog')).to_be_visible()
        expect(page.locator('#importSummary')).to_contain_text(str(len(load('C02_normal_144')[kind])))
        if page.locator('#importPreflightBtn').count():
            preflight=click_api(page,'#importPreflightBtn','import_preflight')
            assert not preflight['errors'],preflight['errors']
        click_api(page,'#importConfirm','import'); expect(page.locator('#importDialog')).not_to_be_visible()
    page.locator('[data-page="seats"]').click(); solve_ui(page,client,'#seatBtn','seats')
    expect(page.locator('#seatSummary')).to_contain_text('144')
    page.locator('[data-page="invigilate"]').click(); solve_ui(page,client,'#invigilatorBtn','invigilators')
    page.locator('[data-page="check"]').click()
    expect(page.locator('#checkResult')).to_contain_text('0 项必须处理')
    assert not client.call('state')['validation']['errors'],'页面零硬问题与实际检查不一致'
    click_api(page,'#confirmBtn','confirm')
    p=client.call('state')['plan']; checked=assert_plan(p); assert checked['exam_rows']==432
    page.screenshot(path=str(root/'检查.png'),full_page=True)
    page.locator('[data-page="export"]').click()
    if page.locator('#exportSelectAll').count(): page.locator('#exportSelectAll').click()
    else:
        for item in page.locator('[data-export]').all(): item.check()
    sections=list(client.call('state')['sections'])
    xlsx=export_ui(page,root,'xlsx')
    assert_excel(xlsx.read_bytes(),p,sections,layouts=json.loads((root/'xlsx-request.json').read_text(encoding='utf-8')).get('layouts'))
    closed=page.locator('#exportChecks details:not([open]) > summary')
    while closed.count(): closed.first.click()
    for item in page.locator('[data-export]').all():
        if item.get_attribute('data-export') in ('students','tickets','seating','labels'): item.check()
        else: item.uncheck()
    pdf=export_ui(page,root,'pdf'); assert pdf.suffix.lower()=='.pdf','产品未实际输出PDF，不能按PDF通过'
    from pypdf import PdfReader
    reader=PdfReader(pdf); text='\n'.join(x.extract_text() or '' for x in reader.pages)
    assert_pdf_text(text,p)
    if shutil.which('pdftoppm'):
        subprocess.run(['pdftoppm','-f','1','-singlefile','-scale-to','1400','-png',str(pdf),str(root/'PDF首页')],
                       check=True,capture_output=True,timeout=30)
    else:
        # 保留实际产品打印HTML的页面截图，PDF内容核对已执行，PDF栅格抽查另列限制。
        dump(root/'pdf-render-note.json',{'status':'未运行','reason':'无pdftoppm，PDF文本核对已完成'})
    dump(root/'actual-plan.json',p)
    navigate(page,'data'); reveal_plan_settings(page); page.locator('#cloneBtn').click()
    page.locator('#cloneName').fill('虚构浏览器副本'); copied=click_api(page,'#formSave','clone')['plan']
    assert copied['id']!=p['id'] and copied['seats']==p['seats']
    return dict(**checked,excel_sections=len(sections),pdf_pages=len(reader.pages),pdf=str(pdf),
                xlsx=str(xlsx),plan_id=p['id'],copied_id=copied['id'])


def numbering_flow(page,client,root):
    from playwright.sync_api import expect
    open_plan(page,client,'C01_tiny_completed');original=client.call('state')['plan']
    page.locator('[data-page="seats"]').click()
    if page.locator('[data-seat-view="table"]').count(): page.locator('[data-seat-view="table"]').click()
    page.locator('[data-seat="s7-001"]').click()
    page.locator('#adjustSeat').fill('2'); page.locator('#swapSeat').check()
    preview=click_api(page,'#seatAdjustSave','adjust_seat_preview')
    assert client.call('state')['plan']==original and preview['revision']==original['revision'],'预览不应提交'
    expect(page.locator('#formTitle')).to_contain_text('交换')
    click_api(page,'#formSave','adjust_seat');expect(page.locator('#formDialog')).not_to_be_visible()
    expect(page.locator('#numberWarningText')).to_contain_text('2 名学生')
    assert client.call('state')['plan']['students'][0]['number']=='0010101'
    page.locator('[data-page="export"]').click()
    if page.locator('#exportXlsx').is_disabled():
        expect(page.locator('#exportGate')).to_contain_text('必须处理')
        assert not client.raw('export',dict(format='xlsx',sections=['students']))['ok']
    else:
        click_api(page,'#exportXlsx','export',ok=False)
        expect(page.locator('.toast.bad').last).to_contain_text('问题')
    page.locator('#numberReviewBtn').click(); page.locator('#numberPrefix').fill('001'); page.locator('#numberOverwrite').check()
    preview=click_api(page,'#numberPreviewBtn','number_preview'); assert preview['changes']==2
    expect(page.locator('#numberPreview')).to_contain_text('2 个考号将改变')
    click_api(page,'#numberApply','numbers'); expect(page.locator('#numberWarning')).not_to_be_visible()
    p=client.call('state')['plan']; assert_plan(p)
    confirmed=bool(p.get('stale'))
    if confirmed:
        navigate(page,'check'); click_api(page,'#confirmBtn','confirm')
    assert p['students'][0]['number']=='0010102' and p['students'][1]['number']=='0010101'
    page.screenshot(path=str(root/'考号调整后.png'),full_page=True)
    page.locator('[data-page="seats"]').click()
    if confirmed:
        expect(page.locator('#globalUndo')).to_have_text('撤销：确认检查结果')
        click_api(page,'#globalUndo','edit_undo')  # 最新一步为检查确认。
    page.locator('#numberBtn').click();click_api(page,'#numberUndo','edit_undo')
    expect(page.locator('#numberWarning')).to_be_visible()  # 号码回退，换座仍保留。
    assert client.call('state')['plan']['students']==original['students']
    page.locator('#numberClose').click();expect(page.locator('#globalUndo')).to_have_text('撤销：调整学生座位');click_api(page,'#globalUndo','edit_undo')
    expect(page.locator('#numberWarning')).not_to_be_visible()
    restored=client.call('state')['plan'];assert restored['seats']==original['seats']
    assert restored['students']==original['students'] and restored['number_sources']==original['number_sources']
    assert_plan(restored)
    return dict(swap=True,mismatch_count=2,formal_export_rejected=True,renumbered=True,unified_undo_exact=True)


def number_rule_flow(page,client,root):
    """座位页与考号生成里的考号方式是同一个设置：任一处修改都立即保存并同步另一处。"""
    from playwright.sync_api import expect
    open_plan(page,client,'C01_tiny_completed');navigate(page,'seats')
    expect(page.locator('#seatNumberRule')).to_have_value(client.call('state')['plan']['settings'].get('number_rule','seat'))
    expect(page.locator('#numberRuleHelp')).to_contain_text('每人独占一个座位')
    with page.expect_response(lambda r:urlparse(r.url).path=='/api/save'):page.locator('#seatNumberRule').select_option('serial')
    expect(page.locator('#numberRule')).to_have_value('serial')
    assert client.call('state')['plan']['settings']['number_rule']=='serial'
    page.locator('#numberBtn').click();expect(page.locator('#numberSerialFields')).to_be_visible()
    with page.expect_response(lambda r:urlparse(r.url).path=='/api/save'):page.locator('#numberRule').select_option('seat')
    expect(page.locator('#seatNumberRule')).to_have_value('seat')
    assert client.call('state')['plan']['settings']['number_rule']=='seat'
    page.locator('[data-default-group="numbering"]').click();expect(page.locator('#numberRule')).to_have_value('seat')
    page.screenshot(path=str(root/'考号方式.png'),full_page=True)
    return dict(synced_both_ways=True,default_reset_keeps_rule=True)


def error_recovery(page,client,root):
    from playwright.sync_api import expect
    open_plan(page,client,'C01_tiny_completed'); original=client.call('state')['plan']
    selector=import_button(page,'students')
    with page.expect_file_chooser() as chooser: page.locator(selector).click()
    chooser.value.set_files(KIT/'fixtures/imports/损坏文件.xlsx')
    expect(page.locator('.toast.bad').last).to_contain_text('无法读取')
    assert client.call('state')['plan']==original
    navigate(page,'home')
    with page.expect_file_chooser() as chooser: page.locator('#importPlanBtn').click()
    chooser.value.set_files(KIT/'fixtures/imports/损坏方案.json')
    expect(page.locator('.toast.bad').last).to_contain_text('无法读取')
    assert client.call('state')['plan']==original
    navigate(page,'data'); reveal_plan_settings(page)
    page.locator('#planName').fill('虚构错误恢复后的方案'); page.locator('#planName').press('Tab')
    if page.locator('#planInfoSave').count(): click_api(page,'#planInfoSave','save')
    expect(page.locator('#currentName')).to_have_text('虚构错误恢复后的方案')
    assert client.call('state')['plan']['name']=='虚构错误恢复后的方案'
    return dict(bad_xlsx_rejected=True,bad_json_rejected=True,current_preserved=True,can_continue_edit=True)


def time_layout(page,client,root):
    from playwright.sync_api import expect
    open_plan(page,client,'C01_tiny_completed'); page.locator('[data-page="schedule"]').click()
    page.locator('#exam-start-0').fill('8：35'); page.locator('#exam-end-0').fill('10:05')
    page.locator('#exam-start-1').fill('14:05')
    click_api(page,'[data-save-exam="0"]','save')
    expect(page.locator('#exam-start-0')).to_have_value('08:35')
    expect(page.locator('#exam-start-1')).to_have_value('14:05')
    page.locator('#exam-start-0').fill('24:00'); page.locator('[data-save-exam="0"]').click()
    expect(page.locator('.toast.bad').last).to_contain_text('小时')
    assert client.call('state')['plan']['exams'][0]['start']=='08:35'
    # 恢复时段，确认待复核后试验方向；保存另一行保留输入已在上一步验证。
    page.locator('#exam-start-0').fill('08:30'); page.locator('#exam-end-0').fill('10:00')
    click_api(page,'[data-save-exam="0"]','save')
    page.locator('[data-page="seats"]').click()
    if page.locator('#unsavedDialog').is_visible():
        expect(page.locator('#unsavedDialog')).to_be_visible()
        page.locator('#discardChanges').click()
    if page.locator('#seatSettings').count(): page.locator('#seatSettings > summary').click()
    page.locator('#seatDirection').select_option('vertical'); page.locator('#seatOrder').select_option('snake')
    click_api(page,'#applyLayoutBtn','save')
    p=client.call('state')['plan']; assert all(r['direction']=='vertical' and r['order']=='snake' for r in p['rooms'])
    texts=page.locator('#roomPreview .seat-cell > small:first-child').all_text_contents()
    assert texts==['01 号','04 号','05 号','02 号','03 号','06 号'],texts
    # 新后端保留物理桌位并改号，因此方向改变后先核对号码，再复核。
    if any(x['code']=='number_seat_mismatch' for x in client.call('state')['validation']['errors']):
        page.locator('#numberReviewBtn').click(); page.locator('#numberOverwrite').check()
        click_api(page,'#numberPreviewBtn','number_preview'); click_api(page,'#numberApply','numbers')
    page.locator('[data-page="check"]').click(); click_api(page,'#confirmBtn','confirm')
    page.locator('[data-page="data"]').click()
    if page.locator('[data-kind="rooms"]').count(): page.locator('[data-kind="rooms"]').click()
    else: page.locator('#entityKind').select_option('rooms')
    page.locator('[data-edit="r01"]').click()
    page.locator('#room-per_desk').fill('2'); expect(page.locator('#roomLayoutStats')).to_contain_text('布局共 12 位')
    expect(page.locator('#roomLayout [data-toggle-seat]')).to_have_count(12)
    page.locator('#room-aisles').fill('1'); page.locator('#room-capacity').fill('12')
    expect(page.locator('#roomApply')).to_be_disabled()
    page.locator('[data-toggle-seat="12"]').click(); expect(page.locator('#roomLayoutStats')).to_contain_text('启用 11 位')
    preview=click_api(page,'#roomChangePreview','room_change_preview')
    dump(root/'实际布局修改预览.json',preview)
    assert preview['room']['capacity']==11
    if preview['requires_confirmation']:page.locator('#roomImpactConfirm').check()
    expect(page.locator('#roomApply')).to_be_enabled(); click_api(page,'#roomApply','room_save')
    p=client.call('state')['plan']; r=p['rooms'][0]
    assert r['per_desk']==2 and r['disabled']==[12] and r['capacity']==11 and r['aisles']==[1]
    page.screenshot(path=str(root/'方向与双人桌.png'),full_page=True)
    return dict(time_typed=True,other_draft_preserved=True,bad_time_rejected=True,vertical_snake=True,
                double_desk=True,aisle=True,disabled_seat=True,capacity=11)


def run(recorder,only=None):
    from .browser_extended import preferences_large,print_layout_scope,unsaved_guard
    try:
        from playwright.sync_api import sync_playwright, expect
        import pypdf
    except ImportError as exc:
        recorder.run('WEB-environment','浏览器/PDF依赖',lambda:(_ for _ in ()).throw(Blocked(str(exc))))
        return
    from .grades_browser import CASES as grade_cases
    from .usability_browser import CASES as usability_cases
    with sync_playwright() as pw:
        try: browser=pw.chromium.launch(headless=True)
        except Exception as exc:
            recorder.run('WEB-environment','浏览器启动',lambda exc=exc:(_ for _ in ()).throw(Blocked(str(exc))))
            return
        # 页面与产品PDF都使用已有的测试浏览器。优先同版本headless shell，
        # 避免macOS完整Chrome在无显示链路时命令行打印挂起。
        executable=Path(pw.chromium.executable_path)
        package=next((p for p in executable.parents if p.name.startswith('chromium-')),None)
        pattern='chromium_headless_shell-'+package.name.removeprefix('chromium-')+'/*/chrome-headless-shell*' if package else ''
        candidates=sorted(package.parent.glob(pattern)) if package else []
        chosen=os.environ.get('EXAM_ROOM_TESTBENCH_PDF_BROWSER') or str(next((p for p in candidates if p.is_file()),executable))
        os.environ['EXAM_ROOM_BROWSER']=chosen
        try:
            for ident,name,fn in [('WEB-normal','144人实际页面上传至Excel/PDF',normal_flow),
                    ('WEB-numbering','页面换座、考号提示、生成及撤销',numbering_flow),
                    ('WEB-number-rule','座位页与考号生成共用同一考号方式',number_rule_flow),
                    ('WEB-recovery','坏文件页面拒绝及继续编辑',error_recovery),
                    ('WEB-time-layout','时间输入、草稿保留、布局与停用',time_layout),
                    ('WEB-preferences','1500人搜索分页、主题字号和小窗口',preferences_large),
                    ('WEB-print-layout','保存版式、科目范围、实际预览Excel/PDF',print_layout_scope),
                    ('WEB-unsaved','未保存修改保留、放弃和保存后继续',unsaved_guard),*grade_cases,*usability_cases]:
                if only and ident not in only: continue
                root=recorder.root/ident; root.mkdir(parents=True,exist_ok=True)
                dump(root/'browser-environment.json',dict(browser=browser.version,page_browser='Playwright Chromium',pdf_browser=chosen))
                def operation(fn=fn,root=root):
                    console=[]; failures=[]; network=[]; tokens=[]; context=browser.new_context(accept_downloads=True,
                        viewport={'width':1440,'height':1000},locale='zh-CN',timezone_id='Asia/Shanghai')
                    context.tracing.start(screenshots=True,snapshots=True,sources=False)
                    page=context.new_page(); page.set_default_timeout(15000)
                    page.on('pageerror',lambda e:failures.append(e.stack or str(e)))
                    page.on('console',lambda m:console.append({'type':m.type,'text':m.text}))
                    def response(r):
                        if urlparse(r.url).path.rsplit('/',1)[-1] in ('editing.js','dragging.js'):
                            network.append({'static_resource':urlparse(r.url).path,'http_status':r.status})
                        if '/api/' in r.url:
                            entry={'endpoint':urlparse(r.url).path,'http_status':r.status}
                            if entry['endpoint'] in ('/api/import','/api/import_preflight'):
                                entry['fictional_request']=r.request.post_data_json
                                entry['result']=r.json()
                            network.append(entry)
                    page.on('response',response)
                    page.on('requestfailed',lambda request:network.append({
                        'endpoint':urlparse(request.url).path,
                        'failure':request.failure,
                    }))
                    try:
                        with service(root/'workspace') as client:
                            tokens.append(client.app.token)
                            data=fn(page,client,root)
                            assert page.evaluate('typeof EditingUI==="object"&&typeof DraggingUI==="object"'),'新版恢复/拖动脚本未加载'
                            assert all(any(x.get('static_resource','').endswith('/'+name) and x.get('http_status')==200 for x in network) for name in ('editing.js','dragging.js')),'新版静态资源没有实际加载成功记录'
                            before=client.call('state')['plan']
                            page.goto('about:blank')
                        # 重启服务并从首页实际打开刚保存的方案，核对重载和页面反馈。
                        with service(root/'workspace') as reopened:
                            tokens.append(reopened.app.token)
                            page.goto(reopened.url)
                            expect(page.locator(f'[data-open="{before["id"]}"]')).to_be_visible()
                            click_api(page,f'[data-open="{before["id"]}"]','open')
                            assert reopened.call('state')['plan']==before
                            expect(page.locator('#planName')).to_have_value(before['name'])
                            page.screenshot(path=str(root/'重开.png'),full_page=True)
                            # 先卸载页面，再关闭重开的服务，避免尚在加载的资源被服务关闭重置。
                            page.goto('about:blank')
                        assert not failures,failures
                        expected_sandbox={f"Blocked script execution in '{url}' because the document's frame is sandboxed and the 'allow-scripts' permission is not set." for url in ('about:blank','about:srcdoc')}
                        assert not [x for x in console if x['type']=='error' and x['text'] not in expected_sandbox],console
                        return dict(**data,browser=browser.version,pdf_browser=chosen,no_javascript_error=True,restarted=True)
                    except Exception:
                        page.screenshot(path=str(root/'失败.png'),full_page=True)
                        content=page.content()
                        for token in tokens: content=content.replace(token,'FICTIONAL-TOKEN-REDACTED')
                        (root/'failed-dom.html').write_text(content,encoding='utf-8')
                        raise
                    finally:
                        dump(root/'console.json',console); dump(root/'network.json',network)
                        dump(root/'page-errors.json',failures)
                        context.tracing.stop(path=str(root/'trace.zip')); context.close()
                        scrub_trace(root/'trace.zip',tokens)
                recorder.run(ident,name,operation)
        finally: browser.close()
