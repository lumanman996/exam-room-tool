"""测试方独立真实HTTP/App/Store验收；虚构样本与原始文件分离。"""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
import pytest
from tools.testbench.common import service,assert_excel,assert_plan
from tools.testbench.usability import fictional_plan,physical_labels,physical_snapshot,business,saved,atomic_failure,assert_seating_html


def save(client,p):return client.call('save',{'plan':p,'revision':p['revision']})['plan']
def undo(client):return client.call('edit_undo',{'revision':saved(client)['revision']})['plan']


def test_bulk_preview_bad_item_stale_revision_and_selected_fields(tmp_path):
    with service(tmp_path,fictional_plan()) as c:
        before=saved(c);body={'kind':'rooms','action':'update','ids':['r01','r02'],'fields':{'location':'虚构新楼'}}
        pre=c.call('bulk_preview',body);assert saved(c)==before
        assert pre['revision']==before['revision'] and len(pre['rows'])==2
        atomic_failure(c,'bulk_apply',{**body,'ids':['r01','not-a-room'],'revision':pre['revision']})
        q=deepcopy(before);q['name']='虚构版本已更新';q=save(c,q)
        atomic_failure(c,'bulk_apply',{**body,'revision':pre['revision']})
        after=c.call('bulk_apply',{**body,'revision':q['revision']})['plan']
        for old,new in zip(q['rooms'],after['rooms']):assert {k:v for k,v in old.items() if k!='location'}=={k:v for k,v in new.items() if k!='location'}
        assert business(undo(c))==business(q)


def test_room_batch_normalized_capacity_conflict_and_reopen(tmp_path):
    with service(tmp_path,fictional_plan()) as c:
        body={'start':10,'count':2,'name_prefix':'虚构新增','template':{'rows':2,'cols':2,'per_desk':2,'capacity':90,'location':'虚构楼',
            'availability':[{'date':'2026-11-12','start':'08:00','end':'12:00'}]}}
        before=saved(c);pre=c.call('room_batch_preview',body)
        assert saved(c)==before and [r['capacity'] for r in pre['rooms']]==[8,8]
        p=c.call('room_batch',{**body,'revision':pre['revision']})['plan']
        assert len(p['rooms'])==4 and all(r['capacity']==8 for r in p['rooms'][2:])
        atomic_failure(c,'room_batch',{**body,'revision':p['revision']})
        ident=p['id']
    with service(tmp_path) as c:
        c.call('open',{'id':ident});assert business(undo(c))==business(before)


@pytest.mark.parametrize('action,fields',[('delete',None),('update',{'rows':1,'cols':2,'capacity':2})])
def test_used_room_impact_preserves_students_and_full_undo(tmp_path,action,fields):
    with service(tmp_path,fictional_plan(special=True,locked=True)) as c:
        before=saved(c);body={'kind':'rooms','action':action,'ids':['r01']}
        if fields:body['fields']=fields
        pre=c.call('bulk_preview',body);assert saved(c)==before
        affected={(x['exam_id'],x['student_id']) for x in pre['impact']['seats']}
        expected={(k,sid) for k,m in before['seats'].items() for sid,a in m.items() if a['room_id']=='r01'}
        assert affected==expected and pre['impact']['locked_seats'] and pre['impact']['monitors']
        atomic_failure(c,'bulk_apply',{**body,'revision':pre['revision']})
        p=c.call('bulk_apply',{**body,'revision':pre['revision'],'confirm_impact':True})['plan']
        assert p['students']==before['students']
        lost={(x['exam_id'],x['student_id']) for x in pre['impact']['removed_seats']}
        assert lost and all(sid not in p['seats'][k] for k,sid in lost)
        assert {'seats','invigilation'}<=set(p['stale'])
        assert business(undo(c))==business(before)


def test_grades_used_unknown_and_aliases_reject_atomically(tmp_path):
    with service(tmp_path,fictional_plan()) as c:
        p=saved(c)
        for ids in (['七年级','九年级'],['不在清单'],['九年级','九年级 ']):
            error=atomic_failure(c,'bulk_apply',{'kind':'grades','action':'delete','ids':ids,'revision':p['revision']})
            assert error
        pre=c.call('bulk_preview',{'kind':'grades','action':'delete','ids':['九年级']})
        c.call('bulk_apply',{'kind':'grades','action':'delete','ids':['九年级'],'revision':pre['revision']})
        assert saved(c)['grades']==['七年级','八年级']
        assert business(undo(c))==business(p)


def test_compact_history_50_reopen_and_client_cannot_forge(tmp_path):
    with service(tmp_path,fictional_plan()) as c:
        for i in range(52):
            p=saved(c);p['teachers'][0]['name']=f'虚构单行修改{i}';p['edit_history']=[{'forged':True}];save(c,p)
        p=saved(c);assert len(p['edit_history'])==50
        assert all(len(h['entities']['teachers']['rows'])==1 and 'edit_history' not in h['before'] for h in p['edit_history'])
        assert all(not ({'students','rooms','teachers','exams'}&set(h['before'])) for h in p['edit_history'])
        # 字节比例受合法change_log影响，不作为未约定的性能门槛；
        # 精简契约明确检查只存一行实体逆补丁，绝无全名单/嵌套撤销链。
        assert all(set(h['entities'])=={'teachers'} and h['entities']['teachers']['order'] is None
            and h['entities']['teachers']['added']==[] and 'edit_history' not in h['before'] for h in p['edit_history'])
        atomic_failure(c,'edit_undo',{'revision':p['revision']-1});ident=p['id']
    with service(tmp_path) as c:
        c.call('open',{'id':ident});before=saved(c);p=undo(c)
        assert p['teachers'][0]['name']=='虚构单行修改50' and p['revision']>before['revision'] and len(p['edit_history'])==49


def test_legacy_snapshot_cannot_cross_later_data_edit(tmp_path):
    with service(tmp_path,fictional_plan()) as c:
        original=saved(c);preview=c.call('number_preview',{'prefix':'041','overwrite':True,'rule':'seat'})
        c.call('numbers',{'prefix':'041','overwrite':True,'rule':'seat','revision':preview['revision']})
        p=saved(c);p['teachers'][0]['name']='虚构后来教师';save(c,p)
        atomic_failure(c,'number_undo',{'revision':saved(c)['revision']})
        c.call('edit_undo',{'revision':saved(c)['revision']})
        c.call('number_undo',{'revision':saved(c)['revision']});assert saved(c)['students']==original['students']


def test_subject_catalog_minutes_partial_time_batch_and_duplicates(tmp_path):
    with service(tmp_path,fictional_plan()) as c:
        p=saved(c);original=deepcopy(p['exams'])
        c.call('subject_catalog_save',{'catalog':[{'name':'数学','duration':119},{'name':'虚构项目','duration':37}],'revision':p['revision']})
        assert saved(c)['exams']==original
        body={'grades':['七年级','八年级'],'subjects':['数学',{'name':'虚构项目','duration':37},'虚构项目'],'date':'2026-11-14','start':'08:21','end':'09:56','duration':10}
        pre=c.call('subject_batch_preview',body);assert len(pre['exams'])==2 and len(pre['duplicates'])>=2
        assert all(e['duration']==95 for e in pre['exams'])
        c.call('subject_batch',{**body,'revision':pre['revision']})
        q=saved(c);assert q['exams'][:len(original)]==original
        assert all(e['duration']==95 for e in q['exams'][len(original):])
        q['exams'][-1].update(start='10:00',end='',duration=37);q=save(c,q)
        assert q['exams'][-1]['duration']==37 and q['exams'][-1]['end']==''
        atomic_failure(c,'subject_batch',{'grades':['未知年级'],'subjects':['虚构项目'],'revision':q['revision']})
        bad=deepcopy(q);bad['exams'][0].update(start='10:00',end='09:00')
        atomic_failure(c,'save',{'plan':bad,'revision':q['revision']})


def test_import_minute_conflict_preflight_and_submit_reject_without_write(tmp_path):
    with service(tmp_path,fictional_plan()) as c:
        p=saved(c);body={'kind':'exams','mode':'append','revision':p['revision'],
            'rows':[{'年级':'七年级','科目':'虚构时长冲突','日期':'2026-11-14','开始':'08:21','结束':'09:56','分钟':90}],
            'mapping':{'grade':'年级','subject':'科目','date':'日期','start':'开始','end':'结束','duration':'分钟'}}
        pre=c.call('import_preflight',body);assert any(e['code']=='duration_mismatch' and e['field']=='duration' for e in pre['errors'])
        atomic_failure(c,'import',body)


def test_default_groups_do_not_mix_fields_or_rewrite_business(tmp_path):
    with service(tmp_path,fictional_plan()) as c:
        before=saved(c)
        for group,allowed in [('seating',{'mode','seed','mix_grades','mix_groups','score_field'}),('monitors',{'invigilators','avoid_subject','avoid_class'}),('solver',{'time_limit'}),('appearance',{'theme','fontScale','density'})]:
            assert set(c.call('defaults',{'group':group})['values'])==allowed
        assert saved(c)==before


def test_label_swap_known_physical_positions_fixed_special_locks_manual_number(tmp_path):
    with service(tmp_path,fictional_plan(special=True,custom=True,locked=True)) as c:
        preview=c.call('number_preview',{'prefix':'041','overwrite':True,'rule':'seat'})
        c.call('numbers',{'prefix':'041','overwrite':True,'rule':'seat','revision':preview['revision']})
        p=saved(c);p['students'][1]['number']='MANUAL-虚构002';p=save(c,p)
        before=saved(c);coords=physical_snapshot(before);assert coords['base','s7-001']==('r01',1,1,True)
        pre=c.call('seat_labels_preview',{'room_id':'r01','first':4,'second':2})
        assert pre['number_review'] and saved(c)==before
        p=c.call('seat_labels_apply',{'room_id':'r01','first':4,'second':2,'revision':pre['revision']})['plan']
        assert physical_snapshot(p)==coords
        assert p['rooms'][0]['seat_labels']=={'1:1':2,'1:2':4,'1:3':3,'2:1':1,'2:2':5,'2:3':6}
        assert p['students']==before['students'] and p['seats']['base']['s7-001']['locked']
        errors=c.call('state')['validation']['errors'];assert any(e['code']=='number_seat_mismatch' for e in errors)
        assert not any(e.get('student_id')==p['students'][1]['id'] and e['code']=='number_seat_mismatch' for e in errors)
        blob=c.download(c.call('export',{'format':'xlsx','sections':['students','student_details','room_students','labels'],'draft':True}))
        assert_excel(blob,p,['students','student_details','room_students','labels'])
        (tmp_path/'虚构座号调整.xlsx').write_bytes(blob)
        ident=p['id']
    with service(tmp_path) as c:
        c.call('open',{'id':ident});assert physical_snapshot(saved(c))==coords
        assert business(undo(c))==business(before)


@pytest.mark.parametrize('exam_id',['e7-1','e7-2'])
def test_actual_exported_seating_html_uses_known_columns_after_label_swap(tmp_path,exam_id):
    with service(tmp_path/'服务',fictional_plan(special=True,custom=True,locked=True)) as c:
        p=saved(c);coords=physical_snapshot(p)
        p=c.call('seat_labels_apply',{'room_id':'r01','first':4,'second':2,'revision':p['revision']})['plan']
        assert physical_snapshot(p)==coords
        result=c.call('export',{'format':'html','sections':['seating'],'draft':True,'scope':{'mode':'exam','exam_ids':[exam_id]}})
        html=c.download(result).decode('utf-8');(tmp_path/'实际座次图.html').write_text(html,encoding='utf-8')
        assert_seating_html(html,p,exam_id)


@pytest.mark.parametrize('first,second',[(1,2),(2,6),(2,2),(0,2)])
def test_disabled_capacity_outside_duplicate_label_rejected(tmp_path,first,second):
    p=fictional_plan();p['rooms'][0].update(capacity=2,disabled=[1])
    with service(tmp_path,p) as c:
        atomic_failure(c,'seat_labels_apply',{'room_id':'r01','first':first,'second':second,'revision':saved(c)['revision']})


@pytest.mark.parametrize('labels',[{'1:1':2},{'1:1':1,'1:2':1,'1:3':3,'2:1':4,'2:2':5,'2:3':6}])
def test_partial_or_duplicate_mapping_cannot_save_or_import(tmp_path,labels):
    import base64
    with service(tmp_path,fictional_plan()) as c:
        p=saved(c);bad=deepcopy(p);bad['rooms'][0]['seat_labels']=labels
        atomic_failure(c,'save',{'plan':bad,'revision':p['revision']})
        atomic_failure(c,'plan_import',{'data':base64.b64encode(json.dumps(bad).encode()).decode()})


def test_student_adjustment_lock_disabled_and_preview_revision(tmp_path):
    with service(tmp_path,fictional_plan(spare=True,locked=True)) as c:
        p=saved(c)
        # 目标锁定位不得交换。人工点选可显式调整选中源学生的锁定状态；
        # 拖动源锁定位的拒绝另由真实pointer页面验收核对。
        atomic_failure(c,'adjust_seat',{'student_id':'s7-002','room_id':'r01','seat':1,'swap':True,'exam_id':'base','revision':p['revision']})
        request={'student_id':'s7-002','room_id':'r01','seat':7,'exam_id':'base'}
        pre=c.call('adjust_seat_preview',request);assert saved(c)==p
        q=deepcopy(p);q['name']='虚构新版本';q=save(c,q)
        atomic_failure(c,'adjust_seat',{**request,'revision':pre['revision']})
        c.call('adjust_seat',{**request,'revision':q['revision']})
        assert saved(c)['seats']['base']['s7-002']['seat']==7


def test_fictional_licence_compatibility_expiry_wrong_product_and_reopen(tmp_path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from exam_room.licensing import License,b64,sign_code
    key=Ed25519PrivateKey.generate();clock={'now':datetime(2026,10,13,tzinfo=timezone.utc)};machine='FICTIONAL-USABILITY-LICENSE'
    def licence():return License(tmp_path/'虚构许可',key.public_key(),machine=machine,clock=lambda:clock['now'])
    with service(tmp_path/'服务',fictional_plan(),license=licence()) as c:
        assert c.call('state')['license']['state']=='trial'
        clock['now']+=timedelta(days=4)
        assert c.call('state')['license']['state']=='expired'
        for format in ('xlsx','html','preview','pdf'):atomic_failure(c,'export',{'format':format,'sections':['students']})
        p=saved(c);p['name']='虚构到期仍可保存';save(c,p)
        blob=json.dumps({'product':'wrong-product','machine':machine,'expiry':None},sort_keys=True,separators=(',',':')).encode()
        assert not c.raw('activate',{'code':b64(blob)+'.'+b64(key.sign(blob))})['ok']
        assert c.call('activate',{'code':sign_code(key,machine,None)})['license']['state']=='active'
        ident=saved(c)['id']
    with service(tmp_path/'服务',license=licence()) as c:
        c.call('open',{'id':ident});assert c.call('state')['license']['state']=='active'


@pytest.mark.parametrize('broken',['missing','python-substitute'])
def test_simulated_formal_missing_validation_locks_export_only(tmp_path,monkeypatch,broken):
    from exam_room import licensing,paths
    monkeypatch.setattr(paths,'FROZEN',True)
    monkeypatch.setattr(licensing,'machine_code',lambda:'FICTIONAL-BROKEN')
    if broken=='missing':monkeypatch.setattr(licensing,'_impl',None)
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key=Ed25519PrivateKey.generate()
    licence=licensing.License(tmp_path/'仅虚构许可',key.public_key(),machine='FICTIONAL-BROKEN')
    with service(tmp_path/'服务',fictional_plan(),license=licence) as c:
        assert c.call('state')['license']['broken']
        p=saved(c);p['name']='虚构模块异常仍保存';save(c,p)
        atomic_failure(c,'export',{'format':'xlsx','sections':['students']})


@pytest.mark.parametrize('condition',['wrong-product','changed-key','corrupt-config','missing-config'])
def test_simulated_native_validation_product_key_config_rejects_without_blocking_save(tmp_path,monkeypatch,condition):
    from types import SimpleNamespace
    from importlib.machinery import EXTENSION_SUFFIXES
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from exam_room import licensing,paths
    import hashlib
    key=Ed25519PrivateKey.generate();raw=key.public_key().public_bytes_raw();public=tmp_path/'仅虚构公钥配置.json'
    public.write_text(json.dumps({'public_key':licensing.b64(raw),'contact':'虚构提供者'}),encoding='utf-8')
    # 仅模拟已加载模块接口/文件后缀；没有真实native编译/冻包通过声明。
    fake=SimpleNamespace(__file__='fictional'+EXTENSION_SUFFIXES[0],PRODUCT='wrong' if condition=='wrong-product' else 'exam-room-tool',
        PUBLIC_KEY_SHA256='0'*64 if condition=='changed-key' else hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(paths,'FROZEN',True);monkeypatch.setattr(paths,'PUBLIC',public)
    monkeypatch.setattr(licensing,'_impl',fake);monkeypatch.setattr(licensing,'machine_code',lambda:'FICTIONAL-CONFIG')
    if condition=='corrupt-config':public.write_bytes(b'{invalid')
    if condition=='missing-config':public.unlink()
    licence=licensing.configured()
    with service(tmp_path/'服务',fictional_plan(),license=licence) as c:
        assert c.call('state')['license']['broken']
        p=saved(c);p['name']='虚构验证模块异常仍保存';save(c,p)
        for format in ('xlsx','preview','pdf'):atomic_failure(c,'export',{'format':format,'sections':['students']})
