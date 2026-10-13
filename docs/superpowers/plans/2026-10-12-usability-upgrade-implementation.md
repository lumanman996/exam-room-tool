# 批量操作、恢复与流程升级实现计划

> 面向AI工作者：按executing-plans串行执行；用户已批准整体设计和继续完成任务。复选框记录交接与实际证据；不再重复询问执行方式。本次复用原有三个对话及共享checkout，严格按文件归属串行交接，不复制未提交改动到新worktree。

**目标：** 完成本次13项已批准需求，完整验证后交付新Windows试用包并等待实机反馈。

**架构：** 服务负责事务化批量变更、持久撤销和统一布局/时长检查，前端负责草稿与操作流程；同一座位模型供检查与报表使用。旧方案缺省字段兼容，产品许可保持独立。

**技术栈：** Python3.12、pywebview、HTML/CSS/JS、pytest、Node、Playwright、Windows Actions与PyInstaller。

## 文件归属与执行顺序

后端单一负责exam_room/*.py、新增领域模块、packaging/*、requirements及对应Python单测、数据协议/接口约定；前端负责exam_room/ui/*、对应Node测试、使用手册；测试负责独立HTTP/真实页面/完整流程验测工具及测试进展；总协调负责本计划、交付/协调记录、版本整合与Git/Windows流水线。后端全部接口冻结后再启动前端；界面冻结后启动独立测试。发现局部问题只解冻其负责人。

## 任务1：持久撤销和恢复契约（后端）

文件：新exam_room/transactions.py、tests/test_edit_history.py；修改model.py、server.py、changes.py、storage.py（仅必要关联）、数据协议。

- [x] 编写真实App/Store失败保护，覆盖普通资料修改、批量删除、保存重开后的撤销，版本不回退及失败不写盘。
```python
before=deepcopy(app.plan)
q=deepcopy(before);q['rooms'][0]['name']='虚构新教室'
app.api_save({'plan':q,'revision':before['revision']})
app.api_edit_undo({'revision':app.plan['revision']})
assert app.plan['rooms']==before['rooms']
assert app.plan['revision']>before['revision']
```
- [x] 实际运行 `.venv/bin/python -m pytest -q tests/test_edit_history.py`，保存预期失败；实现最近50步精简事务、提交标签与view撤销摘要。不记录许可、临时下载或导出文件；对旧任务与过期revision拒绝。
- [x] 全局撤销整笔恢复实体、关联、布局、号码来源和待复核状态；兼容旧座位/监考/号码撤销，不让旧快照越过不同资料变化。复测并冻结接口契约。

## 任务2：年级、考场及设置批量操作（后端）

文件：新exam_room/bulk.py、tests/test_bulk_operations.py；修改rooms.py、model.py、server.py、changes.py、接口约定。

- [x] 失败用例覆盖删除被引用年级、重复编号、批量中一条坏布局、删除已用考场、预览后版本变化、撤销和重开。
```python
rev=app.plan['revision'];old=deepcopy(app.plan)
with pytest.raises(ValueError):
    app.api_bulk_preview({'kind':'grades','action':'delete','ids':['七年级']})
assert app.plan==old and app.plan['revision']==rev
```
- [x] 运行 `.venv/bin/python -m pytest -q tests/test_bulk_operations.py` 确认缺失功能失败；实现bulk_preview/bulk_apply、参数默认复位和直接传入模板布局的room_batch。每次confirm服务端重新检查与原子保存，明确影响和必要确认参数。
- [x] 未使用年级可多选删除；被引用年级提供具体关联信息。已用考场删除/缩小显示学生与监考影响，不静默重排；编号01～99、布局最多99座维持。复测相关rooms/changes/存储测试，记录API与失败证据。

## 任务3：科目目录、批量科目及分钟时长（后端）

文件：新exam_room/subjects.py、tests/test_subject_catalog.py；修改model.py、importer.py、server.py、engine.py（时长入口）、接口约定。

- [x] 失败保护包括预设保存、手动新科目、年级×科目批量预览、重复提示、预设变更不追溯已有日程、负/零时长、起止与导入时长不一致。
```python
q=deepcopy(app.plan);e=q['exams'][0]
e.update(start='08:20',end='09:55',duration=90)
app.api_save({'plan':q,'revision':q['revision']})
assert app.plan['exams'][0]['duration']==95
```
- [x] `.venv/bin/python -m pytest -q tests/test_subject_catalog.py` 先红后绿；目录与本次科目分开持久化。起止完整时统一差值，空时间保留计划分钟供求解；导入冲突预检明确提示处理，不让不同入口绕过。
- [x] 复测导入、日程、检查和旧方案兼容，冻结subject目录及批量API。

## 任务4：自定义座号模型、迁移与报表（后端）

文件：新exam_room/seat_labels.py、tests/test_seat_labels.py；修改engine.py、model.py、rooms.py、changes.py、numbering.py、report.py及打印调用（仅统一布局相关）。

- [x] 先用虚构三学生、不同单科映射和锁定位置保护：交换标签后row/col上的学生不变，标签唯一；停用/容量外目标拒绝；考号待复核；导出使用真实新标签；重开/撤销一致。
```python
def physical_positions(plan):
    lookup={r['id']:{x['seat']:(x['row'],x['col']) for x in engine.seat_layout(r)} for r in plan['rooms']}
    return {scope:{sid:(a['room_id'],*lookup[a['room_id']][a['seat']]) for sid,a in mapping.items()}
            for scope,mapping in plan['seats'].items()}
before=physical_positions(app.plan)
preview=app.api_seat_labels_preview({'room_id':'r0','first':1,'second':2})
app.api_seat_labels_apply({'room_id':'r0','first':1,'second':2,'revision':preview['revision']})
assert physical_positions(app.plan)==before
```
- [x] `.venv/bin/python -m pytest -q tests/test_seat_labels.py` 先红后绿；物理位置与标签独立，同一seat_layout生成座位图、编排、检查和材料。单次交换/恢复默认更新该教室所有科目映射，锁定物理位置保持；人工考号不覆盖。
- [x] 行列形状变化明确处理自定义映射；复测座位、编号、检查与实际Excel读取。前端拖学生复用已有adjust_seat硬规则，不新增并行求解规则。

## 任务5：许可保护与Windows构建支持（后端）

文件：licensing.py、必要新许可实现/公开包装、packaging/compile_license.py、build.py、smoke_test.py、requirements、对应test_license/test_packaging；只读参考两产品当前license包装和compile_license，不读取签发私钥或真实许可。

- [x] 先保护虚构密钥下试用/到期/产品不匹配/模块损坏/旧许可兼容；正式包缺失模块不能变开发无限制，仍可查看与保存。
- [x] 实现产品独立许可验证模块的编译与包内验证，保留既有公钥和联系配置。针对性源码/模拟构建测试；不提前构建Mac或Windows候选。
- [x] 运行 `.venv/bin/python -m pytest -q tests/test_license.py tests/test_packaging.py` 及新增相关保护，交接5任务全部核心接口和指纹；不自行推送、触发CI或追加full。

## 任务6：草稿恢复、批量资料和参数复位（前端，接口冻结后）

文件：新ui/editing.js与tests/frontend/editing.test.js；修改workspace.js、controls.js、rooms.js、app.js、index.html、style.css。

- [x] Node失败保护真实草稿操作历史、恢复最近保存、另页已保存不回退、失败保留输入、表格选择及预览过期失效。
```javascript
const draft = Editing.start({name:'虚构原名'});
draft.set('name','虚构新名');draft.undo();
assert.equal(draft.value.name,'虚构原名');
```
- [x] `node --test tests/frontend/editing.test.js` 先红后绿；接入明确“撤销上一步/恢复上次保存”、每组默认、添加年级、勾选/全选、删除所选、考场批量预览与修改。基础资料显露行列控件；草稿与服务提交分别处理。
- [x] 运行对应前端测试与真实页面专项后交接，不触发全量或构建。

## 任务7：科目目录与顺序引导（前端）

文件：controls.js、workspace.js、index.html、style.css；新增tests/frontend/subjects.test.js、必要navigation.test.js。

- [x] 先保护名称手写与选择、目录编辑不改旧场次、批量预览去重、实时分钟显示、未保存标记、上一项失败不导航。
- [x] Node红绿实现科目组合输入/预设维护/批量添加，保存并继续与上一步；资料未齐时明确定位原因。阴影/浮起/靛蓝选中标签、文字标记、小屏与键盘焦点。
- [x] 测试命令 `node --test tests/frontend/subjects.test.js tests/frontend/navigation.test.js`；真实页面保持草稿与滚动，记录结果。

## 任务8：两种拖动、检查返回与帮助激活（前端）

文件：新ui/dragging.js及对应Node测试；workspace.js、app.js、index.html、style.css、controls.js、使用手册。

- [x] 红绿保护学生移动与交换、标签交换模式隔离、锁定/停用拒绝、模糊时段不拖动、撤销、考号待复核、检查原上下文返回。
- [x] 实现pointer拖动及键盘/点选替代；调用统一服务预览/confirm，不只改DOM标签。检查按同类根因合并并定位具体对象，返回时再验证。
- [x] 激活分步骤/复制机器码/联系作者、分类帮助与可点击解释；不读取真实许可，不新增公开发布与更新替换功能。运行相关Node及真实页面测试，冻结UI与手册指纹。

## 任务9：独立验收与完整回归（测试，前后端冻结后）

文件：新tests/test_usability_acceptance.py、tools/testbench/usability_browser.py；必要run_testbench/浏览器入口/场景登记。

- [x] 独立真实HTTP/Store验证批量失败字节不变、历史重开、物理位置和单科标签、导出Excel/PDF一致、许可边界；实际页面覆盖13项清单、两个拖动模式、上一步/继续、恢复和检查返回。
- [x] 新增用例保留首失败及修复复测；原虚构夹具与inventory不改；报告区分源码与可见原生实机范围。
- [x] 针对性通过后运行 `.venv/bin/python tools/run_testbench.py --mode full`，检查终态、各阶段exit0、源码前后指纹、独立实际材料。不要借旧61项报告放行新业务。

## 任务10：整合与Windows一次交付（总协调）

文件：VERSION、README、交付状态/协调/验收记录、开始使用/实机清单；现有私有仓库workflow。

- [x] 每次交接审核diff与证据、明确文件提交，不覆盖其他对话改动。版本1.1.0、方案version1兼容。
- [x] 完整回归通过后推送已授权私有仓库，Windows完整流程、新原生专项、构建及冻结自检；本轮业务变化禁止复用旧1.0.2完整报告。
- [x] 下载核验ZIP、真实x64程序、公钥/编译许可模块、每文件SHA、空白模板与虚构示例，交付用户Windows实机。失败只定位对应负责人，修复复测；成功后暂停所有追加工作，等待反馈。


2026-10-13最终源码证据：`output/testbench/20261013-131758-cb1d63/report.json`，6阶段exit0、74报告项通过，Python327/Node50、HTTP42、页面26组、规模2组。156文件运行前后及总协调审核当前均一致；批准13项新增页面全部覆盖。独立审核`output/usability-coordinator/source-full-audit.json`；Windows/冻结包/可见实机仍需本轮新证据。


Windows最终交付证据：38352889596、提交3c809ed，74项新full/14项源码隐藏原生通过；真正编译及冻包实际自检成功，1064包内文件SHA核验通过。`dist/exam-room-tool-Windows-1.1.0.zip`及新版清单/验收说明已保存。原首失败Windows73/1及解析修正/7反例保留；用户实机/纸面打印尚未验收。全部授权开发与Windows交付任务完成，停止追加工作等待反馈。
