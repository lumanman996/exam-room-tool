"""虚构规模验收：1500 学生 / 50 考场 / 120 教师。"""
from pathlib import Path
import json,resource,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from exam_room import engine
from exam_room.model import demo_plan
p=demo_plan(large=True);p['settings']['mix_grades']=True
results={'students':1500,'rooms':50,'teachers':120,'room_capacity':30,'mix_grades':True,'python':sys.version.split()[0]}
for name,fn in [('seats',engine.assign_seats),('invigilators',engine.assign_invigilators)]:
 t=time.perf_counter();r=fn(p);results[name]={'seconds':round(time.perf_counter()-t,3),'status':r['status']};print(name,results[name],flush=True)
 if r['status'] in ('optimal','feasible','partial'):p=r['plan']
 else:break
v=engine.validate(p);results['errors']=len(v['errors']);results['warnings']=len(v['warnings'])
results['peak_memory_mb']=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1024*1024 if sys.platform=='darwin' else 1024),2)
f=Path(__file__).resolve().parents[1]/'output'/'benchmark.json';f.parent.mkdir(exist_ok=True);f.write_text(json.dumps(results,ensure_ascii=False,indent=2));print(json.dumps(results,ensure_ascii=False),flush=True)
