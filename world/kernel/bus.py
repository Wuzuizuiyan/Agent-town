"""插件总线：inject、可逆 register、tick/日结钩子。对照策划案 8.4，不引入 Cordis。"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

from world.kernel.errors import TownError

RegisterFn = Callable[..., Any]
HookFn = Callable[..., Any]


class Fiber:
    def __init__(self, plugin_id: str, inject: list[str], apply_fn: Callable):
        self.plugin_id = plugin_id
        self.inject = list(inject)
        self.apply_fn = apply_fn
        self.disposers: list[Callable[[], None]] = []
        self.active = False
        self.tick_failures = 0

    def effect(self, disposer: Callable[[], None]) -> None:
        self.disposers.append(disposer)

    def dispose(self) -> None:
        while self.disposers:
            fn = self.disposers.pop()
            fn()
        self.active = False


class ActionRegistry:
    def __init__(self, bus: "PluginBus"):
        self._bus = bus

    def register(self, api_name: str, handler: RegisterFn) -> None:
        if api_name in self._bus.actions:
            raise TownError("E1001", f"动作重复注册: {api_name}")
        self._bus.actions[api_name] = handler
        fiber = self._bus.current
        if fiber:
            def undo(name=api_name):
                self._bus.actions.pop(name, None)
            fiber.effect(undo)


class EffectRegistry:
    def __init__(self, bus: "PluginBus"):
        self._bus = bus

    def register(self, kind: str, handler: RegisterFn) -> None:
        self._bus.effect_kinds[kind] = handler
        fiber = self._bus.current
        if fiber:
            def undo(k=kind):
                self._bus.effect_kinds.pop(k, None)
            fiber.effect(undo)


class HookRegistry:
    def __init__(self, bus: "PluginBus"):
        self._bus = bus

    def tick_after(self, step: int, fn: HookFn) -> None:
        self._add("tick", step, fn)

    def daily_after(self, step: int, fn: HookFn) -> None:
        self._add("daily", step, fn)

    def _add(self, kind: str, step: int, fn: HookFn) -> None:
        pid = self._bus.current.plugin_id if self._bus.current else None
        entry = (pid, fn)
        self._bus.hooks[(kind, step)].append(entry)
        fiber = self._bus.current
        if fiber:
            def undo():
                lst = self._bus.hooks[(kind, step)]
                if entry in lst:
                    lst.remove(entry)
            fiber.effect(undo)


class PerceptionRegistry:
    def __init__(self, bus: "PluginBus"):
        self._bus = bus

    def register(self, key: str, scope: str, fn: RegisterFn) -> None:
        self._bus.perception[(scope, key)] = fn
        fiber = self._bus.current
        if fiber:
            def undo():
                self._bus.perception.pop((scope, key), None)
            fiber.effect(undo)


class EventAllow:
    def __init__(self, bus: "PluginBus"):
        self._bus = bus

    def allow(self, event_type: str) -> None:
        self._bus.allowed_events.setdefault(event_type, set()).add(self._bus.current.plugin_id if self._bus.current else "kernel")
        fiber = self._bus.current
        if fiber:
            pid = fiber.plugin_id

            def undo():
                s = self._bus.allowed_events.get(event_type)
                if s:
                    s.discard(pid)
            fiber.effect(undo)


class NpcRegistry:
    def __init__(self, bus: "PluginBus"):
        self._bus = bus

    def register(self, npc_id: str, behavior: RegisterFn) -> None:
        self._bus.npc_behaviors[npc_id] = behavior
        fiber = self._bus.current
        if fiber:
            def undo():
                self._bus.npc_behaviors.pop(npc_id, None)
            fiber.effect(undo)


class Context:
    def __init__(self, bus: "PluginBus", services: dict[str, Any]):
        self._bus = bus
        self._services = services
        self.actions = ActionRegistry(bus)
        self.effects = EffectRegistry(bus)
        self.hooks = HookRegistry(bus)
        self.perception = PerceptionRegistry(bus)
        self.events = EventAllow(bus)
        self.npc = NpcRegistry(bus)

    def __getattr__(self, name: str) -> Any:
        if name in self._services:
            return self._services[name]
        raise AttributeError(name)

    def inject(self, name: str) -> Any:
        if name not in self._services:
            raise TownError("E1001", f"缺少 inject 服务: {name}")
        return self._services[name]

    def on_unload(self, fn: Callable[[], None]) -> None:
        if self._bus.current:
            self._bus.current.effect(fn)

    def provide(self, name: str, value: Any) -> None:
        self._services[name] = value
        self._bus.services[name] = value
        fiber = self._bus.current
        if fiber:
            def undo():
                if self._bus.services.get(name) is value:
                    self._bus.services.pop(name, None)
            fiber.effect(undo)


class PluginBus:
    def __init__(self, services: dict[str, Any] | None = None):
        self.services: dict[str, Any] = dict(services or {})
        self.fibers: dict[str, Fiber] = {}
        self.actions: dict[str, RegisterFn] = {}
        self.effect_kinds: dict[str, RegisterFn] = {}
        self.hooks: dict[tuple[str, int], list[tuple[str | None, HookFn]]] = defaultdict(list)
        self.perception: dict[tuple[str, str], RegisterFn] = {}
        self.allowed_events: dict[str, set[str]] = {}
        self.npc_behaviors: dict[str, RegisterFn] = {}
        self.current: Fiber | None = None
        self.fail_limit = 8

    def ctx(self) -> Context:
        return Context(self, self.services)

    def load(self, plugin_id: str, inject: list[str], apply_fn: Callable) -> None:
        missing = [k for k in inject if k not in self.services]
        fiber = Fiber(plugin_id, inject, apply_fn)
        self.fibers[plugin_id] = fiber
        if missing:
            fiber.active = False
            log = self.services.get("log")
            if log:
                log.system("SETTLE_ERROR", f"插件 {plugin_id} 未加载，缺少 inject: {missing}")
            return
        self.current = fiber
        try:
            apply_fn(self.ctx())
            fiber.active = True
        except Exception:
            fiber.dispose()
            raise
        finally:
            self.current = None

    def unload(self, plugin_id: str) -> None:
        fiber = self.fibers.pop(plugin_id, None)
        if fiber:
            fiber.dispose()

    def unload_all(self) -> None:
        for pid in list(self.fibers):
            self.unload(pid)

    def has(self, plugin_id: str) -> bool:
        f = self.fibers.get(plugin_id)
        return bool(f and f.active)

    def run_hooks(self, kind: str, step: int, *args) -> None:
        for pid, fn in list(self.hooks.get((kind, step), [])):
            owner = self.fibers.get(pid) if pid else None
            if owner and owner.tick_failures >= self.fail_limit:
                continue
            try:
                fn(*args)
                if owner:
                    owner.tick_failures = 0
            except Exception:
                if owner:
                    owner.tick_failures += 1
                log = self.services.get("log")
                if log:
                    log.system("SETTLE_ERROR", f"hook {kind}/{step} plugin={pid} failed")

    def action_handler(self, name: str) -> RegisterFn | None:
        return self.actions.get(name)
