#!/usr/bin/env python3
# Agent 小镇 v0.11 经济/生存粗模拟
# 目的：在 v0.10 加压基调校验之上，叠加 v0.11 发展激励层（悬赏任务 + 行商溢价卖单），
#       用模型回答四个问题：①公共池负担（见底斜率）②悬赏兑付率与防刷上限是否有效
#       ③悬赏是否扭曲岗位选择（机动agent理性择业）④行商回收的实际量级与保险丝功能。
# 口径：tick 级需求模拟 + 日结经济结算。简化假设见 校验报告.md §7。

import random

# ---- 配置（与 config/世界参数表.csv 一致）----
FOOD_DECAY = 1.8          # 饱食/tick
FOOD_EAT = 10             # 进食恢复/单位
ENERGY_DECAY = 2
ENERGY_SLEEP = 8
MOOD_MID = 50
MOOD_REG = 0.02           # 比例回归/tick
MOOD_TALK = 2
MOOD_EAT = 0.5
MOOD_DISASTER = 3         # 灾害日减益
MOOD_HUNGRY = 1           # 饱食=0 每 tick
MOOD_HI, MOOD_LO = 70, 35
MOOD_HI_MUL, MOOD_LO_MUL = 1.2, 0.8
PROF_MID_H, PROF_HI_H = 60, 200
PROF_MID_MUL, PROF_HI_MUL = 1.15, 1.3
PROF_DECAY = 0.95
FARM, WOOD, PADDY, ODD, FORAGE = 0.55, 0.5, 0.75, 0.9, 0.25
MINT_RATE, MINT_CAP = 0.25, 3
ODD_CAP = 12
TAX = 0.08
ANCHOR_FOOD, ANCHOR_WOOD = 2.0, 3.0
FOOD_LOSS = 0.15
START_COINS, START_FOOD = 20, 8
SEASON = [(1.3, 1.0), (1.3, 1.0), (1.0, 1.0), (1.0, 1.0), (1.0, 1.0), (0.7, 0.85), (0.7, 0.85)]
EVENT_PROB = {"繁荣": .08, "暴风雨": .08, "虫灾": .06, "商队": .08}
DAYS, TICKS = 30, 24

# ---- v0.11 新增配置（与 CSV「悬赏任务（v0.11）」段一致）----
BOUNTY_MIN, BOUNTY_POOL_PCT, BOUNTY_CAP_DAY = 10.0, 0.03, 15.0   # 悬赏日限额公式
BOUNTY_ROUTINE_CAP = 6.0        # 例行悬赏日限额（老镇通道）
BOUNTY_LABOR_RATE = 0.15        # 悬赏_例行劳作单价
BOUNTY_PLEDGE_CASHBACK = 0.05   # 悬赏_例行认筹返现率
BOUNTY_WORK_REWARD = 0.3        # 悬赏_例行出工奖励
BOUNTY_PER_CAP = 2.0            # 每人日悬赏兑付上限
BOUNTY_PER_SINGLE = 1.5         # 每人单条悬赏日兑付上限
CARAVAN_PREMIUM = 1.3           # 事件_行商溢价率
CARAVAN_LIMIT_FOOD = 10         # 事件_行商限量_食物
A_STOCK_FOOD = 60               # 阿市兜底卖单目标_食物（日供上限）

def clamp(v): return max(0.0, min(100.0, v))

class Agent:
    def __init__(self, name, job, work_ticks, social, standing_order=False, trait_food=1.0, mobile=False):
        self.name, self.job = name, job
        self.work_ticks = work_ticks      # 每日目标工时
        self.social = social              # 每日对话场数
        self.so = standing_order          # 条件进食委托
        self.trait_food = trait_food      # 节俭特质乘算
        self.mobile = mobile              # 机动者：每日理性择业
        self.sat, self.ene, self.mood = 100.0, 100.0, 60.0
        self.food, self.wood, self.coins = float(START_FOOD), 0.0, float(START_COINS)
        self.hours = 0.0                  # 岗位累计工时（熟练度；机动者合并计，近似）
        self.hungry_days = 0
        self.cant_work_days = 0
        self.mood_log = []
        self.job_log = []                 # 机动者择业记录
        self.bounty_total = 0.0           # 累计悬赏兑付
        self._bounty_due = 0.0            # 当日悬赏应兑付（全镇限额压缩前）
    def prof_mul(self):
        if self.hours >= PROF_HI_H: return PROF_HI_MUL
        if self.hours >= PROF_MID_H: return PROF_MID_MUL
        return 1.0
    def mood_mul(self):
        if self.mood >= MOOD_HI: return MOOD_HI_MUL
        if self.mood <= MOOD_LO: return MOOD_LO_MUL
        return 1.0

def run(seed=42, verbose=True, stress=False):
    rng = random.Random(seed)
    agents = [
        Agent("农夫A", "farm", 10, 2), Agent("农夫B", "farm", 10, 2, standing_order=True),
        Agent("农夫C", "farm", 8, 0), Agent("农夫D", "farm", 10, 2, trait_food=0.85),
        Agent("樵夫A", "wood", 10, 1), Agent("樵夫B", "wood", 9, 0),
        Agent("杂役N", "odd", 10, 1), Agent("采集X", "forage", 10, 0),
        Agent("懒汉L", "farm", 4, 1),
        Agent("机动M", "wood", 10, 1, mobile=True),   # v0.11：理性择业者，检验悬赏扭曲
    ]
    pool = 500.0
    pool_min, pool_log = pool, []
    gini_log, disaster_days = [], set()
    event_left = {}
    # v0.11 观测量
    bounty_paid_day, bounty_log = 0.0, []          # 悬赏日兑付
    bounty_capped_days = 0                          # 触及例行限额的日数
    caravan_sink, caravan_tax_sum, caravan_sales = 0.0, 0.0, 0.0
    stockout_days, spillover_days = 0, 0           # 阿市售罄日 / 行商承接日
    a_stock_cfg = 35 if stress else A_STOCK_FOOD   # 压力情景：阿市日供减半
    a_sold_max = 0.0                               # 阿市单日最大销量（评估行商触发距离）

    for day in range(1, DAYS + 1):
        # ---- 日结前置：事件判定（最多 1 个活跃）----
        for k in list(event_left): event_left[k] -= 1;  event_left.pop(k) if event_left[k] <= 0 else None
        if not event_left:
            for k, p in EVENT_PROB.items():
                if rng.random() < p: event_left[k] = 2 if k == "虫灾" else 1; break
        sf, sw = SEASON[(day - 1) % 7]
        if "虫灾" in event_left: sf *= 0.6
        if "暴风雨" in event_left: sw *= 0.7
        tax_today = TAX * (0.5 if "繁荣" in event_left else 1.0)
        disaster = "虫灾" in event_left or "暴风雨" in event_left
        if disaster: disaster_days.add(day)

        # ---- v0.11：老镇例行发布（储备>建设>立足 优先级；第 6-15 日为建设窗口）----
        harvest = (day - 1) % 7 in (0, 1)
        construction = 6 <= day <= 15
        if harvest:      bounty = ("labor", "farm")
        elif construction: bounty = ("construct", None)
        else:            bounty = ("labor", "farm")

        # ---- v0.11：阿市日供与行商摊位 ----
        a_stock = a_stock_cfg * (2 if "商队" in event_left else 1)
        caravan_food = CARAVAN_LIMIT_FOOD if "商队" in event_left else 0
        sold_out = False
        a_sold_start = a_stock

        daily_trade_value = 0.0
        bounty_paid_day = 0.0

        for a in agents:
            # 机动者择业：比较各岗位日预期收益（产出变现 + 铸币 + 悬赏）
            if a.mobile:
                h = a.work_ticks
                val = {
                    "farm": h*FARM*sf*ANCHOR_FOOD*(1-tax_today) + min(h*MINT_RATE, MINT_CAP) + (min(h*BOUNTY_LABOR_RATE, BOUNTY_PER_SINGLE) if bounty == ("labor", "farm") else 0),
                    "wood": h*WOOD*sw*ANCHOR_WOOD*(1-tax_today) + min(h*MINT_RATE, MINT_CAP) + (min(h*BOUNTY_LABOR_RATE, BOUNTY_PER_SINGLE) if bounty == ("labor", "wood") else 0),
                    "odd":  h*ODD,
                    "forage": h*FORAGE*ANCHOR_FOOD*(1-tax_today),
                }
                a.job = max(val.items(), key=lambda kv: kv[1])[0]
                a.job_log.append(a.job)

            worked = 0.0
            # tick 循环：睡眠窗口 = 每日后 5 tick；工作 = 前 19 tick 中按需
            for t in range(TICKS):
                sleeping = t >= 19 or a.ene <= 22
                if sleeping:
                    a.ene = clamp(a.ene + ENERGY_SLEEP)
                else:
                    a.ene = clamp(a.ene - ENERGY_DECAY)
                a.sat = clamp(a.sat - FOOD_DECAY * a.trait_food)
                # 进食（手动阈值 45，委托单阈值 40）
                th = 40 if a.so else 45
                if a.sat <= th and a.food >= 1:
                    a.food -= 1; a.sat = clamp(a.sat + FOOD_EAT); a.mood = clamp(a.mood + MOOD_EAT)
                # 心情：中枢回归 + 饥饿
                a.mood = clamp(a.mood + (MOOD_MID - a.mood) * MOOD_REG)
                if a.sat <= 0: a.mood = clamp(a.mood - MOOD_HUNGRY)
                # 对话（社交 agent 在清醒 tick 中安排）
                if not sleeping and a.social > 0 and t in (8, 14)[:a.social]:
                    a.mood = clamp(a.mood + MOOD_TALK)
                # 劳作
                if (not sleeping and worked < a.work_ticks and a.sat > 0 and a.ene > 20):
                    worked += 1
            # ---- 日结 ----
            if worked > 0:
                base = {"farm": FARM, "wood": WOOD, "odd": 0, "forage": FORAGE}[a.job]
                if a.job in ("farm", "forage"):
                    out = worked * base * (sf if a.job == "farm" else 1.0) * a.mood_mul() * a.prof_mul()
                    a.food += int(out)
                elif a.job == "wood":
                    out = worked * base * sw * a.mood_mul() * a.prof_mul()
                    a.wood += int(out)
                if a.job in ("farm", "wood"):
                    a.hours += worked
                    a.coins += min(worked * MINT_RATE, MINT_CAP)
                elif a.job == "odd":
                    wage_hours = min(worked, ODD_CAP)
                    wage = wage_hours * ODD
                    pool -= wage; a.coins += wage
            else:
                a.hours *= PROF_DECAY
                a.cant_work_days += 1
            if disaster: a.mood = clamp(a.mood - MOOD_DISASTER)

            # ---- v0.11：劳作悬赏兑付（执行者口径；防刷双上限；例行限额等比在全镇层面后置处理）----
            if bounty[0] == "labor" and a.job == bounty[1] and worked > 0:
                pay = min(worked * BOUNTY_LABOR_RATE, BOUNTY_PER_SINGLE, BOUNTY_PER_CAP)
                a._bounty_due = pay
            else:
                a._bounty_due = 0.0

            # 食物损耗（未入库，库存>5 部分视为当日暴露）
            exposed = max(0.0, a.food - 5)
            a.food -= int(exposed * FOOD_LOSS)
            # 交易：食物缺口先买阿市平价（含税），售罄后溢出到行商溢价（商队日）
            need = 5 - a.food
            if need > 0:
                buy_a = min(need, a_stock)
                if a.coins < buy_a * ANCHOR_FOOD * (1 + tax_today):
                    buy_a = int(a.coins / (ANCHOR_FOOD * (1 + tax_today)))
                if buy_a > 0:
                    cost = buy_a * ANCHOR_FOOD * (1 + tax_today)
                    a.coins -= cost; a.food += buy_a; a_stock -= buy_a
                    pool += cost * tax_today / (1 + tax_today); daily_trade_value += cost
                still = need - buy_a
                if still > 0 and a_stock <= 0:
                    sold_out = True
                    if caravan_food > 0:
                        price = ANCHOR_FOOD * CARAVAN_PREMIUM
                        buy_c = min(still, caravan_food, int(a.coins / (price * (1 + tax_today))))
                        if buy_c > 0:
                            cost = buy_c * price * (1 + tax_today)
                            a.coins -= cost; a.food += buy_c; caravan_food -= buy_c
                            caravan_sink += buy_c * price            # 行商所得回收销毁
                            caravan_tax_sum += cost - buy_c * price  # 撮合抽成入池
                            pool += cost - buy_c * price
                            caravan_sales += buy_c
                            spillover_days += 1 if sold_out else 0
            surplus = a.food - 8
            if surplus > 0:
                gain = surplus * ANCHOR_FOOD
                a.coins += gain * (1 - tax_today); a.food -= surplus
                pool += gain * tax_today; daily_trade_value += gain
            if a.wood > 5:
                gain = a.wood * ANCHOR_WOOD
                a.coins += gain * (1 - tax_today); a.wood = 0
                pool += gain * tax_today; daily_trade_value += gain
            if a.sat <= 0: a.hungry_days += 1
            a.mood_log.append(round(a.mood, 1))

        if sold_out: stockout_days += 1
        a_sold_max = max(a_sold_max, a_sold_start - a_stock)

        # ---- v0.11：悬赏全镇兑付（例行限额 6/日，超出等比压缩；池支出）----
        due_list = [(a, a._bounty_due) for a in agents if a._bounty_due > 0]
        if bounty[0] == "construct":
            # 建设悬赏：认筹返现（设定认筹 30/日 ×5%）+ 出工奖励（设定出工 8 工时/日 ×0.3）
            due_construct = 30 * BOUNTY_PLEDGE_CASHBACK + 8 * BOUNTY_WORK_REWARD
            due_construct = min(due_construct, BOUNTY_ROUTINE_CAP)
            pool -= due_construct
            bounty_paid_day += due_construct   # 计入兑付额（按设定值，不归个人，见报告假设）
        elif due_list:
            total_due = sum(d for _, d in due_list)
            scale = min(1.0, BOUNTY_ROUTINE_CAP / total_due)
            if scale < 1.0: bounty_capped_days += 1
            for a, d in due_list:
                pay = d * scale
                a.coins += pay; a.bounty_total += pay
                pool -= pay; bounty_paid_day += pay
        bounty_log.append(round(bounty_paid_day, 2))

        # 老镇例行拨款：第 6-15 日有两个认筹项目（住宅/仓库），每日池内匹配
        if construction:
            pledged = 30.0  # 全镇当日认筹镇币（设定值）
            limit = max(20.0, min(pool * 0.1, 50.0))
            grant = min(pledged * 0.5, 60 - pledged, limit)
            pool -= max(0.0, grant)
        # 流拍补偿：第 18 日一个施工中项目流拍，已兑现 20 工时
        if day == 18: pool -= 20 * 0.5
        # 公告/图纸/公投费入池（设定值：日均 3）
        pool += 3.0

        pool_min = min(pool_min, pool); pool_log.append(round(pool, 1))
        # 基尼系数（定居者镇币）
        xs = sorted(a.coins for a in agents); n = len(xs); s = sum(xs)
        gini = sum((2 * i - n - 1) * x for i, x in enumerate(xs, 1)) / (n * s) if s > 0 else 0
        gini_log.append(round(gini, 3))

    if verbose:
        print(f"== 30 日模拟（seed={seed}{'，压力情景：阿市日供35' if stress else ''}）==")
        print(f"灾害日: {sorted(disaster_days)}")
        print(f"公共池: min={pool_min:.1f} end={pool_log[-1]:.1f} 轨迹[1,7,14,21,30]={[pool_log[i-1] for i in (1,7,14,21,30)]}")
        print(f"基尼系数: [7,14,21,30]={[gini_log[i-1] for i in (7,14,21,30)]}")
        print(f"悬赏兑付: 总额={sum(bounty_log):.1f} 日均={sum(bounty_log)/DAYS:.2f} 触例行限额日={bounty_capped_days} 日兑付序列[1,7,14,21,30]={[bounty_log[i-1] for i in (1,7,14,21,30)]}")
        print(f"行商: 成交={caravan_sales:.0f}单位 回收销毁={caravan_sink:.1f} 税入池={caravan_tax_sum:.1f} 阿市售罄日={stockout_days} 承接人次={spillover_days} 阿市单日最大销量={a_sold_max:.0f}/{a_stock_cfg}")
        mob = [a for a in agents if a.mobile][0]
        from collections import Counter
        print(f"机动M择业分布: {dict(Counter(mob.job_log))}")
        print(f"{'agent':<8}{'镇币':>7}{'食物':>6}{'工时':>7}{'饿天':>5}{'瘫天':>5}{'心情末/均':>12}{'悬赏':>7}")
        for a in agents:
            avg_mood = sum(a.mood_log) / len(a.mood_log)
            print(f"{a.name:<8}{a.coins:>7.1f}{a.food:>6.1f}{a.hours:>7.1f}{a.hungry_days:>5}{a.cant_work_days:>5}{a.mood_log[-1]:>6.1f}/{avg_mood:<5.1f}{a.bounty_total:>7.1f}")
    return agents, pool_min, pool_log[-1], gini_log[-1]

if __name__ == "__main__":
    run()
    print()
    run(stress=True)
