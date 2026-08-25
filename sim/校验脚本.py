#!/usr/bin/env python3
# Agent 小镇 策划案自审脚本（v0.10）
# 检查：①正文引用的配置项在 CSV 中存在 ②章节引用目标存在 ③错误码在 3.1.2 清单中
# 用法：python3 sim/校验脚本.py

import csv, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MDS = sorted(ROOT.glob("*.md"))
TABLES = {t.stem: t for t in (ROOT / "config").glob("*.csv")}

# 载入 CSV 参数名
rows = {}
for name, path in TABLES.items():
    with open(path, encoding="utf-8") as f:
        rows[name] = [r[0].strip() for r in csv.reader(f) if r and not r[0].startswith("#") and r[0].strip() != "参数名"]

text = {p.name: p.read_text(encoding="utf-8") for p in MDS}
all_text = "\n".join(text.values())

errors, warnings = [], []

# ① 配置项引用完整性
# 捕获后逐步裁掉尾部散文，直到命中 CSV 行（精确/前缀/系列族）；仅对强引用语境（见/按/超/达/以《表名》）报缺失
ref_pat = re.compile(r"《(世界参数表|动作前置表|建筑配置表|岗位产出表|NPC配置表|特质效果表)》([\w一-鿿_]+)")
STRONG = ("见《", "按《", "超《", "达《", "以《", "受《")

def key_matches(table, key):
    valid = rows.get(table, [])
    k = key
    while k:
        if k in valid:
            return True
        if k.endswith("系列") and any(v.startswith(k[:-2]) for v in valid):
            return True
        if len(k) >= 2 and any(v.startswith(k) for v in valid):
            return True
        k = k[:-1]
    return False

seen = set()
GENERIC_LEAD = ("对应", "各", "全部", "内", "现", "系列")
for fname, body in text.items():
    for m in ref_pat.finditer(body):
        table, key = m.group(1), m.group(2)
        if (table, key) in seen:
            continue
        seen.add((table, key))
        if key.startswith(GENERIC_LEAD):
            continue
        if key_matches(table, key):
            continue
        ctx = body[max(0, m.start() - 1):m.start() + 1]
        strong = any(body[max(0, m.start() - 1):m.end() + 1].startswith(p, 1) or body[max(0, m.start()-1):m.start()+1] == p[:1] + "《" for p in STRONG) or body[max(0, m.start()-1):m.start()] in "见按超达以受"
        if strong:
            errors.append(f"[配置缺失] {fname}: 《{table}》{key} 在 config/{table}.csv 中不存在")

# ② 章节引用（见 X.Y / 见 X.Y.Z / X.Y.Z 节）
sec_headers = set(re.findall(r"^#{1,3}\s*(\d+\.\d+(?:\.\d+)?)", all_text, re.M))
# 文档内自带的小节定义也算（README 文档地图列出章号）
for fname, body in text.items():
    for m in re.finditer(r"见\s*(\d+\.\d+(?:\.\d+)?)", body):
        sec = m.group(1)
        if sec not in sec_headers and not re.search(rf"^{re.escape(sec)}\s", all_text, re.M):
            errors.append(f"[章节悬空] {fname}: 引用「见 {sec}」但未找到该节标题")

# ③ 错误码
err_table = set(re.findall(r"E10\d{2}", text.get("09-agent行为集与生命周期.md", "")))
for fname, body in text.items():
    for code in set(re.findall(r"E10\d{2}", body)):
        if code not in err_table:
            errors.append(f"[错误码未登记] {fname}: {code} 不在 3.1.2 清单")

# ④ CSV 基本健康
for name, path in TABLES.items():
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if line.strip() and not line.startswith("#") and line.count(",") < 2 and "参数名" not in line:
                warnings.append(f"[CSV 行可疑] {path.name}:{i} 列数过少: {line.strip()[:40]}")

print(f"文档数: {len(MDS)}，配置表: {len(TABLES)}，引用配置项去重: {len(seen)}")
print(f"错误: {len(errors)}，警告: {len(warnings)}")
for e in errors: print(" ", e)
for w in warnings: print(" ", w)
sys.exit(1 if errors else 0)
