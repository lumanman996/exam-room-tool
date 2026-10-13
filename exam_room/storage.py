"""本机方案存储：原子保存、备份和可恢复删除。"""
import json
import os
import re
from pathlib import Path
from copy import deepcopy
from .model import normalize_plan, now, uid


class Store:
    def __init__(self,root):
        self.root=Path(root); self.plans=self.root/'data'/'plans'; self.trash=self.root/'data'/'trash'
        for d in (self.plans,self.trash,self.root/'output'): d.mkdir(parents=True,exist_ok=True)

    def path(self,ident,deleted=False):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',str(ident)): raise ValueError('方案编号不正确。')
        return (self.trash if deleted else self.plans)/(ident+'.json')

    def atomic_write(self,path,blob):
        temp=path.with_name(path.name+'.'+uid()+'.tmp')
        try:
            with temp.open('wb') as stream:
                stream.write(blob);stream.flush();os.fsync(stream.fileno())
            os.replace(temp,path)
        finally:
            temp.unlink(missing_ok=True)

    def save(self,plan):
        p=normalize_plan(plan);p['updated_at']=now();f=self.path(p['id'])
        blob=json.dumps(p,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8')
        if f.exists():
            previous=f.read_bytes()
            try:normalize_plan(json.loads(previous.decode('utf-8')))
            except (ValueError,TypeError,KeyError):pass
            else:self.atomic_write(f.with_suffix('.backup'),previous)
        self.atomic_write(f,blob)
        return p

    def recovery(self,ident,deleted=False):
        backup=self.path(ident,deleted).with_suffix('.backup')
        try:
            p=normalize_plan(json.loads(backup.read_text(encoding='utf-8')))
            if p['id']!=ident:raise ValueError('备份编号不匹配。')
            return dict(available=True,plan=p,revision=p.get('revision',0),updated_at=p.get('updated_at',''))
        except (OSError,ValueError,TypeError,KeyError):return dict(available=False,plan=None)

    def recover(self,ident,expected_revision=None,minimum_revision=0):
        info=self.recovery(ident)
        if not info['available']:raise ValueError('没有可读取的备份，请使用另存的方案文件。')
        if expected_revision is not None and expected_revision!=info['revision']:raise ValueError('备份已变化，请重新预览。')
        f=self.path(ident)
        primary_revision=0
        if f.exists():
            raw=f.read_bytes();self.atomic_write(f.with_name(f.stem+'.damaged-'+uid()[:8]+'.json'),raw)
            try:primary_revision=normalize_plan(json.loads(raw))['revision']
            except (ValueError,TypeError,KeyError):pass
        p=info['plan'];p['revision']=max(int(p.get('revision',0))+1,primary_revision+1,minimum_revision);p['updated_at']=now()
        self.atomic_write(f,json.dumps(p,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8'))
        return p

    def load(self,ident,deleted=False):
        f=self.path(ident,deleted)
        if not f.is_file(): raise ValueError('找不到这份考试方案。')
        try: return normalize_plan(json.loads(f.read_text(encoding='utf-8')))
        except (ValueError,TypeError,KeyError,OSError): raise ValueError('方案文件损坏，可从同目录的 .backup 备份恢复。')

    def list(self,deleted=False):
        out=[]
        for f in (self.trash if deleted else self.plans).glob('*.json'):
            if '.damaged-' in f.name:continue
            try:
                p=normalize_plan(json.loads(f.read_text(encoding='utf-8')))
                out.append(dict(id=p['id'],name=p['name'],school=p.get('school',''),updated_at=p.get('updated_at',''),
                                students=len(p.get('students',[])),exams=len(p.get('exams',[]))))
            except (ValueError,KeyError,TypeError,OSError):
                if '.damaged-' in f.name:continue
                info=self.recovery(f.stem,deleted)
                p=info.get('plan') or {}
                out.append(dict(id=f.stem,name=p.get('name','损坏的方案'),school=p.get('school',''),updated_at=p.get('updated_at',''),students=len(p.get('students',[])),exams=len(p.get('exams',[])),damaged=True,recoverable=info['available']))
        return sorted(out,key=lambda x:x['updated_at'],reverse=True)

    def clone(self,ident,name=None):
        p=self.load(ident); p['id']=uid(); p['name']=name or p['name']+'（副本）'; p['created_at']=now(); p['revision']=0;p['edit_history']=[];p['history']=[];p['number_history']=[]
        return self.save(p)

    def move(self,ident,deleted=False):
        src=self.path(ident,not deleted);dst=self.path(ident,deleted)
        if not src.is_file():raise ValueError('找不到这份考试方案。')
        if dst.exists() or (src.with_suffix('.backup').exists() and dst.with_suffix('.backup').exists()):raise ValueError('目标目录已有同编号方案或备份，无法覆盖，请先恢复处理。')
        try:p=self.load(ident,not deleted)
        except ValueError:p=(self.recovery(ident,not deleted).get('plan') or dict(id=ident,name='损坏的方案'))
        backup=src.with_suffix('.backup');moved=False
        try:
            if backup.exists():os.replace(backup,dst.with_suffix('.backup'));moved=True
            os.replace(src,dst)
        except OSError:
            if moved:os.replace(dst.with_suffix('.backup'),backup)
            raise
        return p

    def delete(self,ident):return self.move(ident,True)
    def restore(self,ident):return self.move(ident,False)
