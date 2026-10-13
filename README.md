# 考场编排

面向初中教务人员的本机考试考场编排工具，覆盖资料导入、日程、座位、监考、检查、保存和材料导出。

## 正式命名

| 项目 | 名称 |
|---|---|
| 中文产品名 | 考场编排 |
| 英文项目名 | exam-room-tool |

当前开发版本为 1.2.0，进度见 [交付状态](docs/交付状态.md)，重要决定见 [决策记录](docs/决策记录.md)，Windows 实机测试安排见 [实机测试清单](docs/Windows实机测试清单.md)。已经实现的本机开发版基础能力：

- Python 3.12 + pywebview 桌面入口，本机 HTTP 服务只监听 `127.0.0.1`。
- 新建考试第一步填写年级数量和名称；导入、年级混排、考号和打印范围都使用本次考试的年级清单。自定义混排组可具名保存并再次选择。
- `.xlsx` / `.csv` 资料预检和导入，四类资料模板，以及缺失考号生成。
- 日程自动安排、按成绩 / 随机 / 班级交叉 / 已有考号编排；四种座号路线、年级混排、座位和监考约束检查。
- 方案 JSON 原子保存、备份、复制、可恢复删除、随机种子和编排调整记录。
- 16 类 Excel、可打印 HTML 和 PDF 材料；版式可保存，后台导出固定方案快照，正式材料按其关联检查阶段放行。
- 明暗主题跟随系统、可增减字号、资料搜索分页、人工调整及未保存编辑保护。
- 独立试用和激活模块、更新检查接口、Windows / Mac PyInstaller 构建脚本。

文档：[数据协议](docs/数据协议.md)、[使用手册](docs/使用手册.md)、[发布流程](docs/发布流程.md)、[设计说明](docs/设计/)。

开发衔接：[前后端接口约定](docs/前后端接口约定.md)。

自动验测台已实现：[测试方案](docs/验测台测试方案.md)、[36 个虚构测试场景与使用说明](testkit/README.md)。使用隔离目录实际运行接口、页面、保存重开、导出核对和规模编排；结果与未运行范围记录在每次独立报告中（`output/testbench/`）。

## 本地运行

```bash
uv venv --python 3.12 .venv
uv pip install -r requirements-dev.txt --python .venv/bin/python
.venv/bin/python -m exam_room --selftest
.venv/bin/python -m exam_room
```

首次使用可以在首页点击“用虚构示例试一试”。新建自己的考试时，先设本次考试的年级，再录入资料；导入表格不会自动增减年级。真实资料和生成的方案保存在本机数据目录；测试和示例均使用虚构数据。

## 源码测试

```bash
.venv/bin/python -m pytest -q
.venv/bin/python tools/run_testbench.py --mode quick
.venv/bin/python tools/run_testbench.py --mode full
```

`quick` 运行资料准备、Python 和前端单元回归及 HTTP 场景；`full` 再运行真实浏览器流程及 1,500 人规模编排。报告位于 `output/testbench/<运行编号>/`；失败、环境阻塞或执行期间代码变化不能放行。准备检查可单独运行：`.venv/bin/python tools/prepare_testkit.py --verify-only`。

## 最终构建

功能改进先在源码环境测试，前后端完整流程调试清楚后才统一构建；开发过程中不反复打包。原生窗口、系统打印及安装包需各平台分别验证。

构建使用许可管理员提供的本产品公钥配置，沿用既有密钥。真实资料、签发私钥和真实许可不进入仓库。正式包编译本产品许可验证模块，并在包内自检核实实际加载结果。

```bash
.venv/bin/python packaging/build.py
.venv/bin/python packaging/smoke_test.py --frozen
```

构建结果位于 `dist/`，会按当前平台生成 `exam-room-tool-Mac.zip` 或 `exam-room-tool-Windows.zip`。

## 参考项目

- 匀班 · 学生均衡分班：[lumanman996/class-assignment-tool](https://github.com/lumanman996/class-assignment-tool)。
- 分寸 · 成绩核算：[lumanman996/chengji-tool](https://github.com/lumanman996/chengji-tool)。

参考它们的教师使用流程、Excel 导入导出、方案或历史记录、桌面打包与测试做法。
考场编排的参试名单、考场容量和座位规则需要独立设计。
