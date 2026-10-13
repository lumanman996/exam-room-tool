"""测试方独立年级验收；通过可见控件操作，不调用前端内部函数。"""
import json
import re
from playwright.sync_api import expect
from .common import load
from .browser import click_api,navigate,reveal_plan_settings,import_button

GRADES=['七年级','八年级','九年级']


def seed(page,client,legacy=False):
    p=load('C01_tiny_completed')
    if not legacy:p['grades']=GRADES[:]
    p=client.import_plan(p)['plan']
    page.goto(client.url)
    click_api(page,f'[data-open="{p["id"]}"]','open')
    expect(page.locator('#planName')).to_have_value(p['name'])
    return p


def mix_options(page):
    navigate(page,'seats')
    reveal_seats(page)
    page.locator('[data-mix-mode="pair"]').click()
    options=page.locator('#mixPair option').all_text_contents()
    assert len(options)==3 and all(any(g in text for text in options) for g in GRADES),options


def reveal_seats(page):
    if page.locator('#seatSettings').get_attribute('open') is None:
        page.locator('#seatSettings > summary').click()


def empty_grades(page,client,root):
    page.goto(client.url);page.locator('#newBtn').click()
    page.locator('#newName').fill('虚构·三年级空考试')
    expect(page.locator('[data-grade-name]')).to_have_count(3)
    for i,g in enumerate(GRADES):page.locator(f'[data-grade-name="{i}"]').fill(g)
    p=click_api(page,'#formSave','new')['plan']
    assert p['grades']==GRADES and not p['students']
    navigate(page,'data')
    expect(page.locator('#gradeSummary .grade-chip')).to_have_count(3)
    expect(page.locator('#gradeSummary')).to_contain_text('九年级')
    mix_options(page)
    # 取消尚未保存的选择，保留空考试用于通用重开核对。
    page.locator('[data-mix-mode="separate"]').click()
    click_api(page,'#mixSettingsSave','save')
    return dict(configured_grades=GRADES,students=0,pairs=3)


def preset_grades(page,client,root):
    p=seed(page,client);assert {x['grade'] for x in p['students']}==set(GRADES[:2])
    mix_options(page)
    # 选择七八；九年级虽无学生仍在正式范围，保持独立。
    pair=next(x.get_attribute('value') for x in page.locator('#mixPair option').all() if '七年级' in x.inner_text() and '八年级' in x.inner_text())
    page.locator('#mixPair').select_option(pair)
    page.locator('#mixPresetSave').click();page.locator('#mixPresetName').fill('虚构七八合编')
    click_api(page,'#formSave','save')
    expect(page.locator('#formDialog')).not_to_be_visible()
    p=client.call('state')['plan'];assert p['grades']==GRADES
    preset=next(x for x in p['settings']['mix_presets'] if x['name']=='虚构七八合编')
    assert preset['groups']==[GRADES[:2]]
    reveal_seats(page)
    page.locator('[data-mix-mode="separate"]').click();click_api(page,'#mixSettingsSave','save')
    reveal_seats(page)
    page.locator('#mixPresetSelect').select_option(preset['id'])
    click_api(page,'#mixPresetApply','save')
    p=client.call('state')['plan'];assert p['settings']['mix_groups']==[GRADES[:2]]
    return dict(configured_grades=GRADES,actual_grades=GRADES[:2],preset=preset)


def unknown_grade(page,client,root):
    seed(page,client);navigate(page,'data')
    before=client.call('state')['plan'];blob=client.app.store.path(before['id']).read_bytes()
    path=root/'虚构未知年级.csv';path.write_text('姓名,年级,班级,考号\n虚构新生,十年级,虚构班,999999\n',encoding='utf-8-sig')
    selector=import_button(page,'students')
    with page.expect_file_chooser() as chooser:page.locator(selector).click()
    chooser.value.set_files(path)
    expect(page.locator('#importDialog')).to_be_visible()
    result=click_api(page,'#importPreflightBtn','import_preflight')
    assert result['errors']
    expect(page.locator('#importConfirm')).to_be_disabled()
    expect(page.locator('#importPreflightResult')).to_contain_text('十年级')
    page.locator('#importCancel').click()
    assert client.call('state')['plan']==before and client.app.store.path(before['id']).read_bytes()==blob
    return dict(unknown_grade_rejected=True,state_revision_and_disk_unchanged=True)


def legacy_grades(page,client,root):
    p=seed(page,client,legacy=True);assert p['grades']==GRADES[:2]
    navigate(page,'data');expect(page.locator('#gradeReview')).to_be_visible()
    page.locator('#editGrades').click();expect(page.locator('[data-grade-name]')).to_have_count(2)
    click_api(page,'#formSave','save')
    expect(page.locator('#gradeReview')).not_to_be_visible()
    assert not client.call('state')['plan']['grade_review_required']
    return dict(legacy_migrated=GRADES[:2],review_saved=True)


def top_menu(page,client,root):
    seed(page,client);before=client.call('state')['plan'];blob=client.app.store.path(before['id']).read_bytes()
    reveal_plan_settings(page);page.locator('#planName').fill('虚构·保留未保存输入')
    page.locator('#overview h1').click()
    expect(page.locator('#planMenu')).not_to_have_attribute('open','')
    reveal_plan_settings(page);expect(page.locator('#planName')).to_have_value('虚构·保留未保存输入')
    assert client.call('state')['plan']==before and client.app.store.path(before['id']).read_bytes()==blob
    # 明确注入保存失败，检查提示/草稿；不是声称产品真实发生故障。
    page.route('**/api/save',lambda route:route.fulfill(status=200,content_type='application/json',body=json.dumps({'ok':False,'error':'虚构注入：保存失败'})))
    try:
        click_api(page,'#planInfoSave','save',ok=False)
        expect(page.locator('#planMenu')).to_have_attribute('open','')
        expect(page.locator('#planInfoError')).to_contain_text('虚构注入')
        expect(page.locator('#planName')).to_have_value('虚构·保留未保存输入')
        assert client.call('state')['plan']==before and client.app.store.path(before['id']).read_bytes()==blob
    finally:page.unroute('**/api/save')
    click_api(page,'#planInfoSave','save')
    expect(page.locator('#planMenu')).not_to_have_attribute('open','')
    assert client.call('state')['plan']['name']=='虚构·保留未保存输入'
    return dict(outside_collapses_without_save=True,failure_retains_draft=True,success_collapses=True)


def empty_scope(page,client,root):
    seed(page,client);navigate(page,'seats');page.locator('[data-seat-tab="numbering"]').click()
    assert page.locator('#numberGrade option').all_text_contents()==['全部年级',*GRADES]
    page.locator('#numberGrade').select_option('九年级')
    result=click_api(page,'#numberPreviewBtn','number_preview')
    assert not result['rows'] and not result['errors'] and result['warnings']
    expect(page.locator('#numberPreview')).to_contain_text('没有学生')
    expect(page.locator('#numberApply')).to_be_disabled()
    before=client.call('state')['plan']
    page.locator('#restoreSaved').click()
    expect(page.locator('#numberDialog')).not_to_have_class(re.compile(r'.*\bdirty\b.*'))
    assert client.call('state')['plan']==before,'恢复未提交参数不能改变已保存方案'
    navigate(page,'export')
    expect(page.locator('#export.active')).to_be_visible()
    assert page.locator('#printGrade option').all_text_contents()==['全部年级',*GRADES]
    page.locator('#exportSelectAll').click()
    page.locator('#printGrade').select_option('九年级')
    page.locator('#previewBtn').click()
    expect(page.locator('#exportStatus')).to_contain_text('预览已更新',timeout=110000)
    expect(page.frame_locator('#printPreview').locator('body')).to_contain_text('没有',timeout=15000)
    return dict(unused_grade_selectable=True,number_preview_rows=0,number_apply_disabled=True,actual_print_preview_empty=True)


CASES=[('WEB-grades-empty','空考试正式三年级与全部混排选项',empty_grades),
    ('WEB-grades-preset','两类学生保留第三年级与具名混排重开',preset_grades),
    ('WEB-grades-unknown','未知年级预检拒绝且磁盘不变',unknown_grade),
    ('WEB-grades-legacy','旧方案年级迁移提示与确认',legacy_grades),
    ('WEB-plan-menu','顶栏收起、草稿、失败与成功保存',top_menu),
    ('WEB-grades-empty-scope','无学生年级考号与实际打印预览',empty_scope)]
