#!/usr/bin/env python3
# Agent Town 策划案 → 飞书 wiki 同步器（可重复运行）
# 流程：清旧节点（可选）→ 带标题建节点 → 填入转换后内容 → 刷新首页文档地图 → 验证
# 转换：剥 YAML frontmatter、抹本地路径、文件引用改 cite。config CSV 与脚本不上传。

import json, os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP_PATH = Path(__file__).resolve().parent / "feishu_token_map.json"
SPACE_ID = "7677092872562150361"
HOME_NODE = "NB2GwaUYniIaQCklaYScpirYntl"
HOME_OBJ = "HzhbdqomdonpVwxTMNLcjQjGnxh"

PAGES = [
    ("01-世界总览.md", "01 世界总览"),
    ("02-时间与空间.md", "02 时间与空间"),
    ("03-资源需求与工作.md", "03 资源需求与工作"),
    ("04-交易契约与声誉.md", "04 交易契约与声誉"),
    ("05-建设.md", "05 建设"),
    ("06-社交与情报.md", "06 社交与情报"),
    ("07-治理与公共空间.md", "07 治理与公共空间"),
    ("08-季节与事件.md", "08 季节与事件"),
    ("09-agent行为集与生命周期.md", "09 agent 行为集与生命周期"),
    ("10-接入接口协议.md", "10 接入接口协议"),
    ("11-镇内机制.md", "11 镇内机制"),
    ("12-配置与演化.md", "12 配置与演化"),
    ("CHANGELOG.md", "变更说明"),
    ("sim/校验报告.md", "数值校验报告"),
]

TABLES = ["世界参数表", "建筑配置表", "岗位产出表", "NPC配置表", "动作前置表", "特质效果表"]
ENV = os.environ.copy(); ENV["LARK_CLI_NO_PROXY"] = "1"

def run(args, timeout=90):
    r = subprocess.run(["lark-cli"] + args, capture_output=True, text=True, timeout=timeout, env=ENV)
    return r

def jparse(out):
    i = out.find("{")
    return json.loads(out[i:]) if i >= 0 else {}

def transform(text, title=None):
    text = re.sub(r"\A---\n.*?\n---\n+", "", text, flags=re.S)      # 剥 frontmatter
    for t in TABLES:
        text = text.replace(f"config/{t}.csv", f"《{t}》")
    text = text.replace("config/ 下 6 张 CSV", "6 张配置表")
    text = text.replace("config/ 下的 CSV 配置表", "六张配置表（GM 侧 CSV 维护）")
    text = text.replace("config/ 六张 CSV 文件", "六张配置表").replace("config/ 六张 CSV", "六张配置表（GM 侧维护）")
    text = re.sub(r"config/[\w一-鿿/]*?([\w一-鿿]+表)\.csv", r"《\1》", text)
    text = text.replace("sim/校验报告.md", "《数值校验报告》").replace("sim/校验报告", "《数值校验报告》")
    text = text.replace("sim/经济模拟.py", "经济模拟脚本").replace("sim/校验脚本.py", "文档自审脚本")
    text = re.sub(r"~/vault/Projects/agent-town/?", "项目目录", text)
    # 通用清理：本地文件名引用去 .md（CHANGELOG 指到「变更说明」）、残余 config/ 目录提及抹除
    text = re.sub(r"([\w一-鿿-]{2,})\.md\b", lambda m: "变更说明" if m.group(1) == "CHANGELOG" else m.group(1), text)
    text = text.replace("加载 config/ 配置", "加载配置")
    text = re.sub(r"config/\s*", "", text)
    if title:
        lines = text.split("\n")
        if lines and lines[0].startswith("# "):
            lines[0] = f"# {title}"
        text = "\n".join(lines)
    return text

def step_clean_legacy():
    r = run(["wiki", "nodes", "list", "--params",
             json.dumps({"space_id": SPACE_ID, "parent_node_token": HOME_NODE}), "--page-all", "--format", "json"])
    items = jparse(r.stdout).get("data", {}).get("items", [])
    for it in items:
        if it["title"] == "Untitled":
            rd = run(["wiki", "+node-delete", "--node-token", it["node_token"], "--obj-type", "wiki", "--yes"])
            print("删除旧节点", it["node_token"], '"task_id"' in rd.stdout or '"ok": true' in rd.stdout)

def step_create_and_fill():
    # 先查现有子节点：有标题则更新（幂等），无则带标题创建
    r = run(["wiki", "nodes", "list", "--params",
             json.dumps({"space_id": SPACE_ID, "parent_node_token": HOME_NODE}), "--page-all", "--format", "json"])
    existing = {it["title"]: it for it in jparse(r.stdout).get("data", {}).get("items", [])}
    token_map = {}
    for fname, title in PAGES:
        body = transform((ROOT / fname).read_text(encoding="utf-8"), title)
        if title in existing:
            obj = existing[title]["obj_token"]; ntok = existing[title]["node_token"]
        else:
            rc = run(["wiki", "+node-create", "--space-id", SPACE_ID,
                      "--parent-node-token", HOME_NODE, "--title", title, "--obj-type", "docx"])
            nd = jparse(rc.stdout).get("data", {})
            node = nd.get("node", nd)
            obj = node.get("obj_token"); ntok = node.get("node_token")
            if not obj:
                print(f"[FAIL 建节点] {title}: {rc.stdout[:250]}"); continue
        ru = run(["docs", "+update", "--doc", obj, "--command", "overwrite",
                  "--doc-format", "markdown", "--content", body], timeout=150)
        ok = '"ok": true' in ru.stdout or '"code": 0' in ru.stdout
        token_map[title] = {"node_token": ntok, "obj_token": obj}
        print(("同步 OK  " if ok else f"[FAIL 填内容] {ru.stdout[:200]}"), title)
    MAP_PATH.write_text(json.dumps(token_map, ensure_ascii=False, indent=2), encoding="utf-8")
    return token_map

def step_home(token_map):
    def cite(t):
        return f'<cite doc-id="{token_map[t]["obj_token"]}" file-type="wiki" title="{t}" type="doc"></cite>'
    body = (ROOT / "README.md").read_text(encoding="utf-8")
    body = re.sub(r"\A---\n.*?\n---\n+", "", body, flags=re.S)
    # 先把文档地图里的本地文件名换成占位（此时 .md 还在），再通用转换，最后展开 cite
    for fname, title in PAGES:
        if title in token_map:
            body = body.replace(fname, f"__CITE__{title}__END__")
    body = transform(body)  # 不换 H1，首页保留「Agent 小镇 策划案」
    for title in token_map:
        body = body.replace(f"__CITE__{title}__END__", cite(title))
    body = body.replace("六张配置表（GM 侧维护）", "六张配置表（GM 侧 CSV 维护）")
    ru = run(["docs", "+update", "--doc", HOME_OBJ, "--command", "overwrite",
              "--doc-format", "markdown", "--content", body], timeout=150)
    print("首页:", "OK" if ('"ok": true' in ru.stdout or '"code": 0' in ru.stdout) else ru.stdout[:300])

def step_verify(token_map):
    r = run(["wiki", "nodes", "list", "--params",
             json.dumps({"space_id": SPACE_ID, "parent_node_token": HOME_NODE}), "--page-all", "--format", "json"])
    items = jparse(r.stdout).get("data", {}).get("items", [])
    print(f"\n== 验证：子节点 {len(items)} 个（期望 14）==")
    bad = 0
    for title, tk in token_map.items():
        rf = run(["docs", "+fetch", "--doc", tk["obj_token"], "--doc-format", "markdown", "--format", "json"])
        doc = jparse(rf.stdout).get("data", {}).get("document", {})
        content = doc.get("content", "")
        issues = []
        if "Untitled" in content[:80]: issues.append("标题")
        if re.search(r"^title: ", content, re.M): issues.append("frontmatter残留")
        if "config/" in content or ".md" in content: issues.append("本地引用残留")
        if f"# {title}" not in content[:120]: issues.append("H1")
        if issues:
            bad += 1
            print(f"  ✗ {title}: {issues}")
    print(f"内容校验异常: {bad}")
    print("\n== 树结构 ==")
    for it in items:
        print(" ", it["title"], "→", it["url"])

if __name__ == "__main__":
    if "--keep" not in sys.argv:
        step_clean_legacy()
    tm = step_create_and_fill()
    step_home(tm)
    step_verify(tm)
