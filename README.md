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
| 策划案/ | 世界规则设计文档（14 章 + CHANGELOG + MVP缺口评估），阅读入口 策划案/README.md |
| config/ | 全部数值配置（7 张 CSV，数值唯一事实源；含外观部件表） |
| sim/ | 数值模拟与校验工具（经济模拟.py、NPC模拟.py、校验脚本.py、校验报告.md） |
| world/ | 世界运行时：不可卸载的 `kernel/`、机制插件 `plugins/<id>/`、启用清单 `profiles/` |
| observer/ | 公开快照、外观校验、演示人口、像素美术生成 |
| assets/ | 地块 / 建筑 / 纸娃娃图层（由 `python3 -m observer.art` 生成） |
| web/observer/ | 观测网站（地图 + 小人 + 捏脸） |
| tests/ | 插件总线、热插拔、生存/市集竖切、观测快照、跨插件 import 静态检查 |

## 运行时

按策划案第 8 章：时钟、五步 tick、九步日结、地图、账本、HTTP `/v1` 属内核；生存/市集/建设等是可装卸机制插件。对照 DeepSeek Harness 只取时间可组合（卸载撤销 register）与空间可组合（inject，禁止插件互 import），不引入 Cordis/dsh。

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest tests -q
TOWN_NO_CLOCK=1 TOWN_GM_TOKEN=dev-gm-token python3 -m world   # 仅 HTTP，不跑墙钟
town   # 默认挂载 world/profiles/full.yml，并按 tick现实秒数 推进
```

接入端点见 策划案/10-接入接口协议.md。第一枪 profile 为 `survival` + `market`（`world/profiles/first_gun.yml`）。

观测网站（公开快照 + 小人 + 捏脸）：

```bash
python3 -m observer.art
cd web/observer && npm install && npm run build
TOWN_OBSERVER_DEMO=1 python3 -m world
# 打开 http://127.0.0.1:8000
# 像素图层由 /media 提供，站点静态资源在 /
```

契约见 策划案/14-观测与外观.md。

## 版本

当前策划案版本 v0.16（2026-08-26）。改动历史与理由见
策划案/CHANGELOG.md（单一事实源）。v0.14 起接入契约见 策划案/10-接入接口协议.md。
运行时分层见 策划案/13-运行时架构.md。观测面见 策划案/14-观测与外观.md。
