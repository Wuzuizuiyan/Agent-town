from __future__ import annotations

from world.kernel.errors import TownError
from world.kernel.money import coins_to_cents
from world.kernel.util import charge_time, clamp, event_active, mood_mul, prof_mul, prof_rank, require_not_frozen, season_of
from world.kernel.mapgrid import region_at

PLUGIN_ID = "survival"
INJECT = ["clock", "map", "ledger", "agents", "needs", "log", "config", "world"]


def apply(ctx):
    ctx.actions.register("work", lambda actor, params: _work(ctx, actor, params))
    ctx.actions.register("eat", lambda actor, params: _eat(ctx, actor, params))
    ctx.actions.register("sleep", lambda actor, params: _sleep(ctx, actor, params))
    ctx.hooks.tick_after(1, lambda world: _decay(ctx, world))
    ctx.hooks.daily_after(2, lambda world: _food_loss(ctx, world))
    ctx.hooks.daily_after(5, lambda world: _produce(ctx, world))


def _cfg(ctx):
    return ctx.config


def _job_base(ctx, name: str, fallback: float) -> float:
    row = ctx.config.job(name)
    if not row:
        return fallback
    try:
        return float(row.get("基础系数") or fallback)
    except ValueError:
        return fallback


def _decay(ctx, world):
    cfg = _cfg(ctx)
    sat_d = cfg.f("饱食衰减率", 1.8)
    en_d = cfg.f("精力衰减率", 2)
    sleep_r = cfg.f("睡眠精力恢复", 8)
    house_m = cfg.f("住宅睡眠加成", 1.3) or float(cfg.action_pre.get("住宅睡眠加成", 1.3))
    mid = cfg.f("心情中枢", 50)
    reg = cfg.f("心情回归速率", 0.02)
    hungry = cfg.f("饥饿心情衰减", 1)
    for a in world.agents.settlers():
        frugal = cfg.trait_mul(a.trait, "饱食衰减率")
        hardy = cfg.trait_mul(a.trait, "精力衰减率")
        sleeper = cfg.trait_mul(a.trait, "睡眠精力恢复")
        a.satiety -= sat_d * frugal
        if a.frozen or a.slept:
            mul = house_m if a.house_id else 1.0
            a.energy += sleep_r * mul * sleeper
        else:
            a.energy -= en_d * hardy
        if not a.frozen:
            a.mood -= (a.mood - mid) * reg
            if a.satiety <= 0:
                a.mood -= hungry
        world.needs.clamp(a.agent_id)


def _food_loss(ctx, world):
    rate = _cfg(ctx).f("未入库食物日损耗率", 0.15)
    for a in world.agents.settlers():
        loss = int(a.food * rate)
        if loss:
            a.food -= loss


def _eat(ctx, actor, params):
    require_not_frozen(actor)
    qty = int(params.get("qty") or 0)
    cap = int(float(ctx.config.action_pre.get("进食单次上限", 5)))
    if qty < 1 or qty > cap:
        raise TownError("E1001")
    charge_time(actor, ctx.config.i("进食耗时", 10))
    ctx.ledger.debit(actor.agent_id, "food", qty)
    rec = ctx.config.f("进食饱食恢复", 10)
    rec *= ctx.config.trait_mul(actor.trait, "进食饱食恢复") or 1.0
    actor.satiety += rec * qty
    mood_g = ctx.config.f("进食心情收益", 0.5) * ctx.config.trait_mul(actor.trait, "心情正向收益")
    actor.mood += mood_g
    ctx.needs.clamp(actor.agent_id)
    return {"qty": qty}


def _sleep(ctx, actor, params):
    require_not_frozen(actor)
    venue = ctx.map.venue_at(actor.x, actor.y)
    region = region_at(actor.x, actor.y)
    on_own_house = bool(
        actor.house_id and venue and venue.get("building_id") == actor.house_id
    )
    empty_residential = region == "residential" and venue is None
    if not (on_own_house or empty_residential):
        raise TownError("E1006")
    actor.slept = True
    actor.time_remaining = 0
    return {"slept": True}


def _work(ctx, actor, params):
    require_not_frozen(actor)
    if actor.satiety <= 0:
        raise TownError("E1004")
    if actor.energy <= ctx.config.f("精力禁工阈值", 20):
        raise TownError("E1005")
    charge_time(actor, ctx.config.i("劳作耗时", 60))
    region = region_at(actor.x, actor.y)
    venue = ctx.map.venue_at(actor.x, actor.y)
    job = None
    pos = (actor.x, actor.y)
    if venue and venue.get("kind") == "paddy":
        b = ctx.world.state.buildings.get(venue["building_id"])
        if not b or b.owner_id != actor.agent_id:
            raise TownError("E1017")
        job = "paddy"
        b.last_work_day = ctx.clock.day
        b.waste_count = 0
    elif venue and venue.get("kind") == "farm_plot":
        b = ctx.world.state.buildings.get(venue["building_id"])
        if not b or b.owner_id != actor.agent_id:
            raise TownError("E1017")
        job = "farm_plot"
        b.last_work_day = ctx.clock.day
    elif venue and venue.get("kind") == "forest_plot":
        b = ctx.world.state.buildings.get(venue["building_id"])
        if not b or b.owner_id != actor.agent_id:
            raise TownError("E1017")
        job = "forest_plot"
        b.last_work_day = ctx.clock.day
    elif region == "farm" and pos in ctx.world.state.open_farm:
        job = "farm"
    elif region == "forest" and pos in ctx.world.state.open_forest:
        job = "wood"
    elif region == "town_hall":
        job = "odd"
        used = actor.day_hours.get("odd", 0)
        if used >= ctx.config.f("以工代赈日工时上限", 12):
            raise TownError("E1029")
    elif region == "wild":
        job = "forage"
    else:
        raise TownError("E1006")
    hours = 1.0 * ctx.config.trait_mul(actor.trait, "劳作工时计量")
    # 雇佣改道：产出仍记在执行者 day_hours，结算时看合约
    actor.day_hours[job] = actor.day_hours.get(job, 0) + hours
    if job in ("farm", "paddy", "farm_plot"):
        actor.farmer_hours += hours
    if job in ("wood", "forest_plot"):
        actor.woodcutter_hours += hours
    hire = _active_hire(ctx, actor)
    if hire and hire["type"] == "fixed_wage":
        wage = hire["wage_cents"]
        _release_wage(ctx, hire, hours)
    return {"job": job, "hours": hours}


def _active_hire(ctx, actor):
    for d in ctx.world.state.documents.values():
        if d.kind == "hire" and d.status == "active" and d.payload.get("worker") == actor.agent_id:
            return d.payload | {"document_id": d.document_id}
    return None


def _release_wage(ctx, hire, hours):
    doc_id = hire["document_id"]
    per = hire.get("wage_cents", 0)
    pay = int(per * hours)
    remaining = sum(f.qty for f in ctx.world.state.freezes if f.document_id == doc_id and f.item == "coins")
    pay = min(pay, remaining)
    if pay <= 0:
        return
    ctx.ledger.consume_frozen(doc_id, hire["employer"], "coins", pay)
    ctx.ledger.credit(hire["worker"], "coins", pay)
    for d in ctx.world.state.documents.values():
        if d.document_id == doc_id:
            d.payload["hours_delivered"] = d.payload.get("hours_delivered", 0) + hours


def _produce(ctx, world):
    cfg = ctx.config
    field_bonus = 0.0
    for b in world.state.buildings.values():
        if b.effect_kind == "farm_labor_mul" and b.status == "done":
            field_bonus += 0.10
    cap = float(cfg.action_pre.get("田圃扩建加成上限", 0.3) or 0.3)
    field_bonus = min(field_bonus, cap)
    season = season_of(world.state.day - 1 if world.state.hour == 0 else world.state.day)
    farm_s = 1.0
    wood_s = 1.0
    if season == "harvest":
        farm_s = cfg.f("丰收季农田产出修正", 1.3)
    elif season == "drought":
        farm_s = cfg.f("枯水季农田产出修正", 0.7)
        wood_s = cfg.f("枯水季木材产出修正", 0.85)
    if event_active(world.state, "pest"):
        farm_s *= 0.6
    if event_active(world.state, "storm"):
        wood_s *= 0.7
    bases = {
        "farm": _job_base(ctx, "农夫", 0.55),
        "wood": _job_base(ctx, "樵夫", 0.5),
        "paddy": _job_base(ctx, "稻田属主", 0.75),
        "farm_plot": _job_base(ctx, "开垦地块属主（农田）", 0.6),
        "forest_plot": _job_base(ctx, "开垦地块属主（林地）", 0.55),
        "odd": _job_base(ctx, "杂役", 0.9),
        "forage": _job_base(ctx, "采集者", 0.25),
    }
    mint_rate = cfg.f("劳动铸币率", 0.25)
    mint_cap = coins_to_cents(cfg.f("劳动铸币日上限", 3), world.places)
    odd_wage = coins_to_cents(cfg.f("以工代赈工资", 0.9), world.places)
    odd_need = []
    for a in world.agents.settlers():
        mm = mood_mul(a.mood, cfg)
        trait_out = cfg.trait_mul(a.trait, "劳作物资产出") or 1.0
        hire = _active_hire(ctx, a)
        dest = hire["employer"] if hire and hire.get("type") != "profit_share" else a.agent_id
        share = 0.0
        if hire and hire.get("type") == "profit_share":
            share = hire.get("profit_share", 0)
            dest = hire["employer"]
        farm_h = a.day_hours.get("farm", 0) + a.day_hours.get("paddy", 0) + a.day_hours.get("farm_plot", 0)
        wood_h = a.day_hours.get("wood", 0) + a.day_hours.get("forest_plot", 0)
        pm_f = prof_mul(prof_rank(a.farmer_hours, cfg), cfg)
        pm_w = prof_mul(prof_rank(a.woodcutter_hours, cfg), cfg)
        food = 0
        wood = 0
        for job, base, sm, pm in (
            ("farm", bases["farm"], farm_s, pm_f),
            ("paddy", bases["paddy"], farm_s, pm_f),
            ("farm_plot", bases["farm_plot"], farm_s, pm_f),
            ("wood", bases["wood"], wood_s, pm_w),
            ("forest_plot", bases["forest_plot"], wood_s, pm_w),
            ("forage", bases["forage"], 1.0, 1.0),
        ):
            h = a.day_hours.get(job, 0)
            if not h:
                continue
            extra = field_bonus if job in ("farm",) else 0
            amt = int(base * mm * pm * trait_out * sm * (1 + extra) * h)
            if job in ("farm", "paddy", "farm_plot", "forage"):
                food += amt
            else:
                wood += amt
        if hire and share:
            keep = int(food * share)
            ctx.ledger.credit(a.agent_id, "food", keep)
            ctx.ledger.credit(dest, "food", food - keep)
            keepw = int(wood * share)
            ctx.ledger.credit(a.agent_id, "wood", keepw)
            ctx.ledger.credit(dest, "wood", wood - keepw)
        else:
            if food:
                ctx.ledger.credit(dest, "food", food)
            if wood:
                ctx.ledger.credit(dest, "wood", wood)
        mint_h = farm_h + wood_h
        mint = min(mint_cap, coins_to_cents(mint_rate * mint_h, world.places))
        if mint:
            ctx.ledger.credit(a.agent_id, "coins", mint)
            ctx.log.write("MINT", actor=a.agent_id, params={"cents": mint})
        odd_h = a.day_hours.get("odd", 0)
        if odd_h:
            odd_need.append((a, int(odd_wage * odd_h)))
        if farm_h == 0:
            a.farmer_hours *= cfg.f("熟练度_荒疏衰减", 0.95)
        if wood_h == 0:
            a.woodcutter_hours *= cfg.f("熟练度_荒疏衰减", 0.95)
    total = sum(v for _, v in odd_need)
    if total and world.state.public_pool_cents < total and total > 0:
        ratio = world.state.public_pool_cents / total if total else 1
        for a, pay in odd_need:
            got = int(pay * ratio)
            world.ledger.pool_debit(got)
            ctx.ledger.credit(a.agent_id, "coins", got)
    else:
        for a, pay in odd_need:
            world.ledger.pool_debit(pay)
            ctx.ledger.credit(a.agent_id, "coins", pay)
