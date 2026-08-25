#!/usr/bin/env python3
# Agent 小镇 v0.12 NPC 建模：① 竞选 NPC 票仓 Monte Carlo ② 对话/闲谈 LLM 成本估算
# 目的：用模型回答两个设计问题——
#   ① NPC 票仓是否落在目标区间：「能翻转均势选情、不能对抗压倒性民意」（3.4.3 的定位校验）
#   ② NPC 对话 LLM 成本的常态量级与限额包线（E1043 双上限即成本闸）
# 口径与假设见 sim/校验报告.md §8。

import random

TRIALS = 20000
VOTE_COEFF = 0.5   # 《世界参数表》NPC投票概率系数（扫描调参落值，见校验报告§8）

def one_election(rng, n_agents, p_agent_a, npc_n, att_a_mean, att_b_mean, with_npc=True, coeff=VOTE_COEFF):
    """单场选举：agent 票按 p_agent_a 二项分布；NPC 票按 3.4.3 态度概率（态度围绕均值 ±5 波动）。"""
    a_votes = sum(1 for _ in range(n_agents) if rng.random() < p_agent_a)
    b_votes = n_agents - a_votes
    if with_npc:
        for _ in range(npc_n):
            att_a = max(0.0, min(100.0, rng.gauss(att_a_mean, 5)))
            att_b = max(0.0, min(100.0, rng.gauss(att_b_mean, 5)))
            if att_a == att_b:
                continue  # 平票按字典序——此处等概率归 A/B 无差别，按弃权处理（概率测度为零）
            top_att = max(att_a, att_b)
            if rng.random() < top_att / 100 * coeff:
                if att_a > att_b: a_votes += 1
                else: b_votes += 1
    return a_votes > b_votes

def win_rate(n_agents, p_agent_a, npc_n, att_a, att_b, with_npc=True, seed=42, coeff=VOTE_COEFF):
    rng = random.Random(seed)
    return sum(one_election(rng, n_agents, p_agent_a, npc_n, att_a, att_b, with_npc, coeff)
               for _ in range(TRIALS)) / TRIALS

def election_mc(coeff=1.0):
    # coeff=1.0 为梯度展示基准（态度差→边际影响的原始梯度）；落盘系数 0.5 经 coeff_sweep 判定
    print("== ① 竞选 Monte Carlo（每格 2 万试次；A=NPC 眼中的高态度候选人；系数 %.1f 基准）==" % coeff)
    print(f"{'agent数':>6}{'agent挺A率':>9}{'NPC票仓':>7}{'NPC对A态度':>9}{'无NPC时A胜率':>11}{'有NPC时A胜率':>11}{'边际':>8}")
    scenarios = [
        # (态度均值A, 态度均值B, 标签)
        (75, 50, "热络vs平常"),
        (60, 50, "微差"),
        (52, 50, "近似均势"),
    ]
    for att_a, att_b, tag in scenarios:
        for n_agents in (8, 12, 20):
            for p in (0.35, 0.45, 0.5, 0.55, 0.6):
                for npc_n in (6, 8):
                    p_without = win_rate(n_agents, p, npc_n, att_a, att_b, with_npc=False)
                    p_with = win_rate(n_agents, p, npc_n, att_a, att_b, coeff=coeff)
                    print(f"{n_agents:>6}{p:>9.2f}{npc_n:>7}{tag:>11}{p_without:>11.3f}{p_with:>11.3f}{p_with-p_without:>8.3f}")
        print()

def dialogue_cost():
    print("== ② 对话/闲谈 LLM 成本估算（token 实算；单价为假设档位，以账号实际为准）==")
    # token 假设：每场 NPC 对话 输入≈400（性格/职能/态度/上下文）+ 输出≈100；闲谈 输入≈800 + 输出≈200
    IN_CHAT, OUT_CHAT = 400, 100
    IN_GOSSIP, OUT_GOSSIP = 800, 200
    PRICE_IN, PRICE_OUT = 2.0, 8.0        # 假设档位：¥2/M 输入、¥8/M 输出（MiniMax-M3 量级，非账号实测价）
    agents, chats_per_agent = 10, 2       # 常态假设：10 名定居者，人均日 2 场 NPC 对话
    daily_chats = agents * chats_per_agent
    daily_in = daily_chats * IN_CHAT + IN_GOSSIP
    daily_out = daily_chats * OUT_CHAT + OUT_GOSSIP
    cost_day = (daily_in * PRICE_IN + daily_out * PRICE_OUT) / 1e6
    print(f"常态包线: {daily_chats} 场/日 + 闲谈 1 条 → 输入 {daily_in:,} + 输出 {daily_out:,} token/日")
    print(f"         ≈ ¥{cost_day:.3f}/日，¥{cost_day*30:.2f}/30 日（假设单价 输入¥{PRICE_IN}/M 输出¥{PRICE_OUT}/M）")
    # 限额包线（极端：9 名常驻 NPC 全部打满日总额 12 场）
    npc_total_cap, n_npc = 12, 9
    max_chats = npc_total_cap * n_npc
    max_in = max_chats * IN_CHAT + IN_GOSSIP
    max_out = max_chats * OUT_CHAT + OUT_GOSSIP
    max_cost = (max_in * PRICE_IN + max_out * PRICE_OUT) / 1e6
    print(f"限额包线: {max_chats} 场/日（{n_npc} NPC × 总额 {npc_total_cap}）→ 输入 {max_in:,} + 输出 {max_out:,} token/日")
    print(f"         ≈ ¥{max_cost:.3f}/日，¥{max_cost*30:.2f}/30 日——E1043 双上限即成本硬顶")
    # 心跳对照：无心跳设计，agent 不说话则成本为 0（闲谈除外）
    print(f"零交互日: 仅闲谈 ≈ ¥{(IN_GOSSIP*PRICE_IN+OUT_GOSSIP*PRICE_OUT)/1e6:.4f}/日；关闭闲谈开关则为 0")

def coeff_sweep():
    """系数调参：目标区间 = 翻转均势（p=0.5 边际 ≥+0.25）且不敌压倒（p=0.35 时 A 胜率 ≤0.35）。
    读数格：热络差（75v50）× agent 8/12/20 × 票仓 6/8 × 系数扫描。"""
    print("== ③ 系数扫描调参（热络vs平常 75v50）==")
    print(f"{'系数':>5}{'agent数':>7}{'票仓':>5}{'p=0.5胜率':>10}{'p=0.5边际':>10}{'p=0.35胜率':>11}{'判定':>8}")
    for coeff in (1.0, 0.7, 0.5, 0.4):
        for n_agents in (8, 12, 20):
            for npc_n in (6, 8):
                base50 = win_rate(n_agents, 0.5, npc_n, 75, 50, with_npc=False)
                with50 = win_rate(n_agents, 0.5, npc_n, 75, 50, coeff=coeff)
                with35 = win_rate(n_agents, 0.35, npc_n, 75, 50, coeff=coeff)
                ok = "通过" if (with50 - base50 >= 0.25 and with35 <= 0.35) else "超界"
                print(f"{coeff:>5}{n_agents:>7}{npc_n:>5}{with50:>10.3f}{with50-base50:>10.3f}{with35:>11.3f}{ok:>8}")
        print()

if __name__ == "__main__":
    election_mc()
    print()
    coeff_sweep()
    print()
    dialogue_cost()
