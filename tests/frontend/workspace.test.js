const test = require('node:test');
const assert = require('node:assert/strict');
const {filterRecords, pageRows, seatContext, occupants, nextStep} = require('../../exam_room/ui/workspace.js');
const plan = {
  grades:['七年级','八年级'],
  students: [
    {id:'s1',name:'林小禾',grade:'七年级',class_name:'七1',number:'000101',subjects:[],original:{备注:'示例'}},
    {id:'s2',name:'林小禾',grade:'七年级',class_name:'七2',number:'000102',subjects:['数学']},
    {id:'s3',name:'周小川',grade:'八年级',class_name:'八1',number:'000201',subjects:[]}
  ],
  exams:[{id:'e1',grade:'七年级',subject:'语文',date:'2026-11-12',start:'08:30',end:'10:00',special_seating:false},{id:'e2',grade:'八年级',subject:'数学',date:'2026-11-12',start:'13:30',end:'15:00',special_seating:true}],
  rooms:[{id:'r1'}],teachers:[],
  seats:{base:{s1:{room_id:'r1',seat:1},s2:{room_id:'r1',seat:2},s3:{room_id:'r1',seat:1}},e1:{s1:{room_id:'r1',seat:3}},e2:{s3:{room_id:'r1',seat:4}}},
  invigilation:{},settings:{},stale:[]
};
test('search keeps namesakes separate and searches visible fields without searching internal IDs',()=>{
  assert.deepEqual(filterRecords(plan.students,'林小禾').map(x=>x.id),['s1','s2']);
  assert.equal(filterRecords(plan.students,'000101').length,1);
  assert.equal(filterRecords(plan.students,'s1').length,0);
  assert.equal(filterRecords(plan.students,'示例').length,1);
  assert.equal(filterRecords(plan.students,'', {grade:'七年级',class_name:'七2'})[0].id,'s2');
});
test('pagination clamps when filtering reduces the page count and never drops source records',()=>{
  const rows=Array.from({length:103},(_,i)=>i);
  assert.deepEqual(pageRows(rows,1,100).rows,[100,101,102]);
  assert.equal(pageRows(rows.slice(0,3),9,100).index,0);
  assert.equal(pageRows([],9,100).pages,1);
  assert.equal(rows.length,103);
});
test('normal subject uses base seats even if an obsolete subject mapping exists',()=>{
  const x=seatContext(plan,'e1');
  assert.deepEqual(x.students.map(s=>s.id),['s1']);
  assert.equal(x.mapping.s1.seat,1);
});
test('special subject uses only its effective seating and correct participants',()=>{
  const x=seatContext(plan,'e2');
  assert.equal(x.mapping.s3.seat,4);
  assert.deepEqual(x.students.map(s=>s.id),['s3']);
});
test('fixed-seat picture filters a selected exam session instead of showing two occupants together',()=>{
  assert.deepEqual(occupants(plan,'base','r1','2026-11-12|08:30|10:00')[1].map(s=>s.id),['s1']);
  assert.deepEqual(occupants(plan,'base','r1','2026-11-12|13:30|15:00')[1].map(s=>s.id),['s3']);
});
test('workflow gives a concrete next action and never equates missing teachers with complete readiness',()=>{
  assert.equal(nextStep({plan:null}).page,'home');
  assert.equal(nextStep({plan,validation:{errors:[],warnings:[]}}).kind,'teachers');
});

test('workflow asks for formal grade scope before interpreting imported students',()=>{
  const next=nextStep({plan:{...plan,grades:[]},validation:{errors:[],warnings:[]}});
  assert.equal(next.grades,true);assert.equal(next.label,'设置本次考试年级');
});
