"""镇币按分量化；食物/木材为整数。"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def coins_to_cents(value, places: int = 2) -> int:
    q = Decimal("1").scaleb(-places)
    d = Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)
    return int(d * (10 ** places))


def cents_to_coins(cents: int, places: int = 2) -> float:
    return round(cents / (10 ** places), places)
