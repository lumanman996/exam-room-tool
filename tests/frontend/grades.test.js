'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {formalGrades,normalizeGrades,gradePairs,validateMixGroups,mixScope}=require('../../exam_room/ui/controls.js');
test('formal grades remain available without students and never grow from imported records',()=>{
  assert.deepEqual(formalGrades({grades:['实验七','实验八','实验九'],students:[]}),['实验七','实验八','实验九']);
  assert.deepEqual(formalGrades({grades:[],students:[{grade:'七年级'}]}),[]);
});
test('grade aliases normalize in user order and reject blank or duplicate names',()=>{
  assert.deepEqual(normalizeGrades([' 实验九 ','初一','8.0']),['实验九','七年级','八年级']);
  assert.throws(()=>normalizeGrades(['七','初一']),/重复/);assert.throws(()=>normalizeGrades(['']),/名称/);
});
test('pair choices include configured grades with no imported students',()=>{
  assert.deepEqual(gradePairs(['甲','乙','丙']),[['甲','乙'],['甲','丙'],['乙','丙']]);
});
test('mix groups reject unknown, repeated, overlapping and singleton grades',()=>{
  for(const groups of [[['甲','丁']],[['甲','甲']],[['甲','乙'],['乙','丙']],[['甲']]])assert.throws(()=>validateMixGroups(groups,['甲','乙','丙']));
  assert.deepEqual(validateMixGroups([['甲','乙']],['甲','乙','丙']),[['甲','乙']]);
});
test('scope distinguishes mixed groups from configured independent grades',()=>{
  assert.deepEqual(mixScope(['甲','乙','丙'],{mix_grades:true,mix_groups:[['甲','乙']]}),{groups:[['甲','乙']],independent:['丙']});
  assert.deepEqual(mixScope(['甲','乙','丙'],{mix_grades:true,mix_groups:[]}),{groups:[['甲','乙','丙']],independent:[]});
});
