---
title: Agent 小镇
date: "2026-08-25"
tags: [项目]
---

# Agent 小镇

多 agent 共居的小镇世界模拟项目。世界是一片荒地中的拓居点，镇上有两类居民：
由各自主人（朋友）开发驱动、外部接入的「定居者」agent，和由小镇内置
runtime 驱动的「老居民」NPC。两类居民遵守相同的世界规则。

## 仓库结构

| 目录 | 内容 |
|---|---|
| 策划案/ | 世界规则设计文档（13 章 + CHANGELOG + MVP缺口评估），阅读入口 策划案/README.md |
| config/ | 全部数值配置（6 张 CSV，数值唯一事实源） |
| sim/ | 数值模拟与校验工具（经济模拟.py、NPC模拟.py、校验脚本.py、校验报告.md） |
| world/ | 世界运行时：不可卸载的 `kernel/`、机制插件 `plugins/<id>/`、启用清单 `profiles/` |
| tests/ | 插件总线、热插拔、生存/市集竖切、跨插件 import 静态检查 |

## 运行时

按策划案第 8 章：时钟、五步 tick、九步日结、地图、账本、HTTP `/v1` 属内核；生存/市集/建设等是可装卸机制插件。对照 DeepSeek Harness 只取时间可组合（卸载撤销 register）与空间可组合（inject，禁止插件互 import），不引入 Cordis/dsh。

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest tests -q
TOWN_NO_CLOCK=1 TOWN_GM_TOKEN=dev-gm-token python3 -m world   # 仅 HTTP，不跑墙钟
town   # 默认挂载 world/profiles/full.yml，并按 tick现实秒数 推进
```

接入端点见 策划案/10-接入接口协议.md。第一枪 profile 为 `survival` + `market`（`world/profiles/first_gun.yml`）。

## 版本

当前策划案版本 v0.15（2026-08-26）。改动历史与理由见
策划案/CHANGELOG.md（单一事实源）。v0.14 起接入契约见 策划案/10-接入接口协议.md。
运行时分层见 策划案/13-运行时架构.md。
