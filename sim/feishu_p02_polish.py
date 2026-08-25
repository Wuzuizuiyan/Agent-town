#!/usr/bin/env python3
# Agent Town 飞书侧 P02 格式适配（只改飞书，不改本地文件）
# ① 单 H1（多余 H1 降级）② 顶部插入三列版本记录（修改人=用户 cite）③ 跨文档引用 → cite
# 首页（文档地图）整体重建：README 内容 + cite 文档地图 + P02 版本记录（沿用用户行原文）。

import json, os, re, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP = json.loads((Path(__file__).resolve().parent / "feishu_token_map.json").read_text(encoding="utf-8"))
HOME_OBJ = "HzhbdqomdonpVwxTMNLcjQjGnxh"
U = '<cite type="user" user-id="ou_2a83209ba79564677b66c8dfbcece03c" user-name="曾政"></cite>'
ENV = os.environ.copy(); ENV["LARK_CLI_NO_PROXY"] = "1"

STEMS = ["01-世界总览", "02-时间与空间", "03-资源需求与工作", "04-交易契约与声誉",
         "05-建设", "06-社交与情报", "07-治理与公共空间", "08-季节与事件",
         "09-agent行为集与生命周期", "10-接入接口协议", "11-镇内机制", "12-配置与演化"]
TITLE_OF = {s: t for s, (_, t) in zip(STEMS, [p for p in [
    ("01", "01 世界总览"), ("02", "02 时间与空间"), ("03", "03 资源需求与工作"),
    ("04", "04 交易契约与声誉"), ("05", "05 建设"), ("06", "06 社交与情报"),
    ("07", "07 治理与公共空间"), ("08", "08 季节与事件"), ("09", "09 agent 行为集与生命周期"),
    ("10", "10 接入接口协议"), ("11", "11 镇内机制"), ("12", "12 配置与演化")]])}

def run(args, timeout=90):
    return subprocess.run(["lark-cli"] + args, capture_output=True, text=True, timeout=timeout, env=ENV)

def jparse(out):
    i = out.find("{");  return json.loads(out[i:]) if i >= 0 else {}

def fetch(obj):
    r = run(["docs", "+fetch", "--doc", obj, "--doc-format", "markdown", "--format", "json"])
    c = jparse(r.stdout).get("data", {}).get("document", {}).get("content", "")
    return re.sub(r"\A<title>.*?</title>\n*", "", c, flags=re.S)  # 剥掉 fetch 的标题元数据行，防回传成正文

def overwrite(obj, body):
    r = run(["docs", "+update", "--doc", obj, "--command", "overwrite",
             "--doc-format", "markdown", "--content", body], timeout=150)
    return '"ok": true' in r.stdout or '"code": 0' in r.stdout

def cite_doc(title):
    return f'<cite doc-id="{MAP[title]["obj_token"]}" file-type="wiki" title="{title}" type="doc"></cite>'

VERSION_TABLE = f"""## 版本记录

| 时间 | 修改内容 | 修改人 |
|---|---|---|
| 8.22 | v0.9a 涌现提频稿（原始单文档） | {U} |
| 8.23 | v0.10 时间制重做落地 | {U} |
| 8.23 | v0.11 悬赏任务 / v0.12 NPC 态度（详见变更说明） | {U} |
| 8.23 | 拆分多文档并上传飞书，P02 格式适配 | {U} |
"""

def polish(body):
    # ① 单 H1：首个 H1 之外的 # 降为 ##
    lines = body.split("\n")
    first_h1 = next(i for i, l in enumerate(lines) if l.startswith("# "))
    for i in range(first_h1 + 1, len(lines)):
        if lines[i].startswith("# "):
            lines[i] = "#" + lines[i]
    body = "\n".join(lines)
    # ② 版本记录：缺失则在首个 ## 节前插入
    if "## 版本记录" not in body:
        m = re.search(r"^## ", body, re.M)
        body = body[:m.start()] + VERSION_TABLE + "\n" + body[m.start():] if m else body + "\n" + VERSION_TABLE
    # ③ 跨文档引用 → cite（dash 词干形态只在文本引用中出现，cite 标题为空格形态，安全）
    for stem in STEMS:
        body = body.replace(stem, cite_doc(TITLE_OF[stem]))
    return body

def rebuild_home():
    body = (ROOT / "README.md").read_text(encoding="utf-8")
    body = re.sub(r"\A---\n.*?\n---\n+", "", body, flags=re.S)
    # 文档地图文件名 → cite 占位（在通用转换之前）
    for fname, title in [("01-世界总览.md", "01 世界总览"), ("02-时间与空间.md", "02 时间与空间"),
                         ("03-资源需求与工作.md", "03 资源需求与工作"), ("04-交易契约与声誉.md", "04 交易契约与声誉"),
                         ("05-建设.md", "05 建设"), ("06-社交与情报.md", "06 社交与情报"),
                         ("07-治理与公共空间.md", "07 治理与公共空间"), ("08-季节与事件.md", "08 季节与事件"),
                         ("09-agent行为集与生命周期.md", "09 agent 行为集与生命周期"), ("10-接入接口协议.md", "10 接入接口协议"),
                         ("11-镇内机制.md", "11 镇内机制"), ("12-配置与演化.md", "12 配置与演化"),
                         ("CHANGELOG.md", "变更说明"), ("sim/校验报告.md", "数值校验报告")]:
        body = body.replace(fname, f"__CITE__{title}__END__")
    # 版本记录换 P02 三列（沿用用户四行原文 + 适配行）
    vr_pat = re.compile(r"## 版本记录\n\n\| 时间 \| 修改内容 \|\n\|---\|---\|\n(.*?)\n(?=\n|\Z)", re.S)
    m = vr_pat.search(body)
    rows = re.findall(r"\| (\d{4}-\d{2}-\d{2}) \| (.*?) \|", m.group(1)) if m else []
    new_vr = "## 版本记录\n\n| 时间 | 修改内容 | 修改人 |\n|---|---|---|\n"
    for d, c in rows:
        new_vr += f"| {d} | {c} | {U} |\n"
    new_vr += f"| 2026-08-23 | 上传飞书并按 P02 格式适配（单 H1、版本记录三列、跨文档引用） | {U} |\n"
    if m:
        body = body[:m.start()] + new_vr + body[m.end():]
    # 通用清理（与上传器同口径）
    for t in ["世界参数表", "建筑配置表", "岗位产出表", "NPC配置表", "动作前置表", "特质效果表"]:
        body = body.replace(f"config/{t}.csv", f"《{t}》")
    body = body.replace("config/ 下的 CSV 配置表", "六张配置表（GM 侧 CSV 维护）")
    body = body.replace("config/ 六张 CSV", "六张配置表（GM 侧 CSV 维护）")
    body = re.sub(r"config/\s*", "", body)
    body = re.sub(r"([\w一-鿿-]{2,})\.md\b", lambda mm: "变更说明" if mm.group(1) == "CHANGELOG" else mm.group(1), body)
    body = body.replace("数值校验报告》", "数值校验报告》")  # 书名号形态保留
    for title in MAP:
        body = body.replace(f"__CITE__{title}__END__", cite_doc(title))
    return body

def main():
    for title, tk in MAP.items():
        body = fetch(tk["obj_token"])
        if not body:
            print(f"[FAIL fetch] {title}"); continue
        new = polish(body)
        ok = overwrite(tk["obj_token"], new)
        h1 = len(re.findall(r"^# ", new, re.M))
        print(("OK  " if ok else "FAIL"), title, f"H1={h1}", "版本记录" in new)
    ok = overwrite(HOME_OBJ, rebuild_home())
    print("首页:", "OK" if ok else "FAIL")

if __name__ == "__main__":
    main()
