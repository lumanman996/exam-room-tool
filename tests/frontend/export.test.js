const test=require('node:test');
const assert=require('node:assert/strict');
const {normalizeLayout, exportRequest, chooseSections,relevantErrors}=require('../../exam_room/ui/export.js');
test('legacy export remains compatible and never sends unsupported layout options',()=>{
  const v={plan:{id:'p',revision:3},capabilities:{}};
  const body=exportRequest(v,'xlsx',['students'],true,{students:{font_size:14}});
  assert.equal(body.draft,true);
  assert.equal(body.layouts,undefined);
  assert.deepEqual(body.sections,['students']);
});
test('layout options preserve text field order and validate numbers without silently shrinking',()=>{
  const layout=normalizeLayout({font_size:14,paper:'A3',orientation:'portrait',columns:2,field_order:['座号','考号','姓名','班级'],column_widths:{考号:40}});
  assert.equal(layout.font_size,14);
  assert.equal(layout.column_widths['考号'],40);
  assert.deepEqual(layout.field_order,['座号','考号','姓名','班级']);
  assert.throws(()=>normalizeLayout({font_size:5}),/字号/);
  assert.throws(()=>normalizeLayout({columns:4}),/栏/);
});
test('export selection allows deliberately clearing all checkboxes and drops unavailable materials',()=>{
  assert.deepEqual(chooseSections({students:'明细',seating:'座次'},[]),[]);
  assert.deepEqual(chooseSections({students:'明细'},['students','room_students']),['students']);
});
test('supported layout export binds to the current plan revision',()=>{
  const v={plan:{id:'p',revision:9},capabilities:{report_layouts:true}};
  const x=exportRequest(v,'pdf',['room_students'],false,{room_students:{font_size:12}});
  assert.equal(x.revision,9);
  assert.equal(x.layouts.room_students.font_size,12);
});

test('selected materials use only their server-declared validation stages',()=>{const schedule={stage:'schedule'},seats={stage:'seats'},monitors={stage:'monitors'};const v={export_stages:{schedule:['data','schedule'],room_students:['data','schedule','seats','numbers']},validation:{stages:{},errors:[schedule,seats,monitors]}};assert.deepEqual(relevantErrors(v,['schedule']),[schedule]);assert.deepEqual(relevantErrors(v,['room_students']),[schedule,seats]);assert.deepEqual(relevantErrors(v,['unknown']),[schedule,seats,monitors]);});
