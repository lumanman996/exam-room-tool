"""可保存的毫米版式；按同一有效座位数据生成逐页打印内容。"""
from collections import defaultdict
from copy import deepcopy
from html import escape
import math
import unicodedata
from . import engine
from .model import plan_grades

MM_PER_PT=25.4/72
PAPERS={'A4':(210,297),'A3':(297,420)}
DEFAULT={'paper':'A4','orientation':'landscape','columns':1,'font_size':11,'line_height':1.4,
         'margins':dict(top=13,right=13,bottom=13,left=13),'color':'mono','page_break':'flow','repeat_headers':True}


def esc(value):return escape(str(value if value is not None else ''))


def scope_options(plan,scope=None):
    scope=scope or {};out={**scope,'mode':scope.get('mode','fixed')}
    if out['mode'] not in ('fixed','exam'):raise ValueError('编排范围须为固定编排或科目有效座位。')
    for key,values in [('exam_ids',[x['id'] for x in plan['exams']]),('room_ids',[x['id'] for x in plan['rooms']]),('grades',plan_grades(plan))]:
        selected=out.get(key,[])
        if not isinstance(selected,list) or any(not isinstance(x,str) or x not in values for x in selected):raise ValueError('导出范围包含不存在的考试、考场或年级，请重新选择。')
        out[key]=selected
    return out


def filtered_rows(plan,scope=None):
    from .report import all_rows
    s=scope_options(plan,scope)
    return [r for r in all_rows(plan) if (not s['exam_ids'] or r['exam_id'] in s['exam_ids']) and (not s['room_ids'] or r['room_id'] in s['room_ids']) and (not s['grades'] or r['年级'] in s['grades'])]


def room_blocks(plan,scope=None):
    s=scope_options(plan,scope);rooms={r['id']:r for r in plan['rooms']};groups=defaultdict(list);scopes={}
    if s['mode']=='exam':
        for r in filtered_rows(plan,s):
            key=(r['room_id'],r['日期'],r['时间']);groups[key].append({**r,'座号':str(r['座号']).zfill(2) if r['座号']!='' else ''})
        for key,rs in groups.items():scopes[key]=key[1]+' '+key[2]+' · '+'、'.join(sorted({r['年级']+' '+r['科目'] for r in rs}))
    else:
        for student in plan['students']:
            if s['grades'] and student['grade'] not in s['grades']:continue
            exams=[e for e in plan['exams'] if (not s['exam_ids'] or e['id'] in s['exam_ids']) and any(p['id']==student['id'] for p in engine.participants(plan,e))]
            if not exams:continue
            # Only exams using the fixed map describe a fixed block. Special maps
            # appear explicitly in subject detail / subject scope instead.
            fixed=[e for e in exams if not e.get('special_seating')]
            if not fixed:continue
            pos=plan['seats'].get('base',{}).get(student['id'],{});rid=pos.get('room_id','')
            if s['room_ids'] and rid not in s['room_ids']:continue
            timeline=tuple(sorted({(e['date'],e['start'],e['end']) for e in fixed}))
            key=(rid,timeline);room=rooms.get(rid,{})
            groups[key].append(dict(student_id=student['id'],room_id=rid,年级=student['grade'],班级=student['class_name'],姓名=student['name'],考号=student['number'],座号=str(pos['seat']).zfill(2) if 'seat' in pos else '',考场=room.get('name','未安排'),考场编号=room.get('code',''),位置=room.get('location','')))
            scopes[key]='；'.join(f'{d} {start}—{end}' for d,start,end in timeline)+'（固定座位；特殊科目请看科目明细）'
    out=[]
    for key,rs in groups.items():
        rid=key[0];room=rooms.get(rid,{})
        # Deduplicate only a student's repeated subjects in the SAME time block.
        rs=list({r['student_id']:r for r in rs}.values());rs.sort(key=lambda r:(int(r['座号'] or 0),r['student_id']))
        out.append(dict(room_id=rid,code=room.get('code',''),name=room.get('name','未安排'),location=room.get('location',''),scope=scopes[key],rows=rs))
    return sorted(out,key=lambda b:(b['code'],b['scope']))


def normalize_layout(value=None,key=None):
    if value is not None and not isinstance(value,dict):raise ValueError('版式设置格式不正确。')
    v=value or {};out={**deepcopy(DEFAULT),**v,'margins':{**DEFAULT['margins'],**v.get('margins',{})}}
    if key in ('room_students','tickets','labels') and 'columns' not in v:out['columns']=2
    if out['paper'] not in PAPERS or out['orientation'] not in ('portrait','landscape'):raise ValueError('请选择 A4/A3 纸张及横向/纵向。')
    for field,low,high in [('columns',1,3),('font_size',9,18),('line_height',1.2,2)]:
        n=out[field]
        if isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or not low<=n<=high or (field=='columns' and int(n)!=n):raise ValueError(f'{field} 设置超出允许范围。')
    if out['color'] not in ('mono','color') or out['page_break'] not in ('room','flow'):raise ValueError('打印配色或分页方式不正确。')
    if out['repeat_headers'] is not True:raise ValueError('跨页材料必须重复表头，避免打印后混淆。')
    for n in out['margins'].values():
        if isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or not 5<=n<=40:raise ValueError('页边距须为 5～40 mm。')
    fields=out.get('field_order',[]);widths=out.get('column_widths',{})
    if not isinstance(fields,list) or any(not isinstance(x,str) for x in fields) or len(set(fields))!=len(fields):raise ValueError('字段顺序格式不正确或存在重复字段。')
    if not isinstance(widths,dict) or any(not isinstance(k,str) or isinstance(n,bool) or not isinstance(n,(float,int)) or not math.isfinite(n) or not 0<n<=400 for k,n in widths.items()):raise ValueError('列宽须为大于 0 的毫米数。')
    out['field_order']=fields;out['column_widths']=widths;out['columns']=int(out['columns']);return out


def layout_for(plan,key,layouts=None):
    return normalize_layout((layouts or {}).get(key,plan.get('report_layouts',{}).get(key)),key)


def dimensions(layout):
    w,h=PAPERS[layout['paper']]
    if layout['orientation']=='landscape':w,h=h,w
    m=layout['margins'];return w,h,w-m['left']-m['right'],h-m['top']-m['bottom']


def width_units(value):
    return sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in str(value))


def table_spec(layout,available,rows):
    fields=layout['field_order'] or available
    if any(k not in available for k in fields):raise ValueError('所选材料没有这些字段：'+'、'.join(k for k in fields if k not in available))
    if not fields:raise ValueError('至少保留一个打印字段。')
    if '座号' in available and '考号' in available and any(k not in fields for k in ('座号','考号','姓名')):raise ValueError('学生材料须保留座号、考号和姓名，避免错人。')
    _,_,usable,_=dimensions(layout);width=(usable-(layout['columns']-1)*6)/layout['columns']
    explicit=layout['column_widths']
    if any(k not in fields for k in explicit):raise ValueError('列宽含未选择的字段，请核对字段顺序。')
    font=layout['font_size']*MM_PER_PT
    minimum={k:max(width_units(k)*font*.5+3,10) for k in fields}
    for k in ('考号','座号'):
        if k in fields:minimum[k]=max(minimum[k],max((width_units(r.get(k,''))*font*.56+3 for r in rows),default=0))
    widths={k:explicit.get(k,minimum[k]) for k in fields}
    if any(widths[k]<minimum[k] for k in fields) or sum(widths.values())>width+.01:raise ValueError('栏数或列宽无法容纳字段及完整考号，请减少栏数、增大纸张或调整列宽。')
    free=[k for k in fields if k not in explicit]
    if free:
        extra=(width-sum(widths.values()))/len(free)
        widths={k:n+(extra if k in free else 0) for k,n in widths.items()}
    return fields,widths


def row_height(row,fields,widths,layout):
    font=layout['font_size']*MM_PER_PT
    lines=max((math.ceil(width_units(row.get(k,''))*font*.56/max(1,widths[k]-3)) for k in fields),default=1)
    return max(1,lines)*font*layout['line_height']+3


def groups_for(plan,key,mats,rows,scope):
    from .report import SECTIONS
    if key=='room_students':
        return [dict(title=f'{b["code"]} 考场 · {b["name"]} · {b["location"]} · {len(b["rows"])} 人',scope=b['scope'],rows=b['rows'],columns=['座号','考号','姓名','班级','年级']) for b in room_blocks(plan,scope)]
    cols=mats[key]['columns'];data=[dict(zip(cols,r)) for r in mats[key]['rows']]
    grouping=None
    if key in ('classes','personal','tickets','labels','rosters','signins'):
        grouping=defaultdict(list)
        for r in rows:
            if key=='classes':ident=(r['年级'],r['班级'])
            elif key in ('personal','tickets'):ident=(r['student_id'],)
            elif key=='labels':ident=(r['student_id'],r['room_id'],r['座号'])
            else:ident=(r['room_id'],r['日期'],r['时间'])
            grouping[ident].append({**r,'座号':str(r['座号']).zfill(2) if r['座号']!='' else ''})
        out=[]
        for rs in grouping.values():
            first=rs[0]
            title=(first['年级']+' '+first['班级']) if key=='classes' else (first['姓名']+' · '+first['班级']+' · 考号 '+first['考号']) if key in ('personal','tickets') else first['考场']+' · '+first['日期']+' '+first['时间']
            if key in ('rosters','signins'):rs=list({r['student_id']:r for r in rs}.values());rs.sort(key=lambda r:int(r['座号'] or 0))
            if key=='tickets':cols=['日期','时间','科目','考场','座号']
            elif key=='labels':
                title=first['姓名']+' · '+first['班级']+' · 考号 '+first['考号'];cols=['日期','时间','科目','考场','座号']
            elif key in ('rosters','signins'):cols=['座号','考号','姓名','班级','年级','科目']+(['签到'] if key=='signins' else [])
            out.append(dict(title=title,scope='',rows=rs,columns=cols))
        return out
    if key=='teacher_personal':
        teachers={t['id']:t for t in plan['teachers']};rooms={r['id']:r for r in plan['rooms']};out=[]
        for tid,t in teachers.items():
            own=[]
            for d in engine.duties(plan):
                if any(r['room_id']==d['room_id'] and r['exam_id'] in d['exam_ids'] for r in rows) and any(a.get('teacher_id')==tid for a in plan['invigilation'].get(d['id'],[])):
                    own.append(dict(教师=t['name'],日期=d['date'],时间=d['start']+'—'+d['end'],考场=rooms[d['room_id']]['name'],位置=rooms[d['room_id']]['location'],科目='、'.join(d['subjects'])))
            if own:out.append(dict(title=t['name'],scope='',rows=own,columns=cols))
        return out
    return [dict(title=SECTIONS[key],scope='',rows=data,columns=cols)] if data else []


def table_html(fields,widths,rows):
    return '<table><colgroup>'+''.join(f'<col style="width:{widths[k]:g}mm">' for k in fields)+'</colgroup><thead><tr>'+''.join('<th>'+esc(k)+'</th>' for k in fields)+'</tr></thead><tbody>'+''.join('<tr>'+''.join(f'<td class="{ "number" if k in ("考号","座号") else ""}">'+esc(r.get(k,''))+'</td>' for k in fields)+'</tr>' for r in rows)+'</tbody></table>'


def paginate_group(group,layout):
    fields,widths=table_spec(layout,group['columns'],group['rows']);font=layout['font_size']*MM_PER_PT
    _,_,_,height=dimensions(layout)
    # Plan title/footer + block title/scope + repeated table heading.
    header_height=18+max(8,row_height({'title':group['title']+' '+group['scope']},['title'],{'title':sum(widths.values())},layout))+font*layout['line_height']+3
    budget=height-24-header_height
    if budget<font*layout['line_height']+3:raise ValueError('页边距、字号或栏数使打印区过小，请调整版式。')
    chunks=[];chunk=[];used=0
    for row in group['rows']:
        h=row_height(row,fields,widths,layout)
        if h>budget:raise ValueError('一行文字超过单页可用高度，请增大纸张、列宽或减少栏数。')
        if chunk and used+h>budget:chunks.append((chunk,header_height+used));chunk=[];used=0
        chunk.append(row);used+=h
    chunks.append((chunk,header_height+used))
    return [dict(title=group['title']+('（续表）' if i else ''),scope=group['scope'],content=table_html(fields,widths,rs),height=h) for i,(rs,h) in enumerate(chunks)]


def seating_groups(plan,rows,scope,layout):
    s=scope_options(plan,scope);rooms={r['id']:r for r in plan['rooms']};out=[]
    _,_,usable,height=dimensions(layout);width=(usable-6*(layout['columns']-1))/layout['columns'];font=layout['font_size']*MM_PER_PT
    if layout['field_order'] or layout['column_widths']:raise ValueError('座次图按实际行列打印，字段列宽只适用于名单表。')
    for d in engine.duties(plan):
        relevant=[r for r in rows if r['room_id']==d['room_id'] and r['exam_id'] in d['exam_ids']]
        if not relevant:continue
        room=rooms[d['room_id']];nc=room['cols']*room['per_desk'];cell_width=width/nc
        placed={r['座号']:r for r in relevant};physical=engine.seat_layout({**room,'disabled':[],'capacity':room['rows']*nc});active={x['seat'] for x in engine.seat_layout(room)}
        if cell_width<15:raise ValueError('座次图列数超过纸张宽度，请减少栏数或使用 A3 横向。')
        height_per=[];row_html=[]
        for rr in range(1,room['rows']+1):
            cells=[];rh=0
            for pos in sorted((p for p in physical if p['row']==rr),key=lambda p:p['col']):
                seat=pos['seat'];r=placed.get(seat);texts=([str(seat).zfill(2)+' 号',r['姓名'],r['班级'],r['考号']] if r else [str(seat).zfill(2)+' 号','空位' if seat in active else '停用' if seat in room['disabled'] else '未使用'])
                if r and width_units(r['考号'])*font*.56+3>cell_width:raise ValueError('座次图无法完整显示考号，请减少栏数或使用更大纸张。')
                rh=max(rh,sum(max(1,math.ceil(width_units(t)*font*.56/(cell_width-3))) for t in texts)*font*layout['line_height']+4)
                gap=pos['col']%room['per_desk']==0 and pos['col']//room['per_desk'] in room['aisles']
                cells.append('<td class="seat'+(' aisle' if gap else '')+'">'+''.join('<div>'+esc(t)+'</div>' for t in texts)+'</td>')
            row_html.append('<tr>'+''.join(cells)+'</tr>');height_per.append(rh)
        title=room['name']+' · '+d['date']+' '+d['start']+'—'+d['end'];budget=height-58;chunks=[];chunk=[];used=0
        for tr,rh in zip(row_html,height_per):
            if rh>budget:raise ValueError('座次图单行高度超出可用纸张，请调整版式。')
            if chunk and used+rh>budget:chunks.append((chunk,used));chunk=[];used=0
            chunk.append(tr);used+=rh
        if chunk:chunks.append((chunk,used))
        for i,(chunk,h) in enumerate(chunks):out.append(dict(title=title+('（续图，行位置接上页）' if i else ''),scope='、'.join(d['subjects']),content='<div class="platform">讲台方向 ↑</div><table class="seats">'+''.join(chunk)+'</table>',height=h+30))
    return out


def document(plan,sections,draft=False,layouts=None,scope=None):
    from .report import materials,check_export,SECTIONS,issue_text
    result=check_export(plan,draft,sections);scope=scope_options(plan,scope);mats,rows,_=materials(plan,scope);pages=[];css=[]
    for key in sections:
        if key not in SECTIONS:raise ValueError('所选导出材料已不存在，请重新选择。')
        l=layout_for(plan,key,layouts);w,h,usable,height=dimensions(l);name='s_'+key;m=l['margins'];font=l['font_size'];line=l['line_height']
        css.append(f'@page {name}{{size:{l["paper"]} {l["orientation"]};margin:{m["top"]}mm {m["right"]}mm {m["bottom"]}mm {m["left"]}mm}}.p_{key}{{page:{name};width:{usable:g}mm;font-size:{font:g}pt;line-height:{line:g}}}.p_{key} th{{background:{"#fff" if l["color"]=="mono" else "#edf0f7"}}}@media screen{{.p_{key}{{width:{w:g}mm;min-height:{h:g}mm;padding:{m["top"]}mm {m["right"]}mm {m["bottom"]}mm {m["left"]}mm}}}}')
        if key=='seating':chunks=seating_groups(plan,rows,scope,l)
        else:chunks=[chunk for group in groups_for(plan,key,mats,rows,scope) for chunk in paginate_group(group,l)]
        if not chunks:chunks=[dict(title=SECTIONS[key],scope='',content='<p>当前范围没有资料。</p>',height=20)]
        # Pack blocks in independent vertical columns; never split a block's title
        # from its data. Every planned chunk fits in one printed column.
        columns=[[] for _ in range(l['columns'])];used=[0]*l['columns']
        def flush():
            if not any(columns):return
            content='<div class="columns" style="grid-template-columns:repeat('+str(l['columns'])+',minmax(0,1fr))">'+''.join('<div>'+''.join(f'<article><h2>{esc(c["title"])}</h2><p class="scope">{esc(c["scope"])}</p>{c["content"]}</article>' for c in col)+'</div>' for col in columns)+'</div>'
            pages.append(dict(section=key,paper=l['paper'],orientation=l['orientation'],content=content,css_class='p_'+key))
        for chunk in chunks:
            fits=[i for i in range(l['columns']) if used[i]+chunk['height']+4<=height-24]
            if not fits or (l['page_break']=='room' and any(columns)):
                flush();columns=[[] for _ in range(l['columns'])];used=[0]*l['columns'];fits=list(range(l['columns']))
            col=min(fits,key=lambda i:used[i]);columns[col].append(chunk);used[col]+=chunk['height']+4
        flush()
    if draft and result['errors']:
        # Errors are also saved in Excel. Printable diagnostic pages use the same
        # pagination and readable minimum size as all other tables.
        l=normalize_layout();g=dict(title='草稿检查清单',scope='',columns=['问题'],rows=[{'问题':issue_text(plan,x)} for x in result['errors']])
        for c in paginate_group(g,l):pages.append(dict(section='checks',paper='A4',orientation='landscape',css_class='p_checks',content='<h2>草稿检查清单</h2>'+c['content']))
        css.append('@page checks{size:A4 landscape;margin:13mm}.p_checks{page:checks;width:271mm;font-size:11pt;line-height:1.4}')
    if not pages:raise ValueError('请至少选择一种材料。')
    base='''*{box-sizing:border-box}body{margin:0;color:#111;font-family:"Songti SC","SimSun",serif}.page{position:relative;break-after:page}.page:last-child{break-after:auto}header,footer{font-size:9pt;line-height:1.4;min-height:5mm;margin:0 0 2mm}header{border-bottom:1px solid #888}footer{margin:2mm 0 0;text-align:right}h1{font-size:14pt;line-height:1.3;margin:0 0 3mm}h2{font-size:1em;line-height:inherit;margin:0 0 1mm;overflow-wrap:anywhere}.scope{margin:0 0 2mm;font-size:.9em;overflow-wrap:anywhere}article{margin:0 0 4mm;break-inside:avoid}.columns{display:grid;gap:6mm}table{width:100%;border-collapse:collapse;table-layout:fixed}th,td{border:.25mm solid #666;padding:1.5mm;vertical-align:middle;text-align:center;overflow-wrap:anywhere}thead{display:table-header-group}tr{break-inside:avoid}.number{white-space:nowrap}.platform{text-align:center;border:1px solid #555;padding:2mm;margin-bottom:3mm}.aisle{border-right:2mm solid #999}@media screen{body{background:#e7e7e7}.page{background:white;margin:15px auto;box-shadow:0 1px 5px #aaa}}'''
    body=[];meta=[]
    for i,p in enumerate(pages,1):
        meta.append(dict(number=i,section=p['section'],paper=p['paper'],orientation=p['orientation']))
        body.append(f'<section class="page {p["css_class"]}" data-page="{i}"><header>考场编排 · {esc(plan["school"])}</header><h1>{"【草稿】" if draft else ""}{esc(plan["name"])} · {esc(SECTIONS.get(p['section'],'编排检查'))}</h1>{p["content"]}<footer>{"草稿，请核对后使用" if draft else "正式材料"} · 方案版本 {plan["revision"]} · 第 {i} / {len(pages)} 页</footer></section>')
    html='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>'+esc(plan['name'])+'</title><style>'+base+''.join(css)+'</style></head><body>'+''.join(body)+'</body></html>'
    return dict(html=html,pages=meta,page_count=len(meta))


def default_layouts():
    student=['年级','班级','姓名','考号','日期','时间','科目','考场','位置','座号']
    fields={k:student for k in ('students','student_details','classes','personal','tickets','rosters','labels')}
    fields.update(room_students=['座号','考号','姓名','班级','年级'],schedule=['年级','科目','日期','开始','结束','时长'],rooms=['日期','时间','考场','位置','科目','人数'],invigilation=['日期','时间','考场','科目','人数','应到监考','监考教师'],workload=['教师','场次','监考分钟'],doors=['日期','时间','考场','位置','科目','人数'],teacher_personal=['教师','日期','时间','考场','位置','科目'],signins=student+['签到'],seating=[])
    fields.update(tickets=['日期','时间','科目','考场','座号'],labels=['日期','时间','科目','考场','座号'],rosters=['座号','考号','姓名','班级','年级','科目'],signins=['座号','考号','姓名','班级','年级','科目','签到'])
    return {k:{**normalize_layout(key=k),'field_order':list(v)} for k,v in fields.items()}
