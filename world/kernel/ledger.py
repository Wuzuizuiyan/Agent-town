"""2.6.0 冻结总则。"""

from __future__ import annotations

from world.kernel.errors import TownError
from world.kernel.money import cents_to_coins
from world.kernel.state import Freeze, WorldState

ITEMS = ("food", "wood", "coins", "receipt_food", "receipt_wood")


class Ledger:
    def __init__(self, state: WorldState, coin_places: int = 2):
        self.state = state
        self.places = coin_places

    def _held(self, agent_id: str, item: str) -> int:
        a = self.state.agents[agent_id]
        if item == "food":
            return a.food
        if item == "wood":
            return a.wood
        if item == "coins":
            return a.coins_cents
        if item == "receipt_food":
            return a.receipt_food
        if item == "receipt_wood":
            return a.receipt_wood
        raise TownError("E1001")

    def _set(self, agent_id: str, item: str, qty: int) -> None:
        a = self.state.agents[agent_id]
        if qty < 0:
            raise TownError("E1008")
        if item == "food":
            a.food = qty
        elif item == "wood":
            a.wood = qty
        elif item == "coins":
            a.coins_cents = qty
        elif item == "receipt_food":
            a.receipt_food = qty
        elif item == "receipt_wood":
            a.receipt_wood = qty

    def frozen(self, agent_id: str, item: str) -> int:
        return sum(f.qty for f in self.state.freezes if f.agent_id == agent_id and f.item == item)

    def available(self, agent_id: str, item: str) -> int:
        return self._held(agent_id, item) - self.frozen(agent_id, item)

    def credit(self, agent_id: str, item: str, qty: int) -> None:
        if qty < 0:
            raise TownError("E1001")
        self._set(agent_id, item, self._held(agent_id, item) + qty)

    def debit(self, agent_id: str, item: str, qty: int) -> None:
        if qty < 0:
            raise TownError("E1001")
        if self._held(agent_id, item) < qty:
            raise TownError("E1008")
        if self.available(agent_id, item) < qty:
            raise TownError("E1023")
        self._set(agent_id, item, self._held(agent_id, item) - qty)

    def freeze(self, agent_id: str, item: str, qty: int, document_id: str) -> str:
        if qty < 0:
            raise TownError("E1001")
        if self._held(agent_id, item) < qty:
            raise TownError("E1008")
        if self.available(agent_id, item) < qty:
            raise TownError("E1023")
        fid = self.state.nid("fr")
        self.state.freezes.append(Freeze(fid, agent_id, item, qty, document_id))
        return fid

    def unfreeze_doc(self, document_id: str) -> None:
        self.state.freezes = [f for f in self.state.freezes if f.document_id != document_id]

    def consume_frozen(self, document_id: str, agent_id: str, item: str, qty: int) -> None:
        left = qty
        keep = []
        for f in self.state.freezes:
            if f.document_id == document_id and f.agent_id == agent_id and f.item == item and left:
                take = min(f.qty, left)
                self._set(agent_id, item, self._held(agent_id, item) - take)
                f.qty -= take
                left -= take
            if f.qty > 0:
                keep.append(f)
        self.state.freezes = keep
        if left:
            raise TownError("E1023")

    def coins_view(self, cents: int) -> float:
        return cents_to_coins(cents, self.places)

    def inventory(self, agent_id: str) -> dict:
        a = self.state.agents[agent_id]
        return {
            "food": a.food,
            "wood": a.wood,
            "coins": self.coins_view(a.coins_cents),
            "warehouse_receipts": {"food": a.receipt_food, "wood": a.receipt_wood},
        }

    def pool_credit(self, cents: int) -> None:
        self.state.public_pool_cents += cents

    def pool_debit(self, cents: int) -> int:
        take = min(cents, self.state.public_pool_cents)
        self.state.public_pool_cents -= take
        return take
