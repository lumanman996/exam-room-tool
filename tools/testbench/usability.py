"""1.1.0独立验收样本与物理坐标答案；不调用产品布局或检查器。"""
from copy import deepcopy
from .common import load
from html.parser import HTMLParser
import re
import unicodedata


class HtmlNode:
    def __init__(self,tag='',attrs=(),parent=None):self.tag=tag;self.attrs=dict(attrs);self.parent=parent;self.children=[];self.parts=[]
    def all(self,tag):return [child for c in self.children for child in ([c] if c.tag==tag else [])+c.all(tag)]
    def text(self):return ''.join(p.text() if isinstance(p,HtmlNode) else p for p in self.parts)


class HtmlTree(HTMLParser):
    def __init__(self,html):
        super().__init__();self.root=HtmlNode();self.stack=[self.root];self.feed(html)
    def handle_starttag(self,tag,attrs):
        node=HtmlNode(tag,attrs,self.stack[-1]);self.stack[-1].children.append(node);self.stack[-1].parts.append(node)
        if tag not in ('meta','br','hr','img','input','link'):self.stack.append(node)
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,0,-1):
            if self.stack[i].tag==tag:self.stack=self.stack[:i];break
    def handle_data(self,data):self.stack[-1].parts.append(data)


def assert_seating_html(html,p,exam_id):
    """逐个实际HTML格核对物理行列、标签及身份，不信任产品layouts。"""
    exam=next(e for e in p['exams'] if e['id']==exam_id)
    mapping=p['seats'][exam_id] if exam['special_seating'] else p['seats']['base']
    students={s['id']:s for s in p['students'] if s['grade']==exam['grade'] and (not s['subjects'] or exam['subject'] in s['subjects'])}
    tables=[x for x in HtmlTree(html).root.all('table') if 'seats' in x.attrs.get('class','').split()]
    assert tables,'未生成实际座次图'
    checked=set()
    for table in tables:
        article=table.parent
        while article and article.tag!='article':article=article.parent
        title=article.all('h2')[0].text()
        room=next(r for r in p['rooms'] if title.startswith(r['name']+' · '))
        assert exam['date'] in title and exam['start']+'—'+exam['end'] in title
        labels=physical_labels(room);at={coord:label for label,coord in labels.items()}
        occupants={mapping[sid]['seat']:s for sid,s in students.items() if mapping[sid]['room_id']==room['id']}
        rows=table.all('tr');assert len(rows)==room['rows'],'座次图缺物理行'
        for row_index,row in enumerate(rows,1):
            cells=row.all('td');assert len(cells)==room['cols']*room['per_desk']
            for col,cell in enumerate(cells,1):
                label=at[row_index,col];text=re.sub(r'\s+','',cell.text())
                assert text.startswith(f'{label:02d}号'),f'物理坐标({row_index},{col})应为{label:02d}号，实际{text}'
                s=occupants.get(label)
                if s:
                    assert s['name'] in text and s['number'] in text,f'物理坐标({row_index},{col})漏失/移动身份：{s["id"]}'
                    checked.add(s['id'])
    assert checked==set(students),'实际座次图漏人'
    return {'exam_id':exam_id,'students':len(checked),'known_physical_columns_verified':True}


def assert_seating_pdf(reader,p,exam_id,room_id='r01'):
    from .common import assert_pdf_text
    exam=next(e for e in p['exams'] if e['id']==exam_id)
    mapping=p['seats'][exam_id] if exam['special_seating'] else p['seats']['base']
    labels=physical_labels(next(r for r in p['rooms'] if r['id']==room_id))
    wanted=[s for s in p['students'] if s['grade']==exam['grade'] and (not s['subjects'] or exam['subject'] in s['subjects']) and mapping[s['id']]['room_id']==room_id]
    first_row=sorted([s for s in wanted if labels[mapping[s['id']]['seat']][0]==1],key=lambda s:labels[mapping[s['id']]['seat']][1])
    text='\n'.join(pg.extract_text() or '' for pg in reader.pages);assert_pdf_text(text,{'students':wanted})
    # Chromium/Windows letter spacing may appear as whitespace between extracted glyphs.
    event_text=re.sub(r'\s+','',unicodedata.normalize('NFKC',text))
    for value in (exam['date'],exam['start'],exam['end'],exam['subject']):
        assert re.sub(r'\s+','',unicodedata.normalize('NFKC',value)) in event_text,f'PDF缺少场次信息：{value}'
    page=next(pg for pg in reader.pages if all(s['name'] in unicodedata.normalize('NFKC',pg.extract_text() or '') for s in first_row))
    fragments=[]
    def visitor(text,cm,tm,font,size):
        clean=re.sub(r'\s+','',unicodedata.normalize('NFKC',text))
        fragments.append((clean,cm[0]*tm[4]+cm[2]*tm[5]+cm[4],cm[1]*tm[4]+cm[3]*tm[5]+cm[5]))
    page.extract_text(visitor_text=visitor)
    xs=[next(x for text,x,y in fragments if s['name'] in text) for s in first_row]
    assert xs==sorted(xs) and len(set(xs))==len(xs),'PDF学生物理列顺序错误：'+str(xs)
    label_xs=[next(x for text,x,y in fragments if text==f"{mapping[s['id']]['seat']:02d}号") for s in first_row]
    assert label_xs==sorted(label_xs),'PDF座号物理列顺序错误：'+str(label_xs)
    return {'exam_id':exam_id,'students':len(wanted),'pdf_identity_number_minutes_and_physical_columns_verified':True}


def physical_labels(room):
    """按虚构样本的行列/完整映射计算；容量在物理遍历中截取。"""
    rows,cols=room['rows'],room['cols']*room['per_desk']
    order=[]
    outer,inner=(cols,rows) if room['direction']=='vertical' else (rows,cols)
    for line in range(1,outer+1):
        for offset in range(1,inner+1):
            step=inner+1-offset if room['order']=='snake' and line%2==0 else offset
            coord=(step,line) if room['direction']=='vertical' else (line,step)
            label=room.get('seat_labels',{}).get(f'{coord[0]}:{coord[1]}',(line-1)*inner+offset)
            order.append((label,coord))
    assert len(set(label for label,_ in order))==rows*cols
    return dict(order)


def physical_snapshot(p):
    labels={r['id']:physical_labels(r) for r in p['rooms']}
    return {(scope,sid):(a['room_id'],*labels[a['room_id']][a['seat']],bool(a.get('locked')))
        for scope,mapping in p['seats'].items() for sid,a in mapping.items()}


def fictional_plan(special=False,custom=False,locked=False,spare=False):
    p=load('C05_special_subject' if special else 'C01_tiny_completed')
    p['grades']=['七年级','八年级','九年级'];p['grade_review_required']=False
    if spare:p['rooms'][0].update(cols=4,capacity=8)
    if custom:
        assert not spare
        # 手工完整置换：1号位于2行1列，4号位于1行1列；其余不变。
        mapping={'1:1':4,'1:2':2,'1:3':3,'2:1':1,'2:2':5,'2:3':6}
        p['rooms'][0]['seat_labels']=mapping
        for seats in p['seats'].values():
            for pos in seats.values():
                if pos['room_id']=='r01':pos['seat']={1:4,4:1}.get(pos['seat'],pos['seat'])
    if locked:p['seats']['base']['s7-001']['locked']=True
    return p


BUSINESS=('name','school','grades','grade_review_required','students','rooms','teachers','exams','settings',
    'seats','invigilation','number_sources','stale','stale_seats','pending_monitor_locks','report_layouts','subject_catalog','history_epoch')


def business(p):return {k:deepcopy(p.get(k)) for k in BUSINESS}


def saved(client):
    p=client.call('state')['plan'];assert client.app.store.load(p['id'])==p
    return p


def atomic_failure(client,name,body):
    p=saved(client);blob=client.app.store.path(p['id']).read_bytes()
    result=client.raw(name,body)
    assert not result['ok'],f'{name}错误输入被接受'
    assert saved(client)==p and client.app.store.path(p['id']).read_bytes()==blob,'失败有部分写入'
    return result['error']
