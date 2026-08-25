#!/usr/bin/env python3
# 第二遍：刷新首页（文档地图 + cite 链接），并更新 token 映射
import json, os, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP_PATH = Path(__file__).resolve().parent / "feishu_token_map.json"
SPACE_ID = "7677092872562150361"
HOME_NODE = "NB2GwaUYniIaQCklaYScpirYntl"
HOME_OBJ = "HzhbdqomdonpVwxTMNLcjQjGnxh"

ENV = os.environ.copy()
ENV["LARK_CLI_NO_PROXY"] = "1"

def run(args, timeout=60):
    return subprocess.run(["lark-cli"] + args, capture_output=True, text=True, timeout=timeout, env=ENV)

# 1. 拉取首页下子节点，补全 obj_token 映射
r = run(["wiki", "nodes", "list", "--params",
         json.dumps({"space_id": SPACE_ID, "parent_node_token": HOME_NODE}), "--page-all", "--format", "json"])
data = json.loads(r.stdout[r.stdout.index("{"):])
items = data["data"]["items"]
token_map = json.loads(MAP_PATH.read_text(encoding="utf-8")) if MAP_PATH.exists() else {}
for it in items:
    title = it["title"]
    token_map.setdefault(title, {})
    token_map[title].update({"node_token": it["node_token"], "obj_token": it["obj_token"], "url": it["url"]})
MAP_PATH.write_text(json.dumps(token_map, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"子节点 {len(items)} 个")
for it in items:
    print(" -", it["title"], it["obj_token"])

def cite(title):
    obj = token_map[title]["obj_token"]
    return f'<cite doc-id="{obj}" file-type="wiki" title="{title}" type="doc"></cite>'

# 2. 首页内容（README 的纯飞书版，文档地图改 cite）
home = f"""# Agent 小镇 策划案

版本：v0.10（时间制重做稿）
日期：2026-08-23
读者：世界开发者、agent 接入开发者（朋友们）
基线：v0.9a → v0.10 全部改动见 {cite("v0.10 变更说明")}

## 标记约定

- 【二期】= 不在一期范围。本文档不设【待定】标记——全部数值集中于六张配置表（《世界参数表》《建筑配置表》《岗位产出表》《NPC配置表》《动作前置表》《特质效果表》，GM 侧 CSV 维护），正文一律以「见《表名》配置项」引用。
- 配置热更新规则见 {cite("12 配置与演化")} 第 6 章。
- 各文档正文中的数值均为当前配置值快照，仅供阅读；与配置表不一致时以配置表为准。
- 本策划案只写规则与已拍板的决定。设计理由保留在配置表说明列与变更说明中。

## 文档地图

| 你想了解什么 | 阅读哪个文档 |
|---|---|
| 世界是什么、初始有什么 | {cite("01 世界总览")}（第 1 章） |
| tick/日结/调速、地图与移动 | {cite("02 时间与空间")}（2.1–2.2） |
| 资源、食物损耗、需求系统、工作产出 | {cite("03 资源需求与工作")}（2.3–2.5） |
| 市集、私交易、委托单、雇佣、借贷、声誉 | {cite("04 交易契约与声誉")}（2.6、2.9–2.11） |
| 建筑、项目、认筹、属主资产、图纸 | {cite("05 建设")}（2.7） |
| 对话、关系值、情报分享 | {cite("06 社交与情报")}（2.8） |
| 公告栏、镇规执法、镇长竞选、公投 | {cite("07 治理与公共空间")}（2.12） |
| 季节与随机事件 | {cite("08 季节与事件")}（2.13） |
| 动作清单、时间预算、感知、生命周期、NPC | {cite("09 agent 行为集与生命周期")}（第 3 章） |
| 端点、字段规格、推/拉模式 | {cite("10 接入接口协议")}（第 4 章） |
| 日志、镇报、统计、GM 工具、镇志 | {cite("11 镇内机制")}（第 5 章） |
| 配置热更新、演化路径、版本边界与兼容说明 | {cite("12 配置与演化")}（第 6–7 章） |
| 改动历史与理由 | {cite("v0.10 变更说明")} |
| 数值推算与平衡校验 | {cite("数值校验报告")} |
| 全部数值 | 六张配置表（GM 侧维护，见 12 第 6 章） |

## 版本记录

| 时间 | 修改内容 |
|---|---|
| 2026-08-22 | v0.9a 涌现提频稿（AP 系统、条件委托、情报分享、契约条款、声望等级、季节事件） |
| 2026-08-23 | v0.10 时间制重做稿：AP 制改时间预算制；修复 6 项 P0；新增 Sybil 限制/镇志/关系摘要/情报与担保确认子动作；初始数值定稿（加压基调）。详见变更说明 |
"""

r2 = run(["docs", "+update", "--doc", HOME_OBJ, "--command", "overwrite",
          "--doc-format", "markdown", "--content", home], timeout=120)
ok = '"ok": true' in r2.stdout or '"code": 0' in r2.stdout
print("首页更新:", "OK" if ok else f"FAIL {r2.stdout[:300]}{r2.stderr[:200]}")
