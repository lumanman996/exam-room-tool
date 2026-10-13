"""隔离虚构资料的前端源码浏览器验测；不读取真实考试。"""
import argparse,json,tempfile,time,sys,hashlib,subprocess,traceback
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from exam_room.server import App,start
from exam_room.licensing import License
from playwright.sync_api import sync_playwright,expect

def run():
    out=Path('output/playwright').resolve();out.mkdir(parents=True,exist_ok=True)
    def fingerprints():
        return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path('exam_room').rglob('*')) if p.is_file() and p.suffix in ('.py','.js','.html','.css')}
    initial=fingerprints();began=datetime.now(timezone.utc).isoformat();metrics={};errors=[];checks=[]
    with tempfile.TemporaryDirectory(prefix='exam-ui-check-') as folder:
        root=Path(folder);app=App(root=root,license=License(root/'license',None,machine='FICTIONAL-UI-CHECK'));server,url,_=start(app)
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch();context=browser.new_context(viewport={'width':1440,'height':1000},color_scheme='light');page=context.new_page()
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(url);page.locator('#demoBtn').wait_for();page.wait_for_timeout(400)
                assert page.locator('#licence').inner_text()=='源码开发版';checks.append('空首页正常读取')
                page.locator('#demoBtn').click();page.locator('#overview.active').wait_for();page.locator('#overviewNext').wait_for()
                for route in ['data','schedule','seats','invigilate','check','export','overview']:
                    page.locator(f'#nav [data-page={route}]').click();page.locator('#'+route+'.active').wait_for();page.wait_for_timeout(150)
                checks.append('七个工作区导航')
                page.screenshot(path=str(out/'overview-light.png'),full_page=True)
                page.locator('.side-bottom .settings-panel').evaluate('(el)=>el.open=true')
                page.locator('#fontMinus').click();assert page.locator('#fontPercent').inner_text()=='95%'
                page.locator('#fontPlus').click();assert page.locator('#fontPercent').inner_text()=='100%'
                page.locator('#themeSelect').select_option('dark');assert page.locator('html').get_attribute('data-theme')=='dark'
                page.wait_for_timeout(200)
                page.screenshot(path=str(out/'overview-dark.png'),full_page=True)
                revision=app.plan['revision'];page.locator('#densitySelect').select_option('compact');page.evaluate('preferenceQueue');page.reload();page.locator('#demoBtn').wait_for();page.wait_for_timeout(300)
                assert page.locator('html').get_attribute('data-theme')=='dark';assert page.locator('html').get_attribute('data-density')=='compact';assert app.plan['revision']==revision
                checks.append('明暗主题、字号增减、密度持久化不修改方案')
                page.locator('#nav [data-page=data]').click();page.locator('[data-kind=rooms]').click();assert page.locator('#roomBatchBtn').is_visible()
                page.locator('[data-kind=students]').click();page.locator('#entitySearch').fill('虚构不存在');page.wait_for_timeout(250);assert '没有找到' in page.locator('#entityTable').inner_text()
                page.locator('#nav [data-page=overview]').click();page.locator('#nav [data-page=data]').click();assert page.locator('#entitySearch').input_value()=='虚构不存在'
                checks.append('资料切换、搜索空结果及筛选保持')
                def choose_materials(keys):
                    for group in page.locator('.material-group').all():
                        if group.get_attribute('open') is None:group.locator('summary').first.click()
                    for checkbox in page.locator('[data-export]').all():checkbox.set_checked(checkbox.get_attribute('data-export') in keys)
                def open_fixture(name):
                    page.locator('#backHome').click();page.locator('#planFileInput').set_input_files(str(Path('testkit/fixtures')/name/'方案.json'));expect(page.locator('#overview.active')).to_be_visible();page.wait_for_timeout(300)
                open_fixture('C01_tiny_completed')
                page.locator('#nav [data-page=data]').click()
                page.locator('#fileInput').set_input_files(str(Path('testkit/fixtures/C01_tiny_completed/学生名单.csv')))
                expect(page.locator('#importDialog')).to_be_visible();page.locator('#importMode').select_option('replace')
                assert page.locator('#importConfirm').is_disabled();page.locator('#importPreflightBtn').click();expect(page.locator('#importConfirm')).to_be_enabled()
                assert '新增 0 条' in page.locator('#importPreflightResult').inner_text();page.locator('#importConfirm').click();expect(page.locator('#importDialog')).not_to_be_visible();assert len(app.plan['students'])==12
                checks.append('导入预检及稳定身份替换')
                page.locator('[data-edit]').first.click();expect(page.locator('#formDialog')).to_be_visible();page.locator('#edit-name').fill('虚构学生改名')
                page.locator('#formCancel').click();expect(page.locator('#unsavedDialog')).to_be_visible();page.locator('#keepEditing').click();assert page.locator('#edit-name').input_value()=='虚构学生改名'
                saved_name=app.plan['students'][0]['name'];page.route('**/api/save',lambda route:route.abort(),times=1)
                page.locator('#formSave').click();expect(page.locator('#formError')).to_contain_text('无法连接');assert page.locator('#edit-name').input_value()=='虚构学生改名';assert app.plan['students'][0]['name']==saved_name
                page.locator('#formSave').click();expect(page.locator('#formDialog')).not_to_be_visible();assert app.plan['students'][0]['name']=='虚构学生改名'
                checks.append('资料编辑未提交保护、连接失败保留输入、重试保存')
                page.locator('#nav [data-page=schedule]').click();page.locator('#exam-start-0').fill('08:30');page.locator('#exam-start-1').fill('14:');page.locator('[data-save-exam="0"]').click();page.wait_for_timeout(300)
                assert page.locator('#exam-start-1').input_value()=='14:';assert page.locator('#exam-start-1').locator('xpath=ancestor::tr').get_attribute('class')=='unsaved'
                page.locator('#nav [data-page=seats]').click();expect(page.locator('#unsavedDialog')).to_be_visible();page.locator('#saveAndContinue').click();expect(page.locator('#unsavedError')).to_be_visible();page.locator('#keepEditing').click();assert page.locator('#exam-start-1').input_value()=='14:';page.locator('#exam-start-1').fill('14:00');page.locator('#nav [data-page=seats]').click();page.locator('#saveAndContinue').click();expect(page.locator('#seats.active')).to_be_visible()
                checks.append('逐行保存保留其他部分输入、无效草稿拒绝后保留、保存后导航')
                page.locator('[data-seat-view=table]').click();page.locator('[data-seat]').first.click();expect(page.locator('#seatAdjustPanel')).to_be_visible();page.locator('#lockSeat').check();page.locator('#seatAdjustSave').click();page.wait_for_timeout(300)
                sid=app.plan['students'][0]['id'];assert app.plan['seats']['base'][sid]['locked'];checks.append('人工座位调整及锁定落盘')
                page.locator('#numberBtn').click();page.locator('#numberPrefix').fill('009');page.locator('#numberGradePrefixes summary').click();page.locator('[data-number-grade=七年级]').fill('017');page.locator('#numberOverwrite').check();page.locator('#numberPreviewBtn').click();expect(page.locator('#numberApply')).to_be_enabled();page.locator('#numberChangesOnly').check();assert '12 条' in page.locator('#numberPager').inner_text();page.locator('#numberApply').click();page.wait_for_timeout(300);assert all(s['number'].startswith('017' if s['grade']=='七年级' else '009') for s in app.plan['students']);checks.append('统一与分年级前缀、考号预览、仅变化、确认生成')
                page.locator('#nav [data-page=invigilate]').click();page.locator('[data-duty-view=teachers]').click();assert page.locator('#workloadTable table').is_visible();page.locator('[data-duty-view=duties]').click();page.locator('[data-duty-id]').first.click();expect(page.locator('#teacherAdjustSave')).to_be_enabled();page.locator('#teacherAdjustSave').click();page.wait_for_timeout(300);checks.append('监考双视图及人工保存')
                page.locator('#nav [data-page=check]').click();page.locator('#confirmBtn').click();page.wait_for_timeout(300)
                assert not app.view()['validation']['errors'],app.view()['validation']['errors']
                page.locator('#nav [data-page=export]').click();expect(page.locator('#printOptions')).to_be_visible();choose_materials(['room_students'])
                page.locator('#printFont').fill('12');page.locator('#printPaper').select_option('A3');page.locator('#printColor').select_option('color');page.locator('#printSave').click();page.wait_for_timeout(300)
                assert app.plan['report_layouts']['room_students']['paper']=='A3';assert not app.plan['stale'];page.locator('#previewBtn').click();expect(page.locator('#printPreview')).to_be_visible(timeout=15000)
                frame=page.frame_locator('#printPreview');expect(frame.locator('section.page')).to_be_visible();assert '009' in frame.locator('body').inner_text();assert '虚构学生改名' in frame.locator('body').inner_text();assert '1 /' in page.locator('#previewMeta').inner_text()
                page.wait_for_timeout(4500);page.locator('.export-layout>div').first.evaluate('(el)=>el.scrollTop=0');page.locator('.main').scroll_into_view_if_needed();page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(out/'room-total-dark.png'),full_page=True)
                with page.expect_download() as info:page.locator('#exportXlsx').click()
                download=info.value;download.save_as(str(out/'考场总表.xlsx'));from openpyxl import load_workbook;book=load_workbook(out/'考场总表.xlsx');cells=[c for row in book['按考场学生总表'] for c in row];assert all(any(c.value==s['number'] and c.data_type=='s' for c in cells) for s in app.plan['students']);assert all(any(c.value==s['name'] for c in cells) for s in app.plan['students']);checks.append('总表版式保存、真实分页预览及Excel导出')
                with page.expect_download(timeout=45000) as info:page.locator('#exportPdf').click()
                pdf=info.value;pdf.save_as(str(out/pdf.suggested_filename));assert pdf.suggested_filename.endswith('.pdf'),pdf.suggested_filename;from pypdf import PdfReader;reader=PdfReader(out/pdf.suggested_filename);assert len(reader.pages)==1;text=''.join(p.extract_text() for p in reader.pages);assert all(s['number'] in text for s in app.plan['students']);checks.append('同一版式实际PDF导出')
                # Default fields must work for every material; preview pages are actual sheets.
                for key in app.view()['sections']:
                    choose_materials([key]);page.locator('#previewBtn').click();expect(page.locator('#printPreview')).to_be_visible(timeout=15000)
                    expect(page.locator('#exportStatus')).to_contain_text('预览已更新',timeout=15000)
                    assert page.frame_locator('#printPreview').locator('section.page').count()==1
                checks.append('16种材料逐项实际打印预览')
                page.locator('#nav [data-page=seats]').click();page.locator('#seatBtn').click();expect(page.locator('#busy')).to_be_visible();assert page.locator('#seatBtn').is_disabled();page.locator('#nav [data-page=overview]').click();expect(page.locator('#busy')).not_to_be_visible(timeout=45000);assert page.locator('#overview').get_attribute('class')=='page active';assert len(app.plan['seats']['base'])==12;checks.append('后台编排允许查看、禁止相关修改、完成后保持当前页面')
                # Corrupt only the isolated fictional file, then operate the recovery entry.
                ident=app.plan['id'];app.store.save(app.plan);app.store.path(ident).write_text('故意损坏的虚构方案',encoding='utf-8')
                page.locator('#backHome').click();page.locator('#refreshBtn').click();page.wait_for_timeout(300);page.locator(f'[data-recover="{ident}"]').click();expect(page.locator('#formDialog')).to_be_visible();page.locator('#formSave').click();expect(page.locator('#overview.active')).to_be_visible();assert app.plan['id']==ident
                checks.append('损坏方案备份预览与恢复')
                # Confirm the material-specific gate remains useful before seating is complete.
                open_fixture('C02_normal_144');page.locator('#nav [data-page=export]').click();choose_materials(['schedule']);assert page.locator('#previewBtn').is_enabled();checks.append('日程材料按阶段放行')
                # Pagination keeps browser work bounded for a real 1,500-row fictional file.
                open_fixture('C20_large_mixed');action_began=time.perf_counter();page.locator('#nav [data-page=data]').click();expect(page.locator('#entityPager')).to_contain_text('1500 条');metrics['data_1500_ms']=round((time.perf_counter()-action_began)*1000,1)
                assert page.locator('#entityTable tbody tr').count()==100;page.locator('#entityPagerNext').click();assert '第 2 / 15 页' in page.locator('#entityPager').inner_text()
                action_began=time.perf_counter();page.locator('#entitySearch').fill('虚构不存在');expect(page.locator('#entityTable')).to_contain_text('没有找到');metrics['search_1500_wall_ms']=round((time.perf_counter()-action_began)*1000,1)
                page.locator('#entitySearch').fill('');expect(page.locator('#entityTable tbody tr')).to_have_count(100)
                page.evaluate("""() => {window.searchSamples=[];let began=null;document.getElementById('entitySearch').addEventListener('input',()=>began=performance.now());new MutationObserver(()=>{if(began!==null){searchSamples.push(performance.now()-began);began=null;}}).observe(document.getElementById('entityTable'),{childList:true});}""")
                for i in range(20):
                    page.locator('#entitySearch').fill('虚构不存在' if i%2==0 else '')
                    expect(page.locator('#entityTable tbody tr')).to_have_count(0 if i%2==0 else 100)
                samples=sorted(page.evaluate('searchSamples'));assert len(samples)==20;metrics['search_1500_p95_ms']=round(samples[18],1);metrics['search_1500_samples']=20
                # Input-method composition does not filter an unfinished Chinese phrase.
                page.locator('#entitySearch').dispatch_event('compositionstart');page.locator('#entitySearch').evaluate("el=>{el.value='虚构不存在';el.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true,data:'虚构不存在'}));}");page.wait_for_timeout(200);assert page.locator('#entityTable tbody tr').count()==100, '输入法合成过程中提前筛选'
                page.locator('#entitySearch').dispatch_event('compositionend');expect(page.locator('#entityTable tbody tr')).to_have_count(0);page.locator('#entitySearch').fill('');expect(page.locator('#entityTable tbody tr')).to_have_count(100)
                checks.append('中文输入法不筛选未完成文字；1500人搜索20次计时')
                page.locator('.side-bottom .settings-panel summary').click()
                page.locator('#themeSelect').select_option('system');page.emulate_media(color_scheme='light');expect(page.locator('html')).to_have_attribute('data-theme','light');page.emulate_media(color_scheme='dark');expect(page.locator('html')).to_have_attribute('data-theme','dark')
                page.locator('#fontReset').click();[page.locator('#fontPlus').click() for _ in range(5)];assert page.locator('#fontPercent').inner_text()=='125%';page.wait_for_timeout(200);page.screenshot(path=str(out/'data-125-dark.png'),full_page=True)
                [page.locator('#fontPlus').click() for _ in range(5)];assert page.locator('#fontPlus').is_disabled();page.set_viewport_size({'width':1050,'height':800});page.wait_for_timeout(200);page.screenshot(path=str(out/'data-150-narrow.png'),full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), '页面横向溢出'
                page.locator('#nav [data-page=seats]').click();page.locator('#roomList [data-room]').last.click();assert '50' in page.locator('#roomCanvasTitle').inner_text()
                page.screenshot(path=str(out/'seats-150-narrow.png'))
                page.locator('#nav [data-page=schedule]').click();page.locator('#examGroupsPanel summary').click();page.locator('#examGroupAdd').click();page.locator('[data-group-exam]').nth(0).check();page.locator('[data-group-exam]').nth(3).check();page.locator('#examGroupSave').click();page.wait_for_timeout(300);assert len(app.plan['settings']['exam_groups'])==1
                checks.append('1500人分页搜索、系统主题变化、125/150字号、1050窗口、明确混考组')
                # A new App/HTTP port has a new browser origin: the app preferences must survive it.
                page.evaluate('preferenceQueue');old_server=server;old_url=url;old_revision=app.plan['revision'];app=App(root=root,license=License(root/'license',None,machine='FICTIONAL-UI-CHECK'));server,url,_=start(app);assert url!=old_url;old_server.shutdown();old_server.server_close();page.goto(url)
                expect(page.locator('#fontPercent')).to_have_text('150%');expect(page.locator('html')).to_have_attribute('data-density','compact');assert page.locator('#themeSelect').input_value()=='system'
                page.locator(f'[data-open="{ident}"]').click();expect(page.locator('#overview.active')).to_be_visible();page.locator('#nav [data-page=export]').click();expect(page.locator('#printPaper')).to_have_value('A3');assert app.plan['report_layouts']['room_students']['font_size']==12
                checks.append('服务真正重启换端口，主题字号密度与方案版式保持')
                if errors:raise AssertionError('\n'.join(errors))
                browser.close()
        except Exception as exc:
            failure={'ok':False,'started_at':began,'failed_at':datetime.now(timezone.utc).isoformat(),'checks_completed':checks,'error':repr(exc),'traceback':traceback.format_exc(),'browser_errors':errors,'metrics':metrics,'source_before':initial,'source_after':fingerprints()};(out/'frontend-results.json').write_text(json.dumps(failure,ensure_ascii=False,indent=2));raise
        finally:server.shutdown()
    final=fingerprints();result={'ok':initial==final,'checks_passed':True,'started_at':began,'finished_at':datetime.now(timezone.utc).isoformat(),'checks':checks,'metrics':metrics,'browser_errors':errors,'evidence':str(out),'source_stable':initial==final,'source_before':initial,'source_after':final,'platform':sys.platform,'python':sys.version,'git_head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()};(out/'frontend-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ('source_before','source_after')},ensure_ascii=False));return 0 if result['ok'] else 2
def run_grades():
    """New formal-grade UI exercised through the real local HTTP service."""
    out=Path('output/frontend-grades').resolve();out.mkdir(parents=True,exist_ok=True)
    def fingerprints():
        return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path('exam_room').rglob('*')) if p.is_file() and p.suffix in ('.py','.js','.html','.css')}
    initial=fingerprints();began=datetime.now(timezone.utc).isoformat();checks=[];errors=[]
    with tempfile.TemporaryDirectory(prefix='exam-grade-ui-') as folder:
        root=Path(folder);app=App(root=root,license=License(root/'license',None,machine='FICTIONAL-GRADE-UI'));server,url,_=start(app)
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000});page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(url);page.locator('#newBtn').click();expect(page.locator('#formDialog')).to_be_visible()
                page.locator('#newName').fill('虚构年级范围验测');page.locator('#grade-name-0').fill('实验甲');page.locator('#grade-name-1').fill('实验乙');page.locator('#grade-name-2').fill('实验丙')
                page.locator('#gradeCount').fill('2');expect(page.locator('[data-grade-name]')).to_have_count(2);page.locator('#gradeCount').fill('3');assert page.locator('#grade-name-2').input_value()=='实验丙'
                page.locator('#grade-name-1').fill('实验甲');page.locator('#formSave').click();expect(page.locator('#formError')).to_contain_text('重复');assert app.plan is None
                page.locator('#grade-name-1').fill('实验乙');page.locator('#formSave').click();expect(page.locator('#overview.active')).to_be_visible();assert app.plan['grades']==['实验甲','实验乙','实验丙'];assert not app.plan['students']
                page.locator('#nav [data-page=seats]').click();assert page.locator('#mixPair option').count()==3;page.locator('#mixAll').click();expect(page.locator('#mixScopeSummary')).to_contain_text('实验甲 ＋ 实验乙 ＋ 实验丙');page.locator('#mixSettingsSave').click();page.wait_for_timeout(150);assert app.plan['settings']['mix_grades'] and not app.plan['students'];checks.append('新建第一步、自定名称、数量调整保留输入、重复拒绝、无学生也可混排')
                page.locator('#nav [data-page=data]').click();expect(page.locator('#gradeSummary')).to_contain_text('实验丙');page.wait_for_timeout(250);page.screenshot(path=str(out/'three-grades-empty.png'));assert page.locator('.grade-chip').count()==3;assert page.locator('.grade-chip').nth(2).inner_text().endswith('0 人')
                page.locator('#addEntityBtn').click();assert page.locator('#edit-grade').evaluate('(el)=>el.tagName')=='SELECT';assert page.locator('#edit-grade option').all_text_contents()==app.plan['grades'];page.locator('#edit-name').fill('虚构甲同学');page.locator('#edit-class_name').fill('实验甲1班');page.locator('#edit-student_no').fill('F001');page.locator('#formSave').click();expect(page.locator('#formDialog')).not_to_be_visible();assert len(app.plan['students'])==1
                page.locator('[data-kind=exams]').click();page.locator('#addEntityBtn').click();assert page.locator('#edit-grade option').all_text_contents()==app.plan['grades'];page.locator('#formCancel').click()
                page.locator('#nav [data-page=seats]').click();page.locator('#numberBtn').click();assert page.locator('#numberGrade option').all_text_contents()==['全部年级',*app.plan['grades']];assert page.locator('[data-number-grade]').count()==3;page.locator('#numberGrade').select_option('实验丙');page.locator('#numberPreviewBtn').click();expect(page.locator('#numberPreview')).to_contain_text('该年级已设置');assert page.locator('#numberApply').is_disabled();page.locator('#numberClose').click()
                page.locator('#nav [data-page=export]').click();assert page.locator('#printGrade option').all_text_contents()==['全部年级',*app.plan['grades']]
                for group in page.locator('.material-group').all():
                    if group.get_attribute('open') is None:group.locator('summary').first.click()
                for box in page.locator('[data-export]').all():box.set_checked(box.get_attribute('data-export')=='room_students')
                page.locator('#draftExport').check();page.locator('#printGrade').select_option('实验丙');revision=app.plan['revision'];page.locator('#previewBtn').click();expect(page.frame_locator('#printPreview').locator('body')).to_contain_text('当前范围没有资料',timeout=15000);assert app.plan['revision']==revision;checks.append('已设无学生年级可选打印范围并返回真实空资料预览')
                checks.append('年级人数含零、学生科目下拉、考号和导出范围使用同一清单')
                page.locator('#nav [data-page=seats]').click();expect(page.locator('#mixAll')).to_have_text('全部 3 个年级混排');assert page.locator('#mixPair option').all_text_contents()==['实验甲 ＋ 实验乙','实验甲 ＋ 实验丙','实验乙 ＋ 实验丙']
                page.locator('#mixAll').click();expect(page.locator('#mixScopeSummary')).to_contain_text('实验甲 ＋ 实验乙 ＋ 实验丙');page.locator('#mixSettingsSave').click();expect(page.locator('#seatSettings')).not_to_have_class('seat-settings dirty');assert app.plan['settings']['mix_grades'] and app.plan['settings']['mix_groups']==[]
                page.locator('[data-mix-mode=pair]').click();page.locator('#mixPair').select_option('0');expect(page.locator('#mixScopeSummary')).to_contain_text('独立编排：实验丙');page.locator('#mixSettingsSave').click();page.wait_for_timeout(250);assert app.plan['settings']['mix_groups']==[['实验甲','实验乙']]
                page.locator('[data-mix-mode=custom]').click();page.locator('#mixGroupAdd').click();groups=page.locator('[data-mix-group]');groups.last.locator('[data-mix-grade=实验乙]').check();groups.last.locator('[data-mix-grade=实验丙]').check();revision=app.plan['revision'];page.locator('#mixSettingsSave').click();expect(page.locator('#mixError')).to_contain_text('多个混排组');assert app.plan['revision']==revision
                groups.last.locator('[data-remove-mix]').click();page.locator('#mixPresetSave').click();page.locator('#mixPresetName').fill('虚构甲乙混排');page.mouse.click(4,4);expect(page.locator('#unsavedDialog')).to_be_visible();page.locator('#keepEditing').click();revision=app.plan['revision'];page.route('**/api/save',lambda route:route.abort(),times=1);page.locator('#formSave').click();expect(page.locator('#formError')).to_contain_text('无法连接');assert page.locator('#mixPresetName').input_value()=='虚构甲乙混排' and app.plan['revision']==revision;page.locator('#formSave').click();expect(page.locator('#formDialog')).not_to_be_visible();page.wait_for_timeout(250);assert app.plan['settings']['mix_presets'][0]['groups']==[['实验甲','实验乙']]
                page.locator('[data-mix-mode=separate]').click();page.locator('#mixSettingsSave').click();page.wait_for_timeout(200);assert not app.plan['settings']['mix_grades'];pid=app.plan['id'];preset=app.plan['settings']['mix_presets'][0]['id']
                page.locator('#backHome').click();page.locator(f'[data-open="{pid}"]').click();page.locator('#nav [data-page=seats]').click();page.locator('#mixPresetSelect').select_option(preset);page.locator('#mixPresetApply').click();page.wait_for_timeout(250);assert app.plan['settings']['mix_groups']==[['实验甲','实验乙']];assert app.plan['grades']==['实验甲','实验乙','实验丙'];expect(page.locator('#mixScopeSummary')).to_contain_text('独立编排：实验丙')
                page.screenshot(path=str(out/'mix-preset-light.png'));checks.append('全范围、所有成对候选、重叠拒绝、具名混排保存重开应用')
                # Save failure and outside-click retain the exact unsaved header text.
                page.locator('#planMenu summary').click();page.locator('#planName').fill('虚构尚未保存名称');rev=app.plan['revision'];page.locator('#currentName').click();expect(page.locator('#planMenu')).not_to_have_attribute('open','');assert app.plan['revision']==rev
                page.locator('#planMenu summary').click();assert page.locator('#planName').input_value()=='虚构尚未保存名称';page.route('**/api/save',lambda route:route.abort(),times=1);page.locator('#planInfoSave').click();expect(page.locator('#planInfoError')).to_contain_text('无法连接');assert page.locator('#planMenu').get_attribute('open') is not None;assert app.plan['revision']==rev
                assert page.locator('#planName').input_value()=='虚构尚未保存名称';page.locator('#planInfoSave').click();expect(page.locator('#planMenu')).not_to_have_attribute('open','');assert app.plan['name']=='虚构尚未保存名称'
                checks.append('顶部保存收起、外部点击保留草稿、失败展开输入保留及重试')
                # Removal rejected by server must keep the old data and edited dialog.
                page.locator('#nav [data-page=data]').click();page.locator('#editGrades').click();page.locator('#grade-name-0').fill('新实验甲');rev=app.plan['revision'];page.locator('#formSave').click();expect(page.locator('#formError')).to_be_visible();assert app.plan['revision']==rev and app.plan['grades'][0]=='实验甲';assert page.locator('#grade-name-0').input_value()=='新实验甲'
                page.mouse.click(4,4);expect(page.locator('#unsavedDialog')).to_be_visible();page.mouse.click(4,4);assert page.locator('#unsavedDialog').is_visible();page.keyboard.press('Escape');assert page.locator('#unsavedDialog').is_visible();page.locator('#keepEditing').click();assert page.locator('#grade-name-0').input_value()=='新实验甲';page.locator('#formCancel').click();page.locator('#discardChanges').click();expect(page.locator('#formDialog')).not_to_be_visible()
                page.locator('[data-kind=rooms]').click();page.locator('#addEntityBtn').click();page.locator('#room-name').fill('虚构背景取消');page.mouse.click(4,4);expect(page.locator('#unsavedDialog')).to_be_visible();page.locator('#discardChanges').click();expect(page.locator('#roomDialog')).not_to_be_visible()
                page.locator('#roomBatchBtn').click();page.locator('#batchNamePrefix').fill('虚构');page.mouse.click(4,4);expect(page.locator('#unsavedDialog')).to_be_visible();page.locator('#discardChanges').click();expect(page.locator('#roomBatchDialog')).not_to_be_visible()
                page.locator('#helpBtn').click();page.mouse.click(4,4);expect(page.locator('#helpDialog')).not_to_be_visible()
                checks.append('引用年级删除保护、设置对话框背景未保存保护且不可绕过、清洁帮助背景关闭')
                # The first missing grade is not an import convenience hint: imports are blocked.
                page.locator('#backHome').click();empty=app.api_new({'name':'虚构未设年级'});page.reload();page.locator(f'[data-open="{empty["plan"]["id"]}"]').click();page.locator('#nav [data-page=data]').click();page.locator('#importEntityBtn').click();expect(page.locator('#formTitle')).to_have_text('本次考试年级');assert app.plan['grades']==[];page.locator('#formCancel').click();page.locator('#addEntityBtn').click();expect(page.locator('#formTitle')).to_have_text('本次考试年级');page.locator('#formCancel').click()
                page.locator('#backHome').click();page.locator(f'[data-open="{pid}"]').click();page.locator('#nav [data-page=data]').click();page.locator('[data-kind=students]').click();bad=root/'未知年级.csv';bad.write_text('年级,班级,姓名,学籍号\n未设置,虚构1班,虚构未知,F009\n',encoding='utf-8-sig');rev=app.plan['revision'];before=app.store.path(pid).read_bytes();page.locator('#fileInput').set_input_files(str(bad));expect(page.locator('#importDialog')).to_be_visible();page.locator('#importPreflightBtn').click();expect(page.locator('#importPreflightResult')).to_contain_text('未设置');assert page.locator('#importConfirm').is_disabled();assert app.plan['revision']==rev and app.store.path(pid).read_bytes()==before;page.mouse.click(4,4);expect(page.locator('#importDialog')).not_to_be_visible()
                checks.append('未设清单阻止新增导入、未知年级预检拒绝且方案文件不变')
                # Legacy fixture supplies a persisted review prompt, cleared only by grade confirmation.
                page.locator('#backHome').click();page.locator('#planFileInput').set_input_files(str(Path('testkit/fixtures/C01_tiny_completed/方案.json')));expect(page.locator('#overview.active')).to_be_visible();page.locator('#nav [data-page=data]').click();expect(page.locator('#gradeReview')).to_be_visible();assert app.plan['grade_review_required'];page.locator('#editGrades').click();page.locator('#formSave').click();expect(page.locator('#formDialog')).not_to_be_visible();expect(page.locator('#gradeReview')).not_to_be_visible();assert not app.plan['grade_review_required']
                page.locator('#nav [data-page=seats]').click();page.locator('#numberBtn').click();page.locator('#numberPrefix').fill('029');page.locator('#numberOverwrite').check();page.locator('#numberPreviewBtn').click();expect(page.locator('#numberApply')).to_be_enabled();assert '12 名学生' in page.locator('#numberPreview').inner_text();page.locator('#numberApply').click();expect(page.locator('#numberDialog')).not_to_be_visible();assert all(s['number'].startswith('029') for s in app.plan['students']);page.locator('#nav [data-page=data]').click()
                page.screenshot(path=str(out/'grades-light.png'));page.locator('.side-bottom .settings-panel summary').click();page.locator('#themeSelect').select_option('dark');page.locator('#fontPlus').click();page.wait_for_timeout(250);page.screenshot(path=str(out/'grades-dark.png'));checks.append('旧方案迁移提示核对确认、明暗主题实际截图')
                for _ in range(9):page.locator('#fontPlus').click()
                page.set_viewport_size({'width':1050,'height':800});page.locator('#nav [data-page=seats]').click();page.locator('#seatSettings summary').click();page.locator('[data-mix-mode=custom]').click();page.locator('#mixGroupAdd').click();page.locator('[data-mix-grade]').first.check();page.locator('[data-mix-grade]').nth(1).check();assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth');page.screenshot(path=str(out/'mix-dark-150-narrow.png'));checks.append('150%字号1050窗口自定义混排无全页横向溢出')
                if errors:raise AssertionError('\n'.join(errors))
                browser.close()
        except Exception as exc:
            (out/'grades-results.json').write_text(json.dumps({'ok':False,'started_at':began,'finished_at':datetime.now(timezone.utc).isoformat(),'checks':checks,'error':repr(exc),'traceback':traceback.format_exc(),'browser_errors':errors,'source_before':initial,'source_after':fingerprints()},ensure_ascii=False,indent=2));raise
        finally:server.shutdown();server.server_close()
    final=fingerprints();result={'ok':True,'source_stable':initial==final,'started_at':began,'finished_at':datetime.now(timezone.utc).isoformat(),'checks':checks,'browser_errors':errors,'source_before':initial,'source_after':final};(out/'grades-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ('source_before','source_after')},ensure_ascii=False));return 0 if result['source_stable'] else 2

if __name__=='__main__':sys.exit(run_grades() if '--grades' in sys.argv else run())
