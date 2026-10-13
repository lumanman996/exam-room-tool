"""通过真实本机HTTP执行样本及集成流程；大规模求解单独监督。"""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request

from .common import KIT, assert_excel, assert_plan, dump, load, service


def regenerate(client, prefix='001'):
    options=dict(prefix=prefix,overwrite=True,rule='seat')
    preview=client.call('number_preview',options)
    assert not preview['errors'], preview['errors']
    return client.call('numbers',dict(**options,revision=preview['revision']))


def complete(client, schedule=False):
    if schedule:
        result=client.solve('schedule'); assert result['task']['status'] in ('optimal','feasible'),result['task']
    result=client.solve('seats'); assert result['task']['status'] in ('optimal','feasible'),result['task']
    p=result['view']['plan']
    if p.get('number_sources'): regenerate(client)
    result=client.solve('invigilators'); assert result['task']['status'] in ('optimal','feasible'),result['task']
    p=client.call('confirm')['plan']; assert_plan(p)
    return p


def assert_golden(client, case, p):
    from .common import expected_rows
    answer=json.loads((KIT/Path(case['path']).parent/'golden_expected.json').read_text(encoding='utf-8'))
    rows,_=expected_rows(p)
    projected=[{k:r[k] for k in ('student_id','exam_id','number','room_id','seat','date','start','end')} for r in rows]
    key=lambda r:(r['exam_id'],r['student_id'])
    assert sorted(projected,key=key)==sorted(answer['exam_student_rows'],key=key)
    sections=list(client.call('state')['sections'])
    info=client.call('export',dict(format='xlsx',sections=sections))
    assert_excel(client.download(info),p,sections)
    html=client.download(client.call('export',dict(format='html',sections=sections))).decode()
    assert '草稿，请核对后使用' not in html
    assert all(s['number'] in html for s in p['students'])
    return dict(exam_rows=len(rows),export_file=info['path'])


def plan_case(recorder, c):
    ident=c['id']; directory=recorder.root/ident
    input_plan=load(ident);grade_rejection=None
    with service(directory/'workspace') as client:
        if ident=='C07_missing_required':
            # 原始空年级负样本原封不动；新规则要求在导入时就拒绝。
            original=load('C01_tiny_completed')
            before=client.import_plan(original)['plan']
            blob=client.app.store.path(before['id']).read_bytes()
            rejected=client.raw('plan_import',{'data':base64.b64encode(json.dumps(input_plan).encode()).decode()})
            assert not rejected['ok'] and '年级' in rejected['error'],rejected
            assert client.call('state')['plan']==before
            assert client.app.store.path(before['id']).read_bytes()==blob
            grade_rejection=dict(empty_grade_rejected=True,original_plan_revision_and_disk_unchanged=True,error=rejected['error'])
            # 仅测试副本补回已知年级，继续原缺姓名/班级、导出拦截和修复流程。
            input_plan=deepcopy(input_plan)
            input_plan['students'][0]['grade']=original['students'][0]['grade']
            dump(directory/'仅补年级的测试副本.json',input_plan)
        client.import_plan(input_plan)
        view=client.call('state'); p=view['plan']; e=c['expected']
        assert all(len(p[k])==n for k,n in c['counts'].items())
        errors={i['code'] for i in view['validation']['errors']}; warnings={i['code'] for i in view['validation']['warnings']}
        assert set(e['required_error_codes']) <= errors
        assert set(e['required_warning_codes']) <= warnings
        if e['zero_hard_errors']: assert not errors,sorted(errors); assert_plan(p)
        if errors:
            # 监考问题只阻断相关材料；包含监考总表才能覆盖全部阶段。
            result=client.raw('export',dict(format='xlsx',sections=['students','invigilation']))
            assert not result['ok'], '相关材料有硬问题却允许正式导出'
            if all(i.get('stage')=='monitors' for i in view['validation']['errors']):
                assert client.raw('export',dict(format='xlsx',sections=['students']))['ok'],'监考问题误阻断已合格学生材料'
            info=client.call('export',dict(format='xlsx',sections=['students'],draft=True))
            import openpyxl
            wb=openpyxl.load_workbook(io.BytesIO(client.download(info)))
            assert '草稿' in wb['学生编排总表']['A1'].value; wb.close()
        details=dict(initial_error_codes=sorted(errors),warning_codes=sorted(warnings),http_import=True)
        if grade_rejection:details['strict_grade_import']=grade_rejection
        if c['golden']: details.update(assert_golden(client,c,p))
        if ident in ('C02_normal_144','C03_unscheduled','C04_locked','C22_selected_mixing'):
            before=deepcopy(p); p=complete(client,schedule=ident in ('C03_unscheduled','C04_locked'))
            if ident=='C04_locked':
                assert p['exams'][0]==before['exams'][0]
                assert p['seats']['base']['s7-001']==before['seats']['base']['s7-001']
                assert p['invigilation']['r01|2026-11-12|08:30|10:00'][0]==before['invigilation']['r01|2026-11-12|08:30|10:00'][0]
            if ident=='C22_selected_mixing':
                by_room={}
                for s in p['students']: by_room.setdefault(p['seats']['base'][s['id']]['room_id'],[]).append(s)
                assert all(all(s['grade']=='九年级' for s in ss) or all(s['grade']!='九年级' for s in ss) for ss in by_room.values())
                assert any(len({s['grade'] for s in ss})==2 for ss in by_room.values()), '七八年级实际没有交插混排'
                for ss in by_room.values():
                    ss.sort(key=lambda s:p['seats']['base'][s['id']]['seat'])
                    if len({s['grade'] for s in ss})==2:
                        assert all(a['grade']!=b['grade'] for a,b in zip(ss,ss[1:]))
            sections=list(view['sections']); info=client.call('export',dict(format='xlsx',sections=sections))
            details.update(assert_excel(client.download(info),p,sections)); details['completed']=True
        elif ident=='C17_teacher_shortage':
            result=client.solve('invigilators'); assert result['task']['status']=='partial',result['task']
            p=result['view']['plan']; assert_plan(p,allow_shortage=True)
            assert sum(x['missing'] for x in result['task']['unfilled'])==3
            assert all(x['reasons'] for x in result['task']['unfilled'])
            assert {x['code'] for x in result['view']['validation']['errors']}=={'invigilator_missing'}
            p['teachers'].append(deepcopy(load('C01_tiny_completed')['teachers'][-1]))
            client.call('save',dict(plan=p,revision=p['revision']))
            result=client.solve('invigilators'); assert result['task']['status'] in ('optimal','feasible')
            p=client.call('confirm')['plan']; assert_plan(p); details['partial_and_recovery']=True
        elif ident=='C24_lock_conflict':
            result=client.solve('seats'); assert result['task']['status'] in e['solver_status']
            assert client.call('state')['plan']['seats']==p['seats']; details['lock_not_relaxed']=True
        elif ident=='C18_number_mismatch':
            assert sum(x['code']=='number_seat_mismatch' for x in view['validation']['errors'])==2
            old=[s['number'] for s in p['students']]; preview=client.call('number_preview',dict(prefix='001',overwrite=True))
            assert preview['changes']==2 and [s['number'] for s in client.call('state')['plan']['students']]==old
            p=regenerate(client)['plan']; assert_plan(p); details['mismatch_repaired']=True
        elif ident=='C25_stale':
            p=client.call('confirm')['plan']; assert not p.get('stale'); assert_plan(p)
        elif ident.startswith(tuple(f'C{i:02}_' for i in (6,7,9,10,11,12,13,14,15,16))):
            # 将故意改坏的字段恢复为手工标准值，检验失败后的复核与正式导出恢复。
            original=load('C01_tiny_completed'); repaired=deepcopy(p)
            fields={6:['students'],7:['students'],9:['rooms'],10:['seats'],11:['exams'],12:['rooms'],
                    13:['teachers'],14:['teachers'],15:['teachers'],16:['invigilation']}[int(ident[1:3])]
            for field in fields: repaired[field]=deepcopy(original[field])
            client.call('save',dict(plan=repaired,revision=p['revision']))
            p=client.call('confirm')['plan']; assert_plan(p)
            info=client.call('export',dict(format='xlsx',sections=['students']))
            assert_excel(client.download(info),p,['students']); details['recovered']=True
        elif ident=='C19_legacy':
            assert all(r['direction']=='horizontal' for r in p['rooms'])
            assert not client.call('number_preview',dict(prefix='001',overwrite=True))['errors']
        elif ident=='C26_safe_text':
            sections=['students','tickets']; info=client.call('export',dict(format='xlsx',sections=sections))
            assert_excel(client.download(info),p,sections)
            html=client.download(client.call('export',dict(format='html',sections=sections))).decode()
            assert '<script>window.TEST' not in html and '&lt;script&gt;window.TEST' in html
        if e.get('scale'): details['scope']='HTTP导入与初始检查；真实规模求解在full的SCALE项目单独执行'
        exported=json.loads(client.download(client.call('plan_export')))
        assert exported==client.call('state')['plan'], '导出方案与当前方案不一致'
        dump(directory/'actual-plan.json',exported)
        details['persisted']=True
    with service(directory/'workspace') as reopened:
        state=reopened.call('open',{'id':exported['id']})
        assert state['plan']==exported, '服务重启后方案内容变化'
    return details


def import_case(recorder,c):
    directory=recorder.root/c['id']; e=c['expected']; f=KIT/c['path']
    with service(directory/'workspace',load('C01_tiny_completed')) as client:
        if c['id'] in ('I01','I02','I03'):
            # 模拟教务先明确设置本次考试范围；不从导入资料推导年级。
            configured=client.call('state')['plan'];configured['grades']=['七年级','八年级','九年级']
            configured=client.call('save',dict(plan=configured,revision=configured['revision']))['plan']
            assert configured['grades']==['七年级','八年级','九年级']
        before=client.call('state')['plan']; data=base64.b64encode(f.read_bytes()).decode()
        if e.get('plan_import_reject'):
            result=client.raw('plan_import',{'data':data}); assert not result['ok']
            assert client.call('state')['plan']==before
            return dict(rejected=True,original_preserved=True)
        body=dict(data=data,filename=f.name,kind=e['kind'])
        result=client.raw('import_preview',body)
        if e.get('preview_reject'):
            assert not result['ok']; assert client.call('state')['plan']==before
            return dict(rejected=True,original_preserved=True)
        assert result['ok']; preview=result['data']; assert preview['count']==e['count']
        if 'sheet' in e: assert preview['sheet']==e['sheet'] and preview['header_row']==e['header_row']
        confirm=dict(kind=e['kind'],rows=preview['rows'],mapping=preview['mapping'],append=False,revision=before['revision'])
        # 新后端在确认前定位必填和重复字段；旧接口在统一检查定位。
        # 两种路径均必须证明错误定位和失败无部分写入，不能只接受任意报错。
        if e.get('validation_error') and hasattr(client.app,'api_import_preflight'):
            pre=client.call('import_preflight',confirm)
            expected=e['validation_error']
            assert any((expected=='number_duplicate' and x.get('field')=='number') or
                (expected=='student_data' and x.get('field')=='name') for x in pre['errors']), pre
            rejected=client.raw('import',confirm); assert not rejected['ok']
            assert client.call('state')['plan']==before
            return dict(rejected_before_commit=True,original_preserved=True,preflight_errors=pre['errors'])
        result=client.raw('import',confirm)
        if e.get('import_reject'):
            assert not result['ok']; assert client.call('state')['plan']==before
            return dict(rejected_at_confirmation=True,original_preserved=True)
        assert result['ok'],result; view=result['data']; p=view['plan']; assert len(p[e['kind']])==e['count']
        if c['id'] in ('I01','I02','I03'):assert p['grades']==configured['grades']
        if e.get('leading_zero'): assert p['students'][0]['number']=='700001' and p['students'][0]['student_no']=='00700001'
        if e.get('original_column'): assert p['students'][0]['original'][e['original_column']]==500
        if e.get('validation_error'): assert e['validation_error'] in {x['code'] for x in view['validation']['errors']}
        return dict(imported=e['count'],check_codes=sorted({x['code'] for x in view['validation']['errors']}))


def persistence(recorder):
    with service(recorder.root/'API-persistence'/'workspace',load('C01_tiny_completed')) as client:
        p=client.call('state')['plan']; ident=p['id']
        q=deepcopy(p); q['name']='虚构保存新名称'
        client.call('save',dict(plan=q,revision=p['revision']))
        assert client.app.store.path(ident).with_suffix('.backup').exists()
        assert not client.raw('save',dict(plan=q,revision=p['revision']))['ok']
        current=client.call('state')['plan']; assert current['name']==q['name']
        copied=client.call('clone',{'id':ident})['plan']; assert copied['id']!=ident and copied['seats']==current['seats']
        client.call('delete',{'id':copied['id']}); assert any(x['id']==copied['id'] for x in client.call('state')['trash'])
        client.call('restore',{'id':copied['id']}); assert client.call('open',{'id':copied['id']})['plan']['seats']==current['seats']
    return dict(backup=True,stale_save_rejected=True,clone_delete_restore=True)


def preview_conflict(recorder):
    with service(recorder.root/'API-preview'/'workspace',load('C01_tiny_completed')) as client:
        preview=client.call('number_preview',dict(prefix='002',overwrite=True))
        p=client.call('state')['plan']; p['name']='虚构预览期间的新修改'
        client.call('save',dict(plan=p,revision=p['revision']))
        assert not client.raw('numbers',dict(prefix='002',overwrite=True,revision=preview['revision']))['ok']
        batch=client.call('room_batch_preview',dict(start=3,count=1)); p=client.call('state')['plan']; p['school']='虚构新校名'
        client.call('save',dict(plan=p,revision=p['revision']))
        assert not client.raw('room_batch',dict(start=3,count=1,revision=batch['revision']))['ok']
    return dict(number_preview_conflict=True,room_preview_conflict=True)


def adjustment(recorder):
    with service(recorder.root/'API-adjustment'/'workspace',load('C01_tiny_completed')) as client:
        p=client.call('state')['plan']; mapping=p['seats']['base']; nums=[s['number'] for s in p['students']]
        v=client.call('adjust_seat',dict(student_id='s7-001',room_id='r01',seat=2,swap=True,locked=True))
        assert v['plan']['seats']['base']['s7-001']['seat']==2
        assert [s['number'] for s in v['plan']['students']]==nums
        assert sum(x['code']=='number_seat_mismatch' for x in v['validation']['errors'])==2
        assert client.call('undo')['plan']['seats']['base']==mapping
        client.call('adjust_seat',dict(student_id='s7-001',room_id='r01',seat=2,swap=True,exam_id='e7-1'))
        v=client.call('state'); assert not any(x['code']=='number_seat_mismatch' for x in v['validation']['errors'])
        assert client.call('undo')['plan']['seats']==p['seats']
        regenerate(client,'002'); assert client.call('number_undo')['plan']['students']==p['students']
    return dict(seat_swap_undo=True,special_seat_undo=True,number_undo_independent=True)


def concurrency(recorder):
    from exam_room import engine
    original=engine.assign_seats; entered=threading.Event(); release=threading.Event()
    def gated(plan,**kwargs):
        entered.set(); assert release.wait(8), '测试屏障超时'
        return original(plan,**kwargs)
    # 仅控制提交时序；仍调用真正求解器。该阶段独立子进程，无其他并发测试。
    engine.assign_seats=gated
    try:
        with service(recorder.root/'API-concurrency'/'workspace',load('C02_normal_144')) as client:
            for action in ('edit','switch','cancel'):
                entered.clear(); release.clear(); client.call('solve',{'kind':'seats','time_limit':5})
                assert entered.wait(5)
                if action=='edit':
                    p=client.call('state')['plan']; p['name']='虚构求解期间的新编辑'
                    client.call('save',dict(plan=p,revision=p['revision']))
                elif action=='switch': client.call('new',{'name':'虚构切换后的新方案'})
                else: client.call('cancel')
                preserved=client.call('state')['plan']; release.set(); deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    result=client.call('task')
                    if result['task']['state']!='running': break
                    time.sleep(.03)
                assert result['task']['status']==('cancelled' if action=='cancel' else 'stale'),result['task']
                assert client.call('state')['plan']==preserved
    finally: release.set(); engine.assign_seats=original
    return dict(new_edit_preserved=True,new_plan_preserved=True,cancellation_preserved=True)


def token_check(recorder):
    with service(recorder.root/'API-token'/'workspace') as client:
        for token in ('','fictional-wrong-token'):
            try: client.raw('state',token=token)
            except urllib.error.HTTPError as e: assert e.code==403
            else: raise AssertionError('错误口令未拒绝')
        request=urllib.request.Request(client.url,headers={'Host':'fictional.invalid'})
        try: urllib.request.urlopen(request)
        except urllib.error.HTTPError as e: assert e.code==403
        else: raise AssertionError('非法Host未拒绝')
    return dict(wrong_token_403=True,wrong_host_403=True)


def license_flow(recorder):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from exam_room.licensing import License,sign_code
    root=recorder.root/'API-license'/'workspace'; key=Ed25519PrivateKey.generate()
    now=datetime(2026,10,6,tzinfo=timezone.utc)
    License(root/'license',key.public_key(),machine='FICTIONAL',clock=lambda:now).status()
    license=License(root/'license',key.public_key(),machine='FICTIONAL',clock=lambda:now+timedelta(days=4))
    with service(root,load('C01_tiny_completed'),license) as client:
        assert client.call('state')['license']['state']=='expired'
        result=client.raw('export',dict(format='xlsx',sections=['students'])); assert not result['ok'] and result['license']
        assert client.call('plan_export')['url']
        assert client.call('clone',{'id':client.call('state')['plan']['id']})['plan']
        assert not client.raw('activate',{'code':'fictional-invalid'})['ok']
        client.call('activate',{'code':sign_code(key,'FICTIONAL',None)})
        assert client.call('export',dict(format='xlsx',sections=['students']))['url']
    return dict(expired_preserves_plan=True,export_blocked=True,temporary_activation_restores_export=True)


def scale_case(recorder,ident):
    dump(recorder.root/ident/'测试预算.json',{'seats_seconds':30,'invigilators_seconds':90,
        'scope':'仅规模验测请求，不修改产品默认时间；partial或缺岗仍失败'})
    with service(recorder.root/ident/'workspace',load('C20_large_mixed' if ident=='SCALE-mixed' else 'C21_large_separate_shortage')) as client:
        result=client.solve('seats',limit=30); details=dict(seats=result['task'],test_budgets_seconds={'seats':30,'invigilators':90})
        if ident=='SCALE-separate':
            assert result['task']['status']=='infeasible',result['task']
            assert not client.call('state')['plan']['settings']['mix_grades']
            return dict(minimum_rooms=51,actual_rooms=50,status='infeasible',rules_not_relaxed=True)
        assert result['task']['status'] in ('feasible','optimal'),result['task']
        # CI机器速度不同；仅扩大验测请求预算，不更改产品默认或接受缺岗partial。
        result=client.solve('invigilators',limit=90)
        dump(recorder.root/ident/'监考任务终态.json',result['task'])
        assert result['task']['status'] in ('feasible','optimal'),result['task']
        assert not result['task']['unfilled'],result['task']
        p=client.call('confirm')['plan']; details['invigilators']=result['task']; details.update(assert_plan(p))
        assert len(p['students'])==1500 and len(p['rooms'])==50 and len(p['teachers'])==120
        assert details['exam_rows']==4500 and details['duties']==150
        info=client.call('export',dict(format='xlsx',sections=['students','invigilation','workload']))
        assert_excel(client.download(info),p,['students','invigilation','workload'])
        dump(recorder.root/ident/'actual-plan.json',p)
        if __import__('sys').platform!='win32':
            import resource,sys
            details['process_peak_memory_mb']=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1024*1024 if sys.platform=='darwin' else 1024),2)
        return details


def run(recorder,scale=False,only=None):
    selected=lambda ident:not only or ident in only
    if scale:
        for ident in ('SCALE-mixed','SCALE-separate'):
            if selected(ident): recorder.run(ident,'1500人实际求解与规则核对',lambda ident=ident:scale_case(recorder,ident))
        return
    cases=json.loads((KIT/'cases.json').read_text(encoding='utf-8'))['cases']
    for c in cases:
        if not selected(c['id']): continue
        fn=plan_case if c['type']=='plan' else import_case
        recorder.run(c['id'],c['name'],lambda c=c,fn=fn:fn(recorder,c))
    for ident,name,fn in [('API-persistence','备份、保存冲突、复制回收恢复',persistence),
        ('API-preview','编号与考场预览版本冲突',preview_conflict),('API-adjustment','交换撤销及考号独立撤销',adjustment),
        ('API-concurrency','真实求解中的修改、切换与取消',concurrency),('API-token','接口口令与Host保护',token_check),
        ('API-license','到期保留编排保存、激活恢复导出',license_flow)]:
        if not selected(ident): continue
        recorder.run(ident,name,lambda fn=fn:fn(recorder))
