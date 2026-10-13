'use strict';
const t=require('node:test'),a=require('node:assert/strict');let E={};try{E=require('../../exam_room/ui/editing.js')}catch{}
t('draft undo restores the last input and detaches external data',()=>{const original={name:'虚构原名',rows:[1]};const d=E.start(original);d.set('name','新名');d.undo();a.equal(d.value.name,'虚构原名');d.value.rows.push(2);a.deepEqual(original.rows,[1]);});
t('restore uses latest saved page without rolling back another page',()=>{const saved={name:'甲',school:'已保存学校'};const d=E.start({name:'甲'});d.set('name','草稿');d.restore({name:saved.name});a.equal(d.value.name,'甲');a.equal(saved.school,'已保存学校');a.equal(d.dirty,false);});
t('failed submit retains all draft values and history',async()=>{const d=E.start({name:'甲'});d.set('name','未提交');await a.rejects(d.submit(async()=>{throw Error('失败')}));a.equal(d.value.name,'未提交');a.equal(d.dirty,true);a.equal(d.canUndo,true);});
t('filter select all never silently selects unrelated entities',()=>{const s=E.selection();s.all(['a','b'],true);s.toggle('b',false);a.deepEqual(s.ids,['a']);s.prune(['b']);a.deepEqual(s.ids,[]);});
t('preview ticket rejects old revision and modified input',()=>{const p=E.previewTicket({ids:['a'],fields:{rows:2}},4);a.equal(p.valid({ids:['a'],fields:{rows:2}},4),true);a.equal(p.valid({ids:['a'],fields:{rows:3}},4),false);a.equal(p.valid({ids:['a'],fields:{rows:2}},5),false);});
t('grade references list students exams and preset groups for precise handling',()=>{a.deepEqual(E.gradeAssociations({students:[{grade:'甲',id:'s'}],exams:[{grade:'甲',id:'e'}],settings:{mix_groups:[['甲','乙']],mix_presets:[{name:'组',groups:[['甲','乙']]}]}} ,'甲').counts,[1,1,1,1]);});
t('committing one draft field preserves undo for another unfinished field',()=>{const d=E.start({first:'旧值',second:'已保存'});d.set('first','本笔提交');d.set('second','未提交');d.rebase(v=>({...v,first:'本笔提交'}));a.equal(d.dirty,true);d.undo();a.deepEqual(d.value,{first:'本笔提交',second:'已保存'});});
t('saved dynamic side-panel fields leave no stale local undo',()=>{
 const base={fields:[{id:'mode',value:'class'}]},latest={fields:[{id:'mode',value:'class'},{id:'adjustSeat',value:'2'},{id:'swapSeat',checked:false}]};
 const d=E.start(base);d.replace({fields:[{id:'mode',value:'class'},{id:'adjustSeat',value:'2'},{id:'swapSeat',checked:true}]});
 d.rebase(old=>({...old,fields:E.commitFieldSubset(old.fields,latest.fields,['adjustSeat','swapSeat'])}));
 a.deepEqual(d.value,latest);a.equal(d.dirty,false);a.equal(d.canUndo,false);
});
t('committing a new side panel retains only another group input history',()=>{
 const base={fields:[{id:'mode',value:'class'}]},latest={fields:[{id:'mode',value:'random'},{id:'adjustSeat',value:'2'},{id:'swapSeat',checked:false}]};
 const d=E.start(base);d.replace({fields:[{id:'mode',value:'random'}]});d.replace({fields:[{id:'mode',value:'random'},{id:'adjustSeat',value:'2'},{id:'swapSeat',checked:true}]});
 d.rebase(old=>({...old,fields:E.commitFieldSubset(old.fields,latest.fields,['adjustSeat','swapSeat'])}));
 a.equal(d.dirty,true);a.equal(d.canUndo,true);d.undo();a.deepEqual(d.value,{fields:[{id:'mode',value:'class'},{id:'adjustSeat',value:'2'},{id:'swapSeat',checked:false}]});a.equal(d.canUndo,false);
});
