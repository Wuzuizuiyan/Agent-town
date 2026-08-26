"""公开动作名 → 中文标签与姿态。"""

from __future__ import annotations

ACTION_LABELS = {
    "idle": "待机",
    "frozen": "离线睡眠",
    "move": "赶路",
    "work": "劳作",
    "contribute": "出工",
    "eat": "进食",
    "sleep": "睡眠",
    "order_place": "挂单",
    "order_cancel": "撤单",
    "trade_private": "私交易",
    "talk": "交谈",
    "project_create": "发起项目",
    "pledge": "认筹",
    "pledge_cancel": "撤销认筹",
    "project_cancel": "撤销项目",
    "hire": "雇佣",
    "labor_transfer": "工时委托",
    "loan": "借贷",
    "bulletin_post": "张贴公告",
    "asset_transfer": "属主转让",
    "election_create": "发起竞选",
    "blueprint_propose": "提案图纸",
    "plebiscite_create": "发起公投",
    "standing_order": "设置委托单",
    "intel_share": "情报分享",
    "bounty_post": "发布悬赏",
    "bind": "绑定",
    "warehouse": "仓储",
    "trade_confirm": "确认私交易",
    "hire_confirm": "确认受雇",
    "labor_accept": "承接工时",
    "loan_confirm": "确认放贷",
    "guarantee_confirm": "确认担保",
    "loan_repay": "提前还款",
    "contract_terminate": "终止合约",
    "transfer_confirm": "确认转让",
    "vote_election": "竞选投票",
    "blueprint_support": "附议图纸",
    "vote_plebiscite": "公投投票",
    "intel_confirm": "确认情报",
}

POSE_OF = {
    "move": "walk",
    "work": "work",
    "contribute": "work",
    "eat": "eat",
    "sleep": "sleep",
    "talk": "talk",
    "intel_share": "talk",
    "order_place": "trade",
    "order_cancel": "trade",
    "trade_private": "trade",
    "trade_confirm": "trade",
    "frozen": "frozen",
}

NPC_STANCE = {
    "npc_market": ("trade", "摆摊"),
    "npc_herald": ("talk", "播报"),
    "npc_guard": ("idle", "巡视"),
    "npc_mayor": ("idle", "理事"),
    "npc_farmer": ("work", "看田"),
    "npc_woodcutter": ("work", "看林"),
    "npc_artisan": ("idle", "看工"),
    "npc_cook": ("eat", "掌勺"),
    "npc_keeper": ("idle", "守库"),
    "npc_trader": ("trade", "行商"),
}

ALLOWED_ACTIONS = set(ACTION_LABELS)


def label_of(action: str) -> str:
    return ACTION_LABELS.get(action, action)
