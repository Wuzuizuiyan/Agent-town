"""插件目录之间禁止互相 import。"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "world" / "plugins"


def test_no_cross_plugin_import():
    offenders = []
    for plugin_dir in sorted(p for p in ROOT.iterdir() if p.is_dir()):
        pid = plugin_dir.name
        for py in plugin_dir.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods = [node.module]
                for mod in mods:
                    if not mod.startswith("world.plugins."):
                        continue
                    other = mod.split(".")[2] if mod.count(".") >= 2 else ""
                    if other and other != pid:
                        offenders.append(f"{py}: import {mod}")
    assert not offenders, "跨插件 import:\n" + "\n".join(offenders)
