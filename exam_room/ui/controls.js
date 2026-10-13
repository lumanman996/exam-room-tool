'use strict';
// Text clocks work the same way in Windows and macOS webviews.
function parseClock(value){
  const m=String(value).trim().replace(/：/g,':').match(/^(\d{1,2}):(\d{2})$/);
  if(!m||Number(m[1])>23||Number(m[2])>59)throw Error('时间请填写为 08:30 这样的格式，小时 00～23、分钟 00～59。');
  return m[1].padStart(2,'0')+':'+m[2];
}
function clockMinutes(value){const [h,m]=parseClock(value).split(':').map(Number);return h*60+m;}
function shiftClock(value,delta){
  const minutes=clockMinutes(value)+delta;
  if(minutes<0||minutes>=1440)throw Error('调整后的时间超出当天，请先修改日期，再填写时间。');
  return String(Math.floor(minutes/60)).padStart(2,'0')+':'+String(minutes%60).padStart(2,'0');
}
function mixPreset(mode,pair,custom=''){
  if(mode==='separate')return {mix_grades:false,mix_groups:[]};
  if(mode==='all')return {mix_grades:true,mix_groups:[]};
  const groups=mode==='pair'?[pair.split('|')]:custom.split(/[;；]/).filter(x=>x.trim()).map(x=>x.split(/[,，、]/).map(g=>g.trim()).filter(Boolean));
  if(!groups.length||groups.some(g=>new Set(g).size<2))throw Error('请至少选择两个不同年级进行混排。');
  return {mix_grades:true,mix_groups:groups};
}
// The formal exam scope is never inferred from imported students.
function formalGrades(plan){return Array.isArray(plan?.grades)?plan.grades.slice():[];}
function normalizeGrades(names){
  const aliases={};for(const [n,ch,j]of [[7,'七','一'],[8,'八','二'],[9,'九','三']])for(const a of [String(n),n+'.0',ch,n+'年级',ch+'年级','初'+j,'初'+(n-6)])aliases[a]=ch+'年级';
  const grades=names.map(x=>{const name=String(x??'').trim();return aliases[name]||name});
  if(grades.some(g=>!g))throw Error('每个年级都要填写名称。');
  if(new Set(grades).size!==grades.length)throw Error('年级名称不能重复；初一和七年级等名称视为同一年级。');
  return grades;
}
function gradePairs(grades){return grades.flatMap((g,i)=>grades.slice(i+1).map(h=>[g,h]));}
function validateMixGroups(groups,grades){
  const used=new Set();for(const group of groups){if(group.length<2||new Set(group).size!==group.length)throw Error('每个混排组至少选择两个不同年级。');for(const g of group){if(!grades.includes(g))throw Error('混排组包含未设置的年级：'+g);if(used.has(g))throw Error('同一年级不能出现在多个混排组：'+g);used.add(g)}}return groups.map(g=>g.slice());
}
function mixScope(grades,settings){const groups=!settings.mix_grades?[]:settings.mix_groups.length?settings.mix_groups.map(g=>g.slice()):grades.length>1?[grades.slice()]:[];return {groups,independent:grades.filter(g=>!groups.some(x=>x.includes(g)))};}
function gradeFields(names){return `<label>本次考试的年级数量<input id="gradeCount" type="number" min="1" step="1" value="${names.length}"></label><div id="gradeFields" class="form-grid"></div><p class="muted">名称可自定，顺序按这里填写的顺序保留。已有学生或科目使用的年级，须先处理关联资料后才能移除。</p>`;}
function bindGradeFields(names){
  const retained=names.slice();function render(){const count=Number($('gradeCount').value);if(!Number.isSafeInteger(count)||count<1)return;document.querySelectorAll('[data-grade-name]').forEach((el,i)=>retained[i]=el.value);$('gradeFields').innerHTML=Array.from({length:count},(_,i)=>`<label>第 ${i+1} 个年级<input data-grade-name="${i}" id="grade-name-${i}" value="${esc(retained[i]??'')}" placeholder="例如 七年级或实验年级"></label>`).join('');}
  $('gradeCount').addEventListener('input',render);render();
}
function readGradeFields(){const count=Number($('gradeCount').value);if(!Number.isSafeInteger(count)||count<1)throw Error('年级数量请填写大于 0 的整数。');const fields=[...document.querySelectorAll('[data-grade-name]')];if(fields.length!==count)throw Error('请先填写各年级名称。');return normalizeGrades(fields.map(el=>el.value));}
function openNewExam(){const names=['七年级','八年级','九年级'];form('新建考试 · 设置参试年级',field('newName','考试名称','期末考试')+gradeFields(names),async()=>{const grades=readGradeFields();view=await api('new',{name:$('newName').value,grades});activePage='overview';renderAll()});bindGradeFields(names);$('formSave').textContent='创建考试';}
function openGradeSettings(){const names=formalGrades(view.plan);form('本次考试年级',gradeFields(names.length?names:['']),async()=>{const q=clone(view.plan);q.grades=readGradeFields();q.grade_review_required=false;await save(q);toast('本次考试年级已保存。')});bindGradeFields(names.length?names:['']);}
function requireGrades(kind){if(['students','exams'].includes(kind)&&!formalGrades(view.plan).length){toast('请先设置本次考试年级，再添加或导入学生、科目。',true);openGradeSettings();return false;}return true;}
function renderGradeSummary(){const p=view.plan,grades=formalGrades(p);$('gradeSummary').innerHTML=grades.length?grades.map(g=>`<span class="grade-chip"><b>${esc(g)}</b><span>${p.students.filter(s=>s.grade===g).length} 人</span></span>`).join(''):'<p class="muted">还没有设置参试年级。请先设置，再录入学生和科目。</p>';$('gradeTotal').textContent=grades.length+' 个年级';$('gradeReview').classList.toggle('hidden',!p.grade_review_required);bind('editGrades',()=>Workspace.requestNavigation(openGradeSettings));}
function clockControl(id,value,label){return `<span class="clock-control"><button type="button" class="clock-step" data-clock="${id}" data-delta="-5" aria-label="${esc(label)}减 5 分钟" title="减 5 分钟">−</button><input id="${id}" type="text" inputmode="text" maxlength="5" placeholder="08:30" value="${esc(value)}" aria-label="${esc(label)}"><button type="button" class="clock-step" data-clock="${id}" data-delta="5" aria-label="${esc(label)}加 5 分钟" title="加 5 分钟">＋</button></span>`;}
function bindClocks(root=document){root.querySelectorAll('[data-clock]').forEach(b=>b.onclick=()=>{try{const input=$(b.dataset.clock);input.value=shiftClock(input.value||'08:00',Number(b.dataset.delta));input.dispatchEvent(new Event('input',{bubbles:true}));}catch(e){toast(e.message,true)}});}
function readWindow(dateId,startId,endId){
  const date=$(dateId).value,start=parseClock($(startId).value),end=parseClock($(endId).value);
  if(!/^\d{4}-\d{2}-\d{2}$/.test(date))throw Error('请填写有效的考试日期。');
  if(clockMinutes(end)<=clockMinutes(start))throw Error('结束时间须晚于开始时间。');
  return {date,start,end};
}
function readExamDraft(i){const date=$('exam-date-'+i).value,start=$('exam-start-'+i).value?parseClock($('exam-start-'+i).value):'',end=$('exam-end-'+i).value?parseClock($('exam-end-'+i).value):'';if(date&&(!/^\d{4}-\d{2}-\d{2}$/.test(date)||Number.isNaN(new Date(date+'T00:00:00Z').getTime())||new Date(date+'T00:00:00Z').toISOString().slice(0,10)!==date))throw Error('考试日期不正确。');const duration=Editing.examDuration(start,end,$('exam-duration-'+i).value).minutes;return {date,start,end,duration};}
function updateScheduleDuration(i){const input=$('exam-duration-'+i),hint=$('exam-duration-hint-'+i);try{const result=Editing.examDuration($('exam-start-'+i).value,$('exam-end-'+i).value,input.value);input.value=result.minutes;input.readOnly=result.readonly;hint.textContent=result.readonly?'自动计算':'计划分钟';hint.className='muted';}catch(e){hint.textContent=e.message;hint.className='issue';input.readOnly=!!($('exam-start-'+i).value&&$('exam-end-'+i).value);}}
function renderScheduleControls(){
  const p=view.plan;renderExamGroups();
  $('examTable').innerHTML=table(['年级','科目','日期','开始时间','结束时间','时长','锁定','操作'],p.exams.map((e,i)=>[
    e.grade,e.subject,raw(`<input type="date" id="exam-date-${i}" aria-label="${esc(e.grade+' '+e.subject+' 日期')}" value="${esc(e.date)}">`),
    raw(clockControl('exam-start-'+i,e.start,e.grade+' '+e.subject+' 开始时间')),raw(clockControl('exam-end-'+i,e.end,e.grade+' '+e.subject+' 结束时间')),
    raw(`<input id="exam-duration-${i}" type="number" min="1" max="1440" value="${e.duration}" ${e.start&&e.end?'readonly':''} aria-label="${esc(e.grade+' '+e.subject+' 时长分钟')}"><small id="exam-duration-hint-${i}" class="muted">${e.start&&e.end?'自动计算':'计划分钟'}</small>`),raw(`<label><input type="checkbox" id="exam-lock-${i}" aria-label="锁定${esc(e.grade+' '+e.subject)}时间" ${e.locked?'checked':''}> 锁定</label>`),
    raw(`<button class="secondary" data-save-exam="${i}">保存</button> <button class="link-button" data-ex-edit="${esc(e.id)}">更多</button>`)]));
  document.querySelectorAll('[data-save-exam]').forEach(b=>b.onclick=async()=>{try{const drafts=otherScheduleDrafts(b.closest('tr'));const i=Number(b.dataset.saveExam),window=readExamDraft(i),q=clone(view.plan);Object.assign(q.exams[i],window,{locked:$('exam-lock-'+i).checked});await save(q);restoreScheduleDrafts(drafts);toast('考试时间已保存，已有座位和监考安排请重新检查。')}catch(e){toast(e.message,true)}});
  document.querySelectorAll('[data-ex-edit]').forEach(b=>b.onclick=()=>editEntity('exams',b.dataset.exEdit));
  $('slotTable').innerHTML=p.settings.slots.map((s,i)=>`<div class="slot-row"><label>日期<input type="date" id="slot-date-${i}" value="${esc(s.date)}"></label><label>开始${clockControl('slot-start-'+i,s.start,'可用时段 '+(i+1)+' 开始时间')}</label><label>结束${clockControl('slot-end-'+i,s.end,'可用时段 '+(i+1)+' 结束时间')}</label><button class="secondary" data-save-slot="${i}">保存时段</button><button class="link-button" data-del-slot="${i}">删除</button></div>`).join('')||'<p class="muted">还没有自动安排时段。</p>';
  document.querySelectorAll('[data-save-slot]').forEach(b=>b.onclick=async()=>{try{const drafts=otherScheduleDrafts(b.closest('.slot-row'));const i=Number(b.dataset.saveSlot),window=readWindow('slot-date-'+i,'slot-start-'+i,'slot-end-'+i),q=clone(view.plan);q.settings.slots[i]=window;await save(q);restoreScheduleDrafts(drafts);toast('可用时段已保存。')}catch(e){toast(e.message,true)}});
  document.querySelectorAll('[data-del-slot]').forEach(b=>b.onclick=async()=>{try{if(scheduleHasUnsaved())throw Error('请先保存黄色行，再删除时段。');const q=clone(view.plan);q.settings.slots.splice(Number(b.dataset.delSlot),1);await save(q)}catch(e){toast(e.message,true)}});
  bindClocks($('schedule'));
  // Keep a partially typed row from disappearing during automatic scheduling.
  $('schedule').querySelectorAll('input').forEach(input=>input.oninput=()=>{input.closest('tr,.slot-row')?.classList.add('unsaved');const index=input.id.match(/^exam-(?:start|end|duration)-(\d+)$/)?.[1];if(index!==undefined)updateScheduleDuration(+index)});
}

function renderExamGroups(groups=view.plan.settings.exam_groups||[]){$('examGroupsList').innerHTML=groups.map((g,i)=>`<fieldset class="exam-group" data-exam-group="${i}"><legend>第 ${i+1} 组</legend><div class="form-grid">${view.plan.exams.map(e=>`<label class="check"><input type="checkbox" id="group-${i}-${esc(e.id)}" data-group-exam="${esc(e.id)}" ${g.exam_ids.includes(e.id)?'checked':''}>${esc(e.grade+' '+e.subject+' · '+e.duration+' 分钟')}</label>`).join('')}</div><button class="link-button" data-remove-group="${i}">删除这一组</button></fieldset>`).join('')||'<p class="muted">未指定同时混考组。已有日程也可以逐行填写相同时间。</p>';$('examGroupsList').querySelectorAll('input').forEach(el=>el.oninput=()=>$('examGroupsPanel').classList.add('dirty'));document.querySelectorAll('[data-remove-group]').forEach(b=>b.onclick=()=>{b.closest('[data-exam-group]').remove();$('examGroupsPanel').classList.add('dirty');window.EditingUI?.changed($('schedule'))});bind('examGroupAdd',()=>{const groups=readExamGroups(false);groups.push({exam_ids:[]});renderExamGroups(groups);$('examGroupsPanel').classList.add('dirty');window.EditingUI?.changed($('schedule'))});bind('examGroupSave',async()=>{try{const q=clone(view.plan);q.settings.exam_groups=readExamGroups();await save(q);$('examGroupsPanel').classList.remove('dirty');toast('同时混考组已保存。自动安排日程时按组同时安排。')}catch(e){errorAt('examGroupError',e)}});}
function readExamGroups(check=true){const groups=[...document.querySelectorAll('[data-exam-group]')].map(row=>({exam_ids:[...row.querySelectorAll('[data-group-exam]:checked')].map(el=>el.dataset.groupExam)}));if(check)for(const g of groups){const exams=g.exam_ids.map(id=>view.plan.exams.find(e=>e.id===id));if(exams.length<2||new Set(exams.map(e=>e.grade)).size!==exams.length||new Set(exams.map(e=>e.duration)).size!==1)throw Error('每组请选择至少两个不同年级且时长相同的科目。');}return groups;}

function otherScheduleDrafts(except){return [...$('schedule').querySelectorAll('.unsaved')].filter(row=>row!==except).flatMap(row=>[...row.querySelectorAll('input')].map(input=>({id:input.id,value:input.value,checked:input.checked})));}
function restoreScheduleDrafts(drafts){for(const draft of drafts){const input=$(draft.id);if(input){input.value=draft.value;input.checked=draft.checked;input.closest('tr,.slot-row')?.classList.add('unsaved');}}}
function scheduleHasUnsaved(){return !!$('schedule').querySelector('.unsaved');}
function renderCustomMix(groups){
  const grades=formalGrades(view.plan);$('mixGroupList').innerHTML=groups.map((group,i)=>`<fieldset data-mix-group="${i}" class="exam-group"><legend>混排组 ${i+1}</legend><div class="form-grid">${grades.map((g,j)=>`<label class="check"><input type="checkbox" data-mix-grade="${esc(g)}" id="mix-grade-${i}-${j}" ${group.includes(g)?'checked':''}>${esc(g)}</label>`).join('')}</div><button class="link-button" data-remove-mix="${i}">删除这一组</button></fieldset>`).join('')||'<p class="muted">添加一组，再勾选需要混排的年级。未勾选的年级独立编排。</p>';
  $('mixGroupList').querySelectorAll('input').forEach(el=>el.oninput=()=>{$('seatSettings').classList.add('dirty');updateMixSummary()});$('mixGroupList').querySelectorAll('[data-remove-mix]').forEach(el=>el.onclick=()=>{el.closest('fieldset').remove();$('seatSettings').classList.add('dirty');updateMixSummary();window.EditingUI?.changed($('seats'))});
}
function readCustomMix(){return [...document.querySelectorAll('[data-mix-group]')].map(row=>[...row.querySelectorAll('[data-mix-grade]:checked')].map(el=>el.dataset.mixGrade));}
function renderMixControls(){
  const s=view.plan.settings,grades=formalGrades(view.plan),groups=s.mix_groups||[],pairs=gradePairs(grades);
  let mode=!s.mix_grades?'separate':!groups.length?'all':groups.length===1&&groups[0].length===2?'pair':'custom';
  if(mode==='pair'&&!pairs.some(g=>g.every(x=>groups[0].includes(x))))mode='custom';
  $('mixPair').innerHTML=pairs.map((g,i)=>option(String(i),g.join(' ＋ '),groups.length===1&&g.every(x=>groups[0].includes(x)))).join('');
  renderCustomMix(groups);$('mixAll').textContent=`全部 ${grades.length} 个年级混排`;
  $('mixCandidates').textContent='本次考试年级：'+(grades.join('、')||'尚未设置');
  document.querySelectorAll('[data-mix-mode]').forEach(b=>{b.disabled=b.dataset.mixMode!=='separate'&&grades.length<2;b.onclick=()=>{selectMixMode(b.dataset.mixMode);$('seatSettings').classList.add('dirty')}});
  const old=$('mixPresetSelect').value,presets=s.mix_presets||[];$('mixPresetSelect').innerHTML=option('','选择已保存的方案',!old)+presets.map(p=>option(p.id,p.name,p.id===old)).join('');
  bind('mixGroupAdd',()=>{renderCustomMix([...readCustomMix(),[]]);$('seatSettings').classList.add('dirty');updateMixSummary();window.EditingUI?.changed($('seats'))});
  bind('mixPresetApply',async()=>{const preset=(view.plan.settings.mix_presets||[]).find(p=>p.id===$('mixPresetSelect').value);if(!preset)throw Error('请先选择一个已保存的混排方案。');validateMixGroups(preset.groups,formalGrades(view.plan));renderCustomMix(preset.groups);selectMixMode('custom');$('seatSettings').classList.add('dirty');await saveMixConfiguration();toast('混排方案已应用并保存。')});
  bind('mixPresetSave',()=>{try{const settings=readMixControls();if(!settings.mix_grades||!settings.mix_groups.length)throw Error('请选择两个年级或自定义年级组，再保存具名方案。');form('保存具名混排方案',field('mixPresetName','方案名称','','text')+'<p class="muted">例如 七八混排、九年级独立。同名保存会更新本次考试的原方案，并保存当前编排规则。</p>',async()=>{const name=$('mixPresetName').value.trim();if(!name)throw Error('请填写混排方案名称。');const q=collectSeatSettings(clone(view.plan)),groups=q.settings.mix_groups;q.settings.mix_presets=q.settings.mix_presets||[];const existing=q.settings.mix_presets.find(p=>p.name===name);if(existing)existing.groups=groups;else q.settings.mix_presets.push({id:crypto.randomUUID(),name,groups});await save(q);$('seatSettings').classList.remove('dirty');toast('混排方案已保存到本次考试。')});}catch(e){errorAt('mixError',e)}});
  bind('mixSettingsSave',async()=>{try{await saveMixConfiguration();toast('编排设置已保存。')}catch(e){errorAt('mixError',e)}});
  $('mixPair').onchange=updateMixSummary;selectMixMode(mode);
}
async function saveMixConfiguration(){const q=collectSeatSettings(clone(view.plan));await save(q);$('seatSettings').classList.remove('dirty');$('mixError').classList.add('hidden');}
function selectMixMode(mode){
  $('mixChoices').dataset.mode=mode;document.querySelectorAll('[data-mix-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mixMode===mode)));
  $('mixPairRow').classList.toggle('hidden',mode!=='pair');$('mixCustomRow').classList.toggle('hidden',mode!=='custom');
  $('mixHint').textContent='混排的考试起止时间须一致。所选年级按座号交插；锁定座位优先，人数不等时继续安排剩余学生。实际考场分配以编排与检查结果为准。';updateMixSummary();
}
function readMixControls(){const mode=$('mixChoices').dataset.mode,grades=formalGrades(view.plan);if(mode==='separate')return {mix_grades:false,mix_groups:[]};if(mode==='all'){if(grades.length<2)throw Error('请先设置至少两个年级，再混排。');return {mix_grades:true,mix_groups:[]};}const groups=mode==='pair'?[gradePairs(grades)[Number($('mixPair').value)]||[]]:readCustomMix();if(!groups.length)throw Error('请添加混排组并选择年级。');return {mix_grades:true,mix_groups:validateMixGroups(groups,grades)};}
function updateMixSummary(){try{const scope=mixScope(formalGrades(view.plan),readMixControls());$('mixScopeSummary').textContent='混排：'+(scope.groups.map(g=>g.join(' ＋ ')).join('；')||'无')+'。独立编排：'+(scope.independent.join('、')||'无')+'。';}catch(e){$('mixScopeSummary').textContent=e.message}}
function syncLayoutControls(){const room=view.plan.rooms.find(x=>x.id===$('previewRoom').value);if(room){$('seatDirection').value=room.direction||'horizontal';$('seatOrder').value=room.order||'straight';}}
function collectSeatSettings(q){Object.assign(q.settings,{mode:$('mode').value,seed:Number($('seed').value)||0,...readMixControls(),score_field:$('scoreField').value==='score'?'':$('scoreField').value});const current=q.rooms.find(r=>r.id===$('previewRoom').value);if(current&&(current.direction!==$('seatDirection').value||current.order!==$('seatOrder').value)){for(const r of q.rooms)if($('layoutScope').value==='all'||r.id===current.id){r.direction=$('seatDirection').value;r.order=$('seatOrder').value;}}return q;}
async function applySeatLayout(){
  const q=clone(view.plan),all=$('layoutScope').value==='all',rid=$('previewRoom').value;
  if(!q.rooms.length)throw Error('请先添加考场。');
  collectSeatSettings(q);
  for(const room of q.rooms)if(all||room.id===rid){room.direction=$('seatDirection').value;room.order=$('seatOrder').value;}
  await save(q);toast('座号方向已应用，请复核座位预览和已有编排。');
}
if(typeof module!=='undefined')module.exports={parseClock,shiftClock,mixPreset,formalGrades,normalizeGrades,gradePairs,validateMixGroups,mixScope};
