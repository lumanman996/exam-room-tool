"""1.1.0十三项独立真实页面验收；只操作可见控件及pointer。"""
from copy import deepcopy
from datetime import datetime,timezone
import io
import json
import time
import unicodedata
from pathlib import Path
from playwright.sync_api import expect
from .browser import click_api,navigate,reveal_plan_settings,export_ui
from .common import assert_excel,assert_pdf_text,dump
from .usability import fictional_plan,business,saved,physical_snapshot,assert_seating_html,assert_seating_pdf


def seed(page,client,p=None):
    p=client.import_plan(p or fictional_plan())['plan'];page.goto(client.url)
    click_api(page,f'[data-open="{p["id"]}"]','open')
    expect(page.locator('#overview.active')).to_be_visible()
    return p


def nav(page,key):
    navigate(page,key);expect(page.locator('#'+key+'.active')).to_be_visible()


def open_details(page,selector):
    if page.locator(selector).get_attribute('open') is None:page.locator(selector+' > summary').first.click()


def cancel(page,dialog='formDialog'):
    page.locator({'formDialog':'#formCancel','bulkDialog':'#bulkClose','roomDialog':'#roomClose','roomBatchDialog':'#batchClose'}[dialog]).click()
    if page.locator('#unsavedDialog').is_visible():page.locator('#discardChanges').click()
    expect(page.locator('#'+dialog)).not_to_be_visible()


def fail_once(page,endpoint):
    page.route('**/api/'+endpoint,lambda route:route.fulfill(status=200,content_type='application/json',
        body=json.dumps({'ok':False,'error':'虚构注入：保存失败'})),times=1)


def pointer(page,source,target):
    a,b=page.locator(source),page.locator(target);a.scroll_into_view_if_needed();b.scroll_into_view_if_needed()
    box,target_box=a.bounding_box(),b.bounding_box();assert box and target_box
    page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2);page.mouse.down()
    page.mouse.move(target_box['x']+target_box['width']/2,target_box['y']+target_box['height']/2,steps=12)
    page.mouse.up()


def held_ready(page,held,count=1):
    end=time.monotonic()+5
    while len(held)<count and time.monotonic()<end:page.wait_for_timeout(20)
    assert len(held)>=count,'实际请求未被截获'


def release_barrier(page):
    # 真实ping响应作为已释放预览的后续事件屏障，避免只凭固定sleep判迟到。
    page.evaluate("fetch('/api/ping',{method:'POST',headers:{'Content-Type':'application/json','X-Token':TOKEN},body:'{}'}).then(r=>r.json())")
    page.wait_for_timeout(80)


def grades_delete(page,c,root):
    p=seed(page,c);nav(page,'data')
    page.locator('[data-select-grade="七年级"]').check();page.locator('#gradeDeleteSelected').click()
    expect(page.locator('#bulkError')).to_contain_text('仍有关联');assert saved(c)==p
    cancel(page,'bulkDialog');page.locator('[data-open-grade-links="七年级"]').click()
    expect(page.locator('#gradeLinks')).to_contain_text('6 / 3')
    page.locator('[data-grade-go="students"]').click();expect(page.locator('#entityGrade')).to_have_value('七年级')
    expect(page.locator('#entityTable tbody tr')).to_have_count(6)
    # 另开空考试验证真正全选删除及已提交撤销。
    nav(page,'home');page.locator('#newBtn').click();click_api(page,'#formSave','new')
    nav(page,'data');before=saved(c);page.locator('#gradeSelectAll').click();page.locator('#gradeDeleteSelected').click()
    click_api(page,'#bulkApply','bulk_apply');expect(page.locator('#bulkDialog')).not_to_be_visible()
    assert saved(c)['grades']==[];click_api(page,'#globalUndo','edit_undo');expect(page.locator('#gradeSummary')).to_contain_text('九年级')
    assert business(saved(c))==business(before)
    return dict(requirements=[1],used_grade_rejected=True,association_located=True,select_all_delete_undo=True)


def manual_monitor_recovery(page,c,root):
    seed(page,c);nav(page,'invigilate');before=saved(c)
    button=page.locator('[data-duty-id]').first
    duty=button.get_attribute('data-duty-id');index=int(button.get_attribute('data-position'))
    assert before['invigilation'][duty][index]['teacher_id'],'虚构监考位置应先已安排'
    button.click();expect(page.locator('#teacherAdjustSave')).to_be_enabled()
    page.locator('#adjustTeacher').select_option('');fail_once(page,'adjust_invigilator')
    click_api(page,'#teacherAdjustSave','adjust_invigilator',ok=False)
    expect(page.locator('#teacherAdjustError')).to_contain_text('虚构注入')
    expect(page.locator('#adjustTeacher')).to_have_value('');assert saved(c)==before
    click_api(page,'#teacherAdjustSave','adjust_invigilator')
    after=saved(c);assert not after['invigilation'][duty][index]['teacher_id']
    expect(page.locator('#draftState')).to_have_text('已提交到本机')
    dump(root/'监考保存前.json',before);dump(root/'监考保存后.json',after)
    click_api(page,'#globalUndo','edit_undo',timeout=8000)
    assert business(saved(c))==business(before),'人工监考保存后一次撤销必须还原整笔事务'
    return dict(requirements=[2],monitor_failure_keeps_input=True,manual_monitor_one_undo=True)


def unrelated_draft_survives_manual_commit(page,c,root):
    seed(page,c);nav(page,'seats');open_details(page,'#seatSettings')
    original_mode=page.locator('#mode').input_value();page.locator('#mode').select_option('random')
    page.locator('[data-seat-view="table"]').click();page.locator('[data-seat="s7-001"]').click()
    before=saved(c);page.locator('#adjustSeat').fill('2');page.locator('#swapSeat').check()
    click_api(page,'#seatAdjustSave','adjust_seat_preview');click_api(page,'#formSave','adjust_seat')
    expect(page.locator('#formDialog')).not_to_be_visible();expect(page.locator('#mode')).to_have_value('random')
    after=saved(c);assert after['settings']==before['settings'],'人工调整不得提交另一组参数草稿'
    page.locator('#globalUndo').click();expect(page.locator('#mode')).to_have_value(original_mode)
    assert saved(c)==after,'存在未提交参数时首先只撤销该草稿'
    click_api(page,'#globalUndo','edit_undo',timeout=8000)
    assert business(saved(c))==business(before),'草稿撤销后下一次必须还原已确认人工调整'
    seed(page,c);nav(page,'invigilate');open_details(page,'#invigilate details')
    original_count=page.locator('#invigilatorCount').input_value();page.locator('#invigilatorCount').fill('3')
    page.locator('[data-duty-id]').first.click();expect(page.locator('#teacherAdjustSave')).to_be_enabled()
    before=saved(c);page.locator('#adjustTeacher').select_option('')
    click_api(page,'#teacherAdjustSave','adjust_invigilator')
    expect(page.locator('#invigilatorCount')).to_have_value('3');after=saved(c)
    assert after['settings']==before['settings'],'人工监考不得提交另一组规则草稿'
    page.locator('#globalUndo').click();expect(page.locator('#invigilatorCount')).to_have_value(original_count)
    assert saved(c)==after;click_api(page,'#globalUndo','edit_undo',timeout=8000)
    assert business(saved(c))==business(before)
    return dict(unrelated_seating_and_monitor_drafts_preserved=True,draft_then_transaction_undo=True)


def recovery(page,c,root):
    seed(page,c);nav(page,'schedule');page.locator('#exam-start-0').fill('08:10');click_api(page,'[data-save-exam="0"]','save')
    expect(page.locator('#exam-duration-0')).to_have_value('110');first=saved(c)
    page.locator('#exam-start-1').fill('15:');page.locator('#globalUndo').click()
    expect(page.locator('#exam-start-1')).to_have_value(first['exams'][1]['start']);assert saved(c)==first
    page.locator('#exam-start-1').fill('15:');page.locator('#restoreSaved').click()
    expect(page.locator('#exam-start-1')).to_have_value(first['exams'][1]['start']);assert saved(c)==first
    nav(page,'data');page.locator('#editGrades').click();page.locator('[data-grade-add]').click()
    page.locator('#grade-name-3').fill('虚构草稿年级');page.locator('#formDialog [data-local-undo]').click()
    expect(page.locator('#grade-name-3')).to_have_value('');page.locator('#formDialog [data-local-undo]').click()
    expect(page.locator('[data-grade-name]')).to_have_count(3)
    page.locator('[data-grade-add]').click();page.locator('#grade-name-3').fill('虚构恢复前')
    page.locator('#formDialog [data-local-restore]').click();expect(page.locator('[data-grade-name]')).to_have_count(3)
    page.locator('[data-grade-add]').click();page.locator('#grade-name-3').fill('虚构恢复后控件')
    click_api(page,'#formSave','save');expect(page.locator('#formDialog')).not_to_be_visible()
    assert saved(c)['grades'][-1]=='虚构恢复后控件' and saved(c)['exams'][0]==first['exams'][0]
    nav(page,'seats');page.locator('[data-seat-view="table"]').click();page.locator('[data-seat="s7-001"]').click()
    before=saved(c);page.locator('#adjustSeat').fill('2');page.locator('#swapSeat').check()
    click_api(page,'#seatAdjustSave','adjust_seat_preview');click_api(page,'#formSave','adjust_seat')
    expect(page.locator('#formDialog')).not_to_be_visible();expect(page.locator('#draftState')).to_have_text('已提交到本机')
    click_api(page,'#globalUndo','edit_undo',timeout=8000)
    assert business(saved(c))==business(before),'一次撤销必须还原刚确认的整笔人工调整'
    monitor=manual_monitor_recovery(page,c,root)
    other_drafts=unrelated_draft_survives_manual_commit(page,c,root)
    return dict(**monitor,**other_drafts,draft_undo=True,dynamic_controls_rebound=True,latest_saved_keeps_other_commit=True,manual_committed_adjust_one_undo=True)


def grades_add(page,c,root):
    seed(page,c);nav(page,'data');page.locator('#editGrades').click();page.locator('[data-grade-add]').click()
    page.locator('#grade-name-3').fill('初一');page.locator('#formSave').click();expect(page.locator('#formError')).to_contain_text('重复')
    p=saved(c);page.locator('#grade-name-3').fill('虚构实验年级');fail_once(page,'save');click_api(page,'#formSave','save',ok=False)
    expect(page.locator('#formError')).to_contain_text('虚构注入');expect(page.locator('#grade-name-3')).to_have_value('虚构实验年级');assert saved(c)==p
    click_api(page,'#formSave','save');expect(page.locator('#formDialog')).not_to_be_visible()
    expect(page.locator('#gradeTotal')).to_contain_text('4');assert saved(c)['grades'][-1]=='虚构实验年级'
    return dict(requirements=[3],duplicate_alias_rejected=True,failed_input_kept=True,manual_add_saved=True)


def room_bulk(page,c,root):
    seed(page,c);nav(page,'data');page.locator('[data-kind="rooms"]').click();old=saved(c)
    page.locator('#entitySelectAll').check();page.locator('#bulkEditSelected').click()
    page.locator('[data-bulk-field="location"]').check();page.locator('[data-bulk-value="location"]').fill('虚构统一二楼')
    click_api(page,'#bulkPreview','bulk_preview');click_api(page,'#bulkApply','bulk_apply')
    expect(page.locator('#bulkDialog')).not_to_be_visible();p=saved(c)
    for a,b in zip(old['rooms'],p['rooms']):assert {k:v for k,v in a.items() if k!='location'}=={k:v for k,v in b.items() if k!='location'}
    page.locator('#entitySearch').fill('没有此考场');expect(page.locator('#entityTable')).to_contain_text('没有找到')
    expect(page.locator('#entitySelectAll')).to_be_disabled();expect(page.locator('#selectionCount')).to_contain_text('已选 2')
    page.locator('#entitySearch').fill('');expect(page.locator('#entityTable tbody tr')).to_have_count(2)
    page.locator('#deleteSelected').click();expect(page.locator('#bulkResult')).to_contain_text('移除 12')
    expect(page.locator('#bulkApply')).to_be_disabled();page.locator('#bulkImpactConfirm').check()
    click_api(page,'#bulkApply','bulk_apply');expect(page.locator('#bulkDialog')).not_to_be_visible()
    assert not saved(c)['rooms'] and len(saved(c)['students'])==12
    click_api(page,'#globalUndo','edit_undo');expect(page.locator('#entityTable tbody tr')).to_have_count(2)
    assert business(saved(c))==business(p)
    return dict(requirements=[4],selected_fields_only=True,filtered_selection_count=True,used_delete_undo=True)


def defaults(page,c,root):
    seed(page,c);original=saved(c);nav(page,'seats');open_details(page,'#seatSettings')
    page.locator('#mode').select_option('random');page.locator('#seed').fill('17');page.locator('[data-default-group="seating"]').click()
    expect(page.locator('#mode')).to_have_value('class');click_api(page,'#mixSettingsSave','save')
    nav(page,'invigilate');open_details(page,'#invigilate details');page.locator('#invigilatorCount').fill('7')
    page.locator('[data-default-group="monitors"]').click();expect(page.locator('#invigilatorCount')).to_have_value('2')
    click_api(page,'#applySettings','save');nav(page,'data');page.locator('[data-kind="rooms"]').click()
    page.locator('[data-edit="r01"]').click();page.locator('#room-name').fill('虚构必须保留名称')
    page.locator('[data-default-group="room_layout"]').click();expect(page.locator('#room-rows')).to_have_value('5')
    expect(page.locator('#room-name')).to_have_value('虚构必须保留名称');cancel(page,'roomDialog')
    page.locator('#roomBatchBtn').click();page.locator('#batch-location').fill('虚构一楼');page.locator('#batchNamePrefix').fill('虚构保留前缀')
    page.locator('#batch-rows').fill('1');page.locator('[data-default-group="batch_layout"]').click()
    expect(page.locator('#batch-rows')).to_have_value('5');expect(page.locator('#batch-location')).to_have_value('虚构一楼')
    expect(page.locator('#batchNamePrefix')).to_have_value('虚构保留前缀');cancel(page,'roomBatchDialog')
    nav(page,'export');page.locator('#printFont').fill('17');page.locator('#printReset').click();expect(page.locator('#printFont')).to_have_value('11')
    page.locator('#restoreSaved').click()
    p=saved(c);assert all(p[k]==original[k] for k in ('name','students','exams','grades','rooms','teachers'))
    return dict(requirements=[5],group_defaults_scoped=True,business_data_kept=True,defaults_drafts_only=True)


def room_create(page,c,root):
    seed(page,c);nav(page,'data');page.locator('[data-kind="rooms"]').click();page.locator('#roomBatchBtn').click()
    page.locator('#batchStart').fill('10');page.locator('#batchCount').fill('2');page.locator('#batch-rows').fill('2');page.locator('#batch-cols').fill('3')
    page.locator('#batch-capacity').fill('30');page.locator('#batch-location').fill('虚构新楼');page.locator('#batch-availability').fill('2026-11-12 08:00-12:00')
    click_api(page,'#batchPreviewBtn','room_batch_preview');expect(page.locator('#batchPreview')).to_contain_text('虚构新楼')
    page.locator('#batch-cols').fill('4');expect(page.locator('#batchApply')).to_be_disabled()
    click_api(page,'#batchPreviewBtn','room_batch_preview');before=saved(c);fail_once(page,'room_batch')
    click_api(page,'#batchApply','room_batch',ok=False);expect(page.locator('#batchError')).to_contain_text('虚构注入');assert saved(c)==before
    click_api(page,'#batchApply','room_batch');expect(page.locator('#roomBatchDialog')).not_to_be_visible()
    assert len(saved(c)['rooms'])==4 and all(r['capacity']==8 for r in saved(c)['rooms'][2:])
    # 已取消考场的迟到预览不得填入新考场。
    held=[];page.route('**/api/room_change_preview',lambda route:held.append(route));page.locator('[data-edit="r01"]').click()
    page.locator('#roomChangePreview').click();held_ready(page,held);cancel(page,'roomDialog');page.locator('[data-edit="r02"]').click()
    held[0].continue_();release_barrier(page);assert page.locator('#roomImpact').inner_text()==''
    expect(page.locator('#roomApply')).to_be_disabled();page.unroute('**/api/room_change_preview')
    click_api(page,'#roomChangePreview','room_change_preview');expect(page.locator('#roomImpact')).to_contain_text('虚构第02考场')
    cancel(page,'roomDialog')
    return dict(requirements=[6],actual_normalized_capacity=8,create_failure_atomic=True,late_room_preview_ignored=True)


def subjects(page,c,root):
    seed(page,c);old=saved(c);nav(page,'data');page.locator('[data-kind="exams"]').click();page.locator('#subjectCatalogBtn').click()
    page.locator('#catalog-duration-0').fill('80');page.locator('[data-catalog-add]').click()
    page.locator('[data-catalog-name]').last.fill('虚构自设科目');page.locator('[data-catalog-duration]').last.fill('37')
    click_api(page,'#formSave','subject_catalog_save');expect(page.locator('#formDialog')).not_to_be_visible()
    assert saved(c)['exams']==old['exams'];page.locator('#addEntityBtn').click();page.locator('#editSubjectPreset').select_option('虚构自设科目')
    expect(page.locator('#edit-duration')).to_have_value('37');page.locator('#edit-subject').fill('虚构手写科目')
    page.locator('#edit-start').fill('08:21');page.locator('#edit-end').fill('09:56');expect(page.locator('#edit-duration')).to_have_value('95')
    expect(page.locator('#edit-duration')).to_have_attribute('readonly','');click_api(page,'#formSave','save')
    expect(page.locator('#formDialog')).not_to_be_visible();assert saved(c)['exams'][-1]['duration']==95
    page.locator('#addEntityBtn').click();page.locator('#edit-subject').fill('虚构计划科目');page.locator('#edit-start').fill('10:00')
    page.locator('#edit-end').fill('');page.locator('#edit-duration').fill('37');click_api(page,'#formSave','save')
    expect(page.locator('#formDialog')).not_to_be_visible();assert saved(c)['exams'][-1]['duration']==37 and saved(c)['exams'][-1]['end']==''
    return dict(requirements=[7],catalog_keeps_old_exams=True,handwritten_and_preset=True,actual_minutes=95,partial_time_plan_minutes=37)


def navigation_styles(page,c,root):
    seed(page,c);nav(page,'data');page.locator('#nextStep').click();expect(page.locator('#schedule.active')).to_be_visible()
    page.locator('#exam-start-0').fill('08:10');expect(page.locator('#draftState')).to_contain_text('未保存')
    page.locator('#previousStep').click();expect(page.locator('#unsavedDialog')).to_be_visible();fail_once(page,'save')
    click_api(page,'#saveAndContinue','save',ok=False);expect(page.locator('#unsavedError')).to_contain_text('虚构注入')
    expect(page.locator('#schedule.active')).to_be_visible();expect(page.locator('#exam-start-0')).to_have_value('08:10')
    page.locator('#keepEditing').click();page.locator('#previousStep').click();click_api(page,'#saveAndContinue','save')
    expect(page.locator('#data.active')).to_be_visible();assert saved(c)['exams'][0]['duration']==110
    page.screenshot(path=str(root/'浅色步骤.png'),full_page=True)
    open_details(page,'.side-bottom .settings-panel');page.locator('#themeSelect').select_option('dark')
    for _ in range(10):page.locator('#fontPlus').click()
    expect(page.locator('#fontPercent')).to_have_text('150%');page.locator('#densitySelect').select_option('compact')
    page.set_viewport_size({'width':1050,'height':800});page.locator('[data-kind="rooms"]').click()
    active=page.locator('#data [data-kind][aria-selected="true"]');expect(active).to_have_count(1)
    assert active.evaluate('(e)=>getComputedStyle(e).boxShadow')!='none'
    page.wait_for_function('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(root/'深色大字窄屏.png'),full_page=True)
    return dict(requirements=[8],previous_step=True,save_then_continue=True,failure_stays=True,active_tab_shadow=True,light_dark_narrow=True)


def subject_batch(page,c,root):
    seed(page,c);nav(page,'data');page.locator('[data-kind="exams"]').click();page.locator('#subjectBatchBtn').click()
    page.locator('[data-subject-grade="七年级"]').check();page.locator('[data-subject-grade="八年级"]').check()
    page.locator('[data-subject-name="语文"]').check();page.locator('[data-subject-name="地理"]').check()
    page.locator('#subjectBatch-start').fill('10:00');page.locator('#subjectBatch-end').fill('10:50')
    click_api(page,'#subjectBatchPreview','subject_batch_preview');expect(page.locator('#subjectBatchResult')).to_contain_text('已有或重复 2')
    expect(page.locator('#subjectBatchResult')).to_contain_text('将新增 2');page.locator('#subjectCustomNames').fill('虚构实验项目')
    expect(page.locator('#formSave')).to_be_disabled();click_api(page,'#subjectBatchPreview','subject_batch_preview')
    click_api(page,'#formSave','subject_batch');expect(page.locator('#formDialog')).not_to_be_visible()
    assert len(saved(c)['exams'])==10 and sum(e['duration']==50 for e in saved(c)['exams'])==4
    held=[];page.route('**/api/subject_batch_preview',lambda route:held.append(route));page.locator('#subjectBatchBtn').click()
    page.locator('[data-subject-grade="七年级"]').check();page.locator('[data-subject-name="体育"]').check()
    page.locator('#subjectBatchPreview').click();held_ready(page,held);cancel(page);page.locator('#subjectCatalogBtn').click()
    held[0].continue_();release_barrier(page);expect(page.locator('#formTitle')).to_contain_text('科目预设')
    expect(page.locator('#formError')).not_to_be_visible();assert page.locator('[data-catalog-name]').count()>=10
    page.unroute('**/api/subject_batch_preview');cancel(page)
    return dict(requirements=[9],grade_subject_product=True,duplicates_not_overwritten=True,late_preview_not_in_other_form=True)


def dragging(page,c,root):
    bad=fictional_plan(spare=True);bad['rooms'][0].update(disabled=[3],capacity=6)
    initial=seed(page,c,bad);nav(page,'seats');page.locator('#seatSession').select_option(index=1)
    page.locator('button[data-drag-mode="students"]').click();pointer(page,'[data-student-drag="s7-002"]','#roomPreview [data-seat="3"]')
    expect(page.locator('.toast')).to_contain_text('停用');assert saved(c)==initial
    page.locator('button[data-drag-mode="labels"]').click();pointer(page,'#roomPreview [data-label-drag="2"]','#roomPreview [data-seat="8"]')
    expect(page.locator('.toast')).to_contain_text('容量');assert saved(c)==initial
    p=seed(page,c,fictional_plan(spare=True,locked=True));nav(page,'seats');page.locator('#seatSession').select_option(index=1)
    page.locator('button[data-drag-mode="students"]').click();pointer(page,'[data-student-drag="s7-001"]','#roomPreview [data-seat="7"]')
    expect(page.locator('.toast')).to_contain_text('锁定');assert saved(c)==p
    pointer(page,'[data-student-drag="s7-002"]','#roomPreview [data-seat="3"]')
    expect(page.locator('#formTitle')).to_contain_text('交换');click_api(page,'#formSave','adjust_seat');expect(page.locator('#formDialog')).not_to_be_visible()
    assert saved(c)['seats']['base']['s7-002']['seat']==3 and saved(c)['seats']['base']['s7-003']['seat']==2
    pointer(page,'[data-student-drag="s7-002"]','#roomPreview [data-seat="7"]')
    expect(page.locator('#formTitle')).to_contain_text('移动');click_api(page,'#formSave','adjust_seat');expect(page.locator('#formDialog')).not_to_be_visible()
    assert saved(c)['seats']['base']['s7-002']['seat']==7
    page.locator('[data-student-drag="s7-002"]').click();page.locator('#roomPreview [data-seat="8"]').focus();page.keyboard.press('Enter')
    expect(page.locator('#formTitle')).to_contain_text('移动');click_api(page,'#formSave','adjust_seat');expect(page.locator('#formDialog')).not_to_be_visible()
    assert saved(c)['seats']['base']['s7-002']['seat']==8
    # 切换到完整自定义标签/单科样本；用真正pointer交换标签。
    p=seed(page,c,fictional_plan(special=True,custom=True,locked=True));coords=physical_snapshot(p);nav(page,'seats')
    page.locator('button[data-drag-mode="labels"]').click();pointer(page,'#roomPreview [data-label-drag="4"]','#roomPreview [data-seat="2"]')
    expect(page.locator('#formTitle')).to_contain_text('交换座号');click_api(page,'#formSave','seat_labels_apply');expect(page.locator('#formDialog')).not_to_be_visible()
    p=saved(c);assert physical_snapshot(p)==coords and p['rooms'][0]['seat_labels']['1:2']==4
    nav(page,'export');page.locator('#exportSelectAll').click();page.locator('#draftExport').check()
    xlsx=export_ui(page,root,'xlsx');request=json.loads((root/'xlsx-request.json').read_text(encoding='utf-8'))
    assert_excel(xlsx.read_bytes(),p,list(c.call('state')['sections']),layouts=request.get('layouts'),scope=request.get('scope'))
    # 实际HTML/PDF的列位置由已知完整映射核对，不能用产品layouts作答案。
    coordinate_checks=[]
    for exam_id in ('e7-1','e7-2'):
        scope={'mode':'exam','exam_ids':[exam_id],'room_ids':['r01']}
        html=c.download(c.call('export',{'format':'html','sections':['seating'],'draft':True,'scope':scope})).decode('utf-8')
        (root/(exam_id+'实际物理座次图.html')).write_text(html,encoding='utf-8');assert_seating_html(html,p,exam_id)
        info=c.call('export',{'format':'pdf','sections':['seating'],'draft':True,'scope':scope});assert info['kind']=='pdf',info
        blob=c.download(info);path=root/(exam_id+'实际物理座次图.pdf');path.write_bytes(blob)
        from pypdf import PdfReader
        scoped=PdfReader(io.BytesIO(blob));assert len(scoped.pages)==info['page_count']
        coordinate_checks.append(assert_seating_pdf(scoped,p,exam_id))
    pdf=export_ui(page,root,'pdf');from pypdf import PdfReader
    reader=PdfReader(pdf);assert_pdf_text('\n'.join(x.extract_text() or '' for x in reader.pages),p)
    dump(root/'材料核对.json',{'excel_sections':16,'pdf_pages':len(reader.pages),'all_identity_numbers_verified':True,'known_columns_verified':True,'fixed_special_pdf_coordinates':coordinate_checks})
    nav(page,'seats');held=[];page.route('**/api/seat_labels_preview',lambda route:held.append(route))
    page.locator('button[data-drag-mode="labels"]').click();page.locator('#labelPointPreview').click();held_ready(page,held)
    page.locator('button[data-drag-mode="students"]').click();held[0].continue_();release_barrier(page)
    expect(page.locator('#formDialog')).not_to_be_visible();page.unroute('**/api/seat_labels_preview')
    page.locator('button[data-drag-mode="labels"]').click();held=[];page.route('**/api/seat_labels_preview',lambda route:held.append(route))
    page.locator('#labelPointPreview').click();held_ready(page,held);page.keyboard.press('Escape');held[0].continue_();release_barrier(page)
    expect(page.locator('#formDialog')).not_to_be_visible();page.unroute('**/api/seat_labels_preview')
    held=[];page.route('**/api/seat_labels_preview',lambda route:held.append(route));page.locator('#labelPointPreview').click();held_ready(page,held)
    page.locator('[data-room="r02"]').click();held[0].continue_();release_barrier(page)
    expect(page.locator('#formDialog')).not_to_be_visible();page.unroute('**/api/seat_labels_preview');page.locator('[data-room="r01"]').click()
    page.locator('#labelFirst').select_option('2');page.locator('#labelSecond').select_option('4')
    click_api(page,'#labelPointPreview','seat_labels_preview');click_api(page,'#formSave','seat_labels_apply')
    expect(page.locator('#formDialog')).not_to_be_visible();assert physical_snapshot(saved(c))==coords
    held=[];page.route('**/api/seat_labels_preview',lambda route:held.append(route));page.locator('#labelPointPreview').click();held_ready(page,held)
    page.locator('#labelReset').click();held_ready(page,held,2);held[1].continue_();expect(page.locator('#formTitle')).to_contain_text('默认座号')
    held[0].continue_();release_barrier(page);expect(page.locator('#formTitle')).to_contain_text('默认座号');page.unroute('**/api/seat_labels_preview')
    click_api(page,'#formSave','seat_labels_apply');expect(page.locator('#formDialog')).not_to_be_visible()
    assert physical_snapshot(saved(c))==coords and saved(c)['rooms'][0]['seat_labels']=={}
    return dict(requirements=[10],actual_pointer_move_exchange=True,actual_pointer_label_swap=True,keyboard_alternative=True,
        physical_positions_and_locks_preserved=True,mode_and_escape_late_guards=True,actual_excel_pdf_html=True)


def room_shrink(page,c,root):
    p=seed(page,c,fictional_plan(special=True,custom=True,locked=True));nav(page,'data');page.locator('[data-kind="rooms"]').click()
    page.locator('[data-edit="r01"]').click();page.locator('#room-rows').fill('1')
    expect(page.locator('#roomError')).to_contain_text('恢复默认座号');page.locator('#roomResetLabels').check()
    expect(page.locator('#roomLayoutStats')).to_contain_text('3 位');click_api(page,'#roomChangePreview','room_change_preview')
    expect(page.locator('#roomImpact')).to_contain_text('移除');expect(page.locator('#roomImpact')).to_contain_text('锁定')
    expect(page.locator('#roomApply')).to_be_disabled();page.locator('#roomImpactConfirm').check()
    before=saved(c);fail_once(page,'room_save');click_api(page,'#roomApply','room_save',ok=False)
    expect(page.locator('#roomError')).to_contain_text('虚构注入');expect(page.locator('#room-rows')).to_have_value('1');assert saved(c)==before
    click_api(page,'#roomApply','room_save');expect(page.locator('#roomDialog')).not_to_be_visible()
    assert len(saved(c)['students'])==12 and len(saved(c)['edit_history'])==len(before['edit_history'])+1
    click_api(page,'#globalUndo','edit_undo');assert business(saved(c))==business(before)
    return dict(requirements=[11],normalized_layout_live=True,reset_and_shape_one_transaction=True,impact_confirmed=True,failure_keeps_input=True)


def checks(page,c,root):
    p=fictional_plan();p['students'][0]['name']=p['students'][1]['name']='';seed(page,c,p);nav(page,'check')
    expect(page.locator('#checkResult')).to_contain_text('影响 2 项');button=page.locator('[data-issue-locate]').filter(has_text='姓名').first
    detail=button.locator('xpath=ancestor::details[1]')
    if detail.get_attribute('open') is None:detail.locator('summary').click()
    button.click();expect(page.locator('#edit-name')).to_be_focused();page.locator('#edit-name').fill('虚构补齐姓名')
    click_api(page,'#formSave','save');expect(page.locator('#formDialog')).not_to_be_visible();page.locator('#returnCheck').click()
    expect(page.locator('#check.active')).to_be_visible();expect(page.locator('#issueContext')).to_contain_text('最新保存')
    assert len([e for e in c.call('state')['validation']['errors'] if e.get('field')=='name'])==1
    seed(page,c,p);nav(page,'check');page.locator('[data-issue-batch]').first.click();page.locator('#issueBatchValue').fill('统一虚构姓名')
    click_api(page,'#formSave','save');expect(page.locator('#formDialog')).not_to_be_visible();page.locator('#returnCheck').click()
    expect(page.locator('#check.active')).to_be_visible();assert not [e for e in c.call('state')['validation']['errors'] if e.get('field')=='name']
    return dict(requirements=[12],object_field_focus=True,return_rechecks=True,same_root_batch=True)


def help_license_header(page,c,root):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from exam_room.licensing import License,sign_code
    key=Ed25519PrivateKey.generate();clock=lambda:datetime(2026,10,13,tzinfo=timezone.utc)
    c.app.license=License(root/'仅虚构许可',key.public_key(),machine='FICTIONAL-UI-USABILITY',clock=clock,contact='虚构提供者')
    seed(page,c);page.context.grant_permissions(['clipboard-read','clipboard-write'])
    page.locator('#helpBtn').click();page.locator('[data-help-section="drag"]').click();expect(page.locator('#helpContent')).to_contain_text('物理位置')
    page.locator('[data-help-section="contact"]').click();page.locator('#helpCopyRoot').click()
    assert page.evaluate('navigator.clipboard.readText()')==str(c.app.root);page.locator('#helpClose').click()
    open_details(page,'.side-bottom .settings-panel');page.locator('#licenceBtn').click()
    expect(page.locator('#activationMachine')).to_have_value('FICTIONAL-UI-USABILITY');page.locator('#copyMachine').click()
    assert page.evaluate('navigator.clipboard.readText()')=='FICTIONAL-UI-USABILITY'
    page.locator('#activationCode').fill('虚构错误码');click_api(page,'#formSave','activate',ok=False)
    expect(page.locator('#activationCode')).to_have_value('虚构错误码');page.locator('#formDialog [data-local-restore]').click()
    expect(page.locator('#activationCode')).to_have_value('');page.locator('#copyMachine').click()
    page.locator('#activationCode').fill(sign_code(key,'FICTIONAL-UI-USABILITY',None));click_api(page,'#formSave','activate')
    expect(page.locator('#formDialog')).not_to_be_visible();expect(page.locator('#licence')).to_have_text('已激活')
    nav(page,'seats');open_details(page,'#seatSettings');page.locator('[data-explain]').click();expect(page.locator('#explainText')).to_contain_text('容量')
    page.keyboard.press('Escape');expect(page.locator('#explainDialog')).not_to_be_visible()
    nav(page,'overview');reveal_plan_settings(page);before=saved(c);page.locator('#planName').fill('虚构顶栏草稿')
    page.locator('#overview h1').click();expect(page.locator('#planMenu')).not_to_have_attribute('open','')
    reveal_plan_settings(page);expect(page.locator('#planName')).to_have_value('虚构顶栏草稿');assert saved(c)==before
    click_api(page,'#planInfoSave','save');expect(page.locator('#planMenu')).not_to_have_attribute('open','')
    return dict(requirements=[13],help_copy_explain=True,temporary_fictional_activation=True,restored_controls_work=True,top_save_collapse=True,outside_keeps_draft=True)


CASES=[('WEB-U01','新版年级批量删除与关联定位',grades_delete),('WEB-U02','草稿撤销动态恢复与最近保存',recovery),
    ('WEB-U03','逐项添加年级与失败保留输入',grades_add),('WEB-U04','考场多选字段修改删除撤销',room_bulk),
    ('WEB-U05','各设置组默认与业务保留',defaults),('WEB-U06','考场直接创建与迟到预览',room_create),
    ('WEB-U07','科目预设手写与分钟一致',subjects),('WEB-U08','步骤保存失败与浅深窄屏',navigation_styles),
    ('WEB-U09','科目批量去重与迟到弹窗',subject_batch),('WEB-U10','两类真实pointer调整与实际材料',dragging),
    ('WEB-U11','手动行列影响与一笔恢复',room_shrink),('WEB-U12','检查字段定位返回与同根因批量',checks),
    ('WEB-U13','帮助激活复制解释与顶栏草稿',help_license_header)]
