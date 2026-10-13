"""只在本机监听的服务；事务化方案保存和可取消后台编排任务。"""
import base64
from copy import deepcopy
import json
import mimetypes
import math
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse,unquote
from . import VERSION,HOMEPAGE,paths,engine,report,importer,updater,numbering,rooms,changes,printing,exporting,transactions,bulk,subjects,seat_labels,errors
from .model import new_plan,normalize_plan,generate_numbers,demo_plan,uid,ENTITY_DEFAULTS
from .validation import grade_scope_issues
from .storage import Store
from .licensing import configured


class LocalHTTPServer(ThreadingHTTPServer):
    # 页面同时加载多个脚本；预留突发连接队列，避免本机连接被重置。
    request_queue_size=64


def open_path(path):
    if sys.platform=='darwin':subprocess.Popen(['open',str(path)])
    elif sys.platform=='win32':os.startfile(str(path))
    else:subprocess.Popen(['xdg-open',str(path)])


class App:
    def __init__(self,root=None,license=None):
        self.root=Path(root or paths.data_root());self.store=Store(self.root);self.license=license or configured()
        self.ui_preferences=self.load_ui_preferences()
        self.token=secrets.token_urlsafe(32);self.lock=threading.RLock();self.plan=None
        self.export_task=None;self.export_cancel_event=threading.Event()
        self.task=None;self.cancel=threading.Event();self.updater=updater.Updater();self.update_info=None
        self.last_ping=time.monotonic();self.downloads={};self.window=None

    @staticmethod
    def normalize_preferences(value):
        if not isinstance(value,dict) or set(value)!={'theme','fontScale','density'}:raise ValueError('显示设置须包含主题、字号和密度。')
        if value['theme'] not in ('system','light','dark') or value['density'] not in ('standard','compact'):raise ValueError('请选择有效的主题和显示密度。')
        size=value['fontScale']
        if isinstance(size,bool) or not isinstance(size,(int,float)) or not math.isfinite(size) or not .9<=size<=1.5:raise ValueError('显示字号比例须为 0.9～1.5。')
        return dict(theme=value['theme'],fontScale=size,density=value['density'])

    def load_ui_preferences(self):
        try:return self.normalize_preferences(json.loads((self.root/'ui-preferences.json').read_text(encoding='utf-8')))
        except (OSError,ValueError,TypeError):return None

    def api_ui_preferences_save(self,b):
        preferences=self.normalize_preferences(b.get('preferences'))
        self.store.atomic_write(self.root/'ui-preferences.json',json.dumps(preferences,ensure_ascii=False,allow_nan=False).encode('utf-8'))
        self.ui_preferences=preferences;return deepcopy(preferences)

    def require(self):
        if self.plan is None:raise ValueError('请先新建或打开一份考试方案。')
        return self.plan

    def checks(self,p):
        return engine.validate(p)

    def view(self):
        p=deepcopy(self.plan)
        return dict(plan=p,subject_catalog=deepcopy(p.get('subject_catalog',subjects.BUILTIN) if p else subjects.BUILTIN),edit_history=transactions.summary(p),validation=self.checks(p) if p else None,duties=engine.duties(p) if p else [],
                    workload=engine.workload(p) if p else [],layouts={r['id']:engine.seat_layout(r) if r['rows']*r['cols']*r['per_desk']<=99 else [] for r in p['rooms']} if p else {},
                    physical_layouts={r['id']:engine.seat_layout({**r,'disabled':[],'capacity':r['rows']*r['cols']*r['per_desk']}) for r in p['rooms'] if r['rows']*r['cols']*r['per_desk']<=99} if p else {},
                    license=self.license.status(),recent=self.store.list(),trash=self.store.list(True),version=VERSION,root=str(self.root),
                    ui_preferences=deepcopy(self.ui_preferences),capabilities=dict(ui_preferences=True,import_preflight=True,recovery=True,validation_stages=True,report_layouts=True,async_export=True,monitor_candidates=True,edit_history=True,bulk_operations=True,subject_catalog=True,seat_labels=True,seat_adjust_preview=True),export_stages={k:sorted(report.export_stages(k)) for k in report.SECTIONS},report_layout_defaults=printing.default_layouts(),export_task=deepcopy(self.export_task),sections=report.SECTIONS,fields=importer.FIELDS,defaults=ENTITY_DEFAULTS,task=deepcopy(self.task),desktop=bool(self.window))

    def commit(self,p,label='保存修改',kind='edit',record=True):
        with self.lock:
            p=normalize_plan(p)
            issues=grade_scope_issues(p)
            if issues:raise ValueError(issues[0]['message'])
            old=self.plan if self.plan and self.plan['id']==p['id'] else None
            if old:
                p['revision']=old['revision']
                if record:p=transactions.record(old,p,label,kind)
            p['revision']=int(p.get('revision',0))+1
            self.plan=self.store.save(p);return self.view()

    def check_revision(self,b):
        p=self.require()
        if b.get('revision')!=p['revision']:raise ValueError('方案已更新，请重新预览后再操作。')
        return p

    def api_edit_undo(self,b):
        p=self.check_revision(b)
        return self.commit(transactions.undo(p),record=False)

    def api_state(self,b):return self.view()
    def api_ping(self,b):self.last_ping=time.monotonic();return {}
    def api_new(self,b):
        p=new_plan(b.get('name') or '新建考试');p['grades']=b.get('grades',[])
        return self.commit(p)
    def api_demo(self,b):return self.commit(demo_plan())
    def api_open(self,b):self.plan=self.store.load(b['id']);return self.view()
    def api_recovery_preview(self,b):
        info=self.store.recovery(b['id'])
        return dict(available=info['available'],revision=info.get('revision'),updated_at=info.get('updated_at'),name=info.get('plan',{}).get('name') if info['available'] else None)
    def api_recover(self,b):
        minimum=self.plan['revision']+1 if self.plan and self.plan['id']==b['id'] else 0
        self.plan=self.store.recover(b['id'],b.get('backup_revision'),minimum);return self.view()
    def api_clone(self,b):self.plan=self.store.clone(b['id'],b.get('name'));return self.view()
    def api_delete(self,b):
        self.store.delete(b['id'])
        if self.plan and self.plan['id']==b['id']:self.plan=None
        return self.view()
    def api_restore(self,b):self.store.restore(b['id']);return self.view()

    def api_save(self,b,label=None):
        old=self.require()
        if not isinstance(b.get('plan'),dict) or 'grades' not in b['plan']:raise ValueError('保存时请保留本次考试年级清单，不能按资料重新推导。')
        raw=deepcopy(b['plan']);raw['edit_history']=deepcopy(old.get('edit_history',[]))
        p=normalize_plan(raw);p=bulk.align_layouts(old,p)
        if p['id']!=old['id'] or int(b.get('revision',p['revision']))!=old['revision']:raise ValueError('方案已在其他操作中更新，请重新载入后再修改。')
        issues=grade_scope_issues(p)
        if issues:raise ValueError(issues[0]['message'])
        p['history']=deepcopy(old['history']);p['history_epoch']=old.get('history_epoch',0);p['number_history']=deepcopy(old.get('number_history',[]))
        impact=bulk.room_impact(old,p)
        if impact['requires_confirmation'] and b.get('confirm_impact') is not True:raise ValueError('请先预览并确认受影响的学生、锁定座位及监考安排。')
        p=bulk.drop_affected(p,impact)
        p=changes.reconcile(old,p,reset_labels=b.get('reset_labels') is True)
        if label is None:
            names={'students':'学生资料','rooms':'考场资料','exams':'考试日程','teachers':'教师资料','grades':'考试年级','settings':'考试设置','report_layouts':'打印版式'}
            label='修改'+('、'.join(v for k,v in names.items() if old.get(k)!=p.get(k)) or '考试方案')
        return self.commit(p,label=label)

    def api_confirm(self,b):
        if 'revision' in b:self.check_revision(b)
        p=deepcopy(self.require()); v=engine.validate(p,include_stale=False)
        if v['errors']:raise ValueError('仍有编排问题，请先处理后再确认。')
        p['stale']=[];p['stale_seats']=[];return self.commit(p,label='确认检查结果')

    def number_options(self,b):
        return {k:b[k] for k in ('prefix','prefixes','overwrite','grade','rule','width','start') if k in b}

    def api_number_preview(self,b):
        p=self.require();return dict(**numbering.preview(p,**self.number_options(b)),revision=p['revision'])

    def api_numbers(self,b):
        p=self.require()
        if not b:return self.commit(generate_numbers(p),label='生成考号')
        if b.get('revision')!=p['revision']:raise ValueError('方案已更新，请重新预览考号后生成。')
        return self.commit(numbering.apply(p,**self.number_options(b)),label='生成考号',kind='numbers')

    def api_number_undo(self,b):
        p=self.require()
        if 'revision' in b:self.check_revision(b)
        if p.get('edit_history'):
            if p['edit_history'][-1]['kind']!='numbers':raise ValueError('后续资料或规则已修改，请使用撤销上一步逐笔恢复。')
            return self.commit(transactions.undo(p),record=False)
        return self.commit(numbering.undo(p),label='撤销生成考号')

    def room_batch_options(self,b):
        options={k:b[k] for k in ('start','count','name_prefix','name_suffix') if k in b}
        if 'template' in b:options['template']=b['template']
        if b.get('template_id'):
            template=next((r for r in self.require()['rooms'] if r['id']==b['template_id']),None)
            if not template:raise ValueError('模板考场已不存在，请重新选择。')
            options['template']=template
        return options

    def api_room_batch_preview(self,b):
        p=self.require();return dict(rooms=rooms.batch(p,**self.room_batch_options(b)),revision=p['revision'])

    def api_room_batch(self,b):
        old=self.require()
        if b.get('revision')!=old['revision']:raise ValueError('方案已更新，请重新预览考场。')
        additions=rooms.batch(old,**self.room_batch_options(b));p=deepcopy(old);p['rooms'].extend(additions)
        return self.api_save(dict(plan=p,revision=old['revision']))

    def api_subject_catalog_save(self,b):
        old=self.check_revision(b);p=deepcopy(old);p['subject_catalog']=subjects.catalog(b.get('catalog'))
        return self.commit(p,label='修改科目预设',kind='subjects')

    def api_subject_batch_preview(self,b):
        old=self.require();return dict(**subjects.batch(old,b),revision=old['revision'])

    def api_subject_batch(self,b):
        old=self.check_revision(b);p=deepcopy(old);p['exams'].extend(subjects.batch(old,b)['exams'])
        return self.api_save(dict(plan=p,revision=old['revision']))

    def api_defaults(self,b):
        group=b.get('group');values=bulk.defaults(group)
        if group=='subjects' and self.plan:
            used={e['subject'] for e in self.plan['exams']};names={r['name'] for r in values}
            values.extend(deepcopy(r) for r in self.plan['subject_catalog'] if r['name'] in used and r['name'] not in names)
        return dict(group=group,values=values)

    def api_bulk_preview(self,b):
        old=self.require();result=bulk.prepare(old,b)
        return {**{k:v for k,v in result.items() if k!='plan'},'revision':old['revision']}

    def api_bulk_apply(self,b):
        old=self.check_revision(b);result=bulk.prepare(old,b)
        if result['requires_confirmation'] and b.get('confirm_impact') is not True:raise ValueError('请先确认受影响的学生、锁定座位及监考安排。')
        label=('批量删除' if b.get('action')=='delete' else '批量修改')+{'rooms':'考场','grades':'年级','exams':'科目','teachers':'教师','students':'学生'}[b['kind']]
        return self.api_save(dict(plan=result['plan'],revision=old['revision'],confirm_impact=True,reset_labels=b.get('reset_labels')),label=label)

    def api_room_layout_preview(self,b):return rooms.layout_preview(b['room'])

    def api_room_change_preview(self,b):
        old=self.require();raw=deepcopy(b['room'])
        if b.get('reset_labels') is True:raw['seat_labels']={}
        if raw.get('id') not in {r['id'] for r in old['rooms']}:
            room=rooms.prepare_room(old,raw);return dict(room=room,layout=rooms.layout_preview(room),revision=old['revision'],requires_confirmation=False,impact=dict(seats=[],removed_seats=[],locked_seats=[],monitors=[]))
        result=bulk.prepare(old,dict(kind='rooms',action='update',ids=[raw['id']],fields={k:v for k,v in raw.items() if k in bulk.ROOM_FIELDS},reset_labels=b.get('reset_labels')))
        room=result['rows'][0]
        return dict(room=room,layout=rooms.layout_preview(room),revision=old['revision'],requires_confirmation=result['requires_confirmation'],impact=result['impact'])

    def api_room_save(self,b):
        old=self.require()
        if b.get('revision')!=old['revision']:raise ValueError('方案已更新，请重新打开考场设置。')
        raw=deepcopy(b['room'])
        if b.get('reset_labels') is True:raw['seat_labels']={}
        p=deepcopy(old)
        # Use exactly the preview normalization, including disabled physical places.
        preview=self.api_room_change_preview(dict(room=raw,reset_labels=b.get('reset_labels')))
        room=preview['room']
        index=next((i for i,r in enumerate(p['rooms']) if r['id']==room['id']),None)
        if index is None:p['rooms'].append(room)
        else:p['rooms'][index]=room
        return self.api_save(dict(plan=p,revision=old['revision'],confirm_impact=b.get('confirm_impact'),reset_labels=b.get('reset_labels')))
    def api_import_preview(self,b):
        try: blob=base64.b64decode(b['data'],validate=True)
        except Exception:raise ValueError('文件传输不完整，请重新选择文件。')
        return importer.preview(blob,b['filename'],b['kind'],b.get('sheet'),b.get('header_row'))

    def api_import_preflight(self,b):
        p=self.require()
        if 'revision' in b and b['revision']!=p['revision']:raise ValueError('方案已更新，请重新预检资料。')
        mode=b.get('mode') or ('append' if b.get('append',True) else 'replace')
        result=importer.preflight(p,b['kind'],b['rows'],b['mapping'],mode)
        return {k:v for k,v in result.items() if k!='plan'}

    def api_import(self,b):
        p=self.require()
        if 'revision' in b and b['revision']!=p['revision']:raise ValueError('方案已更新，请重新预检资料。')
        result=importer.preflight(p,b['kind'],b['rows'],b['mapping'],b.get('mode') or ('append' if b.get('append',True) else 'replace'))
        if result['errors']:raise ValueError(result['errors'][0]['message'])
        return self.api_save(dict(plan=result['plan'],revision=p['revision']))

    def api_entity_prepare(self,b):
        return importer.import_rows(b['kind'],[b['row']],b['mapping'])[0]

    def downloadable(self,name,blob):
        ident=uid();path=self.root/'output'/f'{ident[:8]}-{name}'
        try:path.write_bytes(blob)
        except PermissionError:raise ValueError('文件正被其他程序打开，请关闭后再导出。')
        self.downloads[ident]=path
        return dict(name=name,path=str(path),url='/download/'+ident)

    def api_template(self,b):
        names={'students':'学生名单','rooms':'考场资料','teachers':'教师资料','exams':'考试日程'}
        kind=b['kind'];return self.downloadable(names[kind]+'模板.xlsx',importer.template(kind))

    def api_plan_export(self,b):
        p=self.require();return self.downloadable('考试方案.json',json.dumps(p,ensure_ascii=False,indent=2).encode())

    def api_plan_import(self,b):
        try:p=normalize_plan(json.loads(base64.b64decode(b['data']).decode('utf-8-sig')))
        except Exception as e:raise ValueError('方案文件无法读取：'+(str(e) if errors.is_user_message(e) else '文件内容不是本软件导出的考试方案。'))
        # Import is always a new local copy, preventing unintended overwrite.
        p['id']=uid();p['name']+='（导入）';p['revision']=0;p['edit_history']=[];p['history']=[];p['number_history']=[];return self.commit(p)

    def api_seat_labels_preview(self,b):
        old=self.require();result=seat_labels.prepare(old,b)
        return dict(**{k:v for k,v in result.items() if k!='plan'},revision=old['revision'])

    def api_seat_labels_apply(self,b):
        old=self.check_revision(b);result=seat_labels.prepare(old,b)
        return self.commit(result['plan'],label='调整座号排列',kind='seat_labels')

    def api_adjust_seat_preview(self,b):
        old=self.require()
        q=engine.adjust_seat(old,b['student_id'],b['room_id'],int(b['seat']),b.get('exam_id','base'),bool(b.get('swap')),b.get('locked'))
        return dict(revision=old['revision'],seats=q['seats'],number_review=numbering.source_issues(q))

    def api_adjust_seat(self,b):
        if 'revision' in b and b['revision']!=self.require()['revision']:raise ValueError('方案已更新，请重新选择学生座位。')
        p=engine.adjust_seat(self.require(),b['student_id'],b['room_id'],int(b['seat']),b.get('exam_id','base'),bool(b.get('swap')),b.get('locked'))
        if p['invigilation']:p['stale']=list(set(p.get('stale',[]))|{'invigilation'})
        return self.commit(p,label='调整学生座位',kind='seat')

    def api_adjust_invigilator(self,b):
        if 'revision' in b and b['revision']!=self.require()['revision']:raise ValueError('方案已更新，请重新选择监考教师。')
        p=engine.adjust_invigilator(self.require(),b['duty_id'],int(b['index']),b.get('teacher_id',''),bool(b.get('locked')))
        p['pending_monitor_locks']=[c for c in p.get('pending_monitor_locks',[]) if not(c['duty_id']==b['duty_id'] and c['index']==int(b['index']))]
        return self.commit(p,label='调整监考教师',kind='monitor')

    def api_monitor_candidates(self,b):
        p=self.require();duties={d['id']:d for d in engine.duties(p)};d=duties.get(b.get('duty_id'));index=b.get('index',0)
        if not d or not isinstance(index,int) or not 0<=index<d['required']:raise ValueError('监考场次或位置已变化，请重新选择。')
        candidates=[];loads={x['teacher_id']:x for x in engine.workload(p)}
        for t in p['teachers']:
            reasons=[];issue=engine._teacher_issue(p,t,d)
            if issue:reasons.append(dict(code=issue[0],message=issue[1]))
            for other in duties.values():
                for i,a in enumerate(p['invigilation'].get(other['id'],[])):
                    if other['id']==d['id'] and i==index:continue
                    if a.get('teacher_id')==t['id'] and engine._overlap(engine._event(d),engine._event(other)):reasons.append(dict(code='teacher_overlap',message='该教师在同一时间已有监考任务。',duty_id=other['id']))
            load=loads.get(t['id'],{})
            candidates.append(dict(id=t['id'],name=t['name'],eligible=not reasons,reasons=reasons,count=load.get('count',0),minutes=load.get('minutes',0)))
        candidates.sort(key=lambda x:(not x['eligible'],x['minutes'],x['count'],x['name'],x['id']))
        return dict(revision=p['revision'],duty_id=d['id'],index=index,teachers=candidates)

    def api_monitor_lock_resolve(self,b):
        old=self.require()
        if b.get('revision')!=old['revision']:raise ValueError('方案已更新，请重新核对监考锁定冲突。')
        if b.get('action')!='discard':raise ValueError('请明确选择解除这项失效的监考锁定。')
        conflicts=[c for c in old.get('pending_monitor_locks',[]) if c['duty_id']==b.get('duty_id') and c['index']==b.get('index')]
        if not conflicts:raise ValueError('这项锁定冲突已不存在。')
        p=deepcopy(old);d=next((x for x in engine.duties(p) if x['id']==b['duty_id']),None)
        if not d:raise ValueError('监考场次已不存在。')
        p['pending_monitor_locks']=[c for c in p['pending_monitor_locks'] if c not in conflicts]
        arr=p['invigilation'].get(d['id'],[])
        if b['index']>=d['required']:p['invigilation'][d['id']]=arr[:d['required']]
        elif b['index']<len(arr):arr[b['index']]=dict(teacher_id='',locked=False)
        engine._history(old,p,'解除失效的监考锁定')
        return self.commit(p,label='解除失效的监考锁定',kind='monitor')

    def api_undo(self,b):
        p=deepcopy(self.require())
        if 'revision' in b:self.check_revision(b)
        if p.get('edit_history'):
            if p['edit_history'][-1]['kind'] not in ('seat','monitor'):raise ValueError('资料或规则已经改变，请使用撤销上一步逐笔恢复。')
            return self.commit(transactions.undo(p),record=False)
        if not p['history']:raise ValueError('没有可以撤销的调整。')
        h=p['history'][-1]
        if h.get('epoch',0)!=p.get('history_epoch',0):raise ValueError('资料或规则已经改变，本次撤销不能覆盖后续修改。')
        p['history'].pop();p['stale_seats']=h.get('stale_seats',[]);p['pending_monitor_locks']=h.get('pending_monitor_locks',[]);p['seats']=h['seats'];p['invigilation']=h['invigilation'];p['stale']=h.get('stale',p.get('stale',[]))
        for e in p['exams']:
            if e['id'] in h.get('special_seating',{}):e['special_seating']=h['special_seating'][e['id']]
        return self.commit(p,label='撤销座位或监考调整')

    def api_solve(self,b):
        if 'revision' in b:self.check_revision(b)
        if self.task and self.task['state']=='running':raise ValueError('已有编排正在运行，请稍候或取消。')
        kind=b['kind'];fn={'schedule':engine.schedule,'seats':engine.assign_seats,'invigilators':engine.assign_invigilators}.get(kind)
        if fn is None:raise ValueError('不支持的编排类型。')
        p=deepcopy(self.require()); rev=p['revision'];ident=p['id'];task_id=uid();self.cancel=threading.Event();cancel=self.cancel
        p['settings']['time_limit']=max(1,min(300,float(b.get('time_limit') or p['settings']['time_limit'])))
        self.task=dict(id=task_id,state='running',kind=kind,message='正在检查资料…',started=time.time())
        def progress(msg):
            with self.lock:
                if self.task and self.task['id']==task_id:self.task['message']=msg
        def run():
            try:
                kw=dict(cancel=cancel,progress=progress)
                if kind=='seats':kw['exam_id']=b.get('exam_id') or None
                result=fn(p,**kw)
                with self.lock:
                    if cancel.is_set():result=dict(status='cancelled',message='已取消，本次结果未覆盖原方案。')
                    elif not self.plan or self.plan['id']!=ident or self.plan['revision']!=rev:
                        result=dict(status='stale',message='运行期间方案已修改，本次结果未覆盖新修改，请重新编排。')
                    elif result['status'] in ('optimal','feasible','partial'):
                        q=result['plan']
                        if kind=='schedule':q=changes.reconcile(p,q)
                        stale=set(q.get('stale',[]))
                        if kind=='schedule' and q['exams']!=p['exams'] and q['seats'].get('base'):stale|={'seats','invigilation'}
                        if kind=='seats':
                            q=changes.finish_seating(q,b.get('exam_id') or 'base');stale=set(q.get('stale',[]))
                            if q['invigilation']:stale.add('invigilation')
                        if kind=='schedule':stale.discard('schedule')
                        if kind=='invigilators':stale.discard('invigilation')
                        q['stale']=list(stale);self.commit(q,label={'schedule':'自动安排考试日程','seats':'自动编排座位','invigilators':'自动安排监考'}[kind])
                    self.task.update(state='done',status=result['status'],message=result.get('message','编排完成'),unfilled=result.get('unfilled',[]),proved_minimum=result.get('proved_minimum',False),elapsed=round(time.time()-self.task['started'],2))
            except Exception as e:
                with self.lock:self.task.update(state='error',status='error',message=errors.user_message(e))
        threading.Thread(target=run,daemon=True).start();return self.task

    def api_task(self,b):return dict(task=self.task,view=self.view() if self.task and self.task['state']!='running' else None)
    def api_cancel(self,b):self.cancel.set();return {'message':'已请求取消，请稍候。'}

    def api_report_layout_save(self,b):
        old=self.require()
        if b.get('revision')!=old['revision']:raise ValueError('方案已更新，请重新载入后保存版式。')
        values=b.get('layouts',{})
        if not isinstance(values,dict) or any(k not in report.SECTIONS for k in values):raise ValueError('版式材料名称无效。')
        p=deepcopy(old);p['report_layouts'].update({k:printing.normalize_layout(v,k) for k,v in values.items()})
        # Validate width and page fit now; do not save settings that cannot print.
        for key in values:printing.document(p,[key],True)
        return self.commit(p,label='保存打印版式')

    def api_export_start(self,b):return exporting.start(self,b)
    def api_export_status(self,b):
        if not self.export_task or b.get('id')!=self.export_task['id']:raise ValueError('没有找到这次导出任务，请重新生成。')
        return deepcopy(self.export_task)
    def api_export_cancel(self,b):
        if not self.export_task or b.get('id')!=self.export_task['id']:raise ValueError('没有找到这次导出任务。')
        if self.export_task['state']=='running':self.export_cancel_event.set()
        return dict(message='已请求取消，请稍候。',state=self.export_task['state'])

    def api_export(self,b):
        self.license.require_export();p=deepcopy(self.require());options=exporting.request(p,b)
        result=exporting.build(p,options,self.root/'output',threading.Event(),lambda message:None)
        self.license.require_export();blob=result.pop('blob');download=self.downloadable(result.pop('name'),blob)
        return dict(**result,**download,snapshot_revision=p['revision'],stale=False)

    def api_open_file(self,b):
        p=Path(b['path']).resolve();root=(self.root/'output').resolve()
        if not p.is_relative_to(root) or not p.exists():raise ValueError('找不到导出文件。')
        open_path(p);return {}
    def api_open_folder(self,b):open_path(self.root/'output');return {}
    def api_activate(self,b):self.license.activate(b['code']);return self.view()
    def api_update_check(self,b):self.update_info=updater.check();return self.update_info
    def api_update_start(self,b):
        if not self.update_info or not self.update_info.get('canAuto'):raise ValueError('暂无可自动安装的更新。')
        self.updater.start(self.update_info['asset']);return self.updater.status()
    def api_update_status(self,b):return self.updater.status()
    def api_update_apply(self,b):
        if self.plan:self.store.save(self.plan)
        self.updater.apply();threading.Timer(.7,lambda:os._exit(0)).start();return {}


def start(app=None,port=0):
    app=app or App()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def send(self,code,blob,ctype):
            self.send_response(code);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(blob)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers()
            try:self.wfile.write(blob)
            except (BrokenPipeError,ConnectionResetError):pass
        def local(self):return self.headers.get('Host','').split(':')[0] in ('127.0.0.1','localhost')
        def do_GET(self):
            if not self.local():return self.send(403,b'', 'text/plain')
            name=urlparse(self.path).path
            if name in ('/','/index.html'):
                html=(paths.UI/'index.html').read_text(encoding='utf-8').replace('__TOKEN__',app.token).replace('__UI_PREFS__',json.dumps(app.ui_preferences,ensure_ascii=False,allow_nan=False))
                return self.send(200,html.encode(),'text/html; charset=utf-8')
            if name.startswith('/download/'):
                path=app.downloads.get(name.rsplit('/',1)[-1])
                if path and path.exists():return self.send(200,path.read_bytes(),mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
            if name in ('/app.js','/numbering.js','/rooms.js','/controls.js','/appearance.js','/workspace.js','/export.js','/editing.js','/dragging.js','/style.css'):
                path=paths.UI/name[1:]
                if path.is_file():return self.send(200,path.read_bytes(),'text/javascript; charset=utf-8' if name.endswith('js') else 'text/css; charset=utf-8')
            return self.send(404,b'Not found','text/plain')
        def do_POST(self):
            if not self.local() or not secrets.compare_digest(self.headers.get('X-Token',''),app.token):return self.send(403,b'', 'text/plain')
            name=urlparse(self.path).path
            fn=getattr(app,'api_'+name[5:],None) if name.startswith('/api/') else None
            if not fn:return self.send(404,b'', 'text/plain')
            try:
                length=int(self.headers.get('Content-Length',0))
                if not 0<=length<=45*1024*1024:raise ValueError('请求太大，请拆分资料后重试。')
                body=json.loads(self.rfile.read(length) or b'{}')
                with app.lock:data=fn(body)
                blob=dict(ok=True,data=data)
            except Exception as e:blob=dict(ok=False,error=errors.user_message(e),license=isinstance(e,PermissionError) and e.errno is None)
            self.send(200,json.dumps(blob,ensure_ascii=False,allow_nan=False).encode(),'application/json; charset=utf-8')
    httpd=LocalHTTPServer(('127.0.0.1',port),Handler);httpd.daemon_threads=True
    threading.Thread(target=httpd.serve_forever,daemon=True).start()
    return httpd,f'http://127.0.0.1:{httpd.server_port}/',app
